"""Generate cached advisor embeddings for recommendation matching."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import async_session, init_db
from app.models import AdvisorCollege, AdvisorSchool
from app.services.recommendation_service import ensure_advisor_embeddings


async def _resolve_scope(school_name: str | None, college_name: str | None) -> tuple[int | None, int | None]:
    async with async_session() as db:
        school_id = None
        college_id = None
        if school_name:
            school = (
                await db.execute(select(AdvisorSchool).where(AdvisorSchool.name == school_name))
            ).scalar_one_or_none()
            if not school:
                raise SystemExit(f"学校不存在：{school_name}")
            school_id = school.id
        if college_name:
            stmt = select(AdvisorCollege).where(AdvisorCollege.name == college_name)
            if school_id:
                stmt = stmt.where(AdvisorCollege.school_id == school_id)
            college = (await db.execute(stmt)).scalar_one_or_none()
            if not college:
                raise SystemExit(f"学院不存在：{college_name}")
            college_id = college.id
            school_id = school_id or college.school_id
        return school_id, college_id


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--school-name", default="上海交通大学")
    parser.add_argument("--college-name", default="人工智能学院")
    args = parser.parse_args()

    await init_db()
    school_id, college_id = await _resolve_scope(args.school_name, args.college_name)
    async with async_session() as db:
        generated = await ensure_advisor_embeddings(db, school_id=school_id, college_id=college_id)
        print(f"generated_or_refreshed={generated}")


if __name__ == "__main__":
    asyncio.run(main())
