"""수집 → 분석 → 저장 파이프라인.

사용법:
    python main.py                  # 전체 키워드 수집 + LLM 분석 + 저장
    python main.py --no-llm         # LLM 없이 수집/저장만 (배선 확인용)
    python main.py --limit 5        # 분석할 기사 수 제한 (비용 확인용)
    python main.py --keyword HBM    # 특정 키워드만
"""

import argparse
import sys
import time

import clustering
import collector
import config
import db

# 파일이나 CI 로그로 리다이렉트될 때도 진행 상황이 바로 보이도록 줄 단위로 흘린다.
try:
    sys.stdout.reconfigure(line_buffering=True)
except (AttributeError, ValueError):  # 리다이렉트 대상이 지원하지 않는 경우
    pass


def _recent_cutoff(days: int = 7) -> str:
    """사안 묶음 비교 대상 기간. 너무 넓히면 오래된 기사와 잘못 묶인다."""
    from datetime import date, timedelta
    return (date.today() - timedelta(days=days)).isoformat()


def run(
    keywords: list[str] | None = None,
    use_llm: bool = True,
    limit: int | None = None,
    window_hours: int = config.COLLECT_WINDOW_HOURS,
    delay: float = 0.5,
    crawl: bool = True,
    cluster: bool = True,
) -> dict[str, int]:
    """파이프라인 1회 실행. 처리 결과 카운트를 반환한다."""
    stats = {"수집": 0, "중복스킵": 0, "원문확보": 0, "관련기사": 0,
             "분석": 0, "분석실패": 0, "저장": 0, "중단": 0}

    db.init_db()
    print(f"[1/4] 뉴스 수집 (최근 {window_hours}시간)")
    fetched = collector.fetch_all(
        keywords=keywords, window_hours=window_hours, delay=delay
    )
    stats["수집"] = len(fetched)

    # LLM 호출 전에 이미 있는 기사를 걸러낸다 (API 비용 절감).
    # URL이 달라도 제목이 같으면 같은 사안이므로 함께 제외한다.
    existing_titles = {
        collector.normalize_title(a["title"]) for a in db.get_articles()
    }
    existing_titles.discard("")

    fresh = []
    for art in fetched:
        if db.url_exists(art["url"]):
            stats["중복스킵"] += 1
            continue
        if collector.normalize_title(art["title"]) in existing_titles:
            stats["중복스킵"] += 1
            continue
        fresh.append(art)

    if limit is not None:
        fresh = fresh[:limit]

    print(f"\n[2/4] 원문 크롤링 — 대상 {len(fresh)}건 (기존 DB 중복 {stats['중복스킵']}건 제외)")
    if fresh and crawl:
        fresh = collector.enrich_all(fresh)
        stats["원문확보"] = sum(1 for a in fresh if a.get("crawled"))
    elif fresh:
        print("  (--no-crawl) 원문 크롤링을 건너뜁니다")

    # 같은 사안을 여러 매체가 보도한 경우, 대표 1건만 분석하고 나머지는 관련 기사로 묶는다.
    # 이미 DB에 있는 최근 기사와도 비교해야 어제 나온 사안의 후속 보도를 잡을 수 있다.
    recent = db.get_articles(date_from=_recent_cutoff())
    to_analyze = fresh
    followers: list[dict] = []
    if cluster and fresh:
        for i, art in enumerate(fresh):
            art.setdefault("id", f"new-{i}")     # 아직 DB에 없으므로 임시 id
        groups = clustering.group_articles(recent + fresh)
        new_ids = {a["id"] for a in fresh}
        to_analyze, followers = [], []
        for group in groups:
            members = [m for m in group if m["id"] in new_ids]
            if not members:
                continue
            has_analyzed_rep = any(m["id"] not in new_ids and m.get("summary") for m in group)
            # 기존에 분석된 대표가 있으면 신규는 전부 관련 기사로
            if has_analyzed_rep:
                followers.extend(members)
            else:
                to_analyze.append(members[0])
                followers.extend(members[1:])
        stats["관련기사"] = len(followers)
        if followers:
            print(f"  같은 사안 {len(followers)}건은 관련 기사로 묶어 분석을 생략합니다")

    print(f"\n[3/4] 분석 대상 {len(to_analyze)}건")
    fresh_all = fresh
    fresh = to_analyze

    if use_llm and fresh:
        import processor  # 키가 없으면 여기서 실패하므로 필요할 때만 import

        print(f"  공급자: {processor.provider_label()}"
              f" · 호출 간격 {config.LLM_REQUEST_DELAY}초")

        for i, art in enumerate(fresh, 1):
            print(f"  ({i}/{len(fresh)}) {art['title'][:45]}")
            try:
                analysis = processor.analyze_article(art["title"], art.get("content") or "")
            except processor.AccountError as exc:
                # 크레딧 부족·인증 실패는 남은 기사에도 똑같이 실패한다. 즉시 중단.
                print(f"\n  [중단] {exc}")
                print(f"  분석하지 못한 {len(fresh) - i + 1}건은 저장하지 않고 남겨둡니다.")
                fresh = fresh[: i - 1]
                stats["중단"] = 1
                break
            art.update(analysis)
            if analysis.get("analysis_ok"):
                stats["분석"] += 1
                print(f"        → [{analysis['tag']}] {analysis['category']} ({analysis['score']}점)")
            else:
                stats["분석실패"] += 1
            time.sleep(config.LLM_REQUEST_DELAY)  # rate limit 여유
    elif fresh:
        print("  (--no-llm) 분석을 건너뜁니다")

    print(f"\n[4/4] DB 저장")
    for art in (fresh_all if cluster else fresh):
        art.pop("id", None)          # 임시 id는 저장하지 않는다
        if db.insert_article(art) is not None:
            stats["저장"] += 1

    if cluster and stats["저장"]:
        mapping = clustering.assign_cluster_ids(db.get_articles(date_from=_recent_cutoff()))
        db.set_cluster_ids(mapping)
        print(f"  사안 묶음 갱신 {len(mapping)}건")

    return stats


def reanalyze(
    only_missing: bool = False,
    limit: int | None = None,
    recrawl: bool = False,
) -> dict[str, int]:
    """DB에 이미 있는 기사를 다시 분석해 결과를 덮어쓴다.

    only_missing=True면 아직 분석되지 않은 기사만 처리한다.
    recrawl=True면 본문이 없는 기사의 원문을 먼저 가져온다.
    """
    import processor

    db.init_db()
    targets = db.get_articles()
    if only_missing:
        targets = [a for a in targets if not a.get("summary")]
    if limit is not None:
        targets = targets[:limit]

    stats = {"대상": len(targets), "원문확보": 0, "성공": 0, "실패": 0, "중단": 0}

    if recrawl:
        need = [a for a in targets if not a.get("content")]
        print(f"원문이 없는 기사 {len(need)}건 크롤링")
        if need:
            enriched = collector.enrich_all(need)
            by_id = {}
            for art in enriched:
                if art.get("crawled"):
                    db.update_article_content(art["id"], art["url"], art["content"])
                    stats["원문확보"] += 1
                by_id[art["id"]] = art
            # 메모리상의 targets에도 반영
            for a in targets:
                if a["id"] in by_id:
                    a["url"] = by_id[a["id"]]["url"]
                    a["content"] = by_id[a["id"]].get("content")
        print()
    print(f"재분석 대상 {len(targets)}건")
    print(f"  공급자: {processor.provider_label()}"
          f" · 호출 간격 {config.LLM_REQUEST_DELAY}초")
    if targets:
        eta = len(targets) * config.LLM_REQUEST_DELAY / 60
        print(f"  예상 소요: 약 {eta:.1f}분\n")

    for i, art in enumerate(targets, 1):
        print(f"  ({i}/{len(targets)}) {art['title'][:45]}")
        try:
            body = art.get("content") or art.get("summary") or art["title"]
            analysis = processor.analyze_article(art["title"], body)
        except processor.AccountError as exc:
            print(f"\n  [중단] {exc}")
            print(f"  남은 {len(targets) - i + 1}건은 건드리지 않았습니다.")
            stats["중단"] = 1
            break

        if analysis.get("analysis_ok"):
            db.update_article_analysis(art["id"], analysis)
            stats["성공"] += 1
            print(f"        → [{analysis['tag']}] {analysis['category']} ({analysis['score']}점)")
        else:
            stats["실패"] += 1
        time.sleep(config.LLM_REQUEST_DELAY)

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="뉴스 수집 → 분석 → 저장 파이프라인")
    parser.add_argument("--no-llm", action="store_true", help="LLM 분석 건너뛰기")
    parser.add_argument("--limit", type=int, default=None, help="분석할 최대 기사 수")
    parser.add_argument("--keyword", action="append", help="특정 키워드만 (여러 번 지정 가능)")
    parser.add_argument("--hours", type=int, default=config.COLLECT_WINDOW_HOURS, help="수집 윈도우(시간)")
    parser.add_argument("--no-cluster", action="store_true",
                        help="같은 사안 묶기를 건너뛰고 모든 기사를 개별 분석")
    parser.add_argument("--no-crawl", action="store_true",
                        help="원문 크롤링을 건너뛰고 제목·발췌만으로 분석")
    parser.add_argument("--reanalyze", action="store_true",
                        help="수집하지 않고, DB의 기존 기사를 다시 분석해 덮어쓰기")
    parser.add_argument("--only-missing", action="store_true",
                        help="--reanalyze와 함께: 아직 분석 안 된 기사만 처리")
    parser.add_argument("--recrawl", action="store_true",
                        help="--reanalyze와 함께: 본문이 없는 기사의 원문을 먼저 가져오기")
    args = parser.parse_args()

    if args.reanalyze:
        try:
            stats = reanalyze(only_missing=args.only_missing, limit=args.limit,
                              recrawl=args.recrawl)
        except RuntimeError as exc:
            print(f"\n[중단] {exc}", file=sys.stderr)
            return 1
        print("\n" + "=" * 46)
        print("  재분석 완료")
        print("=" * 46)
        for k, v in stats.items():
            print(f"  {k:8}: {v:3}건")
        print(f"\n  통계: {db.get_stats()}")
        return 1 if stats.get("중단") else 0

    try:
        stats = run(
            keywords=args.keyword,
            use_llm=not args.no_llm,
            limit=args.limit,
            window_hours=args.hours,
            crawl=not args.no_crawl,
            cluster=not args.no_cluster,
        )
    except RuntimeError as exc:
        print(f"\n[중단] {exc}", file=sys.stderr)
        return 1

    print("\n" + "=" * 46)
    print("  파이프라인 완료")
    print("=" * 46)
    for k, v in stats.items():
        print(f"  {k:8}: {v:3}건")
    print(f"  {'DB 총계':8}: {db.count_articles():3}건")
    print(f"\n  통계: {db.get_stats()}")
    print("\n  대시보드 실행: streamlit run app.py")
    if stats.get("중단"):
        print("\n  [주의] 계정 오류로 중간에 멈췄습니다. 위 메시지를 확인하세요.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
