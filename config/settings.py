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

if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is not configured. "
        "Add it to the .env file."
    )


OPENAI_MODEL = os.getenv(
    "OPENAI_MODEL",
    "gpt-5.4-mini",
)