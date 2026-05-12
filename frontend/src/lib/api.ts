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

// ---------- Research Trajectory (研究演化树) ----------

export interface TreeNode {
  label: string;
  summary?: string;
  year_range?: string;
  paper_count?: number;
  paper_ids?: number[];
  children?: TreeNode[];
}

export interface TrajectoryPaperRef {
  id: number;
  title: string;
  year: number;
  venue: string;
  citation_count: number;
  ccf_rank: string;
}

export interface BuzzTimepoint {
  period_label: string;
  heat_label: string;
  topics: string[];
}

export interface TrajectoryData {
  root: TreeNode;
  papers_index: Record<number, TrajectoryPaperRef>;
  buzz_timeline: BuzzTimepoint[];
  refreshed_at: string | null;
}

// ---------- Researcher Persona (研究者人格) ----------

export interface ResearcherPersona {
  user_id: number;
  persona_code: string;
  name_zh: string;
  name_en: string;
  emoji: string;
  tagline?: string;
  description: string;
  traits: string[];
  color_from: string;
  color_to: string;
  dimension_scores: Record<string, number>;
  raw_metrics: Record<string, number>;
  refreshed_at: string | null;
}

// ---------- Capability Profile (多方向能力画像) ----------

export interface CapabilityWork {
  title: string;
  year?: number | null;
  citing_count: number;
}

export interface CapabilityDirectionProfile {
  direction_en: string;
  direction_zh: string;
  weight: number;       // 0-1
  role: "originator" | "early_adopter" | "extender" | "follower" | string;
  role_zh: string;
  role_en: string;
  role_emoji: string;
  role_color: string;
  score: number;
  achievements: string;
  representative_works: CapabilityWork[];
}

export interface CapabilityData {
  user_id: number;
  primary_role: string;
  primary_role_zh: string;
  primary_role_emoji: string;
  primary_role_color: string;
  primary_direction: string;
  profiles: CapabilityDirectionProfile[];
  rationale: string;
  refreshed_at: string | null;
}

// ---------- Annual Poem (年度诗篇) ----------

export interface PoemHighlight {
  label: string;
  value: string;
}

export interface AnnualPoemData {
  user_id: number;
  year: number;
  title: string;
  verses: string[];
  highlights: PoemHighlight[];
  theme: "indigo" | "amber" | "emerald" | "rose";
  refreshed_at: string | null;
}

// ---------- Career History (职业经历) ----------

export interface CareerStep {
  start_year: number | null;
  end_year: number | null;
  type: "education" | "position";
  role: string;
  institution: string;
  advisor: string;
  note: string;
}

export interface CareerData {
  user_id: number;
  timeline: CareerStep[];
  current: string;
  sources: { title: string; url: string }[];
  refreshed_at: string | null;
}

// ---------- Leaderboard / Rankings ----------

export interface LeaderboardEntry {
  rank: number | null;
  percentile: number | null;
  user: {
    id: number;
    name: string;
    avatar_url: string;
    scholar_id: string;
    github_username: string;
    research_direction: string | null;
    seed_tier: string | null;
    honor_tags: string[];
  };
  metrics: {
    h_index: number;
    total_citations: number;
    paper_count: number;
    ccf_a_count: number;
    total_stars: number;
    first_paper_year: number | null;
  };
  persona_code: string | null;
}

export interface LeaderboardData {
  type: "total" | "young" | "direction";
  metric: "h_index" | "total_citations" | "ccf_a_count" | "total_stars";
  direction: string | null;
  total_count: number;
  entries: LeaderboardEntry[];
  target_rank?: {
    rank: number | null;
    percentile: number | null;
    metric_value: number;
  };
}

// ---------- Advisor (导师推荐 / 保研) ----------

export interface AdvisorSchoolBrief {
  id: number;
  name: string;
  short_name: string;
  english_name: string;
  city: string;
  province: string;
  school_type: string;
  is_985: boolean;
  is_211: boolean;
  is_double_first_class: boolean;
  homepage_url: string;
  college_count: number;
  advisor_count: number;
}

export interface AdvisorCollegeBrief {
  id: number;
  school_id: number;
  name: string;
  discipline_category: string;
  homepage_url: string;
  advisor_count: number;
}

export interface AdvisorBrief {
  id: number;
  school_id: number;
  college_id: number;
  name: string;
  title: string;
  is_doctoral_supervisor: boolean;
  research_areas: string[] | null;
  homepage_url: string;
  photo_url: string;
  h_index: number;
  citation_count: number;
  bio?: string;
  email?: string;
  impacthub_user_id?: number | null;
}

export interface AdvisorMention {
  id: number;
  advisor_id: number;
  source: "wechat" | "xiaohongshu" | "zhihu" | "forum" | "other" | string;
  source_account: string;
  title: string;
  url: string;
  snippet: string;
  cover_url: string;
  likes: number;
  reads: number;
  comments: number;
  sentiment: "positive" | "neutral" | "negative" | "" | string;
  tags: string[] | null;
  published_at: string | null;
  created_at: string;
}

export interface AdvisorChatCriteria {
  direction_keywords: string[];
  school_tier: "985" | "211" | "double_first_class" | "any";
  provinces: string[];
  school_types: string[];
  must_have_mention: boolean;
  preferred_traits: string[];
}

/** Unified advisor card data — same shape rendered for both
 *  lookup_advisor (full profile) and search_advisors (list item). */
export interface AdvisorChatRecommendation {
  advisor_id: number;
  name: string;
  title?: string;
  school: string;
  school_short: string;
  is_985: boolean;
  is_211: boolean;
  province: string;
  college: string;
  discipline?: string;
  homepage?: string;
  homepage_url?: string;
  email?: string;
  office?: string;
  bio?: string;
  recruiting_intent?: string;
  is_doctoral_supervisor?: boolean;
  crawl_status?: string;
  h_index: number;
  research_areas?: string[];
  honors?: string[];
  education?: { degree: string; year: number | null; institution: string; advisor: string }[];
  // Mention data: full list if available (lookup), else just count (search)
  mentions?: {
    title?: string;
    url?: string;
    snippet?: string;
    cover_url?: string;
    source: string;
    source_account?: string;
    account?: string;
    tags?: string[] | null;
    sentiment?: string;
    published_at?: string | null;
  }[];
  n_mentions?: number;
  // Optional rerank fields
  match_score?: number;
  tier?: "perfect" | "strong" | "potential";
  reasoning?: string;
  highlights?: string[];
  concerns?: string[];
}

export type AdvisorChatStreamEvent =
  | { type: "thinking" }
  | { type: "tool_start"; name: string; args: Record<string, unknown> }
  | {
      type: "tool_end";
      name: string;
      summary: string;
      new_advisors_count?: number;
      advisor_profile?: AdvisorChatProfile;
    }
  | { type: "delta"; content: string }
  | {
      type: "done";
      recommendations: AdvisorChatRecommendation[];
      advisor_profiles: AdvisorChatProfile[];
      tool_trace?: { name: string; args: Record<string, unknown>; result_summary: string }[];
      error?: string;
    };

export interface AdvisorChatResponse {
  reply: string;
  criteria?: AdvisorChatCriteria | null;
  recommendations: AdvisorChatRecommendation[];
  advisor_profiles?: AdvisorChatProfile[];
  tool_trace?: { name: string; args: Record<string, unknown>; result_summary: string }[];
  ready?: boolean;
}

// Same shape as AdvisorChatRecommendation — unified
export type AdvisorChatProfile = AdvisorChatRecommendation;

export interface MentionFeedItem {
  id: number;
  source: string;
  source_account: string;
  title: string;
  url: string;
  snippet: string;
  cover_url: string;
  likes: number;
  reads: number;
  comments: number;
  sentiment: string;
  tags: string[] | null;
  published_at: string | null;
  advisor_id: number;
  advisor_name: string;
  advisor_title: string;
  advisor_homepage: string;
  college_id: number;
  college_name: string;
  school_id: number;
  school_name: string;
  school_short: string;
  school_province: string;
  is_985: boolean;
  is_211: boolean;
  is_linked: boolean;
}

export interface MentionFeedResponse {
  items: MentionFeedItem[];
  total: number;
  offset: number;
  limit: number;
  facets: {
    sources: Record<string, number>;
    accounts: Record<string, number>;
    sentiments: Record<string, number>;
  };
}

export interface AdvisorSchoolDetail {
  school: AdvisorSchoolBrief;
  colleges_crawled_at: string | null;
  advisors_crawled_at: string | null;
  colleges: AdvisorCollegeBrief[];
}

export interface AdvisorDirectoryStats {
  total_schools: number;
  schools_985: number;
  schools_211: number;
  total_colleges: number;
  total_advisors: number;
  by_province: Record<string, number>;
  by_school_type: Record<string, number>;
}

// ---------- Recruit (B2B 猎头查询) ----------

export interface RecruitCriteria {
  intent_summary: string;
  research_directions: string[];
  must_have_keywords: string[];
  nice_to_have_keywords: string[];
  seniority: "senior" | "mid" | "junior" | "any";
  min_h_index: number;
  min_paper_count: number;
  min_ccf_a_count: number;
  min_total_stars: number;
  needs_open_source: boolean;
  needs_industry_experience: boolean;
  honors_preferred: string[];
  exclude_keywords: string[];
  ranking_priority: string;
}

export interface RecruitKeyWork {
  title: string;
  year: number;
  venue: string;
  ccf_rank: string;
  citation_count: number;
  url: string;
}

export interface RecruitCandidate {
  user_id: number;
  name: string;
  match_score: number;
  tier: "perfect" | "strong" | "potential";
  fit_reasoning: string;
  highlights: string[];
  concerns: string[];
  key_works: RecruitKeyWork[];
  user: {
    id: number;
    name: string;
    avatar_url: string;
    scholar_id: string;
    github_username: string;
    homepage: string;
    bio: string;
    honor_tags: string[];
    research_direction: string;
  };
  metrics: {
    h_index: number;
    total_citations: number;
    paper_count: number;
    ccf_a_count: number;
    total_stars: number;
    first_paper_year: number | null;
  };
  primary_direction: string;
  persona_code: string;
  top_repos: { name: string; stars: number; url: string }[];
}

export interface RecruitSearchResponse {
  criteria: RecruitCriteria;
  results: RecruitCandidate[];
  search_summary: string;
  candidate_pool_size: number;
  filtered_pool_size?: number;
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
  updateProfile(identifier: string, data: { scholar_id?: string; hf_username?: string; github_username?: string; twitter_username?: string; homepage?: string; feishu_webhook?: string }) {
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
    return request<GithubRepo>(`/profile/${identifier}/repos`, {
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
  getTrajectory(identifier: string) {
    return request<TrajectoryData | null>(`/trajectory/${identifier}`);
  },
  refreshTrajectory(identifier: string) {
    return request<{ status: string }>(`/trajectory/${identifier}/refresh`, { method: "POST" });
  },
  getPersona(identifier: string) {
    return request<ResearcherPersona | null>(`/persona/${identifier}`);
  },
  refreshPersona(identifier: string) {
    return request<{ status: string }>(`/persona/${identifier}/refresh`, { method: "POST" });
  },
  getCareer(identifier: string) {
    return request<CareerData | null>(`/career/${identifier}`);
  },
  refreshCareer(identifier: string) {
    return request<{ status: string }>(`/career/${identifier}/refresh`, { method: "POST" });
  },
  getCapability(identifier: string) {
    return request<CapabilityData | null>(`/capability/${identifier}`);
  },
  refreshCapability(identifier: string) {
    return request<{ status: string }>(`/capability/${identifier}/refresh`, { method: "POST" });
  },
  getAnnualPoem(identifier: string, year?: number) {
    const qs = year ? `?year=${year}` : "";
    return request<AnnualPoemData | null>(`/poem/${identifier}${qs}`);
  },
  refreshAnnualPoem(identifier: string, year?: number) {
    const qs = year ? `?year=${year}` : "";
    return request<{ status: string; year: number }>(`/poem/${identifier}/refresh${qs}`, { method: "POST" });
  },
  getRankings(params: {
    type?: "total" | "young" | "direction";
    direction?: string;
    metric?: "h_index" | "total_citations" | "ccf_a_count" | "total_stars";
    offset?: number;
    limit?: number;
    target_user_id?: number;
  }) {
    const sp = new URLSearchParams();
    if (params.type) sp.set("type", params.type);
    if (params.direction) sp.set("direction", params.direction);
    if (params.metric) sp.set("metric", params.metric);
    if (params.offset != null) sp.set("offset", String(params.offset));
    if (params.limit != null) sp.set("limit", String(params.limit));
    if (params.target_user_id) sp.set("target_user_id", String(params.target_user_id));
    return request<LeaderboardData>(`/rankings?${sp.toString()}`);
  },
  getRankingDirections() {
    return request<string[]>(`/rankings/directions`);
  },
  getSiteStats() {
    return request<SiteStats>("/stats");
  },
  getAdvisorStats() {
    return request<AdvisorDirectoryStats>("/advisor/stats");
  },
  crawlAdvisorSchool(schoolId: number, fetchAdvisors = false) {
    return request<{ status: string; school_id: number; fetch_advisors: boolean }>(
      `/advisor/schools/${schoolId}/crawl?fetch_advisors=${fetchAdvisors}`,
      { method: "POST" }
    );
  },
  crawlAdvisorCollege(collegeId: number) {
    return request<{ status: string; college_id: number }>(
      `/advisor/colleges/${collegeId}/crawl-advisors`,
      { method: "POST" }
    );
  },
  listAdvisorSchools(params: { province?: string; school_type?: string; tier?: "985" | "211"; q?: string } = {}) {
    const sp = new URLSearchParams();
    if (params.province) sp.set("province", params.province);
    if (params.school_type) sp.set("school_type", params.school_type);
    if (params.tier) sp.set("tier", params.tier);
    if (params.q) sp.set("q", params.q);
    return request<AdvisorSchoolBrief[]>(`/advisor/schools?${sp.toString()}`);
  },
  getAdvisorSchool(schoolId: number) {
    return request<AdvisorSchoolDetail>(`/advisor/schools/${schoolId}`);
  },
  listAdvisorsInCollege(collegeId: number) {
    return request<AdvisorBrief[]>(`/advisor/colleges/${collegeId}/advisors`);
  },
  listAdvisorMentions(advisorId: number) {
    return request<AdvisorMention[]>(`/advisor/advisors/${advisorId}/mentions`);
  },
  advisorChat(messages: { role: "user" | "assistant"; content: string }[]) {
    return request<AdvisorChatResponse>(`/advisor/chat`, {
      method: "POST",
      body: JSON.stringify({ messages }),
    });
  },
  /** Streaming chat. Returns an async iterator of SSE events.
   * Caller can consume events incrementally:
   *   for await (const ev of api.advisorChatStream(msgs)) { ... } */
  async *advisorChatStream(
    messages: { role: "user" | "assistant"; content: string }[],
    signal?: AbortSignal,
  ): AsyncGenerator<AdvisorChatStreamEvent> {
    const res = await fetch(`${BASE}/advisor/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
      signal,
    });
    if (!res.ok || !res.body) throw new Error(`stream HTTP ${res.status}`);
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      // SSE messages are separated by \n\n; each starts with "data: "
      let sep: number;
      while ((sep = buf.indexOf("\n\n")) >= 0) {
        const raw = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        for (const line of raw.split("\n")) {
          if (!line.startsWith("data:")) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            yield JSON.parse(payload) as AdvisorChatStreamEvent;
          } catch {
            // skip malformed
          }
        }
      }
    }
  },
  mentionsFeed(params: {
    q?: string;
    source?: string;
    account?: string;
    sentiment?: string;
    school_id?: number;
    advisor_id?: number;
    offset?: number;
    limit?: number;
  } = {}) {
    const sp = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
    });
    return request<MentionFeedResponse>(`/advisor/mentions/feed?${sp.toString()}`);
  },
  recruitSearch(jd: string, topK = 10) {
    return request<RecruitSearchResponse>("/recruit/search", {
      method: "POST",
      body: JSON.stringify({ jd, top_k: topK }),
    });
  },
  getDoc(slug: string) {
    return request<{ slug: string; filename: string; content: string }>(`/docs/${slug}`);
  },
  trackVisit(path: string) {
    return request<{ ok: boolean }>("/track", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
  },
};
