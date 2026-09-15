import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("AUTOCUT_DATA_DIR", BASE_DIR / "data"))
UPLOADS_DIR = DATA_DIR / "uploads"
JOBS_DIR = DATA_DIR / "jobs"

for d in (UPLOADS_DIR, JOBS_DIR):
    d.mkdir(parents=True, exist_ok=True)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "auto")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "")  # пусто = автоопределение
DEFAULT_LANGUAGE = os.getenv("WHISPER_DEFAULT_LANGUAGE", "ru")  # язык по умолчанию, если не выбран в UI

DEFAULT_MIN_SCORE = 70
DEFAULT_CLIP_MIN_SEC = 8
DEFAULT_CLIP_MAX_SEC = 90
DEFAULT_MAX_CLIPS = 6
DEFAULT_BURN_SUBTITLES = True

# ретенция джобов: хранить результаты не дольше N дней, но всегда оставлять K последних
JOB_RETENTION_DAYS = float(os.getenv("AUTOCUT_JOB_RETENTION_DAYS", "7"))
KEEP_RECENT_JOBS = int(os.getenv("AUTOCUT_KEEP_RECENT_JOBS", "10"))

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".ts"}