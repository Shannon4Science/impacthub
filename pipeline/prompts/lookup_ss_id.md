# Sonnet agent prompt — reverse-lookup Semantic Scholar authorId

For each advisor in the input file, find the SS authorId via WebSearch.
Faster + higher hit rate than the rate-limited public SS API. Cap each agent at
~50-80 advisors (each lookup is 3-5 tool calls).

```text
Look up Semantic Scholar authorId for each advisor in /tmp/ss_match_<batch>.json
(<SCHOOL CN NAME> CS/AI faculty, batch <X>, <N> entries).

Each input record: {advisor_id, name, title, college, school}.
school = "<SCHOOL EN NAME>".

For EACH advisor:
1. **Normalize the name first** — strip suffixes 博导 / 硕导 / (博导) / (硕导) /
   教授 / 副教授 / 助理教授 / 讲师 / 研究员 / 副研究员 / 助理研究员 before
   searching. ("茅兵博导" → "茅兵", "高阳教授" → "高阳").
2. Convert to pinyin (唐杰 → "Jie Tang").  Try TWO orderings if needed:
   "Given Surname" (most common) and "Surname Given".
3. WebSearch: `"<pinyin>" "<School EN>" site:semanticscholar.org`
4. Extract authorId from URL pattern
   `https://www.semanticscholar.org/author/[NAME]/[NUMERIC_ID]` — the trailing
   digits are the authorId.
5. If unclear, WebFetch the SS author page to verify affiliation contains the
   school keyword.
6. Fallback: DBLP — `<pinyin>` on dblp.org/search?q=, the personal page often
   links to SS.  If still nothing → scholar_id="" confidence="none".

CRITICAL output protocol:
1. Write JSON to /tmp/ss_results_<batch>.json using **Write** tool. Each item:
   {"advisor_id": int, "name": "<original name>", "scholar_id": "...",
    "confidence": "high"|"medium"|"low"|"none"}
2. Do NOT paste / echo / include JSON in your reply — risk of output overflow.
3. Reply under 40 words: total + confidence breakdown + file path.

Be efficient: parallel WebSearch where possible. Aim ≤ 4 tool calls per advisor.
```

Confidence rubric:
- **high**: SS page open, affiliation contains the school, h-index > 5
- **medium**: pinyin + school co-occurrence in SS page, no affiliation verification
- **low**: only DBLP hit, no SS verification
- **none**: nothing found within budget
