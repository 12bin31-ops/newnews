"""구글 뉴스 RSS 기반 뉴스 수집기."""

import concurrent.futures
import html
import json
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

# 구글 뉴스 RSS의 링크는 원문 주소가 아니라 리다이렉트 링크다. 게다가 HTTP
# 리다이렉트가 아니라 JS로 이동시키므로, 구글의 URL 해석 엔드포인트를 직접 호출한다.
GOOGLE_RESOLVE_URL = (
    "https://news.google.com/_/DotsSplashUi/data/batchexecute?rpcids=Fbv4je"
)
MIN_CONTENT_CHARS = 200  # 이보다 짧으면 본문 추출 실패로 본다

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


# ------------------------------------------------------------------ 원문 크롤링


def resolve_google_url(google_url: str) -> Optional[str]:
    """구글 뉴스 리다이렉트 링크에서 실제 기사 주소를 얻는다.

    실패하면 None. 구글이 방식을 바꾸면 여기가 가장 먼저 깨지는 지점이다.
    """
    if "/articles/" not in google_url:
        return google_url if google_url.startswith("http") else None

    try:
        article_id = google_url.split("/articles/")[1].split("?")[0]
        page = requests.get(google_url, headers=REQUEST_HEADERS, timeout=REQUEST_TIMEOUT).text
        sig = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not (sig and ts):
            return None

        inner = json.dumps(
            [
                "garturlreq",
                [
                    ["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
                     None, None, None, None, None, 0, 1],
                    "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0,
                ],
                article_id, int(ts.group(1)), sig.group(1),
            ],
            separators=(",", ":"),
        )
        body = "f.req=" + urllib.parse.quote(
            json.dumps([[["Fbv4je", inner, None, "generic"]]], separators=(",", ":"))
        )
        resp = requests.post(
            GOOGLE_RESOLVE_URL,
            headers={**REQUEST_HEADERS,
                     "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            data=body, timeout=20,
        )
        resp.raise_for_status()

        # 응답 첫 줄은 )]}'  방어 프리픽스라 잘라낸다
        payload = json.loads(resp.text.split("\n", 1)[-1])
        for row in payload:
            if len(row) > 2 and row[0] == "wrb.fr" and row[2]:
                parsed = json.loads(row[2])          # ["garturlres", "<url>", 1]
                if isinstance(parsed, list) and len(parsed) > 1 and parsed[1]:
                    return parsed[1]
    except (requests.RequestException, json.JSONDecodeError, ValueError, IndexError, KeyError):
        return None
    return None


def fetch_article_text(url: str) -> Optional[str]:
    """기사 원문 본문을 추출한다. 실패하면 None."""
    try:
        import trafilatura
    except ImportError:
        return None

    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return None
        text = trafilatura.extract(
            downloaded, include_comments=False, include_tables=False,
            no_fallback=False, favor_precision=True,
        )
    except Exception:
        # 페이월·봇 차단·인코딩 오류 등 언론사마다 실패 양상이 제각각이다
        return None

    if not text:
        return None
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text if len(text) >= MIN_CONTENT_CHARS else None


def enrich_article(article: dict[str, Any]) -> dict[str, Any]:
    """기사 1건의 원문을 가져와 url/content를 채운다.

    실패해도 예외를 던지지 않는다. 원문을 못 가져오면 제목+발췌를 그대로 쓴다.
    """
    real_url = resolve_google_url(article["url"])
    if real_url:
        article["url"] = real_url
        text = fetch_article_text(real_url)
        if text:
            article["content"] = text
            article["crawled"] = True
            return article

    article["crawled"] = False
    return article


def enrich_all(
    articles: list[dict[str, Any]],
    max_workers: int = 4,
) -> list[dict[str, Any]]:
    """여러 기사의 원문을 병렬로 가져온다. I/O 대기가 대부분이라 병렬이 효과적이다."""
    if not articles:
        return articles

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(enrich_article, articles))

    ok = sum(1 for a in results if a.get("crawled"))
    print(f"  원문 확보 {ok}/{len(results)}건"
          f" (실패 {len(results) - ok}건은 제목·발췌로 분석)")
    return results


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
