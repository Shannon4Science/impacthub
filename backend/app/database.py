import aiosqlite.core
import pysqlite3
import sqlite_vec
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text, event

from sqlalchemy.pool import StaticPool

from app.config import DATABASE_URL, DASHSCOPE_EMBEDDING_DIMENSIONS

# The system sqlite3 module on this machine is compiled without loadable
# extension support. aiosqlite uses a module-level sqlite3 reference, so patch it
# before SQLAlchemy opens any connections.
aiosqlite.core.sqlite3 = pysqlite3

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30},          # wait up to 30s for the write lock
    poolclass=StaticPool,                   # single shared connection for SQLite
)

# Set WAL mode and busy_timeout on every new raw connection
@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn, connection_record):
    async def load_vec0(driver_conn):
        await driver_conn.enable_load_extension(True)
        try:
            await driver_conn.load_extension(sqlite_vec.loadable_path())
        finally:
            await driver_conn.enable_load_extension(False)

    try:
        dbapi_conn.run_async(load_vec0)
    except Exception as exc:
        raise RuntimeError("sqlite-vec 扩展加载失败，导师推荐功能不能启动") from exc

    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    async with engine.begin() as conn:
        await conn.execute(text("SELECT vec_version()"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS advisor_embedding_vec USING vec0(
                    embedding float[{DASHSCOPE_EMBEDDING_DIMENSIONS}] distance_metric=cosine
                )
                """
            )
        )
        vec_schema = (
            await conn.execute(
                text("SELECT sql FROM sqlite_master WHERE name = 'advisor_embedding_vec'")
            )
        ).scalar_one()
        expected_vec_schema = f"embedding float[{DASHSCOPE_EMBEDDING_DIMENSIONS}] distance_metric=cosine"
        if expected_vec_schema not in vec_schema:
            raise RuntimeError("advisor_embedding_vec 结构不符合当前配置，请先迁移或重建向量表")
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
        try:
            await conn.execute(text("ALTER TABLE advisor_mentions ADD COLUMN external_id VARCHAR(120) DEFAULT ''"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE advisor_mentions ADD COLUMN mention_type VARCHAR(30) DEFAULT 'general'"))
        except Exception:
            pass
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_advisor_mentions_external
                ON advisor_mentions(advisor_id, source, external_id)
                WHERE advisor_id != 0 AND external_id != ''
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_advisor_mentions_url_without_external
                ON advisor_mentions(advisor_id, source, url)
                WHERE advisor_id != 0 AND source = 'xiaohongshu' AND external_id = '' AND url != ''
                """
            )
        )
        # advisors: cached recruitment summary imported from XHS pipeline output
        try:
            await conn.execute(text("ALTER TABLE advisors ADD COLUMN recruitment_summary_json JSON DEFAULT NULL"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE advisors ADD COLUMN recruitment_summary_refreshed_at DATETIME DEFAULT NULL"))
        except Exception:
            pass
        try:
            await conn.execute(text("ALTER TABLE advisors ADD COLUMN recruitment_summary_status VARCHAR(20) DEFAULT ''"))
        except Exception:
            pass


async def get_db():
    async with async_session() as session:
        yield session
