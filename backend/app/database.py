from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text, event

from sqlalchemy.pool import StaticPool

from app.config import DATABASE_URL

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30},          # wait up to 30s for the write lock
    poolclass=StaticPool,                   # single shared connection for SQLite
)

# Set WAL mode and busy_timeout on every new raw connection
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Add honor_tags column to existing DB if not present (SQLite migration)
        try:
            await conn.execute(
                text("ALTER TABLE notable_citations ADD COLUMN honor_tags JSON DEFAULT NULL")
            )
        except Exception:
            pass  # Column already exists
        try:
            await conn.execute(
                text("ALTER TABLE users ADD COLUMN honor_tags JSON DEFAULT NULL")
            )
        except Exception:
            pass
        try:
            await conn.execute(
                text("ALTER TABLE users ADD COLUMN research_direction VARCHAR(20) DEFAULT ''")
            )
        except Exception:
            pass
        try:
            await conn.execute(
                text("ALTER TABLE users ADD COLUMN seed_tier VARCHAR(20) DEFAULT ''")
            )
        except Exception:
            pass
        # annual_poems and career_histories are covered by create_all above
        # capability_profiles: schema changed from single-type to per-direction
        try:
            await conn.execute(text("ALTER TABLE capability_profiles ADD COLUMN primary_role VARCHAR(20) DEFAULT ''"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE capability_profiles ADD COLUMN primary_direction VARCHAR(100) DEFAULT ''"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE capability_profiles ADD COLUMN profiles_json JSON DEFAULT '[]'"))
        except Exception:
            pass
        # advisor_mentions: pending fields for unlinked-then-reconciled flow
        try:
            await conn.execute(text("ALTER TABLE advisor_mentions ADD COLUMN pending_advisor_name VARCHAR(80) DEFAULT ''"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE advisor_mentions ADD COLUMN pending_school_name VARCHAR(120) DEFAULT ''"))
        except Exception:
            pass


async def get_db():
    async with async_session() as session:
        yield session
