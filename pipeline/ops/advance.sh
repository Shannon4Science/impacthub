#!/bin/bash
# Watchdog — every cron tick, relaunch any dead crawl/enrich job that still has
# work to do.  Idempotent: skips jobs that are already running or have nothing
# remaining.  Reads /tmp/advance_watchdog.log for the audit trail.
set -u
ROOT=/mnt/dhwfile/raise/user/linhonglin/impacthub
PIPELINE=$ROOT/pipeline
DB=$ROOT/backend/data/impacthub.db
LOG=/tmp/advance_watchdog.log
TS=$(date '+%F %T')

is_running() {
  # Real python processes only — ignore stale claude shell wrappers that still
  # carry the pattern in their `eval '...'` argv.
  pgrep -af "$1" | grep -v "eval '" | grep -v "claude-" | grep -q "^[0-9]* python"
}

# One sqlite3 query returns all 8 numbers we need (was: 2 python subprocesses per
# school per tick).  Output schema: "<key>=<count>" lines.
read_remaining() {
  sqlite3 "$DB" <<'SQL' 2>/dev/null
.mode list
.separator =
WITH csai AS (
  SELECT id, school_id FROM advisor_colleges
   WHERE name LIKE '%计算机%' OR name LIKE '%人工智能%' OR name LIKE '%软件%'
      OR name LIKE '%信息%'   OR name LIKE '%AI%'      OR name LIKE '%智能%'
      OR name LIKE '%数据%'   OR name LIKE '%网络空间%'
)
SELECT 'detail_31', COUNT(*) FROM advisors a JOIN csai c ON a.college_id=c.id
 WHERE a.school_id=31 AND (a.bio IS NULL OR a.bio='') AND a.homepage_url != '';
SELECT 'detail_66', COUNT(*) FROM advisors a JOIN csai c ON a.college_id=c.id
 WHERE a.school_id=66 AND (a.bio IS NULL OR a.bio='') AND a.homepage_url != '';
SELECT 'enrich_32', COUNT(*) FROM advisors a
   LEFT JOIN ai_summaries s ON s.user_id=a.impacthub_user_id
 WHERE a.school_id=32 AND a.impacthub_user_id IS NOT NULL AND a.impacthub_user_id!=0
   AND (s.id IS NULL OR s.summary='');
SELECT 'enrich_65', COUNT(*) FROM advisors a
   LEFT JOIN ai_summaries s ON s.user_id=a.impacthub_user_id
 WHERE a.school_id=65 AND a.impacthub_user_id IS NOT NULL AND a.impacthub_user_id!=0
   AND (s.id IS NULL OR s.summary='');
SQL
}

# Slurp counts into associative-array-ish vars (one fork per tick instead of 8).
REMAINING=$(read_remaining)
get() { echo "$REMAINING" | awk -F= -v k="$1" '$1==k{print $2}'; }

start_detail() {
  local label=$1 school=$2 sid=$3 remaining_key=$4 maxn=${5:-250}
  local proc="04_advisor_details.*--school $school"
  if is_running "$proc"; then
    echo "[$TS] $label detail already running, skip" >> $LOG; return
  fi
  local n=$(get "$remaining_key")
  if ! [[ "$n" =~ ^[0-9]+$ ]]; then
    echo "[$TS] $label detail: DB query failed, skip this tick" >> $LOG; return
  fi
  if [ "$n" -le 0 ]; then
    echo "[$TS] $label detail: 0 remaining, skip" >> $LOG; return
  fi
  echo "[$TS] $label detail: $n remaining, relaunching" >> $LOG
  cd $PIPELINE && nohup python crawl/04_advisor_details.py --school "$school" --max $maxn \
    >> /tmp/${label}_detail.out 2>&1 &
}

start_enrich() {
  local label=$1 school=$2 remaining_key=$3
  # run_all.py loops the 6 LLM tabs in dep order; one process per school is enough.
  local proc="analyze/run_all\\.py.*--schools $school"
  if is_running "$proc"; then
    echo "[$TS] $label enrich already running, skip" >> $LOG; return
  fi
  local n=$(get "$remaining_key")
  if ! [[ "$n" =~ ^[0-9]+$ ]]; then
    echo "[$TS] $label enrich: DB query failed, skip this tick" >> $LOG; return
  fi
  if [ "$n" -le 0 ]; then
    echo "[$TS] $label enrich: 0 remaining, skip" >> $LOG; return
  fi
  echo "[$TS] $label enrich: $n users without ai_summary, relaunching" >> $LOG
  cd $PIPELINE && nohup python analyze/run_all.py --schools "$school" --concurrency 10 \
    >> /tmp/enrich_${label}.out 2>&1 &
}

start_detail Fudan 复旦 31 detail_31 250
start_detail USTC  中国科学技术 66 detail_66 200
start_enrich SJTU  SJTU enrich_32
start_enrich ZJU   ZJU  enrich_65

echo "[$TS] sweep done" >> $LOG
