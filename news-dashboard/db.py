"""SQLite DB 초기화 및 CRUD 함수."""

import sqlite3
from datetime import datetime
from typing import Any, Optional

import config

# ---------------------------------------------------------------- 연결 관리

def get_connection() -> sqlite3.Connection:
    """DB 커넥션 반환. row_factory를 걸어 dict 변환이 쉽게 되도록 한다."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- 스키마

CREATE_ARTICLES = """
CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    url             TEXT NOT NULL UNIQUE,
    source          TEXT,
    published_at    TEXT,
    collected_at    TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    summary         TEXT,
    category        TEXT,
    category_reason TEXT,
    tag             TEXT,
    score           INTEGER,
    keywords        TEXT
)
"""

CREATE_COMMENTS = """
CREATE TABLE IF NOT EXISTS comments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    article_id  INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    author      TEXT NOT NULL,
    comment     TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
)
"""

CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published_at)",
    "CREATE INDEX IF NOT EXISTS idx_articles_tag ON articles(tag)",
    "CREATE INDEX IF NOT EXISTS idx_comments_article ON comments(article_id)",
]


def init_db() -> None:
    """테이블이 없으면 생성한다. 여러 번 호출해도 안전."""
    with get_connection() as conn:
        conn.execute(CREATE_ARTICLES)
        conn.execute(CREATE_COMMENTS)
        for stmt in CREATE_INDEXES:
            conn.execute(stmt)


# ---------------------------------------------------------------- articles

# 날짜 필터·집계의 기준 컬럼. 수집일(스크랩한 날) 또는 발행일.
DATE_BASES = {"collected_at", "published_at"}


def _date_expr(basis: str) -> str:
    """날짜 기준 SQL 표현식. 값이 비어 있으면 collected_at으로 대체한다."""
    if basis not in DATE_BASES:
        raise ValueError(f"date_basis는 {DATE_BASES} 중 하나여야 합니다: {basis!r}")
    if basis == "collected_at":
        return "date(collected_at)"
    return "date(COALESCE(NULLIF(published_at, ''), collected_at))"


ARTICLE_FIELDS = [
    "title", "url", "source", "published_at", "collected_at",
    "summary", "category", "category_reason", "tag", "score", "keywords",
]


def _normalize_article(article: dict[str, Any]) -> dict[str, Any]:
    """dict/list 형태의 category·keywords를 콤마 문자열로 평탄화한다."""
    row = {k: article.get(k) for k in ARTICLE_FIELDS}

    for key in ("category", "keywords"):
        value = row.get(key)
        if isinstance(value, (list, tuple, set)):
            row[key] = ", ".join(str(v).strip() for v in value if str(v).strip())

    if not row.get("collected_at"):
        row["collected_at"] = _now()

    if row.get("score") is not None:
        try:
            row["score"] = int(row["score"])
        except (TypeError, ValueError):
            row["score"] = None

    return row


def insert_article(article: dict[str, Any]) -> Optional[int]:
    """기사 1건 저장. URL이 이미 있으면 무시하고 None을 반환한다."""
    if not article.get("url") or not article.get("title"):
        return None

    row = _normalize_article(article)
    columns = ", ".join(ARTICLE_FIELDS)
    placeholders = ", ".join(f":{f}" for f in ARTICLE_FIELDS)
    sql = f"INSERT OR IGNORE INTO articles ({columns}) VALUES ({placeholders})"

    with get_connection() as conn:
        cur = conn.execute(sql, row)
        # INSERT OR IGNORE로 스킵되면 rowcount == 0
        return cur.lastrowid if cur.rowcount else None


def get_articles(
    category: Optional[str | list[str]] = None,
    tag: Optional[str | list[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_score: Optional[int] = None,
    date_basis: str = "collected_at",
    on_date: Optional[str] = None,
) -> list[dict[str, Any]]:
    """필터링 조회. category는 콤마 문자열 안에 포함되면 매칭(다중 카테고리 지원).

    on_date를 주면 해당 날짜 하루만 조회한다(date_from/date_to보다 우선).
    """
    dexpr = _date_expr(date_basis)
    sql = "SELECT * FROM articles WHERE 1=1"
    params: list[Any] = []

    if category:
        cats = [category] if isinstance(category, str) else list(category)
        if cats:
            clause = " OR ".join(["category LIKE ?"] * len(cats))
            sql += f" AND ({clause})"
            params.extend(f"%{c}%" for c in cats)

    if tag:
        tags = [tag] if isinstance(tag, str) else list(tag)
        if tags:
            sql += f" AND tag IN ({', '.join('?' * len(tags))})"
            params.extend(tags)

    if on_date:
        sql += f" AND {dexpr} = date(?)"
        params.append(on_date)
    else:
        if date_from:
            sql += f" AND {dexpr} >= date(?)"
            params.append(date_from)
        if date_to:
            sql += f" AND {dexpr} <= date(?)"
            params.append(date_to)

    if min_score is not None:
        sql += " AND COALESCE(score, 0) >= ?"
        params.append(min_score)

    sql += " ORDER BY COALESCE(score, 0) DESC, COALESCE(published_at, collected_at) DESC"

    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def update_article_analysis(article_id: int, analysis: dict[str, Any]) -> bool:
    """기존 기사의 분석 결과(요약·분류·태그·점수·키워드)만 덮어쓴다."""
    row = _normalize_article({**analysis, "title": "x", "url": "x"})
    with get_connection() as conn:
        cur = conn.execute(
            """UPDATE articles
                  SET summary = :summary, category = :category,
                      category_reason = :category_reason, tag = :tag,
                      score = :score, keywords = :keywords
                WHERE id = :id""",
            {
                "summary": row["summary"],
                "category": row["category"],
                "category_reason": row["category_reason"],
                "tag": row["tag"],
                "score": row["score"],
                "keywords": row["keywords"],
                "id": article_id,
            },
        )
        return cur.rowcount > 0


def get_article(article_id: int) -> Optional[dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
        return dict(row) if row else None


def url_exists(url: str) -> bool:
    """수집 단계에서 LLM 호출 전에 중복을 걸러내기 위한 헬퍼."""
    with get_connection() as conn:
        return conn.execute("SELECT 1 FROM articles WHERE url = ?", (url,)).fetchone() is not None


def delete_article(article_id: int) -> bool:
    """기사 1건 삭제. 코멘트는 FK ON DELETE CASCADE로 함께 지워진다."""
    with get_connection() as conn:
        return conn.execute("DELETE FROM articles WHERE id = ?", (article_id,)).rowcount > 0


def count_articles() -> int:
    with get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]


def get_stats(
    date_from: Optional[str] = None,
    on_date: Optional[str] = None,
    date_basis: str = "collected_at",
) -> dict[str, int]:
    """대시보드 상단 통계용: 총 건수 / 기회 / 위협 / 중립."""
    dexpr = _date_expr(date_basis)
    sql = "SELECT tag, COUNT(*) AS cnt FROM articles WHERE 1=1"
    params: list[Any] = []
    if on_date:
        sql += f" AND {dexpr} = date(?)"
        params.append(on_date)
    elif date_from:
        sql += f" AND {dexpr} >= date(?)"
        params.append(date_from)
    sql += " GROUP BY tag"

    stats = {"총계": 0, "기회": 0, "위협": 0, "중립": 0}
    with get_connection() as conn:
        for row in conn.execute(sql, params):
            stats["총계"] += row["cnt"]
            if row["tag"] in stats:
                stats[row["tag"]] = row["cnt"]
    return stats


def get_daily_counts(
    date_basis: str = "collected_at",
    category: Optional[str | list[str]] = None,
    tag: Optional[str | list[str]] = None,
    min_score: Optional[int] = None,
) -> dict[str, dict[str, int]]:
    """달력 렌더링용 날짜별 집계.

    반환: {"2026-08-24": {"총계": 8, "기회": 3, "위협": 2, "중립": 3}, ...}
    필터를 주면 필터가 적용된 집계를 돌려준다.
    """
    dexpr = _date_expr(date_basis)
    sql = f"SELECT {dexpr} AS d, tag, COUNT(*) AS cnt FROM articles WHERE 1=1"
    params: list[Any] = []

    if category:
        cats = [category] if isinstance(category, str) else list(category)
        if cats:
            clause = " OR ".join(["category LIKE ?"] * len(cats))
            sql += f" AND ({clause})"
            params.extend(f"%{c}%" for c in cats)

    if tag:
        tags = [tag] if isinstance(tag, str) else list(tag)
        if tags:
            sql += f" AND tag IN ({', '.join('?' * len(tags))})"
            params.extend(tags)

    if min_score is not None:
        sql += " AND COALESCE(score, 0) >= ?"
        params.append(min_score)

    sql += " GROUP BY d, tag"

    out: dict[str, dict[str, int]] = {}
    with get_connection() as conn:
        for row in conn.execute(sql, params):
            day = row["d"]
            if not day:
                continue
            bucket = out.setdefault(day, {"총계": 0, "기회": 0, "위협": 0, "중립": 0})
            bucket["총계"] += row["cnt"]
            if row["tag"] in bucket:
                bucket[row["tag"]] += row["cnt"]
    return out


def get_date_bounds(date_basis: str = "collected_at") -> tuple[Optional[str], Optional[str]]:
    """데이터가 존재하는 가장 이른/늦은 날짜. 달력 이동 범위 제한에 쓴다."""
    dexpr = _date_expr(date_basis)
    with get_connection() as conn:
        row = conn.execute(f"SELECT MIN({dexpr}), MAX({dexpr}) FROM articles").fetchone()
        return (row[0], row[1]) if row else (None, None)


# ---------------------------------------------------------------- comments

def add_comment(article_id: int, author: str, comment: str) -> Optional[int]:
    """코멘트 추가. 빈 내용이면 저장하지 않는다."""
    author = (author or "").strip() or "익명"
    comment = (comment or "").strip()
    if not comment:
        return None

    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO comments (article_id, author, comment, created_at) VALUES (?, ?, ?, ?)",
            (article_id, author, comment, _now()),
        )
        return cur.lastrowid


def get_comments(article_id: int) -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM comments WHERE article_id = ? ORDER BY created_at ASC, id ASC",
            (article_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_comments(article_id: int) -> int:
    with get_connection() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM comments WHERE article_id = ?", (article_id,)
        ).fetchone()[0]


if __name__ == "__main__":
    init_db()
    print(f"DB 초기화 완료: {config.DB_PATH}")
    print(f"저장된 기사 수: {count_articles()}")
