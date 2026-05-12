# Sonnet agent prompt — discover faculty in a school's CS/AI departments

Use when a department's faculty list isn't reachable by the standard HTML crawler
(network-blocked, JS-rendered, or layout the heuristic can't parse). Spawn one
agent per ~50 advisors to stay safely under the 32K output-token budget.

```text
Discover ALL faculty (教授/副教授/助理教授/讲师/研究员/副研究员/助理研究员/院士/特聘)
in <SCHOOL NAME 中文> CS/AI departments. Skip admin staff (党委/团委/办公室/秘书/工会 etc).

Target depts (use the college_id verbatim in output):
- cid=<CID> <DEPT> <URL>
- ...

Workflow per dept:
1. WebFetch the homepage to find the 师资/教师/Faculty page link.
2. WebFetch the faculty list page (and pagination if any).
3. For each entry, gather: name (Chinese), title, homepage_url (personal page; fall
   back to profile detail URL), email, research_areas (3-6 Chinese keywords),
   bio (1-3 Chinese sentences: current role + degree origin).
4. No cap — be exhaustive. Use parallel WebFetch.

CRITICAL output protocol:
1. Use the Write tool to write a JSON array to /tmp/<school>_advisors.json:
   {"college_id": int, "name": "...", "title": "...", "homepage_url": "...",
    "email": "...", "research_areas": ["..."], "bio": "..."}
2. Do NOT paste / echo / include the JSON in your reply — risk of 32K output overflow.
3. Reply under 60 words: total + per-dept breakdown + file path.
```

After agent: feed the JSON into `pipeline/match/ingest_agent_results.py` (TODO —
currently inline in `/tmp/ingest_agent_results.py`).
