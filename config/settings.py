import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------
# Project paths
# ---------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROJECTS_DIR = PROJECT_ROOT / "projects"
OUTPUT_DIR = PROJECT_ROOT / "output"
CACHE_DIR = PROJECT_ROOT / "cache"
LOGS_DIR = PROJECT_ROOT / "logs"


# ---------------------------------------------------------
# Environment
# ---------------------------------------------------------

load_dotenv()

PROJECT_ENV = os.getenv("PROJECT_ENV", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


# ---------------------------------------------------------
# OpenAI
# ---------------------------------------------------------

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.4-mini",
)


# ---------------------------------------------------------
# vidIQ MCP (optional)
# ---------------------------------------------------------

VIDIQ_MCP_URL = os.getenv(
    "VIDIQ_MCP_URL",
    "https://mcp.vidiq.com/mcp",
)
VIDIQ_MCP_API_KEY = os.getenv("VIDIQ_MCP_API_KEY")
RITZZ_CANDIDATE_POOL_TARGET = int(os.getenv("RITZZ_CANDIDATE_POOL_TARGET", "30"))
RITZZ_DISCOVERY_FALLBACK_STAGES = tuple(
    stage.strip()
    for stage in os.getenv(
        "RITZZ_DISCOVERY_FALLBACK_STAGES",
        "broader-trending,rising,evergreen,long-tail,competitor-outliers,unscoped",
    ).split(",")
    if stage.strip()
)
RITZZ_M7_LIMITED_THRESHOLD = int(os.getenv("RITZZ_M7_LIMITED_THRESHOLD", "3"))
RITZZ_M7_EMERGING_THRESHOLD = int(os.getenv("RITZZ_M7_EMERGING_THRESHOLD", "6"))
RITZZ_M7_ESTABLISHED_THRESHOLD = int(os.getenv("RITZZ_M7_ESTABLISHED_THRESHOLD", "12"))
RITZZ_COMPETITORS_FILE = Path(
    os.getenv("RITZZ_COMPETITORS_FILE", str(PROJECT_ROOT / "config" / "competitors.json"))
)
RITZZ_COMPETITOR_LOOKBACK_DAYS = int(
    os.getenv("RITZZ_COMPETITOR_LOOKBACK_DAYS", "365")
)
RITZZ_COMPETITOR_VIDEO_LIMIT = int(os.getenv("RITZZ_COMPETITOR_VIDEO_LIMIT", "20"))
RITZZ_OUTLIER_MIN_SCORE = float(os.getenv("RITZZ_OUTLIER_MIN_SCORE", "2"))
RITZZ_FIT_PASS_THRESHOLD = float(
    os.getenv(
        "RITZZ_RITZZ_FIT_THRESHOLD",
        os.getenv("RITZZ_FIT_PASS_THRESHOLD", "65"),
    )
)
if not 0 <= RITZZ_FIT_PASS_THRESHOLD <= 100:
    raise ValueError("RITZZ_FIT_PASS_THRESHOLD must be between 0 and 100.")
if not 15 <= RITZZ_CANDIDATE_POOL_TARGET <= 30:
    raise ValueError("RITZZ_CANDIDATE_POOL_TARGET must be between 15 and 30.")
if set(RITZZ_DISCOVERY_FALLBACK_STAGES) - {
    "broader-trending",
    "rising",
    "evergreen",
    "long-tail",
    "competitor-outliers",
    "unscoped",
}:
    raise ValueError("RITZZ_DISCOVERY_FALLBACK_STAGES contains an unknown stage.")
if not (
    0 < RITZZ_M7_LIMITED_THRESHOLD
    < RITZZ_M7_EMERGING_THRESHOLD
    < RITZZ_M7_ESTABLISHED_THRESHOLD
):
    raise ValueError(
        "M7 sample thresholds must be positive and strictly increasing."
    )
if not 1 <= RITZZ_COMPETITOR_LOOKBACK_DAYS <= 3650:
    raise ValueError("RITZZ_COMPETITOR_LOOKBACK_DAYS must be between 1 and 3650.")
if not 1 <= RITZZ_COMPETITOR_VIDEO_LIMIT <= 50:
    raise ValueError("RITZZ_COMPETITOR_VIDEO_LIMIT must be between 1 and 50.")
if RITZZ_OUTLIER_MIN_SCORE < 0:
    raise ValueError("RITZZ_OUTLIER_MIN_SCORE cannot be negative.")
