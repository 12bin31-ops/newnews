"""같은 사안을 다룬 기사를 묶는다.

여러 매체가 같은 뉴스를 서로 다른 제목으로 내보내므로, URL이나 제목 정확일치로는
걸러지지 않는다. 본문 TF-IDF 코사인 유사도와 제목 문자 바이그램 유사도를
동시에 만족할 때만 같은 사안으로 본다.

두 조건을 모두 요구하는 이유:
- 본문만 보면 "HBM", "삼성전자" 같은 업계 공통 어휘 때문에 무관한 기사가 묶인다.
- 제목만 보면 한국어 조사 변화("주식"/"주식이냐")로 같은 사안을 놓친다.
임계값은 실제 수집 데이터로 조정했다(오병합 0, 정탐 5/5).
"""

import math
import re
from collections import Counter
from typing import Any, Optional

# 업계 기사 어디에나 나오는 단어는 변별력이 없어 제외한다
STOPWORDS = set(
    "기자 뉴스 단독 속보 포커스 카드 사설 분석 전망 종합 이상 대한 관련 있다 했다 "
    "위해 통해 이번 지난 올해 내년 것으로 대해 라고 이라고 밝혔다 전했다".split()
)

CONTENT_THRESHOLD = 0.16   # 본문 TF-IDF 코사인
TITLE_THRESHOLD = 0.25     # 제목 문자 바이그램 겹침
CONTENT_CHARS = 300        # 본문 앞부분만 사용 (뒤쪽은 기자 서명·관련기사 등 잡음)


def _clean(text: str) -> str:
    """대괄호·괄호 구간은 매체 표기나 말머리라 제거한다."""
    return re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text or "")


def _words(text: str) -> list[str]:
    tokens = re.findall(r"[가-힣]{2,}|[a-zA-Z]{3,}|\d+%", _clean(text).lower())
    return [w for w in tokens if w not in STOPWORDS]


def _title_bigrams(title: str) -> set[str]:
    """제목의 문자 바이그램. 한국어 조사 변화에 강하다."""
    s = re.sub(r"[^0-9a-z가-힣]", "", _clean(title).lower())
    return {s[i : i + 2] for i in range(len(s) - 1)}


def _doc_words(article: dict[str, Any]) -> list[str]:
    body = (article.get("content") or article.get("summary") or "")[:CONTENT_CHARS]
    return _words(f"{article.get('title', '')} {body}")


def _build_vectors(articles: list[dict[str, Any]]) -> dict[Any, dict[str, float]]:
    """TF-IDF 벡터를 만든다. 흔한 단어의 가중치를 낮춰 변별력을 높인다."""
    docs = {a["id"]: _doc_words(a) for a in articles}
    n = len(docs) or 1
    df: Counter = Counter()
    for words in docs.values():
        df.update(set(words))
    idf = {w: math.log(n / (1 + c)) + 1 for w, c in df.items()}

    vectors = {}
    for key, words in docs.items():
        tf = Counter(words)
        vec = {w: (1 + math.log(c)) * idf[w] for w, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in vec.values())) or 1.0
        vectors[key] = {w: x / norm for w, x in vec.items()}
    return vectors


def _cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(x * b.get(w, 0.0) for w, x in a.items())


def _overlap(a: set[str], b: set[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if (a and b) else 0.0


def group_articles(
    articles: list[dict[str, Any]],
    content_threshold: float = CONTENT_THRESHOLD,
    title_threshold: float = TITLE_THRESHOLD,
) -> list[list[dict[str, Any]]]:
    """기사를 같은 사안끼리 묶어 반환한다.

    각 묶음의 첫 원소가 대표 기사(본문이 가장 긴 것)다.
    """
    if len(articles) < 2:
        return [[a] for a in articles]

    vectors = _build_vectors(articles)
    bigrams = {a["id"]: _title_bigrams(a.get("title", "")) for a in articles}

    # 발행 순서대로 처리해 먼저 나온 기사를 기준으로 묶는다
    ordered = sorted(
        articles,
        key=lambda a: (a.get("published_at") or a.get("collected_at") or "", a["id"]),
    )

    clusters: list[list[dict[str, Any]]] = []
    for article in ordered:
        aid = article["id"]
        best, best_score = None, 0.0
        for cluster in clusters:
            # 평균 연결 — 한 건과만 비슷해서 딸려 들어가는 연쇄 병합을 막는다
            sim = sum(_cosine(vectors[aid], vectors[m["id"]]) for m in cluster) / len(cluster)
            title_sim = max(_overlap(bigrams[aid], bigrams[m["id"]]) for m in cluster)
            if sim >= content_threshold and title_sim >= title_threshold and sim > best_score:
                best, best_score = cluster, sim
        if best is not None:
            best.append(article)
        else:
            clusters.append([article])

    # 대표는 본문이 가장 긴 기사 — 정보가 가장 많다
    for cluster in clusters:
        cluster.sort(key=lambda a: len(a.get("content") or ""), reverse=True)
    return clusters


def assign_cluster_ids(articles: list[dict[str, Any]]) -> dict[int, int]:
    """기사 id → 대표 기사 id 매핑을 만든다. 단독 기사는 자기 자신이 대표."""
    mapping: dict[int, int] = {}
    for cluster in group_articles(articles):
        rep = cluster[0]["id"]
        for member in cluster:
            mapping[member["id"]] = rep
    return mapping
