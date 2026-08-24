"""구글 뉴스 RSS 기반 뉴스 수집기."""

import html
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import feedparser
import requests

import config

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"

# feedparser가 내부적으로 쓰는 urllib은 macOS python.org 빌드에서 SSL 인증서
# 검증에 실패하는 경우가 있어, requests(certifi 번들)로 받아 파싱만 맡긴다.
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    )
}
REQUEST_TIMEOUT = 15

# 구글 뉴스 제목은 "기사 제목 - 언론사" 형태로 오는 경우가 많다
TITLE_SOURCE_RE = re.compile(r"\s+-\s+([^-]+)$")


def normalize_title(title: str) -> str:
    """제목 중복 판정을 위한 정규화. 공백·기호·괄호 내용 차이를 무시한다.

    같은 사안을 여러 매체가 거의 같은 제목으로 내보내는 경우가 많아,
    URL만으로는 중복을 걸러낼 수 없다.
    """
    t = (title or "").lower()
    t = re.sub(r"\[[^\]]*\]", " ", t)       # [단독], [핫칩스 2026] 등 대괄호 구간
    t = re.sub(r"\([^)]*\)", " ", t)         # 괄호 구간
    t = re.sub(r"[^0-9a-z가-힣]", "", t)     # 공백·기호 전부 제거
    return t


def _strip_html(text: str) -> str:
    """RSS summary에 섞인 HTML 태그와 엔티티를 제거한다."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_published(entry: Any) -> Optional[datetime]:
    """entry의 발행일을 tz-aware datetime으로 파싱한다."""
    parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if not parsed:
        return None
    try:
        # published_parsed는 UTC 기준 struct_time
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _extract_source(entry: Any, title: str) -> tuple[str, str]:
    """(정리된 제목, 언론사)를 반환한다."""
    source = ""
    src_obj = getattr(entry, "source", None)
    if src_obj is not None:
        source = getattr(src_obj, "title", "") or (
            src_obj.get("title", "") if isinstance(src_obj, dict) else ""
        )

    clean_title = title
    match = TITLE_SOURCE_RE.search(title)
    if match:
        tail = match.group(1).strip()
        # 제목 끝의 " - 언론사"를 잘라낸다
        if not source:
            source = tail
        clean_title = title[: match.start()].strip()

    return clean_title or title, (source or "출처 미상").strip()


def fetch_news(
    keyword: str,
    window_hours: int = config.COLLECT_WINDOW_HOURS,
    limit: int = config.MAX_ARTICLES_PER_KEYWORD,
) -> list[dict[str, Any]]:
    """키워드로 구글 뉴스 RSS를 검색해 최근 기사 리스트를 반환한다.

    반환 dict 키: title, url, source, published_at, content, keyword
    """
    query = urllib.parse.quote_plus(keyword)
    url = GOOGLE_NEWS_RSS.format(query=query)

    try:
        resp = requests.get(url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except requests.RequestException as exc:  # 네트워크/HTTP 실패는 건너뛴다
        print(f"  [!] '{keyword}' 피드 요청 실패: {exc}")
        return []
    except Exception as exc:
        print(f"  [!] '{keyword}' 피드 파싱 실패: {exc}")
        return []

    if getattr(feed, "bozo", 0) and not getattr(feed, "entries", None):
        print(f"  [!] '{keyword}' 피드 파싱 실패: {getattr(feed, 'bozo_exception', '알 수 없음')}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    articles: list[dict[str, Any]] = []

    for entry in feed.entries:
        link = getattr(entry, "link", "").strip()
        raw_title = _strip_html(getattr(entry, "title", ""))
        if not link or not raw_title:
            continue

        published = _parse_published(entry)
        if published is not None and published < cutoff:
            continue  # 수집 윈도우 밖

        title, source = _extract_source(entry, raw_title)
        summary_text = _strip_html(getattr(entry, "summary", ""))

        articles.append({
            "title": title,
            "url": link,
            "source": source,
            "published_at": published.astimezone().isoformat(timespec="seconds") if published else "",
            # 구글 RSS는 본문 전문을 주지 않는다. 제목+발췌를 LLM 입력으로 사용.
            "content": summary_text or title,
            "keyword": keyword,
        })

        if len(articles) >= limit:
            break

    return articles


def fetch_all(
    keywords: Optional[list[str]] = None,
    window_hours: int = config.COLLECT_WINDOW_HOURS,
    limit_per_keyword: int = config.MAX_ARTICLES_PER_KEYWORD,
    delay: float = 0.5,
) -> list[dict[str, Any]]:
    """전체 키워드를 순회 수집하고 URL 기준으로 중복을 제거한다."""
    keywords = keywords or config.SEARCH_KEYWORDS
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    results: list[dict[str, Any]] = []
    dup_titles = 0

    for kw in keywords:
        found = fetch_news(kw, window_hours=window_hours, limit=limit_per_keyword)
        new_count = 0
        for art in found:
            if art["url"] in seen_urls:
                continue
            tnorm = normalize_title(art["title"])
            if tnorm and tnorm in seen_titles:
                dup_titles += 1  # 다른 매체가 같은 제목으로 낸 기사
                continue
            seen_urls.add(art["url"])
            if tnorm:
                seen_titles.add(tnorm)
            results.append(art)
            new_count += 1
        print(f"  · {kw:14} → {len(found):2}건 수집 / {new_count:2}건 신규")
        time.sleep(delay)  # 구글 쪽 부하를 줄이기 위한 간격

    if dup_titles:
        print(f"  (제목이 같은 중복 기사 {dup_titles}건 제외)")
    return results


if __name__ == "__main__":
    print(f"[수집 시작] 최근 {config.COLLECT_WINDOW_HOURS}시간, 키워드 {len(config.SEARCH_KEYWORDS)}개")
    items = fetch_all()
    print(f"\n[결과] 중복 제거 후 총 {len(items)}건\n")
    for i, a in enumerate(items[:10], 1):
        print(f"{i:2}. [{a['source']}] {a['title']}")
        print(f"    {a['published_at']}  ({a['keyword']})")
        print(f"    {a['url'][:100]}")
