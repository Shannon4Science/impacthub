"""LLM-driven generic crawler for university faculty directories.

Per-school adapters don't scale to 147 schools. Instead we:
  1. Fetch the school homepage
  2. Ask LLM to identify the "院系设置 / 组织机构" link
  3. Fetch that page, ask LLM to extract the college list
  4. Per college, fetch its homepage, ask LLM to find "师资队伍 / 教师队伍" link
  5. Fetch that page, ask LLM to extract teacher stubs (name + title + URL)

All HTML is pre-cleaned with BeautifulSoup (strip scripts/styles/comments,
keep only <a> + nav text) to keep token cost down.

Cost target: ≈$0.01-0.05 per school for college discovery.
"""

import asyncio
import json
import logging
import re
import ssl
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import chardet
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


def _make_permissive_ssl_context() -> ssl.SSLContext:
    """Old .edu.cn servers (NJU, SCUT, etc.) need legacy ciphers + skip verify."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    # Allow legacy renegotiation / weak ciphers used by some .edu.cn servers
    try:
        ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT
    except Exception:
        pass
    try:
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
    except ssl.SSLError:
        try:
            ctx.set_ciphers("ALL:@SECLEVEL=0")
        except ssl.SSLError:
            pass
    return ctx


_PERMISSIVE_SSL = _make_permissive_ssl_context()

from app.config import LLM_API_BASE, LLM_API_KEY, LLM_FALLBACK_MODEL
from app.models import AdvisorSchool, AdvisorCollege, Advisor, AdvisorMention

logger = logging.getLogger(__name__)

# Use the lighter model for HTML parsing — output is structured, not creative
CRAWL_MODEL = LLM_FALLBACK_MODEL  # gpt-5-mini

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Upgrade-Insecure-Requests": "1",
}

REQUEST_TIMEOUT = 25.0
REQUEST_DELAY_SECONDS = 6.0  # politeness pause between scrape requests
MAX_HTML_TOKENS = 12_000     # rough cap on cleaned HTML fed to LLM


# ──────────────────────────── HTTP helpers ────────────────────────────

_JS_REDIRECT_RE = re.compile(
    r"""(?:window\.location|window\.location\.href|location\.href|location)\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
_META_REFRESH_RE = re.compile(
    r"""<meta[^>]+http-equiv=['"]?refresh['"]?[^>]+content=['"]?\d+\s*;\s*url=([^'">\s]+)""",
    re.IGNORECASE,
)


async def fetch_html(
    client: httpx.AsyncClient,
    url: str,
    *,
    follow_js_redirect: bool = True,
    _depth: int = 0,
) -> str | None:
    """Fetch a URL with encoding sniffing for Chinese sites (often GBK).

    Also follows JS redirects (`window.location.href = 'X'`) and meta-refresh
    once per call — CMS-hosted faculty pages often have a placeholder page that
    JS-redirects to the actual list.

    Accepts 200/202/203 (some CN sites use 202). On SSL handshake failure,
    falls back to http://.
    """
    async def _do_get(c: httpx.AsyncClient) -> httpx.Response:
        return await c.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT, follow_redirects=True)

    try:
        try:
            resp = await _do_get(client)
        except (httpx.HTTPError, httpx.TimeoutException) as e:
            msg = str(e)
            # SSL handshake failure → re-try with permissive SSL context (legacy ciphers)
            if "SSL" in msg or "handshake" in msg.lower():
                logger.info("fetch_html %s SSL fail, retrying with legacy ciphers", url)
                async with httpx.AsyncClient(verify=_PERMISSIVE_SSL) as legacy_client:
                    resp = await _do_get(legacy_client)
            else:
                raise
        # Some CN sites return 202 Accepted with the HTML body — treat as success
        if resp.status_code not in (200, 202, 203):
            logger.info("fetch_html %s → %d", url, resp.status_code)
            return None
        raw = resp.content
        encoding = resp.encoding
        if not encoding or encoding.lower() in ("iso-8859-1", "ascii"):
            detected = chardet.detect(raw[:8192])
            if detected.get("encoding"):
                encoding = detected["encoding"]
            else:
                encoding = "utf-8"
        try:
            text = raw.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = raw.decode("utf-8", errors="replace")

        # Follow JS / meta-refresh redirects (only if page is short enough to be a stub)
        if follow_js_redirect and _depth < 2 and len(text) < 5000:
            for pattern in (_JS_REDIRECT_RE, _META_REFRESH_RE):
                m = pattern.search(text)
                if m:
                    target = m.group(1).strip()
                    if target and not target.startswith(("javascript:", "mailto:", "#")):
                        new_url = urljoin(str(resp.url), target)
                        if new_url != url:
                            logger.info("fetch_html JS-redirect %s → %s", url, new_url)
                            return await fetch_html(
                                client, new_url, follow_js_redirect=True, _depth=_depth + 1,
                            )
        return text
    except (httpx.HTTPError, httpx.TimeoutException) as e:
        logger.info("fetch_html %s failed: %s", url, e)
        return None


def clean_html_for_llm(html: str, base_url: str) -> str:
    """Strip scripts/styles/comments. Keep only structural text + <a> with absolute URLs."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")

    # Remove noise
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "img", "video", "audio", "form"]):
        tag.decompose()
    for tag in soup.find_all(string=lambda s: isinstance(s, type(soup.new_string("")))):
        # comments are not strings; leave alone
        pass

    # Resolve all relative URLs
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "mailto:", "#")) or not href:
            a.decompose()
            continue
        a["href"] = urljoin(base_url, href)

    # Build a compact representation: link list + text body
    parts: list[str] = []
    seen_urls: set[str] = set()
    for a in soup.find_all("a", href=True):
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        if not text or len(text) > 60:
            continue
        href = a["href"]
        if href in seen_urls:
            continue
        seen_urls.add(href)
        parts.append(f"[{text}]({href})")

    # Rough title / page heading too
    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    head = ""
    h1 = soup.find(["h1", "h2"])
    if h1:
        head = re.sub(r"\s+", " ", h1.get_text(strip=True))[:200]

    body = "\n".join(parts)
    # Truncate by char count (rough proxy for tokens)
    if len(body) > MAX_HTML_TOKENS * 3:
        body = body[: MAX_HTML_TOKENS * 3]

    out = []
    if title:
        out.append(f"<title>{title}</title>")
    if head:
        out.append(f"<heading>{head}</heading>")
    out.append("<links>")
    out.append(body)
    out.append("</links>")
    return "\n".join(out)


# ──────────────────────────── LLM helper ────────────────────────────

def _parse_json(text: str) -> Any:
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        s = s.rsplit("```", 1)[0].strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        m = re.search(r"(\[.*\]|\{.*\})", s, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                return None
    return None


async def _call_llm(client: httpx.AsyncClient, prompt: str, max_tokens: int = 4000) -> Any:
    """Chat-completion call with JSON-output expectation."""
    try:
        resp = await client.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": CRAWL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_completion_tokens": max_tokens,
            },
            timeout=120,
        )
        if resp.status_code != 200:
            logger.warning("Crawler LLM %d: %s", resp.status_code, resp.text[:200])
            return None
        text = resp.json()["choices"][0]["message"].get("content", "")
        return _parse_json(text)
    except Exception as e:
        logger.warning("Crawler LLM call failed: %s", e)
        return None


# ──────────────────────────── Stage 1: find college index link ────────────────────────────

COLLEGE_INDEX_PROMPT = """你正在帮助分析一个中国大学官网，目标是找到"院系设置 / 组织机构 / 学院列表"页面的链接。

### 学校
{school_name} ({homepage})

### 主页提取的链接列表（已剔除 JS/CSS/图片）
{html}

### 任务
从上面链接中找出**最可能是院系设置/学院列表/组织机构入口**的那一条链接。

判断关键词（任一即可）：院系设置、组织机构、教学单位、学院、学部、学系、Schools, Colleges, Departments, Academics, Faculty list

### 输出严格 JSON
{{"url": "https://...", "label": "原链接文字", "confidence": "high|medium|low", "reason": "为什么选它"}}

如果没有任何候选链接，输出 {{"url": "", "confidence": "none", "reason": "说明"}}。

只输出 JSON，不要 markdown。"""


COLLEGE_INDEX_URL_HINTS = (
    "yxsz", "zzjg", "yuanxi", "yxlb", "academic", "schools",
    "colleges", "departments", "yxbm", "gljg",
)


def heuristic_find_college_index(html: str, base_url: str) -> dict | None:
    """Find the most likely 院系设置 link from a school homepage."""
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    best: tuple[int, str, str] | None = None
    for a in soup.find_all("a", href=True):
        href_raw = a["href"].strip()
        if href_raw.startswith(("javascript:", "mailto:", "#")) or not href_raw:
            continue
        href = urljoin(base_url, href_raw)
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        text = re.sub(r"[*\u2022\u25cf\[\]【】]", "", text).strip()
        if not text or len(text) > 30:
            continue
        score = 0
        # Exact (high-priority) text matches — academic only
        if text in {"院系设置", "教学单位", "院系一览", "学院设置", "学院列表",
                    "院系导航", "院系导览", "教学单位一览", "教学科研单位",
                    "教学科研机构", "教学院系", "学院与系", "院系机构"}:
            score += 70
        # Mid: more generic 机构/组织 keywords (could be admin)
        elif text in {"组织机构", "机构设置", "机构导览", "院系", "院部",
                      "教学机构", "学术机构", "院所", "系所"}:
            score += 35
        elif "院系" in text and len(text) <= 8:
            score += 25
        # English equivalents
        elif text.lower() in {"schools", "colleges", "departments", "academics", "academic units", "faculties"}:
            score += 50
        # URL hint
        href_low = href.lower()
        for hint in COLLEGE_INDEX_URL_HINTS:
            if hint in href_low:
                score += 12
                break
        if score >= 25:
            if best is None or score > best[0]:
                best = (score, text, href)
    if best is None:
        return None
    return {"url": best[2], "label": best[1], "confidence": "high" if best[0] >= 50 else "medium"}


async def find_college_index_link(client: httpx.AsyncClient, school: AdvisorSchool, homepage_html: str) -> dict | None:
    """Heuristic-first; fall back to LLM only if no candidate scores above threshold."""
    h = heuristic_find_college_index(homepage_html, school.homepage_url)
    if h:
        return h
    # Fallback to LLM (expensive, may fail)
    cleaned = clean_html_for_llm(homepage_html, school.homepage_url)
    if not cleaned:
        return None
    prompt = COLLEGE_INDEX_PROMPT.format(
        school_name=school.name,
        homepage=school.homepage_url,
        html=cleaned[: MAX_HTML_TOKENS * 3],
    )
    return await _call_llm(client, prompt, max_tokens=400)


# ──────────────────────────── Stage 2: extract college list ────────────────────────────

COLLEGE_LIST_PROMPT = """你正在分析中国大学的"院系设置"页面，需要提取完整的学院列表。

### 学校
{school_name}

### 页面提取的链接列表
{html}

### 任务
列出该校所有的**学院/学部/学系/书院**（不要列出"行政部门""学术机构"或非教学单位）。
对每个学院给出：
- name: 中文全名（例如"计算机科学与技术系"或"人工智能学院"）
- url: 学院主页 URL（如果链接里有）
- discipline_category: 一级学科类别，从 [工学, 理学, 文学, 历史学, 哲学, 经济学, 管理学, 法学, 教育学, 艺术学, 医学, 农学, 军事学] 选一个最贴切的，无法判断写空字符串
- english_name: 英文名（如果能从链接文字看出）

### 严格 JSON 数组输出
[
  {{"name": "计算机科学与技术系", "url": "https://www.cs.tsinghua.edu.cn", "discipline_category": "工学", "english_name": "Department of Computer Science and Technology"}},
  ...
]

要求：
- 不要遗漏，但也不要把"研究院/中心"当作学院（除非它显然是教学型学院）
- 不要包含"招生网""研究生院""校友会"这种行政页
- 如果学院 URL 没有就给空字符串
- 只输出 JSON 数组，不要 markdown"""


# College keywords for heuristic extraction (Chinese university taxonomy)
COLLEGE_SUFFIXES = ("学院", "学部", "学系", "书院", "研究院", "系")
COLLEGE_KEYWORDS = ("学院", "学部", "学系", "书院", "研究院")
NON_COLLEGE_NAMES = {
    # Admin / non-academic pages that share the 院/系 substring
    "招生网", "研究生院", "校友会", "校友网", "教育部", "新闻网", "图书馆",
    "出版社", "校史馆", "档案馆", "校地合作研究院", "联系我们", "联系方式",
    "院长信箱", "院长寄语", "学院首页", "学院概况", "院系简介", "院系介绍",
    "通知", "动态",
}


def _looks_like_college_name(text: str) -> bool:
    """A string looks like an academic unit if it ends with a college suffix
    AND doesn't trigger a non-college blacklist."""
    if not text:
        return False
    # Suffix check: must end with one of the academic suffixes
    if not text.endswith(COLLEGE_SUFFIXES):
        return False
    # Special case: bare "系" suffix needs the prefix to be substantive (≥2 chars)
    if text.endswith("系") and not text.endswith(("学系",)):
        prefix = text[:-1]
        if len(prefix) < 2:
            return False
        # Generic 系 compounds that aren't departments
        BAD_SUFFIXES = ("体系", "系统", "院系", "系列", "联系", "关系")
        if text.endswith(BAD_SUFFIXES):
            return False
    return True

DISCIPLINE_KEYWORDS = {
    "工学": [
        "工程", "工学", "技术", "电子", "机械", "建筑", "土木", "化工", "材料",
        "信息", "计算机", "软件", "自动化", "微电子", "集成电路", "通信", "电气",
        "测控", "船舶", "航空", "航天", "兵器", "核工程", "矿业", "冶金",
        "纺织", "印刷", "包装", "环境", "能源", "动力", "石油", "地质工程",
        "测绘", "交通", "水利", "海洋工程", "网络", "智能", "人工智能", "数据科学",
        "机器人", "公安",
    ],
    "理学": [
        "物理", "化学", "数学", "天文", "地理", "海洋", "生物", "生命", "地质",
        "大气", "统计", "心理", "认知", "数据", "理学",
    ],
    "文学": ["文学", "中文", "外语", "外国语", "语言", "新闻", "传播", "汉语", "翻译"],
    "历史学": ["历史", "考古", "文博"],
    "哲学": ["哲学", "马克思主义"],
    "经济学": ["经济", "金融", "财政", "会计"],
    "管理学": ["管理", "工商", "公共管理", "商学", "MBA"],
    "法学": ["法学", "政治", "国际关系", "社会", "民族"],
    "教育学": ["教育", "体育"],
    "艺术学": ["艺术", "美术", "音乐", "戏剧", "影视", "设计", "舞蹈"],
    "医学": ["医学", "药学", "护理", "口腔", "公共卫生", "中医", "中药", "卫生", "临床"],
    "农学": ["农学", "园艺", "林学", "动物", "植物", "畜牧", "兽医", "水产", "园林"],
    "军事学": ["军事", "国防"],
}


def classify_discipline(name: str) -> str:
    """Map a college name to a 一级学科类别 by keyword."""
    for cat, kws in DISCIPLINE_KEYWORDS.items():
        for kw in kws:
            if kw in name:
                return cat
    return ""


def heuristic_extract_colleges(html: str, base_url: str) -> list[dict]:
    """Pure-BS4 college extraction: find anchors whose text contains 学院/学部/书院.

    No LLM needed — Chinese university 院系设置 pages are highly conventional.
    Filters out admin pages and duplicate URLs.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    base_host = urlparse(base_url).hostname or ""

    seen_urls: set[str] = set()
    seen_names: set[str] = set()
    out: list[dict] = []

    for a in soup.find_all("a", href=True):
        href_raw = a["href"].strip()
        if href_raw.startswith(("javascript:", "mailto:", "#")) or not href_raw:
            continue
        href = urljoin(base_url, href_raw)
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        text = re.sub(r"[*\u2022\u25cf\[\]【】]", "", text).strip()  # strip decorative chars
        if not text:
            continue
        if not _looks_like_college_name(text):
            continue
        if any(bad in text for bad in NON_COLLEGE_NAMES):
            continue
        if len(text) > 60 or len(text) < 2:
            continue
        # External vs internal: prefer external college subdomains and same-school subdomains
        href_host = urlparse(href).hostname or ""
        # Skip self-anchors / global navigation
        if href_host == base_host and href.endswith(("/yxsz.htm", "/zzjg.htm")):
            continue
        # Dedup
        if href in seen_urls or text in seen_names:
            continue
        seen_urls.add(href)
        seen_names.add(text)
        out.append({
            "name": text[:100],
            "url": href[:500],
            "discipline_category": classify_discipline(text),
            "english_name": "",
        })
    return out


async def extract_college_list(
    client: httpx.AsyncClient,
    school: AdvisorSchool,
    college_index_url: str,
    college_index_html: str,
) -> list[dict]:
    """Heuristic-first college extraction. LLM not used here (too expensive + slow for link lists)."""
    return heuristic_extract_colleges(college_index_html, college_index_url)


# ──────────────────────────── Stage 3: find faculty list link ────────────────────────────

FACULTY_INDEX_PROMPT = """你正在分析中国大学某个学院的官网，目标是找到"师资队伍 / 教师队伍 / 导师列表"页面的链接。

### 学院
{college_name}（{school_name}）— {college_url}

### 学院主页链接列表
{html}

### 任务
找出**最可能是师资队伍/导师列表/教师名录**的链接。
关键词：师资队伍、教师队伍、导师列表、师资力量、教授名录、Faculty, People, Staff

### 严格 JSON 输出
{{"url": "https://...", "label": "...", "confidence": "high|medium|low"}}

如果没有候选，输出 {{"url": "", "confidence": "none"}}。
只输出 JSON。"""


FACULTY_TEXT_KEYWORDS = (
    "师资队伍", "师资力量", "师资介绍", "师资", "教师队伍", "教师介绍",
    "导师列表", "导师介绍", "导师", "全体教师", "教授", "People", "Faculty",
    "Staff", "Teachers", "教研团队",
)
FACULTY_URL_HINTS = (
    "szdw", "jsdw", "dsdw", "teacher", "faculty", "people", "staff",
    "professor", "szjs", "shizi",
)
FACULTY_NEGATIVE = (
    "招聘", "宣讲", "招生", "讲座", "聘任公告",
)


def heuristic_find_faculty_link(html: str, base_url: str) -> dict | None:
    """Find the most likely '师资队伍' / 'Faculty' link from a college homepage.

    Scores each <a> by text/URL keyword match and returns the best one.
    """
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    best: tuple[int, str, str] | None = None  # (score, text, url)
    for a in soup.find_all("a", href=True):
        href_raw = a["href"].strip()
        if href_raw.startswith(("javascript:", "mailto:", "#")) or not href_raw:
            continue
        href = urljoin(base_url, href_raw)
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        text = re.sub(r"[*\u2022\u25cf\[\]【】]", "", text).strip()
        if not text or len(text) > 30:
            continue
        # Negative keywords (招聘 etc.) — skip
        if any(neg in text for neg in FACULTY_NEGATIVE):
            continue

        score = 0
        # Strong text matches
        if "师资队伍" in text or "教师队伍" in text or "师资力量" in text:
            score += 50
        elif "师资" in text or "导师" in text or "教师" in text:
            score += 30
        elif text.lower() in {"faculty", "people", "staff", "teachers"}:
            score += 35
        elif "教授" in text and len(text) <= 6:
            score += 15

        # URL hints
        href_low = href.lower()
        for hint in FACULTY_URL_HINTS:
            if hint in href_low:
                score += 10
                break

        if score > 0:
            if best is None or score > best[0]:
                best = (score, text, href)

    if best is None:
        return None
    return {"url": best[2], "label": best[1], "confidence": "high" if best[0] >= 40 else "medium"}


async def find_faculty_list_link(
    client: httpx.AsyncClient,
    school: AdvisorSchool,
    college: AdvisorCollege,
    college_html: str,
) -> dict | None:
    """Heuristic-first faculty link finder."""
    return heuristic_find_faculty_link(college_html, college.homepage_url)


# ──────────────────────────── Stage 4: extract advisor stubs ────────────────────────────

ADVISOR_LIST_PROMPT = """你正在分析中国大学某学院的"师资队伍/导师列表"页面，需要抽取教师名单。

### 学院
{college_name}（{school_name}）

### 页面链接列表
{html}

### 任务
提取页面上列出的所有**研究生导师/教师**。每位给出：
- name: 中文姓名（**只要 2-4 字的中文姓名**，不要把"教授""博导"等词写进姓名）
- title: 职称（教授/副教授/讲师/研究员/副研究员/助理研究员/特聘教授）— 看不出留空
- homepage: 教师个人主页 URL（如果链接里有）

### 严格 JSON 数组输出
[
  {{"name": "张三", "title": "教授", "homepage": "https://..."}},
  ...
]

要求：
- 不要把行政人员/秘书写进来（看头衔判断）
- 同一人不要重复
- 如果页面上没有明确的导师/教师列表（只是"师资简介"宣传性页面），返回空数组 []
- 只输出 JSON 数组"""


# Common surnames + characters that suggest a Chinese name
# These help distinguish "李国良" (a name) from "首页" (a nav word)
NAVIGATION_BLACKLIST = {
    "首页", "新闻", "通知", "动态", "概况", "简介", "联系", "招生", "招聘",
    "教务", "教学", "科研", "返回", "下一页", "上一页", "更多", "查看", "详情",
    "公告", "中心", "组织", "机构", "下载", "资料", "服务", "管理",
    "研究", "实验", "课程", "导师", "教师", "教授", "教职", "师资",
    "本科", "硕士", "博士", "学生", "学位", "学院", "学部", "学系",
}

# A "name-like" anchor: 2-4 Chinese characters, no English/digits, not a nav word
_NAME_RE = re.compile(r"^[\u4e00-\u9fff·]{2,4}$")


def heuristic_extract_advisors(html: str, base_url: str) -> list[dict]:
    """Extract teacher stubs from a 师资 page.

    Pattern: <a> whose text is a 2-4 char Chinese name and href points to a detail page.
    """
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    # Strip nav/footer to reduce false positives
    for tag in soup(["nav", "header", "footer", "script", "style", "form"]):
        tag.decompose()

    candidates: list[dict] = []
    seen_names: set[str] = set()
    for a in soup.find_all("a", href=True):
        href_raw = a["href"].strip()
        if href_raw.startswith(("javascript:", "mailto:", "#")) or not href_raw:
            continue
        text = re.sub(r"\s+", "", a.get_text(strip=True))
        text = re.sub(r"[*\u2022\u25cf\[\]【】（）()]", "", text)
        if not _NAME_RE.match(text):
            continue
        # Filter nav words by substring (e.g., "师资状况" contains "师资")
        if any(bad in text for bad in NAVIGATION_BLACKLIST):
            continue
        if text in seen_names:
            continue
        href = urljoin(base_url, href_raw)
        # Real teacher detail pages match either:
        #   (a) numeric ID in path (info/1111/3490.htm, people/123)
        #   (b) keyword path with pinyin slug (facultydetails/xxx, teacher/<name>, personal/...)
        href_path = urlparse(href).path
        href_low = href.lower()
        has_digit = bool(re.search(r"\d{2,}", href_path))
        has_keyword = any(p in href_low for p in (
            "facultydetail", "teacherdetail", "facultyinfo", "personal",
            "teacher/", "faculty/", "people/", "prof/", "/szjs/",
        ))
        # Generic file-extension fallback (when paired with digits)
        has_doc_ext = href_low.endswith((".htm", ".html", ".aspx", ".jsp"))
        if not (has_keyword or (has_digit and has_doc_ext)):
            continue
        seen_names.add(text)
        candidates.append({
            "name": text,
            "title": "",
            "homepage": href,
        })

    # Heuristic floor: faculty pages usually list ≥3 teachers; <3 likely false positives
    if len(candidates) < 3:
        return []
    return candidates


async def extract_advisor_list(
    client: httpx.AsyncClient,
    school: AdvisorSchool,
    college: AdvisorCollege,
    faculty_url: str,
    faculty_html: str,
) -> list[dict]:
    """Heuristic-first advisor extraction. Falls back to LLM only if heuristic returns 0.

    Pure regex/BS4 catches typical 师资 pages where each teacher is an <a> linking to detail.
    For pages that use cards / no anchors, we'd need LLM but keep it as a future fallback.
    """
    advisors = heuristic_extract_advisors(faculty_html, faculty_url)
    return advisors


# ──────────────────────────── Orchestrator ────────────────────────────

LLM_FALLBACK_PROMPT = """请联网搜索中国大学「{school_name}」（官网 {homepage}）的**学院列表**，返回严格 JSON。

任务：列出该校所有教学型学院（不要列招生办、研究生院等行政单位），每个给出：
- name: 学院中文全名
- url: 该学院官网 URL（如能找到，没找到留空字符串）
- discipline_category: 一级学科（工学/理学/文学/历史学/哲学/经济学/管理学/法学/教育学/艺术学/医学/农学/军事学），看不出留空

### 严格 JSON 数组（不要 markdown、不要解释）
[
  {{"name": "...", "url": "https://...", "discipline_category": "..."}}
]

要求：
- 至少列 5 个学院（如果该校确有更多请尽量全列，常见综合校 20-50 个）
- url 优先用学校官网下的子域名（例如 cs.school.edu.cn）
- 不要凭空编造学院名"""


async def llm_search_college_list(client: httpx.AsyncClient, school: AdvisorSchool) -> list[dict]:
    """Last-resort fallback: ask LLM Responses API + web_search_preview to find
    the school's college list. Used when direct scraping fails (412/SSL/JS).
    """
    prompt = LLM_FALLBACK_PROMPT.format(school_name=school.name, homepage=school.homepage_url)
    try:
        resp = await client.post(
            f"{LLM_API_BASE}/responses",
            headers={"Authorization": f"Bearer {LLM_API_KEY}"},
            json={
                "model": LLM_BUZZ_MODEL,
                "tools": [{"type": "web_search_preview"}],
                "input": prompt,
                "max_output_tokens": 8000,
            },
            timeout=240,
        )
        if resp.status_code != 200:
            logger.warning("LLM fallback %s → %d", school.name, resp.status_code)
            return []
        data = resp.json()
        text = ""
        for item in data.get("output", []):
            if item.get("type") == "message":
                for c in item.get("content", []):
                    if c.get("type") == "output_text":
                        text = c.get("text", "")
        parsed = _parse_json(text)
        if not isinstance(parsed, list):
            return []
        out: list[dict] = []
        for c in parsed:
            if not isinstance(c, dict):
                continue
            name = str(c.get("name", "")).strip()
            if not (2 <= len(name) <= 80):
                continue
            url = str(c.get("url", "")).strip()
            cat = str(c.get("discipline_category", "")).strip()
            out.append({
                "name": name[:100],
                "url": url[:500],
                "discipline_category": cat[:40] if cat else classify_discipline(name),
                "english_name": "",
            })
        logger.info("LLM fallback for %s: %d colleges", school.name, len(out))
        return out
    except Exception as e:
        logger.warning("LLM fallback %s failed: %s", school.name, e)
        return []


# Lazy import (avoid circular)
from app.config import LLM_BUZZ_MODEL  # noqa: E402


async def crawl_school_colleges(
    db: AsyncSession,
    school: AdvisorSchool,
    *,
    fetch_advisors: bool = False,
) -> dict:
    """End-to-end: fetch homepage → find college index → extract colleges (and optionally advisors).

    Returns: {colleges_added, advisors_added, errors[]}
    Strategy: try the dedicated 院系设置 page first; fall back to extracting
    directly from the homepage if that yields nothing. Some schools (Fudan, ZJU)
    list colleges inline on the homepage with no separate index page.
    """
    if not school.homepage_url:
        return {"colleges_added": 0, "advisors_added": 0, "errors": ["no homepage_url"]}

    errors: list[str] = []
    colleges_added = 0
    advisors_added = 0

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        homepage_html = await fetch_html(client, school.homepage_url)

        college_records: list[dict] = []
        college_index_url = ""

        # If homepage fetch failed entirely, jump straight to LLM web-search fallback
        if not homepage_html:
            errors.append("homepage fetch failed; trying LLM fallback")
            college_records = await llm_search_college_list(client, school)
            if not college_records:
                school.colleges_crawled_at = datetime.utcnow()
                await db.flush()
                errors.append("LLM fallback also empty")
                return {"colleges_added": 0, "advisors_added": 0, "errors": errors}
            school.faculty_index_url = "(llm-search)"
            # Skip stages 2-4 — go straight to upsert
            existing_names = {
                c.name for c in (await db.execute(
                    select(AdvisorCollege).where(AdvisorCollege.school_id == school.id)
                )).scalars().all()
            }
            for c in college_records:
                if c["name"] in existing_names:
                    continue
                db.add(AdvisorCollege(
                    school_id=school.id,
                    name=c["name"],
                    english_name=c.get("english_name", ""),
                    discipline_category=c.get("discipline_category", ""),
                    homepage_url=c.get("url", ""),
                ))
                colleges_added += 1
            school.colleges_crawled_at = datetime.utcnow()
            await db.flush()
            return {"colleges_added": colleges_added, "advisors_added": 0, "errors": errors}

        # Stage 2: find college-index link
        link_info = await find_college_index_link(client, school, homepage_html)
        if link_info and link_info.get("url"):
            college_index_url = link_info["url"]
            school.faculty_index_url = college_index_url
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
            college_index_html = await fetch_html(client, college_index_url)
            if college_index_html:
                college_records = await extract_college_list(
                    client, school, college_index_url, college_index_html,
                )
            else:
                errors.append(f"college index page fetch failed: {college_index_url}")

        # Fallback: if dedicated index returned too few colleges (<= 3), ALSO try
        # extracting directly from the homepage and merge — keep whichever has more.
        # Reason: some school 组织机构 pages list only admin units, not academic
        # colleges, yielding e.g. 1 misleading 孔子学院 entry.
        if len(college_records) <= 3:
            from_home = heuristic_extract_colleges(homepage_html, school.homepage_url)
            if len(from_home) > len(college_records):
                college_records = from_home
                school.faculty_index_url = school.homepage_url

        if not college_records:
            errors.append("no colleges extracted from index or homepage")
            # Still mark crawled so the batch doesn't infinite-retry; a separate
            # retry pass can clear colleges_crawled_at for these schools.
            school.colleges_crawled_at = datetime.utcnow()
            await db.flush()
            return {"colleges_added": 0, "advisors_added": 0, "errors": errors}

        # Upsert into DB
        existing = (await db.execute(
            select(AdvisorCollege).where(AdvisorCollege.school_id == school.id)
        )).scalars().all()
        existing_names = {c.name for c in existing}

        new_colleges: list[AdvisorCollege] = []
        for c in college_records:
            if c["name"] in existing_names:
                continue
            college = AdvisorCollege(
                school_id=school.id,
                name=c["name"],
                english_name=c.get("english_name", ""),
                discipline_category=c.get("discipline_category", ""),
                homepage_url=c.get("url", ""),
            )
            db.add(college)
            new_colleges.append(college)
            colleges_added += 1

        school.colleges_crawled_at = datetime.utcnow()
        await db.flush()

        if fetch_advisors:
            for college in new_colleges:
                if not college.homepage_url:
                    continue
                try:
                    n = await _crawl_one_college_advisors(client, db, school, college)
                    advisors_added += n
                except Exception as e:
                    errors.append(f"{college.name}: {e}")
                # be polite
                await asyncio.sleep(REQUEST_DELAY_SECONDS)

            school.advisor_count = (await db.execute(
                select(Advisor).where(Advisor.school_id == school.id)
            )).scalars().all().__len__()
            school.advisors_crawled_at = datetime.utcnow()

    return {
        "colleges_added": colleges_added,
        "advisors_added": advisors_added,
        "errors": errors,
    }


FACULTY_SUB_KEYWORDS = (
    "教授", "副教授", "讲师", "研究员", "副研究员", "助理研究员",
    "全部教师", "全体教师", "在职教师", "导师", "教师名录", "教师一览",
)


def _find_faculty_sub_links(html: str, base_url: str) -> list[str]:
    """When a 师资 page is just a CMS frame, look for sub-listing pages
    (e.g. 教授 / 副教授 / 全部教师) on it."""
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    out: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href_raw = a["href"].strip()
        if href_raw.startswith(("javascript:", "mailto:", "#")) or not href_raw:
            continue
        href = urljoin(base_url, href_raw)
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        text = re.sub(r"[*\u2022\u25cf\[\]【】]", "", text).strip()
        if not text or len(text) > 20:
            continue
        if not any(k in text for k in FACULTY_SUB_KEYWORDS):
            continue
        if any(neg in text for neg in ("招聘", "聘任", "公告")):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append(href)
        if len(out) >= 6:
            break
    return out


async def _crawl_one_college_advisors(
    client: httpx.AsyncClient,
    db: AsyncSession,
    school: AdvisorSchool,
    college: AdvisorCollege,
) -> int:
    """Inner helper: crawl advisor stubs for one college. Returns count added."""
    college_html = await fetch_html(client, college.homepage_url)
    if not college_html:
        return 0
    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    link_info = await find_faculty_list_link(client, school, college, college_html)
    if not link_info or not link_info.get("url"):
        return 0
    faculty_url = link_info["url"]

    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    faculty_html = await fetch_html(client, faculty_url)
    if not faculty_html:
        return 0

    advisors = await extract_advisor_list(client, school, college, faculty_url, faculty_html)

    # Fallback: if the 师资 page is a CMS frame with no teacher anchors,
    # follow sub-category links (教授 / 副教授 / 全部教师) and merge results.
    if not advisors:
        seen_names: set[str] = set()
        merged: list[dict] = []
        for sub_url in _find_faculty_sub_links(faculty_html, faculty_url):
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
            sub_html = await fetch_html(client, sub_url)
            if not sub_html:
                continue
            for a in heuristic_extract_advisors(sub_html, sub_url):
                if a["name"] in seen_names:
                    continue
                seen_names.add(a["name"])
                merged.append(a)
        advisors = merged

    if not advisors:
        return 0

    existing = (await db.execute(
        select(Advisor).where(Advisor.college_id == college.id)
    )).scalars().all()
    existing_names = {a.name for a in existing}

    added = 0
    new_advisor_names: list[str] = []
    for a in advisors:
        if a["name"] in existing_names:
            continue
        db.add(Advisor(
            school_id=school.id,
            college_id=college.id,
            name=a["name"],
            title=a.get("title", ""),
            homepage_url=a.get("homepage", ""),
            source_url=faculty_url,
            crawl_status="stub",
            crawled_at=datetime.utcnow(),
        ))
        added += 1
        new_advisor_names.append(a["name"])
    college.advisor_count = (college.advisor_count or 0) + added
    college.advisors_crawled_at = datetime.utcnow()
    await db.flush()

    # Reconcile: any unlinked mentions matching these new (school, name) → link up
    if new_advisor_names:
        await reconcile_unlinked_mentions(db, school, new_advisor_names)
        await db.flush()

    return added


async def reconcile_unlinked_mentions(
    db: AsyncSession,
    school: AdvisorSchool,
    advisor_names: list[str] | None = None,
) -> int:
    """Link previously-stored unlinked mentions (advisor_id=0 with pending_*)
    to actual Advisor rows whenever the advisor was newly inserted.

    Matches by pending_school_name == school.name AND pending_advisor_name in
    `advisor_names`. If `advisor_names` is None, attempts to reconcile all
    unlinked mentions for this school.
    """
    stmt = select(AdvisorMention).where(
        AdvisorMention.advisor_id == 0,
        AdvisorMention.pending_school_name == school.name,
    )
    if advisor_names:
        stmt = stmt.where(AdvisorMention.pending_advisor_name.in_(advisor_names))
    pending_rows = (await db.execute(stmt)).scalars().all()
    if not pending_rows:
        return 0

    # Look up the matching advisors in this school in one go
    names_needed = {m.pending_advisor_name for m in pending_rows}
    advisors = (await db.execute(
        select(Advisor).where(
            Advisor.school_id == school.id,
            Advisor.name.in_(names_needed),
        )
    )).scalars().all()
    by_name: dict[str, Advisor] = {a.name: a for a in advisors}

    linked = 0
    for m in pending_rows:
        a = by_name.get(m.pending_advisor_name)
        if not a:
            continue
        m.advisor_id = a.id
        # Keep pending_* for audit; or wipe — choosing to keep
        linked += 1
    if linked:
        logger.info("Reconciled %d unlinked mentions for %s", linked, school.name)
    return linked


# ──────────────────────────── Stage 5: per-advisor detail (Phase 3) ────────────────────────────

ADVISOR_DETAIL_PROMPT = """你正在分析一位中国高校老师的个人主页 HTML。请抽取以下结构化字段并以 JSON 输出。

### 老师
{name}（{school_name} · {college_name}）— {url}

### 主页文本（已剔除导航/脚本）
{text}

### 任务（仅基于上面的文本，不要瞎编）
- title: 职称（教授 / 副教授 / 助理教授 / 研究员 / 副研究员 / 讲师 / 博士后 / 长聘 / 特聘 等）
- is_doctoral_supervisor: true/false（是否博导）
- is_master_supervisor: true/false（是否硕导）
- email: 邮箱地址
- office: 办公地点（如 "电院 3 号楼 305"）
- phone: 电话
- photo_url: 个人照片 URL（如 HTML 里有头像 <img>）
- research_areas: ["视觉生成", "多模态学习", "扩散模型", ...]（具体方向，3-8 个，避免"AI/ML 这种太泛）
- bio: 1-3 句话简介（**只复述主页里写的内容**，不要外推）
- education: [{{"degree":"博士","year":2018,"institution":"清华大学","advisor":"张三"}}, ...]（教育背景）
- honors: ["IEEE Fellow", "杰青", ...]（头衔/奖项；从主页明确写到的提取，不要猜）
- recruiting_intent: 关于招生意愿/招生条件/招生方向的明确陈述（原文摘抄，不要总结）

### 严格 JSON（只输出 JSON）
{{
  "title": "...",
  "is_doctoral_supervisor": true,
  "is_master_supervisor": true,
  "email": "...",
  "office": "...",
  "phone": "...",
  "photo_url": "https://...",
  "research_areas": ["..."],
  "bio": "...",
  "education": [{{"degree":"...","year":2018,"institution":"...","advisor":"..."}}],
  "honors": ["..."],
  "recruiting_intent": "..."
}}

未知字段留空字符串/空数组。
"""


def _clean_advisor_page(html: str) -> str:
    """Strip scripts/styles only, keep all visible content.

    NOTE: 不能去 <header>/<nav>/<footer> — Chinese university faculty pages
    often put real bio content INSIDE these semantic tags due to
    non-standard markup (e.g. Tsinghua CS puts research/honors/email all
    inside <header>). Stripping nav etc. removes 95% of the bio.
    """
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    # Only strip truly inert elements — forms/headers may contain real bio
    # content on Chinese university CMS pages
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    # Trim leading nav-like cruft (breadcrumb headers): everything up to "正文" if present
    if "正文" in text[:1000]:
        text = text[text.index("正文") + 2:]
    # Cap length but generously for advisor bios
    return text[:12000]


def _extract_first_photo(html: str, base_url: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "lxml")
    for img in soup.find_all("img", src=True):
        src = img["src"].strip()
        if not src or src.startswith("data:"):
            continue
        absolute = urljoin(base_url, src)
        # Heuristic: skip layout images (logo / banner / icon)
        low = absolute.lower()
        if any(b in low for b in ("logo", "banner", "icon", "header", "footer", "/ui/", "background")):
            continue
        return absolute
    return ""


def _extract_email_regex(text: str) -> str:
    """Find first email-like string."""
    if not text:
        return ""
    m = re.search(r"[A-Za-z0-9._%+-]+(?:\s*[@]\s*|\s*\[at\]\s*|\s*【at】\s*)[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    if m:
        return re.sub(r"\s*(?:\[at\]|【at】)\s*", "@", m.group(0)).replace(" ", "")[:120]
    return ""


async def crawl_advisor_detail(
    db: AsyncSession,
    advisor: Advisor,
) -> dict:
    """Phase 3: enrich one advisor's record by parsing their homepage with LLM."""
    if not advisor.homepage_url:
        return {"ok": False, "error": "no homepage_url"}

    school = await db.get(AdvisorSchool, advisor.school_id)
    college = await db.get(AdvisorCollege, advisor.college_id)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        html = await fetch_html(client, advisor.homepage_url)
        if not html:
            return {"ok": False, "error": "homepage fetch failed"}

        text = _clean_advisor_page(html)
        photo_fallback = _extract_first_photo(html, advisor.homepage_url)
        email_regex = _extract_email_regex(text)

        prompt = ADVISOR_DETAIL_PROMPT.format(
            name=advisor.name,
            school_name=school.name if school else "",
            college_name=college.name if college else "",
            url=advisor.homepage_url,
            text=text,
        )
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        result = await _call_llm(client, prompt, max_tokens=4000)

    if not isinstance(result, dict):
        return {"ok": False, "error": "LLM returned non-dict"}

    def _str(key: str, max_len: int = 300) -> str:
        return str(result.get(key) or "")[:max_len]

    advisor.title = _str("title", 60) or advisor.title
    advisor.is_doctoral_supervisor = bool(result.get("is_doctoral_supervisor"))
    advisor.is_master_supervisor = bool(result.get("is_master_supervisor"))
    advisor.email = _str("email", 120) or email_regex or advisor.email
    advisor.office = _str("office", 200) or advisor.office
    advisor.phone = _str("phone", 40) or advisor.phone
    advisor.photo_url = _str("photo_url", 500) or photo_fallback or advisor.photo_url

    areas = result.get("research_areas")
    if isinstance(areas, list):
        advisor.research_areas = [str(a)[:80] for a in areas if str(a).strip()][:10]

    advisor.bio = _str("bio", 1500) or advisor.bio

    edu = result.get("education")
    if isinstance(edu, list):
        cleaned = []
        for e in edu[:8]:
            if isinstance(e, dict):
                cleaned.append({
                    "degree": str(e.get("degree", ""))[:40],
                    "year": e.get("year") if isinstance(e.get("year"), int) else None,
                    "institution": str(e.get("institution", ""))[:120],
                    "advisor": str(e.get("advisor", ""))[:80],
                })
        advisor.education = cleaned or None

    honors = result.get("honors")
    if isinstance(honors, list):
        advisor.honors = [str(h)[:80] for h in honors if str(h).strip()][:8]

    advisor.recruiting_intent = _str("recruiting_intent", 1500) or advisor.recruiting_intent
    advisor.crawl_status = "detailed"
    advisor.last_refreshed_at = datetime.utcnow()
    await db.flush()
    return {"ok": True, "advisor_id": advisor.id, "areas_n": len(advisor.research_areas or [])}


async def crawl_college_advisors(db: AsyncSession, college: AdvisorCollege) -> dict:
    """Re-runnable entry: crawl advisors for an existing college record."""
    if not college.homepage_url:
        return {"advisors_added": 0, "errors": ["college has no homepage_url"]}
    school = await db.get(AdvisorSchool, college.school_id)
    if not school:
        return {"advisors_added": 0, "errors": ["school not found"]}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            added = await _crawl_one_college_advisors(client, db, school, college)
        except Exception as e:
            return {"advisors_added": 0, "errors": [str(e)]}
    return {"advisors_added": added, "errors": []}
