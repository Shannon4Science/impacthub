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
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import chardet
import httpx
from bs4 import BeautifulSoup
from sqlalchemy import func, select
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
from app.models import (
    AdvisorSchool,
    AdvisorCollege,
    Advisor,
    AdvisorMention,
    AdvisorEmbeddingMetadata,
    XhsCrawlRun,
)

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

MANUAL_COLLEGE_SEED_PATH = (
    Path(__file__).resolve().parents[3] / "pipeline" / "data" / "advisor_college_seeds.json"
)


def _load_manual_college_seeds() -> dict[str, dict]:
    """Load manually maintained college entry URLs keyed by school name."""
    if not MANUAL_COLLEGE_SEED_PATH.exists():
        return {}

    payload = json.loads(MANUAL_COLLEGE_SEED_PATH.read_text(encoding="utf-8"))
    schools = payload.get("schools", [])
    if not isinstance(schools, list):
        raise ValueError("advisor_college_seeds.json: schools must be a list")

    seeds: dict[str, dict] = {}
    for school_seed in schools:
        if not isinstance(school_seed, dict):
            raise ValueError("advisor_college_seeds.json: each school seed must be an object")
        school_name = (school_seed.get("school") or school_seed.get("school_name") or "").strip()
        if not school_name:
            raise ValueError("advisor_college_seeds.json: school is required")

        colleges = school_seed.get("colleges", [])
        if not isinstance(colleges, list):
            raise ValueError(f"advisor_college_seeds.json: colleges for {school_name} must be a list")
        if not colleges:
            raise ValueError(f"advisor_college_seeds.json: colleges for {school_name} is empty")

        normalized_colleges: list[dict] = []
        for college_seed in colleges:
            if not isinstance(college_seed, dict):
                raise ValueError(f"advisor_college_seeds.json: college seed for {school_name} must be an object")
            name = (college_seed.get("name") or "").strip()
            url = (
                college_seed.get("url")
                or college_seed.get("homepage_url")
                or ""
            ).strip()
            faculty_list_url = (
                college_seed.get("faculty_list_url")
                or college_seed.get("advisor_list_url")
                or ""
            ).strip()
            if not name:
                raise ValueError(f"advisor_college_seeds.json: college name is required for {school_name}")
            if not url:
                raise ValueError(f"advisor_college_seeds.json: url is required for {school_name} / {name}")
            normalized_colleges.append({
                "name": name,
                "english_name": (college_seed.get("english_name") or "").strip(),
                "discipline_category": (college_seed.get("discipline_category") or "").strip(),
                "url": url,
                "faculty_list_url": faculty_list_url,
            })

        seeds[school_name] = {
            "college_index_url": (school_seed.get("college_index_url") or "").strip(),
            "colleges": normalized_colleges,
        }

    return seeds


# ──────────────────────────── HTTP helpers ────────────────────────────

_JS_REDIRECT_RE = re.compile(
    r"""(?:window\.location|window\.location\.href|location\.href|location)\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
_META_REFRESH_RE = re.compile(
    r"""<meta[^>]+http-equiv=['"]?refresh['"]?[^>]+content=['"]?\d+\s*;\s*url=([^'">\s]+)""",
    re.IGNORECASE,
)


def _is_zju_person_generic_index_redirect(source_url: str, target_url: str) -> bool:
    source = urlparse(source_url)
    target = urlparse(target_url)
    if source.netloc.lower() != "person.zju.edu.cn":
        return False
    if target.netloc.lower() != "person.zju.edu.cn":
        return False
    return source.path.rstrip("/") != "/index" and target.path.rstrip("/") == "/index"


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
                            if _is_zju_person_generic_index_redirect(str(resp.url), new_url):
                                logger.info("fetch_html ignored generic ZJU person redirect %s → %s", url, new_url)
                                return None
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

def _fix_unescaped_quotes(raw: str) -> str:
    """Fix unescaped bare double-quotes inside JSON string values.

    LLM sometimes outputs Chinese book-title marks as bare ASCII quotes
    (e.g. "入选教育部"新世纪"") which breaks json.loads. This scans each
    line tracking JSON string state and replaces interior bare quotes with
    a fullwidth left-double-quotation-mark so the JSON becomes parseable.
    """
    lines = raw.split("\n")
    fixed_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped in ("{", "}", "[", "]", "},", "],", ""):
            fixed_lines.append(line)
            continue
        result_chars = []
        in_string = False
        i = 0
        chars = list(line)
        while i < len(chars):
            c = chars[i]
            if c == "\\" and in_string and i + 1 < len(chars):
                result_chars.append(c)
                result_chars.append(chars[i + 1])
                i += 2
                continue
            if c == '"':
                if not in_string:
                    in_string = True
                    result_chars.append(c)
                else:
                    rest = line[i + 1:].lstrip()
                    if not rest or rest[0] in (",", ":", "]", "}", "\n"):
                        in_string = False
                        result_chars.append(c)
                    else:
                        result_chars.append("“")
                i += 1
            else:
                result_chars.append(c)
                i += 1
        fixed_lines.append("".join(result_chars))
    return "\n".join(fixed_lines)


def _parse_json(text: str) -> Any:
    if not text:
        return None
    s = text.strip()
    # Strip Claude <thinking>...</thinking> tags
    s = re.sub(r"<thinking>.*?</thinking>", "", s, flags=re.DOTALL).strip()
    # Strip markdown code block
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        s = s.rsplit("```", 1)[0].strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    # Try fixing unescaped bare quotes
    fixed = _fix_unescaped_quotes(s)
    if fixed != s:
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass
    # Fallback: greedy regex for outermost JSON object or array
    m = re.search(r"(\{.*\}|\[.*\])", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            fixed2 = _fix_unescaped_quotes(m.group())
            try:
                return json.loads(fixed2)
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
    "尾页", "首页", "末页", "第一页", "工程师", "实验师", "技术专员",
    "博导", "硕导", "回国前", "国际会议",
}

# A "name-like" anchor: 2-4 Chinese characters, no English/digits, not a nav word
_NAME_RE = re.compile(r"^[\u4e00-\u9fff·]{2,4}$")
_ZJU_HOST_RE = re.compile(r"(^|\.)zju\.edu\.cn$", re.I)
_FUDAN_HOST_RE = re.compile(r"(^|\.)fudan\.edu\.cn$", re.I)
_TITLE_KEYWORDS = (
    "教授", "副教授", "讲师", "研究员", "副研究员", "助理研究员",
    "特聘教授", "求是", "百人计划", "院士", "博导", "硕导",
)


def _is_zju_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return bool(_ZJU_HOST_RE.search(host))


def _is_fudan_url(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return bool(_FUDAN_HOST_RE.search(host))


def _is_name_like(text: str) -> bool:
    text = re.sub(r"\s+", "", text or "")
    text = re.sub(r"[*\u2022\u25cf\[\]【】（）()]", "", text)
    if not _NAME_RE.match(text):
        return False
    return not any(bad in text for bad in NAVIGATION_BLACKLIST)


def _looks_like_academic_title(text: str) -> bool:
    return any(k in (text or "") for k in _TITLE_KEYWORDS)


def _extract_zju_plain_text_advisors(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """ZJU Webplus pages sometimes list teachers as plain table text, not anchors."""
    candidates: list[dict] = []
    seen_names: set[str] = set()

    for li in soup.find_all("li"):
        li_text = re.sub(r"\s+", " ", li.get_text(" ", strip=True)).strip()
        if not _looks_like_academic_title(li_text):
            continue
        name = ""
        name_el = li.select_one(".con1rmrt")
        if name_el:
            name = re.sub(r"\s+", "", name_el.get_text("", strip=True))
        if not name:
            img = li.find("img", alt=True)
            if img:
                name = re.sub(r"\s+", "", img["alt"])
        if not _is_name_like(name) or name in seen_names:
            continue

        homepage = ""
        for a in li.find_all("a", href=True):
            href = urljoin(base_url, a["href"].strip())
            host = urlparse(href).hostname or ""
            if host == "person.zju.edu.cn":
                homepage = href
                break
            if not homepage and not urlparse(href).path.rstrip("/").endswith("/list.htm"):
                homepage = href

        title = ""
        title_match = re.search(r"([^\n，,；;]{0,12}(?:教授|研究员|讲师|院士))", li_text)
        if title_match:
            title = title_match.group(1).strip()[:60]
            if title.startswith(name):
                title = title[len(name):].strip(" ，,")[:60]
        seen_names.add(name)
        candidates.append({"name": name, "title": title, "homepage": homepage})

    for tr in soup.find_all("tr"):
        cells = [
            re.sub(r"\s+", " ", cell.get_text(" ", strip=True)).strip()
            for cell in tr.find_all(["td", "th"])
        ]
        if len(cells) < 2:
            continue
        for i, cell_text in enumerate(cells):
            name = re.sub(r"\s+", "", cell_text)
            if not _is_name_like(name) or name in seen_names:
                continue
            nearby = " ".join(cells[max(0, i - 1): i + 3])
            if not _looks_like_academic_title(nearby):
                continue
            title = ""
            if i + 1 < len(cells) and _looks_like_academic_title(cells[i + 1]):
                title = cells[i + 1][:60]
            seen_names.add(name)
            candidates.append({"name": name, "title": title, "homepage": ""})

    page_text = soup.get_text("\n", strip=True)
    for match in re.finditer(
        r"(?<![\u4e00-\u9fff])([\u4e00-\u9fff·]{2,4})[，,]\s*([^\n，,]{0,20}(?:教授|研究员|讲师|院士))",
        page_text,
    ):
        name = match.group(1).strip()
        if not _is_name_like(name) or name in seen_names:
            continue
        seen_names.add(name)
        candidates.append({
            "name": name,
            "title": match.group(2).strip()[:60],
            "homepage": "",
        })

    return candidates


def _is_zju_icsr_faculty_url(url: str) -> bool:
    parsed = urlparse(url or "")
    if parsed.hostname != "icsr.zju.edu.cn":
        return False
    return parsed.path.rstrip("/") in {"/jsdw/list.htm", "/jzjr/list.htm"}


def _clean_inline_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    text = re.sub(r"\s+([，,。：；;/])", r"\1", text)
    text = re.sub(r"([，,。：；;/])\s+", r"\1", text)
    return text


def _split_research_areas(text: str) -> list[str]:
    text = re.sub(r"^研究方向[:：]\s*", "", text or "").strip(" 。；;，,")
    if not text:
        return []
    parts = re.split(r"[、,，；;]", text)
    return [p.strip(" /。；;，,")[:80] for p in parts if p.strip(" /。；;，,")][:10]


def _zju_icsr_title_from_text(text: str) -> str:
    title_match = re.search(
        r"(求是讲席教授|求是特聘教授|长聘副教授|百人计划研究员|特聘研究员|"
        r"教授|副教授|研究员|副研究员|助理研究员|讲师|院士)",
        text,
    )
    return title_match.group(1)[:60] if title_match else ""


def _merge_zju_icsr_profile(profiles: dict[str, dict], profile: dict) -> None:
    name = profile.get("name", "")
    if not name:
        return
    existing = profiles.get(name)
    if not existing:
        profiles[name] = profile
        return
    if profile.get("email") and not existing.get("email"):
        existing["email"] = profile["email"]
    if profile.get("title") and not existing.get("title"):
        existing["title"] = profile["title"]
    if profile.get("homepage") and not existing.get("homepage"):
        existing["homepage"] = profile["homepage"]
    if profile.get("research_areas") and not existing.get("research_areas"):
        existing["research_areas"] = profile["research_areas"]
    if profile.get("external_links"):
        seen = {
            item.get("url")
            for item in existing.get("external_links", []) or []
            if isinstance(item, dict)
        }
        merged_links = list(existing.get("external_links", []) or [])
        for item in profile.get("external_links") or []:
            if not isinstance(item, dict) or not item.get("url") or item.get("url") in seen:
                continue
            merged_links.append(item)
            seen.add(item["url"])
        existing["external_links"] = merged_links[:30]
    if len(profile.get("bio", "")) > len(existing.get("bio", "")):
        email = existing.get("email") or profile.get("email", "")
        homepage = existing.get("homepage") or profile.get("homepage", "")
        research_areas = existing.get("research_areas") or profile.get("research_areas") or []
        title = existing.get("title") or profile.get("title", "")
        external_links = existing.get("external_links") or profile.get("external_links") or []
        existing.update(profile)
        existing["email"] = email
        existing["homepage"] = homepage
        existing["research_areas"] = research_areas
        existing["title"] = title
        existing["external_links"] = external_links


def _extract_zju_icsr_text_links(text: str, base_url: str) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _BARE_URL_RE.finditer(text or ""):
        raw_url = m.group(0)
        url = urljoin(base_url, _clean_url_token(raw_url))
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        normalized = parsed._replace(fragment="").geturl()
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append({
            "kind": _classify_link_kind(normalized, ""),
            "url": normalized,
            "label": "导师简介链接",
            "reason": "浙大网安教师队伍页面导师简介中给出的链接",
        })
    return links


def _merge_zju_icsr_long_introductions(
    profiles: dict[str, dict],
    soup: BeautifulSoup,
    base_url: str,
) -> None:
    names = sorted(profiles.keys(), key=len, reverse=True)
    if not names:
        return

    for td in soup.find_all("td"):
        text = _clean_inline_text(td.get_text(" ", strip=True))
        if "导师简介" not in text:
            continue
        text = re.sub(r"^导师简介[:：]\s*", "", text).strip()
        starts: list[tuple[int, str]] = []
        for name in names:
            for m in re.finditer(rf"{re.escape(name)}\s*[，,]", text):
                prefix = text[:m.start()].rstrip()
                if prefix and prefix[-1] not in "。！？/":
                    continue
                intro_head = text[m.start():m.start() + 120]
                if not re.search(r"(教授|研究员|博导|博士生导师|博士|院士|讲席|特聘|百人|青年人才)", intro_head):
                    continue
                starts.append((m.start(), name))
                break
        starts.sort()
        for index, (start, name) in enumerate(starts):
            end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
            segment = text[start:end].strip()
            if len(segment) < 80:
                continue
            links = _extract_zju_icsr_text_links(segment, base_url)
            homepage = ""
            for link in links:
                if link.get("kind") in {"personal_homepage", "blog", "github", "other_academic"}:
                    homepage = link["url"]
                    break
            _merge_zju_icsr_profile(profiles, {
                "name": name,
                "title": _zju_icsr_title_from_text(segment),
                "homepage": homepage,
                "email": _extract_email_regex(segment),
                "research_areas": [],
                "external_links": links,
                "bio": segment[:6000],
                "raw_html": f"<section data-source=\"zju-icsr-long-introduction\">{segment[:100000]}</section>",
            })
        return


def _extract_zju_icsr_advisor_profiles(html: str, base_url: str) -> dict[str, dict]:
    """Extract inline profiles from 浙江大学网安学院教师队伍 pages."""
    if not html or not _is_zju_icsr_faculty_url(base_url):
        return {}
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["nav", "header", "footer", "script", "style", "form"]):
        tag.decompose()

    profiles: dict[str, dict] = {}

    for tr in soup.find_all("tr"):
        cells = [_clean_inline_text(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if len(cells) < 5 or not cells[0].isdigit() or "@" not in cells[-1]:
            continue
        name = re.sub(r"\s+", "", cells[1])
        if not _is_name_like(name):
            continue
        title = cells[2][:60]
        direction = cells[3]
        email = _extract_email_regex(cells[-1]) or cells[-1][:120]
        bio = f"{name}，{title}。研究方向：{direction}。"
        if email:
            bio += f"邮箱：{email}。"
        _merge_zju_icsr_profile(profiles, {
            "name": name,
            "title": title,
            "homepage": "",
            "email": email,
            "research_areas": _split_research_areas(direction),
            "bio": bio,
            "raw_html": str(tr)[:100000],
        })

    is_dual_appointment_page = urlparse(base_url).path.rstrip("/") == "/jzjr/list.htm"
    for td in soup.find_all("td"):
        text = _clean_inline_text(td.get_text(" ", strip=True))
        if not _looks_like_academic_title(text):
            continue
        if "研究方向" not in text and not is_dual_appointment_page:
            continue

        name = ""
        homepage = ""
        for a in td.find_all("a", href=True):
            candidate = re.sub(r"\s+", "", a.get_text("", strip=True))
            if _is_name_like(candidate):
                name = candidate
                homepage = urljoin(base_url, a["href"].strip())
                break
        if not name:
            strong = td.find(["strong", "b"])
            if strong:
                candidate = re.sub(r"\s+", "", strong.get_text("", strip=True))
                if _is_name_like(candidate):
                    name = candidate
        name_match = re.match(r"^([\u4e00-\u9fff·]{2,4})[，,]?\s*(.+)$", text)
        if not name and name_match:
            name = re.sub(r"\s+", "", name_match.group(1))
        if not _is_name_like(name):
            continue

        paragraphs = [
            _clean_inline_text(p.get_text(" ", strip=True))
            for p in td.find_all("p")
            if _clean_inline_text(p.get_text(" ", strip=True))
        ]
        direction = ""
        if is_dual_appointment_page:
            for paragraph in reversed(paragraphs):
                if not any(skip in paragraph for skip in ("大学", "学院", "博士")):
                    direction = paragraph
                    break
        else:
            direction_match = re.search(r"研究方向[:：]\s*(.+)$", text)
            direction = direction_match.group(1).strip(" 。；;，,") if direction_match else ""
        email = _extract_email_regex(text)
        _merge_zju_icsr_profile(profiles, {
            "name": name,
            "title": _zju_icsr_title_from_text(text),
            "homepage": homepage,
            "email": email,
            "research_areas": _split_research_areas(direction),
            "bio": text[:6000],
            "raw_html": str(td)[:100000],
        })

    if urlparse(base_url).path.rstrip("/") == "/jsdw/list.htm":
        _merge_zju_icsr_long_introductions(profiles, soup, base_url)

    return profiles


def _title_from_fudan_text(text: str) -> str:
    m = re.search(
        r"(浩清特聘教授|青年研究员|青年副研究员|助理教授|教授|副教授|"
        r"研究员|副研究员|助理研究员|讲师)",
        text or "",
    )
    return m.group(1)[:60] if m else ""


def _profile_links_from_fudan_homepage(homepage: str, label: str) -> list[dict[str, str]]:
    if not homepage:
        return []
    return [{
        "kind": _classify_link_kind(homepage, label),
        "url": homepage,
        "label": label[:120],
        "reason": "复旦教师列表页给出的教师主页链接",
    }]


def _fudan_display_name_to_cn(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    text = re.sub(r"[*\u2022\u25cf\[\]【】（）()]", "", text)
    text = re.split(r"[|｜/／]", text, maxsplit=1)[0]
    text = re.sub(r"^(Prof\.?|Professor|Dr\.?)", "", text, flags=re.I)
    return text.strip()


def _extract_fudan_inline_advisors(html: str, base_url: str) -> list[dict]:
    """Extract Fudan-specific teacher list layouts.

    Covers:
    - Webplus article tables used by 大数据学院, where each row already contains
      a long bio and research directions.
    - Visual card lists used by AI3.
    - ASP.NET pic lists used by 未来信息创新学院.
    - Composition-unit layouts used by CIRAM-related sites.
    """
    if not html or not _is_fudan_url(base_url):
        return []

    stripped = html.lstrip("\ufeff \t\r\n")
    if stripped.startswith("{") and '"teachers"' in stripped:
        try:
            payload = json.loads(stripped)
        except ValueError:
            payload = {}
        profiles: list[dict] = []
        seen_names: set[str] = set()
        for item in payload.get("teachers", []):
            if not isinstance(item, dict):
                continue
            name = _fudan_display_name_to_cn(str(item.get("name") or ""))
            if not _is_name_like(name) or name in seen_names:
                continue
            seen_names.add(name)
            homepage = str(item.get("homepage") or "").strip()
            image = str(item.get("image") or "").strip()
            research_areas = item.get("researchInterests") or []
            if not isinstance(research_areas, list):
                research_areas = []
            information = _clean_inline_text(str(item.get("information") or ""))
            title = str(item.get("title") or "")[:60]
            bio = information or "，".join(
                part for part in [
                    name,
                    title,
                    "、".join(str(area) for area in research_areas if str(area).strip()),
                ]
                if part
            )
            profiles.append({
                "name": name,
                "title": title,
                "homepage": urljoin(base_url, homepage) if homepage else "",
                "photo_url": urljoin(base_url, image) if image else "",
                "research_areas": [
                    str(area)[:80] for area in research_areas if str(area).strip()
                ][:10],
                "external_links": _profile_links_from_fudan_homepage(homepage, "教师主页"),
                "bio": bio[:6000],
                "raw_html": json.dumps(item, ensure_ascii=False)[:100000],
                "source_url": base_url,
            })
        if profiles:
            return profiles

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["nav", "header", "footer", "script", "style", "form"]):
        tag.decompose()

    profiles: list[dict] = []
    seen_names: set[str] = set()

    def add_profile(profile: dict) -> None:
        name = re.sub(r"\s+", "", str(profile.get("name") or ""))
        if not _is_name_like(name) or name in seen_names:
            return
        profile["name"] = name
        seen_names.add(name)
        profiles.append(profile)

    for row in soup.select(".wp_articlecontent tr"):
        h4 = row.find("h4")
        if not h4:
            continue
        name_anchor = h4.find("a")
        name = re.sub(r"\s+", "", (name_anchor or h4).get_text("", strip=True))
        if not _is_name_like(name):
            continue
        homepage = urljoin(base_url, name_anchor["href"].strip()) if name_anchor and name_anchor.get("href") else ""
        cells = row.find_all("td")
        content_cell = cells[-1] if cells else row
        text = _clean_inline_text(content_cell.get_text(" ", strip=True))
        if len(text) < 20:
            continue
        photo = ""
        img = row.find("img", src=True)
        if img:
            photo = urljoin(base_url, img["src"].strip())
        research_text = ""
        m = re.search(r"主要研究方向[:：]\s*(.+?)(?:。|$)", text)
        if m:
            research_text = m.group(1)
        add_profile({
            "name": name,
            "title": _title_from_fudan_text(text),
            "homepage": homepage,
            "email": _extract_email_regex(text),
            "photo_url": photo,
            "research_areas": _split_research_areas(research_text),
            "external_links": _profile_links_from_fudan_homepage(homepage, "教师主页"),
            "bio": text[:6000],
            "raw_html": str(row)[:100000],
            "source_url": base_url,
        })

    for li in soup.select(".person-box li"):
        anchor = li.find("a", href=True)
        if not anchor:
            continue
        name = _fudan_display_name_to_cn(anchor.get_text("", strip=True))
        if not _is_name_like(name):
            continue
        href = anchor["href"].strip()
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        add_profile({
            "name": name,
            "title": "",
            "homepage": urljoin(base_url, href),
            "bio": name,
            "raw_html": str(li)[:100000],
            "source_url": base_url,
        })

    for li in soup.select(".teachlist .item_list.list2 li.item, .item_list.list2 li.item"):
        anchor = li.find("a", href=True)
        name_el = li.select_one(".item_title")
        if not anchor or not name_el:
            continue
        name = _fudan_display_name_to_cn(name_el.get_text("", strip=True))
        if not _is_name_like(name):
            continue
        title_el = li.select_one(".sub_title")
        info_text = _clean_inline_text(li.get_text(" ", strip=True))
        img = li.find("img", src=True)
        add_profile({
            "name": name,
            "title": _clean_inline_text(title_el.get_text(" ", strip=True))[:60] if title_el else "",
            "homepage": urljoin(base_url, anchor["href"].strip()),
            "email": _extract_email_regex(info_text),
            "office": "",
            "photo_url": urljoin(base_url, img["src"].strip()) if img else "",
            "bio": info_text[:6000],
            "raw_html": str(li)[:100000],
            "source_url": base_url,
        })

    for li in soup.select("ul.news_list.list2 li.news, .news_list.list2 li.news"):
        anchor = li.find("a", href=True)
        if not anchor:
            continue
        label = anchor.get("title") or anchor.get_text("", strip=True)
        name = _fudan_display_name_to_cn(label)
        if not _is_name_like(name):
            continue
        href_raw = anchor["href"].strip()
        if href_raw.startswith(("javascript:", "mailto:", "#")) or not href_raw:
            continue
        href = urljoin(base_url, href_raw)
        if _same_page_url(href, base_url):
            continue
        title = ""
        path = urlparse(href).path
        m = re.search(r"/([a-z0-9_]+|js|fjs)_", path, re.I)
        if m:
            title = {"js": "教授", "fjs": "副教授"}.get(m.group(1).lower(), "")
        add_profile({
            "name": name,
            "title": title,
            "homepage": href,
            "bio": _clean_inline_text(li.get_text(" ", strip=True))[:6000],
            "raw_html": str(li)[:100000],
            "source_url": base_url,
        })

    for li in soup.select("ul.teacher-list li, .teacher-list li"):
        anchor = li.find("a", href=True)
        if not anchor:
            continue
        name_el = li.select_one(".teacher-name")
        name = re.sub(r"\s+", "", (name_el or anchor).get_text("", strip=True))
        if not _is_name_like(name):
            name = re.sub(r"\s+", "", anchor.get("title", ""))
        if not _is_name_like(name):
            continue
        title_text = _clean_inline_text(li.get_text(" ", strip=True))
        img = li.find("img", src=True)
        add_profile({
            "name": name,
            "title": _title_from_fudan_text(title_text),
            "homepage": urljoin(base_url, anchor["href"].strip()),
            "photo_url": urljoin(base_url, img["src"].strip()) if img else "",
            "bio": title_text[:6000],
            "raw_html": str(li)[:100000],
            "source_url": base_url,
        })

    for li in soup.select("ul.pic-list li, .pic-list li"):
        anchors = [a for a in li.find_all("a", href=True) if _is_name_like(a.get_text("", strip=True))]
        if not anchors:
            continue
        anchor = anchors[-1]
        name = re.sub(r"\s+", "", anchor.get_text("", strip=True))
        img = li.find("img", src=True)
        add_profile({
            "name": name,
            "title": "",
            "homepage": urljoin(base_url, anchor["href"].strip()),
            "photo_url": urljoin(base_url, img["src"].strip()) if img else "",
            "bio": "",
            "raw_html": str(li)[:100000],
            "source_url": base_url,
        })

    return profiles


def _fudan_extra_faculty_urls(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if host != "ciram.fudan.edu.cn":
        return []
    return [
        "https://teai.fudan.edu.cn/config/zh.txt",
        "https://faet.fudan.edu.cn/23898/list.htm",
        "https://iiinn.fudan.edu.cn/szdw/list.htm",
        "https://cmxai.fudan.edu.cn/faculty/list.htm",
    ]


def _is_fudan_ai_faculty_url(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower() == "ai.fudan.edu.cn" and parsed.path in {
        "/53161/list.htm",
        "/szdw/list.htm",
    }


def _is_fudan_ai_academic_teacher(row: dict) -> bool:
    rank = str(row.get("exField9") or "").strip()
    title = str(row.get("exField1") or row.get("career") or "").strip()
    academic_rank = rank in {"院士", "正高", "副高"}
    academic_title = bool(re.search(r"院士|教授|研究员|讲师|博导|硕导|导师", title))
    non_academic_title = bool(re.search(r"工程师|实验师|教务|秘书|行政|辅导员|办公室|主管|科研助理|行政助理", title))
    has_supervisor_signal = bool(re.search(r"博导|硕导|导师|助理研究员|助理教授", title))
    return (academic_rank or academic_title) and (not non_academic_title or has_supervisor_signal)


def _is_authoritative_fudan_advisor_source(url: str) -> bool:
    return _is_fudan_ai_faculty_url(url)


def heuristic_extract_advisors(html: str, base_url: str) -> list[dict]:
    """Extract teacher stubs from a 师资 page.

    Pattern: <a> whose text is a 2-4 char Chinese name and href points to a detail page.
    """
    if not html:
        return []
    if _is_zju_icsr_faculty_url(base_url):
        return list(_extract_zju_icsr_advisor_profiles(html, base_url).values())
    fudan_profiles = _extract_fudan_inline_advisors(html, base_url)
    if fudan_profiles:
        return fudan_profiles

    soup = BeautifulSoup(html, "lxml")
    # Strip nav/footer to reduce false positives
    for tag in soup(["nav", "header", "footer", "script", "style", "form"]):
        tag.decompose()

    candidates: list[dict] = []
    seen_names: set[str] = set()
    is_zju = _is_zju_url(base_url)
    for a in soup.find_all("a", href=True):
        href_raw = a["href"].strip()
        if href_raw.startswith(("javascript:", "mailto:", "#")) or not href_raw:
            continue
        href = urljoin(base_url, href_raw)
        if _same_page_url(href, base_url):
            continue
        text = re.sub(r"\s+", "", a.get_text(strip=True))
        text = re.sub(r"[*\u2022\u25cf\[\]【】（）()]", "", text)
        if not _is_name_like(text) and (is_zju or _is_zju_url(href)):
            text = re.sub(r"\s+", "", a.get("title", ""))
            text = re.sub(r"[*\u2022\u25cf\[\]【】（）()]", "", text)
        if not _is_name_like(text):
            continue
        if text in seen_names:
            continue
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
        has_zju_redirect = is_zju and (
            "_redirect" in href_low or "articleid=" in href_low
        )
        has_zju_person_homepage = (urlparse(href).hostname or "") == "person.zju.edu.cn"
        # Generic file-extension fallback (when paired with digits)
        has_doc_ext = href_low.endswith((".htm", ".html", ".aspx", ".jsp"))
        is_cms_list_page = href_path.rstrip("/").endswith("/list.htm")
        if not (
            has_keyword
            or has_zju_redirect
            or has_zju_person_homepage
            or (has_digit and has_doc_ext and not is_cms_list_page)
        ):
            continue
        seen_names.add(text)
        candidates.append({
            "name": text,
            "title": "",
            "homepage": href,
        })

    if is_zju:
        for advisor in _extract_zju_plain_text_advisors(soup, base_url):
            if advisor["name"] in seen_names:
                continue
            seen_names.add(advisor["name"])
            candidates.append(advisor)

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
    colleges_updated = 0

    manual_seed = _load_manual_college_seeds().get(school.name)
    if manual_seed is not None:
        existing = (await db.execute(
            select(AdvisorCollege).where(AdvisorCollege.school_id == school.id)
        )).scalars().all()
        existing_by_name = {c.name: c for c in existing}
        existing_by_clean_name: dict[str, AdvisorCollege] = {}
        for existing_college in existing:
            clean_name = re.sub(r"^\s*>\s*", "", existing_college.name or "").strip()
            existing_by_clean_name.setdefault(clean_name, existing_college)

        colleges_to_crawl: list[AdvisorCollege] = []
        for c in manual_seed["colleges"]:
            existing_college = existing_by_name.get(c["name"]) or existing_by_clean_name.get(c["name"])
            if existing_college:
                old_homepage_url = existing_college.homepage_url
                old_faculty_list_url = existing_college.faculty_list_url
                existing_college.name = c["name"]
                if c.get("english_name"):
                    existing_college.english_name = c["english_name"]
                if c.get("discipline_category"):
                    existing_college.discipline_category = c["discipline_category"]
                existing_college.homepage_url = c.get("url", "")
                if c.get("faculty_list_url"):
                    existing_college.faculty_list_url = c["faculty_list_url"]
                if (
                    existing_college.advisors_crawled_at is None
                    or old_homepage_url != existing_college.homepage_url
                    or old_faculty_list_url != existing_college.faculty_list_url
                ):
                    colleges_to_crawl.append(existing_college)
                colleges_updated += 1
                continue
            college = AdvisorCollege(
                school_id=school.id,
                name=c["name"],
                english_name=c.get("english_name", ""),
                discipline_category=c.get("discipline_category", ""),
                homepage_url=c.get("url", ""),
                faculty_list_url=c.get("faculty_list_url", ""),
            )
            db.add(college)
            colleges_to_crawl.append(college)
            colleges_added += 1

        if manual_seed.get("college_index_url"):
            school.faculty_index_url = manual_seed["college_index_url"]
        school.colleges_crawled_at = datetime.utcnow()
        await db.flush()

        if fetch_advisors:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                for college in colleges_to_crawl:
                    try:
                        n = await _crawl_one_college_advisors(client, db, school, college)
                        advisors_added += n
                    except Exception as e:
                        errors.append(f"{college.name}: {e}")
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)

            school.advisor_count = (await db.execute(
                select(func.count(Advisor.id)).where(Advisor.school_id == school.id)
            )).scalar() or 0
            school.advisors_crawled_at = datetime.utcnow()

        return {
            "colleges_added": colleges_added,
            "colleges_updated": colleges_updated,
            "advisors_added": advisors_added,
            "errors": errors,
            "source": "manual-seed",
        }

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
    "全部教师", "全体教师", "在职教师", "导师", "教师", "教师名录", "教师一览",
    "院士",
)
ZJU_FACULTY_ORG_KEYWORDS = (
    "学科队伍", "研究所", "研究中心", "工程中心", "实验教学中心", "实验中心",
)


def _same_page_url(a: str, b: str) -> bool:
    pa = urlparse(a)
    pb = urlparse(b)
    return (
        (pa.hostname or "").lower() == (pb.hostname or "").lower()
        and pa.path.rstrip("/") == pb.path.rstrip("/")
        and (pa.query or "") == (pb.query or "")
    )


def _find_faculty_sub_links(html: str, base_url: str) -> list[str]:
    """When a 师资 page is just a CMS frame, look for sub-listing pages
    (e.g. 教授 / 副教授 / 全部教师) on it."""
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    out: list[str] = []
    seen: set[str] = set()
    is_zju = _is_zju_url(base_url)
    for a in soup.find_all("a", href=True):
        href_raw = a["href"].strip()
        if href_raw.startswith(("javascript:", "mailto:", "#")) or not href_raw:
            continue
        href = urljoin(base_url, href_raw)
        if _same_page_url(href, base_url):
            continue
        if not urlparse(href).path.rstrip("/").endswith("/list.htm"):
            continue
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        text = re.sub(r"[*\u2022\u25cf\[\]【】]", "", text).strip()
        if not text or len(text) > 30:
            continue
        if text in {"学生内部网", "教师内部网", "会议室预订（内网）", "会议室预订"}:
            continue
        is_faculty_sub = any(k in text for k in FACULTY_SUB_KEYWORDS)
        is_zju_org_sub = is_zju and any(k in text for k in ZJU_FACULTY_ORG_KEYWORDS)
        if not (is_faculty_sub or is_zju_org_sub):
            continue
        if any(neg in text for neg in ("招聘", "聘任", "公告", "退休")):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append(href)
        if len(out) >= 20:
            break
    return out


def _find_fudan_pagination_links(html: str, base_url: str) -> list[str]:
    """Find Fudan faculty pagination links.

    Fudan's relevant CS/AI pages use two common patterns:
    - Webplus: /list.htm, /list2.htm ... with all_pages in the DOM.
    - ASP.NET MvcPager: /Data/List/apy?page=__page__.
    """
    if not html or not _is_fudan_url(base_url):
        return []
    soup = BeautifulSoup(html, "lxml")
    out: list[str] = []
    seen: set[str] = {base_url}

    def add(url: str) -> None:
        absolute = urljoin(base_url, url)
        if absolute in seen:
            return
        seen.add(absolute)
        out.append(absolute)

    for a in soup.select(".wp_paging a[href], .pagination a[href]"):
        href = a["href"].strip()
        if href and not href.startswith(("javascript:", "#")):
            add(href)

    page_count = 0
    all_pages = soup.select_one("em.all_pages")
    if all_pages:
        try:
            page_count = int(all_pages.get_text("", strip=True))
        except ValueError:
            page_count = 0
    if not page_count:
        pager = soup.select_one("[data-pagecount][data-urlformat]")
        if pager:
            try:
                page_count = int(pager.get("data-pagecount") or "0")
            except ValueError:
                page_count = 0
            url_format = pager.get("data-urlformat") or ""
            for page in range(2, min(page_count, 50) + 1):
                add(url_format.replace("__page__", str(page)))
    else:
        parsed = urlparse(base_url)
        path = parsed.path
        for page in range(2, min(page_count, 50) + 1):
            if re.search(r"/list\d*\.htm$", path):
                page_path = re.sub(r"/list\d*\.htm$", f"/list{page}.htm", path)
                add(parsed._replace(path=page_path).geturl())

    return out[:80]


async def _fetch_fudan_general_query_teachers(
    client: httpx.AsyncClient,
    html: str,
    base_url: str,
) -> list[dict]:
    """Fetch dynamic Fudan Webplus teacher lists backed by _wp3services.

    BME currently renders only a placeholder in static HTML and fills the list
    from this endpoint. Ciram uses the same template family, but its public
    endpoint currently returns no rows; in that case this returns [].
    """
    if not html or not _is_fudan_url(base_url):
        return []
    if (
        not _is_fudan_ai_faculty_url(base_url)
        and "_wp3services/generalQuery" not in html
        and "teacherHome" not in html
        and "{标题内容}" not in html
    ):
        return []
    site_match = re.search(r"sudy-wp-siteId=['\"](\d+)['\"]", html)
    if not site_match:
        return []
    endpoint = urljoin(base_url, "/_wp3services/generalQuery")
    return_infos = [
        {"field": "title", "name": "title"},
        {"field": "exField1", "name": "exField1"},
        {"field": "exField3", "name": "exField3"},
        {"field": "exField4", "name": "exField4"},
        {"field": "exField7", "name": "exField7"},
        {"field": "exField9", "name": "exField9"},
        {"field": "exField10", "name": "exField10"},
        {"field": "career", "name": "career"},
        {"field": "phone", "name": "phone"},
        {"field": "firstLetter", "name": "firstLetter"},
        {"field": "email", "name": "email"},
        {"field": "cnUrl", "name": "cnUrl"},
        {"field": "headerPic", "name": "headerPic"},
    ]
    orders = [{"field": "letter", "type": "asc"}]
    form = {
        "queryObj": "teacherHome",
        "siteId": site_match.group(1),
        "level": "1",
        "articleType": "1",
        "pageIndex": "1",
        "rows": "300",
        "orders": json.dumps(orders, ensure_ascii=False),
        "returnInfos": json.dumps(return_infos, ensure_ascii=False),
        "conditions": json.dumps([{"field": "scope", "value": 0, "judge": "="}], ensure_ascii=False),
    }
    resp = await client.post(endpoint, data=form, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
    if resp.status_code not in (200, 202, 203):
        return []
    try:
        payload = resp.json()
    except ValueError:
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []
    advisors: list[dict] = []
    seen_names: set[str] = set()
    is_fudan_ai_faculty = _is_fudan_ai_faculty_url(base_url)
    for row in rows:
        if not isinstance(row, dict):
            continue
        if is_fudan_ai_faculty and not _is_fudan_ai_academic_teacher(row):
            continue
        name = re.sub(r"\s+", "", str(row.get("title") or ""))
        if not _is_name_like(name) or name in seen_names:
            continue
        seen_names.add(name)
        if is_fudan_ai_faculty:
            title = str(row.get("exField1") or row.get("exField9") or row.get("career") or "")[:60]
        else:
            title = str(row.get("exField7") or row.get("exField1") or row.get("career") or "")[:60]
        department = str(row.get("exField3") or row.get("exField4") or "")
        if department.strip() in {"无", "暂无"}:
            department = ""
        rank = str(row.get("exField9") or "")
        talent = str(row.get("exField10") or "")
        if talent.strip() in {"无", "暂无"}:
            talent = ""
        email = str(row.get("email") or "")[:120]
        phone = str(row.get("phone") or "")[:40]
        homepage = urljoin(base_url, str(row.get("cnUrl") or ""))
        photo = urljoin(base_url, str(row.get("headerPic") or "")) if row.get("headerPic") else ""
        bio_parts = [name]
        for part in (title, rank, department, talent):
            if part and part not in bio_parts:
                bio_parts.append(part)
        advisors.append({
            "name": name,
            "title": title,
            "homepage": homepage,
            "email": email,
            "phone": phone,
            "photo_url": photo,
            "bio": "，".join(bio_parts) + "。",
            "external_links": _profile_links_from_fudan_homepage(homepage, "教师主页"),
            "source_url": base_url,
        })
    return advisors


async def _crawl_one_college_advisors(
    client: httpx.AsyncClient,
    db: AsyncSession,
    school: AdvisorSchool,
    college: AdvisorCollege,
) -> int:
    """Inner helper: crawl advisor stubs for one college. Returns count added."""
    faculty_url = (college.faculty_list_url or "").strip()
    if not faculty_url:
        college_html = await fetch_html(client, college.homepage_url)
        if not college_html:
            return 0
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        link_info = await find_faculty_list_link(client, school, college, college_html)
        if not link_info or not link_info.get("url"):
            return 0
        faculty_url = link_info["url"]
        college.faculty_list_url = faculty_url

    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    faculty_html = await fetch_html(client, faculty_url)
    if not faculty_html:
        return 0

    advisors = await extract_advisor_list(client, school, college, faculty_url, faculty_html)
    if _is_fudan_url(faculty_url):
        dynamic_advisors = await _fetch_fudan_general_query_teachers(client, faculty_html, faculty_url)
        seen_dynamic_names = {a["name"] for a in advisors}
        for a in dynamic_advisors:
            if a["name"] in seen_dynamic_names:
                continue
            seen_dynamic_names.add(a["name"])
            advisors.append(a)
    for advisor in advisors:
        advisor.setdefault("source_url", faculty_url)
        if advisor.get("bio"):
            advisor.setdefault("raw_html", faculty_html[:100000])

    # Some Webplus faculty pages are a category frame or only show one institute.
    # Follow the visible sub-list pages and merge them without deleting existing DB rows.
    seen_names: set[str] = {a["name"] for a in advisors}
    for sub_url in _find_faculty_sub_links(faculty_html, faculty_url):
        if _same_page_url(sub_url, faculty_url):
            continue
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        sub_html = await fetch_html(client, sub_url)
        if not sub_html:
            continue
        for a in heuristic_extract_advisors(sub_html, sub_url):
            if a["name"] in seen_names:
                continue
            a.setdefault("source_url", sub_url)
            if a.get("bio"):
                a.setdefault("raw_html", sub_html[:100000])
            seen_names.add(a["name"])
            advisors.append(a)

    # Fudan CS/AI pages often put most teachers on explicit pagination pages.
    for page_url in _find_fudan_pagination_links(faculty_html, faculty_url):
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        page_html = await fetch_html(client, page_url)
        if not page_html:
            continue
        page_advisors = heuristic_extract_advisors(page_html, page_url)
        dynamic_page_advisors = await _fetch_fudan_general_query_teachers(client, page_html, page_url)
        page_advisors.extend(dynamic_page_advisors)
        for a in page_advisors:
            if a["name"] in seen_names:
                continue
            a.setdefault("source_url", page_url)
            if a.get("bio"):
                a.setdefault("raw_html", page_html[:100000])
            seen_names.add(a["name"])
            advisors.append(a)

    # CIRAM's own current 师资 page is empty, while its official 组成单位
    # point to separate public faculty lists. Aggregate those URLs only for
    # this Fudan site-specific adapter.
    for extra_url in _fudan_extra_faculty_urls(faculty_url):
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        extra_html = await fetch_html(client, extra_url)
        if not extra_html:
            continue
        extra_pages = [(extra_url, extra_html)]
        for page_url in _find_fudan_pagination_links(extra_html, extra_url):
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
            page_html = await fetch_html(client, page_url)
            if page_html:
                extra_pages.append((page_url, page_html))
        for page_url, page_html in extra_pages:
            page_advisors = heuristic_extract_advisors(page_html, page_url)
            dynamic_page_advisors = await _fetch_fudan_general_query_teachers(client, page_html, page_url)
            page_advisors.extend(dynamic_page_advisors)
            for a in page_advisors:
                if a["name"] in seen_names:
                    continue
                a.setdefault("source_url", page_url)
                if a.get("bio"):
                    a.setdefault("raw_html", page_html[:100000])
                seen_names.add(a["name"])
                advisors.append(a)

    if not advisors:
        return 0

    existing = (await db.execute(
        select(Advisor).where(Advisor.college_id == college.id)
    )).scalars().all()
    authoritative_sync = _is_authoritative_fudan_advisor_source(faculty_url)
    if authoritative_sync:
        current_names = {a["name"] for a in advisors}
        stale_advisors = [a for a in existing if a.name not in current_names]
        stale_by_id = {a.id: a for a in stale_advisors}
        if stale_by_id:
            stale_ids = list(stale_by_id)
            stale_mentions = (await db.execute(
                select(AdvisorMention).where(AdvisorMention.advisor_id.in_(stale_ids))
            )).scalars().all()
            for mention in stale_mentions:
                stale_advisor = stale_by_id.get(mention.advisor_id)
                if stale_advisor:
                    mention.pending_advisor_name = mention.pending_advisor_name or stale_advisor.name
                    mention.pending_school_name = mention.pending_school_name or school.name
                    mention.advisor_id = 0
            stale_embeddings = (await db.execute(
                select(AdvisorEmbeddingMetadata).where(AdvisorEmbeddingMetadata.advisor_id.in_(stale_ids))
            )).scalars().all()
            for embedding in stale_embeddings:
                await db.delete(embedding)
            stale_xhs_runs = (await db.execute(
                select(XhsCrawlRun).where(XhsCrawlRun.advisor_id.in_(stale_ids))
            )).scalars().all()
            for run in stale_xhs_runs:
                await db.delete(run)
            for stale_advisor in stale_advisors:
                await db.delete(stale_advisor)
            existing = [a for a in existing if a.name in current_names]
    existing_by_name = {a.name: a for a in existing}

    added = 0
    new_advisor_names: list[str] = []
    for a in advisors:
        source_url = a.get("source_url", faculty_url)
        is_source_adapter_detail = (
            _is_zju_icsr_faculty_url(source_url)
            or _is_fudan_url(source_url)
        )
        existing_advisor = existing_by_name.get(a["name"])
        if existing_advisor:
            if a.get("title"):
                existing_advisor.title = a["title"]
            if a.get("homepage"):
                existing_advisor.homepage_url = a["homepage"]
            if a.get("email"):
                existing_advisor.email = str(a["email"])[:120]
            if a.get("phone"):
                existing_advisor.phone = str(a["phone"])[:40]
            if a.get("photo_url"):
                existing_advisor.photo_url = str(a["photo_url"])[:500]
            if isinstance(a.get("research_areas"), list):
                existing_advisor.research_areas = [
                    str(area)[:80] for area in a["research_areas"] if str(area).strip()
                ][:10]
            if isinstance(a.get("external_links"), list):
                existing_advisor.external_links = a["external_links"][:30] or existing_advisor.external_links
            if a.get("bio"):
                if not (existing_advisor.crawl_status == "detailed" and is_source_adapter_detail):
                    existing_advisor.bio = str(a["bio"])[:6000]
                    existing_advisor.crawl_status = "partial" if is_source_adapter_detail else "detailed"
                    if a.get("raw_html"):
                        existing_advisor.raw_html = str(a["raw_html"])[:100000]
            existing_advisor.source_url = a.get("source_url", faculty_url)
            existing_advisor.crawled_at = datetime.utcnow()
            continue
        db.add(Advisor(
            school_id=school.id,
            college_id=college.id,
            name=a["name"],
            title=a.get("title", ""),
            homepage_url=a.get("homepage", ""),
            email=str(a.get("email", ""))[:120],
            phone=str(a.get("phone", ""))[:40],
            photo_url=str(a.get("photo_url", ""))[:500],
            research_areas=[
                str(area)[:80] for area in a.get("research_areas", []) if str(area).strip()
            ][:10] if isinstance(a.get("research_areas"), list) else [],
            external_links=a.get("external_links")[:30] if isinstance(a.get("external_links"), list) else None,
            bio=str(a.get("bio", ""))[:6000],
            raw_html=str(a.get("raw_html", ""))[:100000],
            source_url=source_url,
            crawl_status="partial" if is_source_adapter_detail and a.get("bio") else "detailed" if a.get("bio") else "stub",
            crawled_at=datetime.utcnow(),
        ))
        added += 1
        new_advisor_names.append(a["name"])
    college.advisor_count = len(existing_by_name) + added if authoritative_sync else (college.advisor_count or 0) + added
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

### 页面链接（从 HTML 正文和 a[href] 中抽出的真实 URL）
{links}

### 任务（仅基于上面的文本，不要瞎编）
- title: 职称（教授 / 副教授 / 助理教授 / 研究员 / 副研究员 / 讲师 / 博士后 / 长聘 / 特聘 等）
- title 要保留主页里的最具体原文短语；例如“百人计划研究员”不要简化成“研究员”
- is_doctoral_supervisor: true/false/null（只有主页明确写“博士生导师/博导”才填 true；明确否定才填 false；没写填 null）
- is_master_supervisor: true/false/null（只有主页明确写“硕士生导师/硕导”才填 true；明确否定才填 false；没写填 null；不要因为是博导就推断为硕导）
- email: 邮箱地址
- office: 办公地点（如 "电院 3 号楼 305"）
- phone: 电话
- photo_url: 个人照片 URL（如 HTML 里有头像 <img>）
- research_areas: ["视觉生成", "多模态学习", "扩散模型", ...]（具体方向，3-12 个，避免"AI/ML"这种太泛）
- bio: 3-5 句话简介（**只复述主页里写的内容**，不要外推）。比一句话简介更完整，但不要写成长篇小传：
  - 优先保留主要任职、关键教育/工作经历、研究方向、代表性学术成果或论文指标。
  - 重要奖项、学生培养、招生表述如果主页明确写出，也可以压缩进简介；不要为了短而删掉最关键的信息。
  - 只要主页文本里有姓名、职称、学院、研究方向、联系方式等基本信息，bio 就不要留空；可以客观写明“主页未提供更多经历/成果信息”。
- education: [{{"degree":"博士","year":2018,"institution":"清华大学","advisor":"张三"}}, ...]（教育背景）
- honors: ["IEEE Fellow", "杰青", ...]（明确奖项、荣誉、人才项目；尽量完整保留；不要收录博导/硕导、单位、研究方向）
- recruiting_intent: 关于招生意愿/招生条件/招生方向的明确陈述（原文摘抄，不要总结）
- external_links: 从“页面链接”里挑出对导师画像、学术身份确认、论文指标、开源项目、实验室/招生信息有价值的链接。
  - 只能使用“页面链接”中真实出现的 URL，不要编造 URL。
  - 忽略学校首页、学院首页、登录、搜索、语言切换、栏目锚点、分享、统计等导航链接。
  - kind 只能从以下值中选：
    personal_homepage / lab / google_scholar / semantic_scholar / dblp / orcid / github / huggingface / cv / publications / recruitment / blog / social / other_academic

### 严格 JSON（只输出 JSON）
{{
  "title": "...",
  "is_doctoral_supervisor": true,
  "is_master_supervisor": null,
  "email": "...",
  "office": "...",
  "phone": "...",
  "photo_url": "https://...",
  "research_areas": ["..."],
  "bio": "3-5句话的经历、成果和主页简介...",
  "education": [{{"degree":"...","year":2018,"institution":"...","advisor":"..."}}],
  "honors": ["..."],
  "recruiting_intent": "...",
  "external_links": [
    {{"kind": "github", "url": "https://github.com/...", "label": "GitHub", "reason": "老师主页明确挂出的代码主页"}}
  ]
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


GENERIC_CONTACT_EMAILS = {
    "cs_school@fudan.edu.cn",
    "ciram_dzb@fudan.edu.cn",
}


def _drop_generic_contact_email(email: str) -> str:
    normalized = (email or "").strip().lower()
    if normalized in GENERIC_CONTACT_EMAILS:
        return ""
    return email


_BARE_URL_RE = re.compile(r"https?://[^\s<>'\"，。；;、）)】\]\}]+", re.IGNORECASE)

_LINK_KIND_BY_DOMAIN = [
    ("scholar.google.", "google_scholar"),
    ("semanticscholar.org", "semantic_scholar"),
    ("dblp.org", "dblp"),
    ("orcid.org", "orcid"),
    ("github.com", "github"),
    ("huggingface.co", "huggingface"),
]

_NAV_LINK_LABELS = {
    "首页", "home", "学校概况", "zju profile", "浙大服务", "zju services",
    "关于主页", "about", "中文", "english", "登录", "logout", "main",
    "管理主页", "退出登录", "平台统计", "platform statistics", "搜全文", "搜基本信息",
}


def _clean_url_token(value: str) -> str:
    return value.strip().strip(" \t\r\n\"'<>，。；;、）)】]}.,")


def _classify_link_kind(url: str, label: str = "") -> str:
    low_url = url.lower()
    low_label = label.lower()
    for domain, kind in _LINK_KIND_BY_DOMAIN:
        if domain in low_url:
            return kind
    if low_url.endswith(".pdf") or "cv" in low_label or "简历" in label:
        return "cv"
    if any(k in low_label for k in ("publication", "paper", "selected papers")) or any(k in label for k in ("论文", "成果", "代表作")):
        return "publications"
    if any(k in low_label for k in ("lab", "group")) or any(k in label for k in ("实验室", "课题组", "团队")):
        return "lab"
    if any(k in low_label for k in ("blog", "posts")) or any(k in label for k in ("博客", "文章")):
        return "blog"
    if any(k in low_label for k in ("recruit", "opening", "admission")) or any(k in label for k in ("招生", "招聘")):
        return "recruitment"
    if any(k in low_label for k in ("homepage", "personal website", "website")) or any(k in label for k in ("个人主页", "主页")):
        return "personal_homepage"
    return "other_academic"


def _extract_link_candidates(html: str, base_url: str, *, max_links: int = 120) -> list[dict[str, str]]:
    """Extract real URL candidates before LLM filtering.

    This keeps both href links and bare URLs pasted as text. The LLM only
    decides which candidate is valuable; it should not invent URLs.
    """
    if not html:
        return []

    base_host = urlparse(base_url).netloc.lower()
    seen: set[str] = set()
    candidates: list[dict[str, str]] = []

    def add(url: str, label: str, source: str) -> None:
        cleaned = _clean_url_token(url)
        if not cleaned:
            return
        absolute = urljoin(base_url, cleaned)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            return
        if parsed.fragment and parsed._replace(fragment="").geturl().rstrip("/") == base_url.rstrip("/"):
            return
        normalized = parsed._replace(fragment="").geturl()
        label_clean = re.sub(r"\s+", " ", (label or "")).strip()[:120]
        if label_clean.lower() in _NAV_LINK_LABELS:
            return
        if normalized in seen:
            return
        seen.add(normalized)

        kind = _classify_link_kind(normalized, label_clean)
        host = parsed.netloc.lower()
        is_same_site = host == base_host
        is_known = kind != "other_academic"
        if is_same_site and not is_known:
            return
        candidates.append({
            "kind_hint": kind,
            "url": normalized,
            "label": label_clean,
            "source": source,
        })

    soup = BeautifulSoup(html, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        add(href, a.get_text(" ", strip=True), "href")

    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    visible_text = soup.get_text("\n", strip=True)
    for m in _BARE_URL_RE.finditer(visible_text):
        add(m.group(0), "", "text")

    candidates.sort(key=lambda item: (
        0 if item["kind_hint"] != "other_academic" else 1,
        0 if item["source"] == "text" else 1,
        item["url"],
    ))
    return candidates[:max_links]


def _format_link_candidates_for_prompt(candidates: list[dict[str, str]]) -> str:
    if not candidates:
        return "[]"
    compact = [
        {
            "kind_hint": c.get("kind_hint", ""),
            "url": c.get("url", ""),
            "label": c.get("label", ""),
            "source": c.get("source", ""),
        }
        for c in candidates
    ]
    return json.dumps(compact, ensure_ascii=False, indent=2)


def _sanitize_external_links(value: Any, candidates: list[dict[str, str]]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    allowed = {c["url"]: c for c in candidates if c.get("url")}
    cleaned: list[dict[str, str]] = []
    seen: set[str] = set()
    allowed_kinds = {
        "personal_homepage", "lab", "google_scholar", "semantic_scholar", "dblp",
        "orcid", "github", "huggingface", "cv", "publications", "recruitment",
        "blog", "social", "other_academic",
    }
    for item in value:
        if not isinstance(item, dict):
            continue
        url = _clean_url_token(str(item.get("url") or ""))
        if url not in allowed or url in seen:
            continue
        kind = str(item.get("kind") or allowed[url].get("kind_hint") or "other_academic")
        if kind not in allowed_kinds:
            kind = allowed[url].get("kind_hint") or "other_academic"
        label = str(item.get("label") or allowed[url].get("label") or "")[:120]
        reason = str(item.get("reason") or "")[:300]
        cleaned.append({"kind": kind, "url": url, "label": label, "reason": reason})
        seen.add(url)
        if len(cleaned) >= 30:
            break
    return cleaned


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "是", "有", "1"}:
            return True
        if normalized in {"false", "no", "否", "无", "0"}:
            return False
    return None


def _sanitize_honors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    blocked_exact = {"博士生导师", "硕士生导师", "博导", "硕导"}
    honors: list[str] = []
    seen: set[str] = set()
    for raw in value[:40]:
        honor = str(raw).strip()[:160]
        if not honor:
            continue
        compact = re.sub(r"\s+", "", honor)
        if compact in blocked_exact:
            continue
        if honor in seen:
            continue
        seen.add(honor)
        honors.append(honor)
        if len(honors) >= 30:
            break
    return honors


async def _expand_zju_person_page(
    client: httpx.AsyncClient,
    html: str,
    base_url: str,
) -> tuple[str, list[str]]:
    """Merge async columns for person.zju.edu.cn profile pages."""
    parsed = urlparse(base_url)
    if parsed.netloc.lower() != "person.zju.edu.cn":
        return html, []

    # ZJU's column JSON endpoints are frequently guarded by anti-spider
    # validation. The reader render has proven to expose the same visible page
    # content with one request, so use it first and keep column probing only as
    # a fallback.
    reader_errors: list[str] = []
    try:
        status_code, markdown = await _fetch_zju_reader_markdown(base_url)
    except Exception as exc:
        reader_errors.append(f"reader: {type(exc).__name__}")
    else:
        if status_code in (200, 202, 203) and markdown.strip() and "Markdown Content:" in markdown:
            return f"{html}\n<section data-zju-reader='jina'><h2>ZJU Reader Render</h2><pre>{markdown}</pre></section>", []
        reader_errors.append(f"reader: HTTP {status_code}")

    page_uid = ""
    api_column = ""
    site_path = "/person"
    m = re.search(r"pageUid\s*=\s*['\"]([^'\"]+)['\"]", html)
    if m:
        page_uid = m.group(1)
    m = re.search(r"apiColumn\s*=\s*['\"]([^'\"]+)['\"]", html)
    if m:
        api_column = m.group(1)
    m = re.search(r"site_path\s*=\s*['\"]([^'\"]+)['\"]", html)
    if m:
        site_path = m.group(1)
    if not page_uid or not api_column:
        return html, []

    soup = BeautifulSoup(html, "lxml")
    columns: list[tuple[str, str]] = []
    for li in soup.select("li[col]"):
        column_id = (li.get("col") or "").strip()
        if not column_id:
            continue
        label = li.get_text(" ", strip=True)
        if column_id not in {c[0] for c in columns}:
            columns.append((column_id, label))

    merged = [html]
    errors: list[str] = reader_errors[:]
    merged_columns = 0
    for index, (column_id, label) in enumerate(columns[:12]):
        if index:
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
        sep = "&" if "?" in api_column else "?"
        column_url = urljoin(base_url, f"{site_path}{api_column}{sep}column_id={column_id}&pageUid={page_uid}&type=1")
        try:
            status_code, body = await _fetch_zju_column_html(column_url)
        except Exception as exc:
            errors.append(f"{label or column_id}: {type(exc).__name__}")
            continue
        if status_code not in (200, 202, 203):
            errors.append(f"{label or column_id}: HTTP {status_code}")
            continue
        if "asValidate" in body or "请验证以继续访问" in body:
            errors.append(f"{label or column_id}: anti-spider validation")
            continue
        content = ""
        try:
            data = json.loads(body)
            raw_data = data.get("data")
            if isinstance(raw_data, dict):
                content = str(raw_data.get("content") or raw_data.get("summary") or "")
            elif isinstance(raw_data, str):
                content = raw_data
        except Exception:
            content = body
        if content.strip():
            merged.append(f"<section data-zju-column='{column_id}'><h2>{label}</h2>{content}</section>")
            merged_columns += 1

    if errors or not merged_columns:
        try:
            status_code, markdown = await _fetch_zju_reader_markdown(base_url)
        except Exception as exc:
            errors.append(f"reader: {type(exc).__name__}")
        else:
            if status_code in (200, 202, 203) and markdown.strip() and "Markdown Content:" in markdown:
                merged.append(f"<section data-zju-reader='jina'><h2>ZJU Reader Render</h2><pre>{markdown}</pre></section>")
            else:
                errors.append(f"reader: HTTP {status_code}")

    if errors:
        logger.warning("ZJU person adapter partial failures for %s: %s", base_url, "; ".join(errors[:5]))
    return "\n".join(merged), errors


async def _fetch_zju_column_html(column_url: str) -> tuple[int, str]:
    """Fetch a ZJU async column with a clean curl request.

    person.zju.edu.cn exposes the column data as JSON, but the anti-spider
    layer is sensitive to Python/httpx sessions and cookies. A stateless curl
    request using only the signed URL is the smallest ZJU-specific adaptation
    that matched the site behavior in probing.
    """
    proc = await asyncio.create_subprocess_exec(
        "curl",
        "-L",
        "--silent",
        "--show-error",
        "--max-time",
        str(int(REQUEST_TIMEOUT)),
        "--write-out",
        "\n%{http_code}",
        "-A",
        "curl/8.7.1",
        "-H",
        "Accept: */*",
        column_url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(detail or f"curl exited {proc.returncode}")

    raw = stdout.decode("utf-8", "replace")
    body, sep, code_text = raw.rpartition("\n")
    if not sep:
        return 0, raw
    try:
        return int(code_text.strip()), body
    except ValueError:
        return 0, raw


async def _fetch_zju_reader_markdown(base_url: str) -> tuple[int, str]:
    parsed = urlparse(base_url)
    clean_url = parsed._replace(fragment="").geturl()
    reader_url = f"https://r.jina.ai/{clean_url}"
    proc = await asyncio.create_subprocess_exec(
        "curl",
        "-L",
        "--silent",
        "--show-error",
        "--max-time",
        str(int(REQUEST_TIMEOUT)),
        "--write-out",
        "\n%{http_code}",
        "-A",
        "curl/8.7.1",
        reader_url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(detail or f"curl exited {proc.returncode}")

    raw = stdout.decode("utf-8", "replace")
    body, sep, code_text = raw.rpartition("\n")
    if not sep:
        return 0, raw
    try:
        return int(code_text.strip()), body
    except ValueError:
        return 0, raw


async def _prepare_advisor_page_context(
    client: httpx.AsyncClient,
    url: str,
) -> tuple[str, str, list[dict[str, str]], list[str]]:
    html = await fetch_html(client, url)
    if not html:
        return "", "", [], ["homepage fetch failed"]
    merged_html, adapter_errors = await _expand_zju_person_page(client, html, url)
    text = _clean_advisor_page(merged_html)
    links = _extract_link_candidates(merged_html, url)
    return merged_html, text, links, adapter_errors


async def _crawl_zju_icsr_source_detail(
    client: httpx.AsyncClient,
    advisor: Advisor,
    school: AdvisorSchool | None,
    college: AdvisorCollege | None,
) -> dict:
    source_url = (advisor.source_url or "").strip()
    if not _is_zju_icsr_faculty_url(source_url):
        return {"ok": False, "error": "no homepage_url"}

    html = await fetch_html(client, source_url)
    if not html:
        return {"ok": False, "error": "source page fetch failed"}

    profile = _extract_zju_icsr_advisor_profiles(html, source_url).get(advisor.name)
    if not profile:
        return {"ok": False, "error": "advisor not found in ZJU ICSR source page"}

    raw_html = str(profile.get("raw_html") or html[:100000])
    text = _clean_advisor_page(raw_html)
    link_candidates = _extract_link_candidates(raw_html, source_url)
    for item in profile.get("external_links") or []:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        url = str(item["url"])
        if any(candidate.get("url") == url for candidate in link_candidates):
            continue
        link_candidates.append({
            "kind_hint": str(item.get("kind") or _classify_link_kind(url, str(item.get("label") or ""))),
            "url": url,
            "label": str(item.get("label") or "")[:120],
            "source": "text",
        })

    prompt = ADVISOR_DETAIL_PROMPT.format(
        name=advisor.name,
        school_name=school.name if school else "",
        college_name=college.name if college else "",
        url=source_url,
        text=text,
        links=_format_link_candidates_for_prompt(link_candidates),
    )
    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    result = await _call_llm(client, prompt, max_tokens=4000)
    if not isinstance(result, dict):
        return {"ok": False, "error": "LLM returned non-dict"}

    def _str(key: str, max_len: int = 300) -> str:
        return str(result.get(key) or "")[:max_len]

    advisor.title = str(profile.get("title") or "")[:60] or advisor.title
    advisor.title = _str("title", 60) or advisor.title
    advisor.is_doctoral_supervisor = _optional_bool(result.get("is_doctoral_supervisor"))
    advisor.is_master_supervisor = _optional_bool(result.get("is_master_supervisor"))
    advisor.email = (
        _drop_generic_contact_email(_str("email", 120))
        or _drop_generic_contact_email(str(profile.get("email") or "")[:120])
        or advisor.email
    )
    advisor.office = _str("office", 200) or advisor.office
    advisor.phone = _str("phone", 40) or advisor.phone
    advisor.photo_url = _str("photo_url", 500) or advisor.photo_url
    areas = result.get("research_areas") or profile.get("research_areas")
    if isinstance(areas, list):
        advisor.research_areas = [str(a)[:80] for a in areas if str(a).strip()][:10]
    if profile.get("homepage"):
        advisor.homepage_url = str(profile["homepage"])[:500]
    advisor.bio = _str("bio", 6000) or advisor.bio
    edu = result.get("education")
    if isinstance(edu, list):
        advisor.education = [
            {
                "degree": str(e.get("degree", ""))[:40],
                "year": e.get("year") if isinstance(e.get("year"), int) else None,
                "institution": str(e.get("institution", ""))[:120],
                "advisor": str(e.get("advisor", ""))[:80],
            }
            for e in edu[:8]
            if isinstance(e, dict)
        ] or None
    honors = result.get("honors")
    if isinstance(honors, list):
        advisor.honors = _sanitize_honors(honors) or None
    advisor.recruiting_intent = _str("recruiting_intent", 3000) or advisor.recruiting_intent
    parsed_links = _sanitize_external_links(result.get("external_links"), link_candidates)
    advisor.external_links = parsed_links or profile.get("external_links") or None
    advisor.raw_html = raw_html[:100000]
    advisor.crawl_status = "detailed" if (advisor.bio or "").strip() else "partial"
    advisor.last_refreshed_at = datetime.utcnow()
    return {
        "ok": True,
        "advisor_id": advisor.id,
        "areas_n": len(advisor.research_areas or []),
        "external_links_n": len(advisor.external_links or []),
        "bio_present": bool((advisor.bio or "").strip()),
        "adapter_errors": [],
    }


async def crawl_advisor_detail(
    db: AsyncSession,
    advisor: Advisor,
) -> dict:
    """Phase 3: enrich one advisor's record by parsing their homepage with LLM."""
    school = await db.get(AdvisorSchool, advisor.school_id)
    college = await db.get(AdvisorCollege, advisor.college_id)

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        if not advisor.homepage_url:
            return await _crawl_zju_icsr_source_detail(client, advisor, school, college)

        html, text, link_candidates, adapter_errors = await _prepare_advisor_page_context(client, advisor.homepage_url)
        if not html:
            return {"ok": False, "error": "; ".join(adapter_errors) or "homepage fetch failed"}

        photo_fallback = _extract_first_photo(html, advisor.homepage_url)
        email_regex = _drop_generic_contact_email(_extract_email_regex(text))

        prompt = ADVISOR_DETAIL_PROMPT.format(
            name=advisor.name,
            school_name=school.name if school else "",
            college_name=college.name if college else "",
            url=advisor.homepage_url,
            text=text,
            links=_format_link_candidates_for_prompt(link_candidates),
        )
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
        result = await _call_llm(client, prompt, max_tokens=4000)

    if not isinstance(result, dict):
        return {"ok": False, "error": "LLM returned non-dict"}

    def _str(key: str, max_len: int = 300) -> str:
        return str(result.get(key) or "")[:max_len]

    advisor.title = _str("title", 60) or advisor.title
    advisor.is_doctoral_supervisor = _optional_bool(result.get("is_doctoral_supervisor"))
    advisor.is_master_supervisor = _optional_bool(result.get("is_master_supervisor"))
    advisor.email = _drop_generic_contact_email(_str("email", 120)) or email_regex or advisor.email
    advisor.office = _str("office", 200) or advisor.office
    advisor.phone = _str("phone", 40) or advisor.phone
    advisor.photo_url = _str("photo_url", 500) or photo_fallback or advisor.photo_url

    areas = result.get("research_areas")
    if isinstance(areas, list):
        advisor.research_areas = [str(a)[:80] for a in areas if str(a).strip()][:10]

    advisor.bio = _str("bio", 6000) or advisor.bio
    bio_present = bool((advisor.bio or "").strip())

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
        advisor.honors = _sanitize_honors(honors) or None

    advisor.recruiting_intent = _str("recruiting_intent", 3000) or advisor.recruiting_intent
    parsed_links = _sanitize_external_links(result.get("external_links"), link_candidates)
    if link_candidates or not adapter_errors:
        advisor.external_links = parsed_links or None
    advisor.raw_html = html[:100000]
    advisor.crawl_status = "detailed" if bio_present else "partial"
    advisor.last_refreshed_at = datetime.utcnow()
    await db.flush()
    return {
        "ok": True,
        "advisor_id": advisor.id,
        "areas_n": len(advisor.research_areas or []),
        "external_links_n": len(advisor.external_links or []),
        "bio_present": bio_present,
        "adapter_errors": adapter_errors,
    }


async def crawl_college_advisors(db: AsyncSession, college: AdvisorCollege) -> dict:
    """Re-runnable entry: crawl advisors for an existing college record."""
    if not college.homepage_url and not college.faculty_list_url:
        return {"advisors_added": 0, "errors": ["college has no homepage_url or faculty_list_url"]}
    school = await db.get(AdvisorSchool, college.school_id)
    if not school:
        return {"advisors_added": 0, "errors": ["school not found"]}
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            added = await _crawl_one_college_advisors(client, db, school, college)
        except Exception as e:
            return {"advisors_added": 0, "errors": [str(e)]}
    return {"advisors_added": added, "errors": []}
