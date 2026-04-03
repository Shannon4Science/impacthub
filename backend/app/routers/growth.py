"""Growth tracking endpoints: daily snapshots and trend data."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services.snapshot_service import get_growth_data
from app.schemas import GrowthData, GrowthSeries, GrowthPoint
from app.deps import resolve_user

router = APIRouter()

METRIC_LABELS = {
    "total_citations": "总引用",
    "total_stars": "GitHub Stars",
    "total_forks": "GitHub Forks",
    "total_downloads": "HF 下载",
    "total_hf_likes": "HF 点赞",
    "paper_count": "论文数",
    "h_index": "h-index",
    "ccf_a_count": "CCF-A 论文",
    "ccf_b_count": "CCF-B 论文",
}


@router.get("/growth/{identifier}", response_model=GrowthData)
async def get_growth(
    days: int = Query(default=30, ge=7, le=365),
    user: User = Depends(resolve_user),
    db: AsyncSession = Depends(get_db),
):
    raw = await get_growth_data(db, user.id, days)

    series = []
    for metric, points in raw["series"].items():
        series.append(GrowthSeries(
            metric=metric,
            label=METRIC_LABELS.get(metric, metric),
            data=[GrowthPoint(date=p["date"], value=p["value"]) for p in points],
        ))

    return GrowthData(
        series=series,
        daily_delta=raw.get("daily_delta", {}),
    )
