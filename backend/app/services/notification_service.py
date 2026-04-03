"""Notification service: sends milestone achievements to Feishu/Lark webhook."""

import logging
from datetime import datetime

import httpx

from app.models import Milestone, User

logger = logging.getLogger(__name__)

METRIC_LABELS = {
    "citations": "引用",
    "stars": "GitHub Star",
    "downloads": "下载",
    "hf_likes": "HF 点赞",
}

MILESTONE_EMOJIS = {
    10: "🌱",
    50: "🌿",
    100: "🔥",
    200: "💎",
    500: "🏆",
    1000: "👑",
    5000: "🚀",
    10000: "⭐",
    50000: "🌟",
    100000: "💫",
}


def _get_emoji(threshold: int) -> str:
    best = "🎉"
    for t, e in sorted(MILESTONE_EMOJIS.items()):
        if threshold >= t:
            best = e
    return best


def _build_feishu_card(user: User, milestone: Milestone) -> dict:
    """Build a Feishu interactive card message."""
    metric_label = METRIC_LABELS.get(milestone.metric_type, milestone.metric_type)
    emoji = _get_emoji(milestone.threshold)
    is_total = milestone.metric_key == "__total__"
    target = "总计" if is_total else milestone.metric_key

    title = f"{emoji} 里程碑达成！{metric_label}突破 {milestone.threshold:,}"

    elements = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**{user.name or user.github_username}** 的"
                    f"{'总' if is_total else ''}{metric_label}"
                    f"{'（' + target + '）' if not is_total else ''}"
                    f"已达到 **{milestone.achieved_value:,}**！"
                ),
            },
        },
        {"tag": "hr"},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"📊 指标类型: {metric_label}\n"
                    f"🎯 里程碑: {milestone.threshold:,}\n"
                    f"📈 当前值: {milestone.achieved_value:,}\n"
                    f"🕐 达成时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
                ),
            },
        },
    ]

    return {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "purple",
            },
            "elements": elements,
        },
    }


async def send_milestone_notification(user: User, milestone: Milestone):
    """Send a milestone achievement notification to configured channels."""
    if not user.feishu_webhook:
        return

    payload = _build_feishu_card(user, milestone)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(user.feishu_webhook, json=payload)
            if resp.status_code == 200:
                logger.info(
                    "Feishu notification sent for user %d: %s/%s crossed %d",
                    user.id, milestone.metric_type, milestone.metric_key, milestone.threshold,
                )
            else:
                logger.warning("Feishu webhook failed: %s %s", resp.status_code, resp.text[:200])
        except Exception:
            logger.exception("Failed to send Feishu notification")


async def send_daily_summary(user: User, deltas: dict[str, float]):
    """Send a daily summary of metric changes to Feishu."""
    if not user.feishu_webhook:
        return

    lines = []
    for metric, delta in deltas.items():
        if delta > 0:
            label = METRIC_LABELS.get(metric, metric)
            lines.append(f"📈 {label}: **+{int(delta):,}**")

    if not lines:
        return

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"📊 {user.name or user.github_username} 每日数据变化"},
                "template": "blue",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "\n".join(lines),
                    },
                },
            ],
        },
    }

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.post(user.feishu_webhook, json=payload)
            if resp.status_code == 200:
                logger.info("Daily summary sent for user %d", user.id)
        except Exception:
            logger.exception("Failed to send daily summary")
