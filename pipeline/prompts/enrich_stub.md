# Sonnet agent prompt — enrich advisor stubs with bio/research_areas/photo

Use when stubs have `homepage_url` but the standard crawler couldn't extract bio
(JS-rendered profile pages, weird layouts, etc.).

```text
Enrich faculty stubs for <SCHOOL NAME 中文> CS/AI departments.

Read /tmp/<school>_stubs.json — array of {id, name, title, homepage_url,
college, college_id}.

For EACH record:
1. WebFetch the homepage_url.
2. Extract:
   - bio (1-3 Chinese sentences: current position + degree origin)
   - research_areas (3-6 Chinese keywords)
   - email (if shown)
   - photo_url (if a personal photo is shown; otherwise "")
3. If the name is clearly admin/non-faculty (院长寄语, 团学工作, 实践基地, …)
   set "skip": true and don't bother fetching.
4. If the URL 404s or doesn't look like a personal page, set "skip": true.

Use parallel WebFetch (10+ at a time when possible).

Output: write a flat JSON array to /tmp/<school>_enriched.json:
{"id": int, "bio": "...", "research_areas": ["..."], "email": "...",
 "photo_url": "...", "skip": false}

Do NOT paste JSON in your reply.
Reply: total processed, enriched count, skipped count, file path. Under 100 words.
```
