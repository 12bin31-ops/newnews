"""프로젝트 전역 설정 — API 키 로드, 검색 키워드, 카테고리 정의."""

import os
from pathlib import Path

from dotenv import load_dotenv

# .env 로드 (프로젝트 루트 기준)
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# --- LLM 공급자 -------------------------------------------------------------
# "gemini"(무료 티어) 또는 "anthropic". .env의 LLM_PROVIDER로 전환한다.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").strip().lower()

# --- API 키 ---------------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

# 연속 호출 사이 대기(초). Gemini 무료 티어는 분당 요청 수(RPM) 제한이 낮아 넉넉히 둔다.
# 13초 ≈ 4.6 RPM. 유료 전환 시 .env에서 LLM_REQUEST_DELAY를 낮추면 된다.
LLM_REQUEST_DELAY = float(
    os.getenv("LLM_REQUEST_DELAY", "5" if LLM_PROVIDER == "gemini" else "0.3")
)

# --- 경로 -----------------------------------------------------------------
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "news.db"

# --- 수집 설정 -------------------------------------------------------------
SEARCH_KEYWORDS = [
    "SK하이닉스",
    "삼성전자 반도체",
    "HBM",
    "NVIDIA AI칩",
    "반도체 시장",
    "메모리 반도체",
]

# 최근 며칠 이내 기사만 수집할지 (시간 단위)
COLLECT_WINDOW_HOURS = 48

# 키워드당 최대 수집 건수
MAX_ARTICLES_PER_KEYWORD = 10

# --- 분류 체계 -------------------------------------------------------------
CATEGORIES = [
    "시장상황",
    "경쟁사동향",
    "자사언급",
    "기술트렌드",
    "규제정책",
    "고객사동향",
]

TAGS = ["기회", "위협", "중립"]

# 자사 기준 (자사언급 카테고리 판정용) — 필요에 맞게 수정하세요
OUR_COMPANY = "SK하이닉스"
