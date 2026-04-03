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
