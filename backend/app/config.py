from pathlib import Path
import os as _os
from dotenv import load_dotenv as _load_dotenv

# Load .env from the project root (backend/)
_load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DATABASE_URL = f"sqlite+aiosqlite:///{DATA_DIR / 'impacthub.db'}"

SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
GITHUB_API = "https://api.github.com"
HUGGINGFACE_API = "https://huggingface.co/api"

GITHUB_TOKEN: str | None = None

# Proxy for outbound API calls (SS, GitHub, HF) from within the cluster.
OUTBOUND_PROXY: str | None = _os.environ.get("OUTBOUND_PROXY")

# LLM / Search API
LLM_API_BASE: str = _os.environ.get("LLM_API_BASE", "")
LLM_API_KEY: str = _os.environ.get("LLM_API_KEY", "")
LLM_BUZZ_MODEL: str = _os.environ.get("LLM_BUZZ_MODEL", "gpt-5")

REFRESH_INTERVAL_HOURS = 6

MILESTONE_THRESHOLDS = {
    "citations": [10, 50, 100, 200, 500, 1000, 5000],
    "stars": [10, 50, 100, 500, 1000, 5000, 10000],
    "downloads": [100, 1000, 10000, 50000, 100000],
    "hf_likes": [10, 50, 100, 500, 1000],
}
