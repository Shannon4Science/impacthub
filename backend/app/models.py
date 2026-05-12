from datetime import datetime, date

from sqlalchemy import Boolean, String, Integer, Float, Text, DateTime, Date, ForeignKey, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    avatar_url: Mapped[str] = mapped_column(String(500), default="")
    bio: Mapped[str] = mapped_column(Text, default="")
    scholar_id: Mapped[str] = mapped_column(String(100), default="")
    github_username: Mapped[str] = mapped_column(String(100), default="")
    hf_username: Mapped[str] = mapped_column(String(100), default="")
    twitter_username: Mapped[str] = mapped_column(String(100), default="")
    homepage: Mapped[str] = mapped_column(String(500), default="")
    feishu_webhook: Mapped[str] = mapped_column(String(500), default="")
    visible: Mapped[bool] = mapped_column(Boolean, default=False)
    # Honor tags (杰青 / 长江 / ACM Fellow / 院士 / Turing Award ...). NULL = not yet set.
    honor_tags: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    # Seed/leaderboard metadata (NULL for non-seed users)
    research_direction: Mapped[str] = mapped_column(String(20), default="")  # llm/cv/vlm/systems/theory/rl
    seed_tier: Mapped[str] = mapped_column(String(20), default="")            # senior/mid/rising
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    papers: Mapped[list["Paper"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    repos: Mapped[list["GithubRepo"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    hf_items: Mapped[list["HFItem"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    milestones: Mapped[list["Milestone"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    snapshots: Mapped[list["DataSnapshot"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Paper(Base):
    __tablename__ = "papers"
    __table_args__ = (UniqueConstraint("user_id", "semantic_scholar_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    semantic_scholar_id: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(Text)
    year: Mapped[int] = mapped_column(Integer, default=0)
    venue: Mapped[str] = mapped_column(String(300), default="")
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    authors_json: Mapped[dict | list] = mapped_column(JSON, default=list)
    url: Mapped[str] = mapped_column(String(500), default="")
    ccf_rank: Mapped[str] = mapped_column(String(5), default="")
    ccf_category: Mapped[str] = mapped_column(String(50), default="")
    dblp_key: Mapped[str] = mapped_column(String(300), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="papers")


class GithubRepo(Base):
    __tablename__ = "github_repos"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    repo_name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    stars: Mapped[int] = mapped_column(Integer, default=0)
    forks: Mapped[int] = mapped_column(Integer, default=0)
    language: Mapped[str] = mapped_column(String(100), default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    is_pinned: Mapped[bool] = mapped_column(default=False)
    created_at_remote: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="repos")


class HFItem(Base):
    __tablename__ = "hf_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    item_id: Mapped[str] = mapped_column(String(300))
    item_type: Mapped[str] = mapped_column(String(20))  # "model" or "dataset"
    name: Mapped[str] = mapped_column(String(300))
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    url: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="hf_items")


class Milestone(Base):
    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    metric_type: Mapped[str] = mapped_column(String(50))  # citations / stars / downloads / hf_likes
    metric_key: Mapped[str] = mapped_column(String(300))   # paper title, repo name, etc. or "__total__"
    threshold: Mapped[int] = mapped_column(Integer)
    achieved_value: Mapped[int] = mapped_column(Integer)
    achieved_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="milestones")


class NotableCitation(Base):
    __tablename__ = "notable_citations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"))
    citing_paper_ss_id: Mapped[str] = mapped_column(String(100))
    citing_paper_title: Mapped[str] = mapped_column(Text, default="")
    citing_paper_year: Mapped[int] = mapped_column(Integer, default=0)
    citing_paper_venue: Mapped[str] = mapped_column(String(300), default="")
    author_name: Mapped[str] = mapped_column(String(200), default="")
    author_ss_id: Mapped[str] = mapped_column(String(100), default="")
    author_h_index: Mapped[int] = mapped_column(Integer, default=0)
    author_citation_count: Mapped[int] = mapped_column(Integer, default=0)
    author_paper_count: Mapped[int] = mapped_column(Integer, default=0)
    scholar_level: Mapped[str] = mapped_column(String(20), default="notable")
    is_influential: Mapped[bool] = mapped_column(default=False)
    contexts_json: Mapped[dict | list] = mapped_column(JSON, default=list)
    intents_json: Mapped[dict | list] = mapped_column(JSON, default=list)
    # NULL = not enriched yet; [] = enriched, no honors; ["IEEE Fellow", ...] = has honors
    honor_tags: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship()
    paper: Mapped["Paper"] = relationship()


class CitationAnalysis(Base):
    __tablename__ = "citation_analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    paper_id: Mapped[int] = mapped_column(ForeignKey("papers.id"), unique=True)
    total_citing_papers: Mapped[int] = mapped_column(Integer, default=0)
    influential_count: Mapped[int] = mapped_column(Integer, default=0)
    top_scholar_count: Mapped[int] = mapped_column(Integer, default=0)
    notable_scholar_count: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship()
    paper: Mapped["Paper"] = relationship()


class BuzzSnapshot(Base):
    """Stores the latest web/social buzz summary for a researcher."""
    __tablename__ = "buzz_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    heat_label: Mapped[str] = mapped_column(String(10), default="")   # "hot" | "medium" | "cold"
    summary: Mapped[str] = mapped_column(Text, default="")            # Perplexity narrative
    sources: Mapped[dict | list] = mapped_column(JSON, default=list)  # list of {title, url}
    topics: Mapped[dict | list] = mapped_column(JSON, default=list)   # list of topic strings
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship()


class AISummary(Base):
    """AI-generated researcher summary and tags."""
    __tablename__ = "ai_summaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[dict | list] = mapped_column(JSON, default=list)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship()


class PageView(Base):
    """Simple page view counter."""
    __tablename__ = "page_views"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(500), default="/")
    ip: Mapped[str] = mapped_column(String(50), default="")
    user_agent: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class DataSnapshot(Base):
    __tablename__ = "data_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    metric_type: Mapped[str] = mapped_column(String(50))
    metric_key: Mapped[str] = mapped_column(String(300))
    value: Mapped[float] = mapped_column(Float, default=0)
    snapshot_date: Mapped[date] = mapped_column(Date, default=date.today)

    user: Mapped["User"] = relationship(back_populates="snapshots")


class ResearchTrajectory(Base):
    """Cached LLM-generated research trajectory analysis."""
    __tablename__ = "research_trajectories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    trajectory_json: Mapped[dict | list] = mapped_column(JSON, default=dict)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship()


class ResearcherPersona(Base):
    """Researcher personality type (MBTI-style classification)."""
    __tablename__ = "researcher_personas"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    persona_code: Mapped[str] = mapped_column(String(10), default="")
    dimension_scores: Mapped[dict | list] = mapped_column(JSON, default=dict)
    raw_metrics: Mapped[dict | list] = mapped_column(JSON, default=dict)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship()


class CareerHistory(Base):
    """LLM+web-search sourced career timeline (education + positions)."""
    __tablename__ = "career_histories"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    # list of steps: {start_year, end_year, type, role, institution, advisor, note}
    timeline_json: Mapped[dict | list] = mapped_column(JSON, default=list)
    # one-line current position summary
    current: Mapped[str] = mapped_column(String(300), default="")
    # list of {title, url}
    sources: Mapped[dict | list] = mapped_column(JSON, default=list)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship()


class CapabilityProfile(Base):
    """Multi-direction capability portrait.

    For each research direction the user works in, LLM picks a role
    (originator / early_adopter / extender / follower) and summarises
    the achievements with representative works.
    """
    __tablename__ = "capability_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    # Dominant role overall (derived from the highest-weight direction)
    primary_role: Mapped[str] = mapped_column(String(20), default="")
    # Dominant direction label (Chinese)
    primary_direction: Mapped[str] = mapped_column(String(100), default="")
    # Full per-direction breakdown — list of {
    #   direction_en, direction_zh, weight (0-1 proportion of the person's work),
    #   role, score (0-1), achievements, representative_works: [{title, year, citing_count}]
    # }
    profiles_json: Mapped[dict | list] = mapped_column(JSON, default=list)
    # LLM one-line overall summary
    rationale: Mapped[str] = mapped_column(Text, default="")
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship()


class AdvisorSchool(Base):
    """211+ universities used as the directory root for the 保研 advisor system."""
    __tablename__ = "advisor_schools"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)               # 中文全名
    short_name: Mapped[str] = mapped_column(String(40), default="")           # 清华 / 北大 / 浙大
    english_name: Mapped[str] = mapped_column(String(200), default="")
    city: Mapped[str] = mapped_column(String(40), default="")
    province: Mapped[str] = mapped_column(String(40), default="")
    school_type: Mapped[str] = mapped_column(String(40), default="")          # 综合/理工/师范/财经/医药/政法/农林/民族/语言/艺术/军事/体育
    is_985: Mapped[bool] = mapped_column(Boolean, default=False)
    is_211: Mapped[bool] = mapped_column(Boolean, default=True)
    is_double_first_class: Mapped[bool] = mapped_column(Boolean, default=False)
    homepage_url: Mapped[str] = mapped_column(String(500), default="")
    faculty_index_url: Mapped[str] = mapped_column(String(500), default="")   # "院系设置" 入口
    grad_index_url: Mapped[str] = mapped_column(String(500), default="")      # 研究生院 / 招生网入口
    logo_url: Mapped[str] = mapped_column(String(500), default="")
    # Crawl bookkeeping
    colleges_crawled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    advisors_crawled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    advisor_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    colleges: Mapped[list["AdvisorCollege"]] = relationship(back_populates="school", cascade="all, delete-orphan")
    advisors: Mapped[list["Advisor"]] = relationship(back_populates="school", cascade="all, delete-orphan")


class AdvisorCollege(Base):
    """A 学院/系/学部 within a school (e.g., 清华-计算机系)."""
    __tablename__ = "advisor_colleges"
    __table_args__ = (UniqueConstraint("school_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("advisor_schools.id"))
    name: Mapped[str] = mapped_column(String(150))                            # e.g. 计算机科学与技术系
    english_name: Mapped[str] = mapped_column(String(300), default="")
    discipline_category: Mapped[str] = mapped_column(String(40), default="")  # 工学/理学/文学/医学/经济学/管理学/法学/教育学/艺术学/历史学/哲学/农学/军事学
    homepage_url: Mapped[str] = mapped_column(String(500), default="")
    faculty_list_url: Mapped[str] = mapped_column(String(500), default="")    # 师资/导师列表 URL
    advisors_crawled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    advisor_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    school: Mapped["AdvisorSchool"] = relationship(back_populates="colleges")
    advisors: Mapped[list["Advisor"]] = relationship(back_populates="college", cascade="all, delete-orphan")


class Advisor(Base):
    """A single graduate advisor (导师). Independent of ImpactHub User."""
    __tablename__ = "advisors"
    __table_args__ = (UniqueConstraint("school_id", "college_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    school_id: Mapped[int] = mapped_column(ForeignKey("advisor_schools.id"))
    college_id: Mapped[int] = mapped_column(ForeignKey("advisor_colleges.id"))
    name: Mapped[str] = mapped_column(String(80))
    name_en: Mapped[str] = mapped_column(String(120), default="")
    title: Mapped[str] = mapped_column(String(60), default="")               # 教授 / 副教授 / 讲师 / 研究员 / 副研究员 / 助理研究员
    is_doctoral_supervisor: Mapped[bool] = mapped_column(Boolean, default=False)  # 博导
    is_master_supervisor: Mapped[bool] = mapped_column(Boolean, default=False)    # 硕导

    # Contact
    homepage_url: Mapped[str] = mapped_column(String(500), default="")
    email: Mapped[str] = mapped_column(String(120), default="")
    office: Mapped[str] = mapped_column(String(200), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    photo_url: Mapped[str] = mapped_column(String(500), default="")

    # Academic profile
    research_areas: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)  # ["NLP", "对齐"]
    bio: Mapped[str] = mapped_column(Text, default="")
    education: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)        # parsed timeline
    honors: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)           # 杰青/长江/院士

    # Recruiting (招生情况) — Layer C, often missing
    recruiting_intent: Mapped[str] = mapped_column(Text, default="")
    grad_quota_master: Mapped[int] = mapped_column(Integer, default=0)   # 硕士名额
    grad_quota_phd: Mapped[int] = mapped_column(Integer, default=0)      # 博士名额
    accepts_recommended: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # 是否招保研

    # External linkage (filled by Layer B)
    semantic_scholar_id: Mapped[str] = mapped_column(String(100), default="")
    h_index: Mapped[int] = mapped_column(Integer, default=0)
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    paper_count: Mapped[int] = mapped_column(Integer, default=0)
    impacthub_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # if matched to ImpactHub User

    # Provenance
    source_url: Mapped[str] = mapped_column(String(500), default="")
    raw_html: Mapped[str] = mapped_column(Text, default="")              # original HTML snippet for re-parsing
    crawl_status: Mapped[str] = mapped_column(String(20), default="stub")  # stub / detailed / failed
    crawled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    school: Mapped["AdvisorSchool"] = relationship(back_populates="advisors")
    college: Mapped["AdvisorCollege"] = relationship(back_populates="advisors")


class AdvisorMention(Base):
    """A 公众号 article / 小红书 post / 知乎 answer / forum thread that mentions
    a specific advisor. The collection side (你来负责) is decoupled — this table
    is pure storage. Bulk-imported via scripts/import_advisor_mentions.py.
    """
    __tablename__ = "advisor_mentions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # advisor_id = 0 means unlinked (advisor not yet in DB).
    # Once the advisor is crawled, a reconcile pass updates this column.
    advisor_id: Mapped[int] = mapped_column(ForeignKey("advisors.id"), default=0)
    # If unlinked, store the raw name + school so we can reconcile later
    pending_advisor_name: Mapped[str] = mapped_column(String(80), default="")
    pending_school_name: Mapped[str] = mapped_column(String(120), default="")
    source: Mapped[str] = mapped_column(String(30))            # wechat / xiaohongshu / zhihu / forum / other
    source_account: Mapped[str] = mapped_column(String(120), default="")  # 公众号名 / 小红书账号
    title: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    snippet: Mapped[str] = mapped_column(Text, default="")     # excerpt / summary
    cover_url: Mapped[str] = mapped_column(String(500), default="")
    # Engagement metrics — fill what's available, leave 0 otherwise
    likes: Mapped[int] = mapped_column(Integer, default=0)
    reads: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    # Optional sentiment label assigned during ingest: positive / neutral / negative
    sentiment: Mapped[str] = mapped_column(String(20), default="")
    # Free-form tags ["招生", "口碑", "组氛围", "push", "放养", ...]
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True, default=None)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    advisor: Mapped["Advisor"] = relationship()


class AnnualPoem(Base):
    """Xiaohongshu-style annual poem: LLM-generated poetic year-in-review."""
    __tablename__ = "annual_poems"
    __table_args__ = (UniqueConstraint("user_id", "year"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    year: Mapped[int] = mapped_column(Integer)
    # payload: {title, verses: [str, ...], highlights: [{label, value}], theme}
    content_json: Mapped[dict | list] = mapped_column(JSON, default=dict)
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship()
