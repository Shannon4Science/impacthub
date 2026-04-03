const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export interface Paper {
  id: number;
  semantic_scholar_id: string;
  title: string;
  year: number;
  venue: string;
  citation_count: number;
  authors: string[];
  url: string;
  ccf_rank: string;
  ccf_category: string;
  updated_at: string;
}

export interface GithubRepo {
  id: number;
  repo_name: string;
  description: string;
  stars: number;
  forks: number;
  language: string;
  url: string;
  is_pinned?: boolean;
  updated_at: string;
}

export interface HFItem {
  id: number;
  item_id: string;
  item_type: "model" | "dataset";
  name: string;
  downloads: number;
  likes: number;
  url: string;
  updated_at: string;
}

export interface Milestone {
  id: number;
  metric_type: string;
  metric_key: string;
  threshold: number;
  achieved_value: number;
  achieved_at: string;
}

export interface ProfileFull {
  user: UserProfile;
  papers: Paper[];
  repos: GithubRepo[];
  hf_items: HFItem[];
}

export interface Stats {
  total_citations: number;
  total_stars: number;
  total_forks: number;
  total_downloads: number;
  total_hf_likes: number;
  paper_count: number;
  repo_count: number;
  hf_count: number;
  h_index: number;
  ccf_a_count: number;
  ccf_b_count: number;
  ccf_c_count: number;
}

export interface GrowthPoint {
  date: string;
  value: number;
}

export interface GrowthSeries {
  metric: string;
  label: string;
  data: GrowthPoint[];
}

export interface GrowthData {
  series: GrowthSeries[];
  daily_delta: Record<string, number>;
}

export interface UserProfile {
  id: number;
  name: string;
  avatar_url: string;
  bio: string;
  scholar_id: string;
  github_username: string;
  hf_username: string;
  twitter_username: string;
  homepage: string;
  feishu_webhook: string;
  created_at?: string;
}

export interface TimelineEntry {
  date: string;
  type: "paper" | "repo" | "hf_model" | "hf_dataset";
  title: string;
  detail: string;
  url: string;
}

export interface NotableCitationItem {
  id: number;
  paper_id: number;
  paper_title: string;
  citing_paper_title: string;
  citing_paper_year: number;
  citing_paper_venue: string;
  author_name: string;
  author_ss_id: string;
  author_h_index: number;
  author_citation_count: number;
  author_paper_count: number;
  scholar_level: "top" | "notable";
  is_influential: boolean;
  contexts: string[];
  intents: string[];
  honor_tags: string[];
}

export interface PaperCitationAnalysis {
  paper_id: number;
  paper_title: string;
  paper_citation_count: number;
  total_citing_papers: number;
  influential_count: number;
  top_scholar_count: number;
  notable_scholar_count: number;
  analyzed_at: string | null;
}

export interface CitationOverview {
  total_papers_analyzed: number;
  total_papers: number;
  analysis_done: number;
  analysis_total: number;
  total_notable_scholars: number;
  unique_notable_scholars: number;
  top_scholar_total: number;
  notable_scholar_total: number;
  top_scholars: NotableCitationItem[];
  notable_scholars: NotableCitationItem[];
  paper_analyses: PaperCitationAnalysis[];
  paper_analyses_total: number;
  is_analyzing: boolean;
  honor_scholar_count: number;
  honor_is_enriching: boolean;
  honor_enriched: boolean;
}

export interface DiscoveryStatus {
  user: UserProfile;
  scholar_found: boolean;
  scholar_confidence: string;
  github_found?: boolean;
  github_confidence?: string;
  hf_found: boolean;
  hf_confidence: string;
  message: string;
}

export interface AISummary {
  user_id: number;
  summary: string;
  tags: string[];
  refreshed_at: string | null;
}

export interface PaperReportResult {
  user: string;
  filter: {
    year_from: number;
    year_to: number;
    ccf_rank: string;
    min_citations: number;
  };
  summary: {
    total: number;
    ccf_a: number;
    ccf_b: number;
    ccf_c: number;
    total_citations: number;
  };
  papers: {
    title: string;
    year: number;
    venue: string;
    ccf_rank: string;
    ccf_category: string;
    citation_count: number;
    authors: string[];
    url: string;
  }[];
}

export interface BuzzSnapshot {
  user_id: number;
  heat_label: "very_hot" | "hot" | "medium" | "cold" | "very_cold" | "";
  summary: string;
  sources: { title: string; url: string }[];
  topics: string[];
  refreshed_at: string | null;
}

export interface GrantTypeInfo {
  key: string;
  name: string;
  tone: string;
  desc: string;
  group: string;
}

export interface NotableCitationBrief {
  author_name: string;
  author_h_index: number;
  honor_tags: string[];
  citing_paper_title: string;
  citing_paper_venue: string;
  citing_paper_year: number;
  context_snippet: string;
}

export interface PaperEvidenceOut {
  paper_id: number;
  title: string;
  venue: string;
  year: number;
  citation_count: number;
  ccf_rank: string;
  authors: string[];
  total_citing_papers: number;
  influential_count: number;
  top_scholar_count: number;
  notable_scholar_count: number;
  notable_citations: NotableCitationBrief[];
}

export interface PaperSelectionIn {
  paper_id: number;
  scientific_question: string;
  innovation_summary: string;
  relevance: string;
  linked_repo_ids: number[];
  linked_hf_item_ids: number[];
}

export interface ResearchBasisRequest {
  grant_type: string;
  project_title: string;
  papers: PaperSelectionIn[];
}

export interface SiteStats {
  total_profiles: number;
  total_papers: number;
  total_citations: number;
  total_repos: number;
  total_stars: number;
  total_hf_items: number;
  total_views: number;
  weekly_visitors: number;
}

export interface ScholarSearchResult {
  authorId: string;
  name: string;
  paperCount: number;
  citationCount: number;
  hIndex: number;
  affiliations: string[];
  domain: string;
}

/** All API methods accept a string identifier (scholar_id or numeric id). */
export const api = {
  searchScholars(query: string, offset = 0, limit = 10) {
    return request<{ results: ScholarSearchResult[]; total: number; offset: number; has_more: boolean }>(
      `/scholar-search?q=${encodeURIComponent(query)}&offset=${offset}&limit=${limit}`
    );
  },
  searchGithubRepos(query: string) {
    return request<{ results: { full_name: string; description: string; stars: number; language: string }[] }>(
      `/github-search?q=${encodeURIComponent(query)}`
    );
  },
  searchHFItems(query: string, type: "model" | "dataset" = "model") {
    return request<{ results: { id: string; downloads: number; likes: number }[] }>(
      `/hf-search?q=${encodeURIComponent(query)}&type=${type}`
    );
  },
  createProfile(data: { scholar_id: string }) {
    return request<DiscoveryStatus>("/profile", {
      method: "POST",
      body: JSON.stringify(data),
    });
  },
  updateProfile(identifier: string, data: { scholar_id?: string; hf_username?: string }) {
    return request<UserProfile>(`/profile/${identifier}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
  },
  getProfile(identifier: string) {
    return request<ProfileFull>(`/profile/${identifier}`);
  },
  getStats(identifier: string) {
    return request<Stats>(`/profile/${identifier}/stats`);
  },
  getTimeline(identifier: string) {
    return request<TimelineEntry[]>(`/profile/${identifier}/timeline`);
  },
  getMilestones(identifier: string) {
    return request<Milestone[]>(`/milestones/${identifier}`);
  },
  refresh(identifier: string) {
    return request<{ status: string }>(`/refresh/${identifier}`, { method: "POST" });
  },
  addRepo(identifier: string, repoFullName: string) {
    return request<Repo>(`/profile/${identifier}/repos`, {
      method: "POST",
      body: JSON.stringify({ repo_full_name: repoFullName }),
    });
  },
  deleteRepo(identifier: string, repoId: number) {
    return request<{ ok: boolean }>(`/profile/${identifier}/repos/${repoId}`, {
      method: "DELETE",
    });
  },
  addHFItem(identifier: string, itemId: string, itemType: "model" | "dataset") {
    return request<HFItem>(`/profile/${identifier}/hf-items`, {
      method: "POST",
      body: JSON.stringify({ item_id: itemId, item_type: itemType }),
    });
  },
  deleteHFItem(identifier: string, itemId: number) {
    return request<{ ok: boolean }>(`/profile/${identifier}/hf-items/${itemId}`, {
      method: "DELETE",
    });
  },
  listUsers() {
    return request<(UserProfile & { paper_count: number; total_citations: number; repo_count: number; total_stars: number; hf_count: number; total_downloads: number })[]>("/profiles");
  },
  getCitationOverview(identifier: string) {
    return request<CitationOverview>(`/citations/${identifier}`);
  },
  triggerCitationAnalysis(identifier: string) {
    return request<{ status: string }>(`/citations/${identifier}/analyze`, { method: "POST" });
  },
  enrichHonors(identifier: string) {
    return request<{ status: string }>(`/citations/${identifier}/enrich-honors`, { method: "POST" });
  },
  getScholars(identifier: string, level: "top" | "notable", offset: number, limit = 20) {
    return request<{ items: NotableCitationItem[]; offset: number; limit: number }>(
      `/citations/${identifier}/scholars?level=${level}&offset=${offset}&limit=${limit}`
    );
  },
  getPaperAnalyses(identifier: string, offset: number, limit = 20) {
    return request<{ items: PaperCitationAnalysis[]; offset: number; limit: number }>(
      `/citations/${identifier}/papers?offset=${offset}&limit=${limit}`
    );
  },
  getGrowth(identifier: string, days = 30) {
    return request<GrowthData>(`/growth/${identifier}?days=${days}`);
  },
  getReportSummary(identifier: string) {
    return request<Record<string, unknown>>(`/report/${identifier}/summary`);
  },
  getBuzz(identifier: string) {
    return request<BuzzSnapshot | null>(`/buzz/${identifier}`);
  },
  refreshBuzz(identifier: string) {
    return request<{ status: string }>(`/buzz/${identifier}/refresh`, { method: "POST" });
  },
  getAISummary(identifier: string) {
    return request<AISummary | null>(`/ai-summary/${identifier}`);
  },
  refreshAISummary(identifier: string) {
    return request<{ status: string }>(`/ai-summary/${identifier}/refresh`, { method: "POST" });
  },
  getPaperReport(identifier: string, params: {
    year_from?: number;
    year_to?: number;
    ccf_rank?: string;
    min_citations?: number;
    first_author?: string;
  }) {
    const sp = new URLSearchParams();
    if (params.year_from) sp.set("year_from", String(params.year_from));
    if (params.year_to) sp.set("year_to", String(params.year_to));
    if (params.ccf_rank) sp.set("ccf_rank", params.ccf_rank);
    if (params.min_citations) sp.set("min_citations", String(params.min_citations));
    if (params.first_author) sp.set("first_author", params.first_author);
    return request<PaperReportResult>(`/report/${identifier}/papers?${sp.toString()}`);
  },
  getGrantTypes() {
    return request<GrantTypeInfo[]>("/report/grant-types");
  },
  getPaperEvidence(identifier: string, paperId: number) {
    return request<PaperEvidenceOut>(`/report/${identifier}/paper-evidence/${paperId}`);
  },
  generateResearchBasis(identifier: string, req: ResearchBasisRequest) {
    return request<{ markdown: string }>(`/report/${identifier}/research-basis`, {
      method: "POST",
      body: JSON.stringify(req),
    });
  },
  getSiteStats() {
    return request<SiteStats>("/stats");
  },
  trackVisit(path: string) {
    return request<{ ok: boolean }>("/track", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
  },
};
