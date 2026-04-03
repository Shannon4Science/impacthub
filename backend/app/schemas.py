from datetime import datetime
from pydantic import BaseModel


class UserCreate(BaseModel):
    scholar_id: str
    github_username: str = ""
    hf_username: str = ""


class UserOut(BaseModel):
    id: int
    name: str
    avatar_url: str
    bio: str
    scholar_id: str
    github_username: str
    hf_username: str
    twitter_username: str = ""
    homepage: str = ""
    feishu_webhook: str = ""
    created_at: datetime | None = None

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    scholar_id: str | None = None
    hf_username: str | None = None
    github_username: str | None = None
    twitter_username: str | None = None
    homepage: str | None = None
    feishu_webhook: str | None = None


class DiscoveryStatus(BaseModel):
    user: UserOut
    scholar_found: bool
    scholar_confidence: str
    github_found: bool = True
    github_confidence: str = ""
    hf_found: bool
    hf_confidence: str
    message: str


class PaperOut(BaseModel):
    id: int
    semantic_scholar_id: str
    title: str
    year: int
    venue: str
    citation_count: int
    authors: list[str]
    url: str
    ccf_rank: str = ""
    ccf_category: str = ""
    updated_at: datetime

    model_config = {"from_attributes": True}


class RepoOut(BaseModel):
    id: int
    repo_name: str
    description: str
    stars: int
    forks: int
    language: str
    url: str
    is_pinned: bool = False
    updated_at: datetime

    model_config = {"from_attributes": True}


class HFItemOut(BaseModel):
    id: int
    item_id: str
    item_type: str
    name: str
    downloads: int
    likes: int
    url: str
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProfileFull(BaseModel):
    user: UserOut
    papers: list[PaperOut]
    repos: list[RepoOut]
    hf_items: list[HFItemOut]


class StatsOut(BaseModel):
    total_citations: int
    total_stars: int
    total_forks: int
    total_downloads: int
    total_hf_likes: int
    paper_count: int
    repo_count: int
    hf_count: int
    h_index: int
    ccf_a_count: int = 0
    ccf_b_count: int = 0
    ccf_c_count: int = 0


class TimelineEntry(BaseModel):
    date: str
    type: str
    title: str
    detail: str
    url: str


class NotableCitationOut(BaseModel):
    id: int
    paper_id: int
    paper_title: str = ""
    citing_paper_title: str
    citing_paper_year: int
    citing_paper_venue: str
    author_name: str
    author_ss_id: str
    author_h_index: int
    author_citation_count: int
    author_paper_count: int
    scholar_level: str
    is_influential: bool
    contexts: list[str] = []
    intents: list[str] = []
    honor_tags: list[str] = []


class CitationAnalysisOut(BaseModel):
    paper_id: int
    paper_title: str
    paper_citation_count: int
    total_citing_papers: int
    influential_count: int
    top_scholar_count: int
    notable_scholar_count: int
    analyzed_at: datetime | None = None


class CitationOverview(BaseModel):
    total_papers_analyzed: int
    total_papers: int = 0               # total papers for this user
    analysis_done: int = 0              # papers analyzed so far (during active analysis)
    analysis_total: int = 0             # papers to analyze (during active analysis)
    total_notable_scholars: int
    unique_notable_scholars: int
    top_scholar_total: int = 0          # total count of top scholars (h>=50)
    notable_scholar_total: int = 0      # total count of notable scholars (h>=25)
    top_scholars: list[NotableCitationOut]
    notable_scholars: list[NotableCitationOut]
    paper_analyses: list[CitationAnalysisOut]
    paper_analyses_total: int = 0       # total count of paper analyses
    is_analyzing: bool = False
    honor_scholar_count: int = 0     # unique authors with any honor tag
    honor_is_enriching: bool = False
    honor_enriched: bool = False      # True if enrichment has been run at least once


class GrowthPoint(BaseModel):
    date: str
    value: float


class GrowthSeries(BaseModel):
    metric: str
    label: str
    data: list[GrowthPoint]


class GrowthData(BaseModel):
    series: list[GrowthSeries]
    daily_delta: dict[str, float] = {}


class MilestoneOut(BaseModel):
    id: int
    metric_type: str
    metric_key: str
    threshold: int
    achieved_value: int
    achieved_at: datetime

    model_config = {"from_attributes": True}


# ---------- Research Basis (研究基础) ----------

class PaperSelectionIn(BaseModel):
    paper_id: int
    scientific_question: str = ""
    innovation_summary: str = ""
    relevance: str = ""
    linked_repo_ids: list[int] = []
    linked_hf_item_ids: list[int] = []


class ResearchBasisRequest(BaseModel):
    grant_type: str = "general"
    project_title: str = ""
    papers: list[PaperSelectionIn] = []


class NotableCitationBrief(BaseModel):
    author_name: str
    author_h_index: int
    honor_tags: list[str] = []
    citing_paper_title: str
    citing_paper_venue: str
    citing_paper_year: int
    context_snippet: str = ""


class PaperEvidenceOut(BaseModel):
    paper_id: int
    title: str
    venue: str
    year: int
    citation_count: int
    ccf_rank: str = ""
    authors: list[str] = []
    total_citing_papers: int = 0
    influential_count: int = 0
    top_scholar_count: int = 0
    notable_scholar_count: int = 0
    notable_citations: list[NotableCitationBrief] = []
