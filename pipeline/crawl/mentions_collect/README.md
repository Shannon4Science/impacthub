# Advisor Mentions（导师舆情/口碑）导入

把公众号 / 小红书 / 知乎等渠道关于导师的内容沉淀到数据库，给保研学生看。

## 流程

1. **采集**（你来做）— 写一份 JSONL，每行一条记录。建议 source_account 默认填 `鹿鸣观山海`。
2. **导入**（脚本帮你做）：
   ```bash
   cd backend
   python scripts/import_advisor_mentions.py path/to/your.jsonl --dedup-by-url
   ```
3. **校验**：调 API `GET /api/advisor/advisors/{id}/mentions` 看是否入库。

## JSONL 字段

每行一个 JSON 对象。`advisor_name + school_name` 用于匹配 advisor，必须二选一组合（同名时必须给 school 消歧）。

```jsonl
{"advisor_name":"唐杰","school_name":"清华大学","source":"wechat","source_account":"鹿鸣观山海","title":"清华唐杰团队 2026 招生","url":"https://mp.weixin.qq.com/s/...","snippet":"组里今年扩招 5 名硕博...","likes":420,"reads":12000,"sentiment":"positive","tags":["招生","组氛围"],"published_at":"2026-04-15T08:00:00+08:00"}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `advisor_name` | 推荐 | 导师姓名（与 DB 中 advisors.name 完全匹配） |
| `school_name` | 推荐 | 学校全名（同名导师时用于消歧） |
| `advisor_id` | 可选 | 直接给数字 ID，匹配最快 |
| `source` | 是 | `wechat` / `xiaohongshu` / `zhihu` / `forum` / `other` |
| `source_account` | 否 | 如 "鹿鸣观山海" |
| `title` | 否 | 文章标题 |
| `url` | 否 | 原文链接 |
| `snippet` | 否 | 摘要 / 摘抄关键句 |
| `cover_url` | 否 | 封面图 |
| `likes` / `reads` / `comments` | 否 | 互动数（缺数据填 0） |
| `sentiment` | 否 | `positive` / `neutral` / `negative` |
| `tags` | 否 | 字符串数组：`["招生","push","放养","组氛围"]` 等 |
| `published_at` | 否 | ISO8601 时间 |

## 命令选项

- `--dry-run` — 只解析 + 匹配，不写库（用于排查同名歧义）
- `--dedup-by-url` — 同一 advisor + 同一 url 已存在则跳过
- `--default-source wechat` — 记录里没填 source 时的默认值
- `--default-account 鹿鸣观山海` — 记录里没填 source_account 时的默认值

例：
```bash
python scripts/import_advisor_mentions.py mentions/2026-04-luming.jsonl \
    --default-account 鹿鸣观山海 --dedup-by-url
```

## 同名歧义

某些常见姓名在多所学校重复（如 张伟 / 王伟），脚本会跳过这种行并打印 first 10 例。补 `school_name` 重跑即可。

## 示例文件

`luming_example.jsonl` — 公众号"鹿鸣观山海"的两条示例。
