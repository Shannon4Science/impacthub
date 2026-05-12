"""Import the 211 school seed list into advisor_schools.

Usage:
    cd backend && python scripts/import_advisor_schools.py
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline._common import setup_logging  # noqa: E402  (also adds backend/ to sys.path)

from sqlalchemy import select

from app.database import async_session, init_db
from app.models import AdvisorSchool


SEED_PATH = Path(__file__).resolve().parent.parent / "data" / "advisor_schools_211.json"


async def main():
    await init_db()
    payload = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    schools = payload["schools"]
    inserted = 0
    updated = 0
    async with async_session() as db:
        for s in schools:
            existing = (await db.execute(
                select(AdvisorSchool).where(AdvisorSchool.name == s["name"])
            )).scalars().first()
            if existing:
                existing.short_name = s.get("short_name", "")
                existing.english_name = s.get("english_name", "")
                existing.city = s.get("city", "")
                existing.province = s.get("province", "")
                existing.school_type = s.get("school_type", "")
                existing.is_985 = bool(s.get("is_985"))
                existing.is_211 = bool(s.get("is_211", True))
                existing.is_double_first_class = bool(s.get("is_double_first_class"))
                existing.homepage_url = s.get("homepage_url", "")
                updated += 1
            else:
                db.add(AdvisorSchool(
                    name=s["name"],
                    short_name=s.get("short_name", ""),
                    english_name=s.get("english_name", ""),
                    city=s.get("city", ""),
                    province=s.get("province", ""),
                    school_type=s.get("school_type", ""),
                    is_985=bool(s.get("is_985")),
                    is_211=bool(s.get("is_211", True)),
                    is_double_first_class=bool(s.get("is_double_first_class")),
                    homepage_url=s.get("homepage_url", ""),
                ))
                inserted += 1
        await db.commit()
    print(f"Done. inserted={inserted} updated={updated} total={inserted+updated}")


if __name__ == "__main__":
    asyncio.run(main())
