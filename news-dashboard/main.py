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

import collector
import config
import db

# 파일이나 CI 로그로 리다이렉트될 때도 진행 상황이 바로 보이도록 줄 단위로 흘린다.
try:
    sys.stdout.reconfigure(line_buffering=True)
except (AttributeError, ValueError):  # 리다이렉트 대상이 지원하지 않는 경우
    pass


def run(
    keywords: list[str] | None = None,
    use_llm: bool = True,
    limit: int | None = None,
    window_hours: int = config.COLLECT_WINDOW_HOURS,
    delay: float = 0.5,
) -> dict[str, int]:
    """파이프라인 1회 실행. 처리 결과 카운트를 반환한다."""
    stats = {"수집": 0, "중복스킵": 0, "분석": 0, "분석실패": 0, "저장": 0, "중단": 0}

    db.init_db()
    print(f"[1/3] 뉴스 수집 (최근 {window_hours}시간)")
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

    print(f"\n[2/3] 분석 대상 {len(fresh)}건 (기존 DB 중복 {stats['중복스킵']}건 제외)")

    if use_llm and fresh:
        import processor  # 키가 없으면 여기서 실패하므로 필요할 때만 import

        print(f"  공급자: {processor.provider_label()}"
              f" · 호출 간격 {config.LLM_REQUEST_DELAY}초")

        for i, art in enumerate(fresh, 1):
            print(f"  ({i}/{len(fresh)}) {art['title'][:45]}")
            try:
                analysis = processor.analyze_article(art["title"], art.get("content", ""))
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

    print(f"\n[3/3] DB 저장")
    for art in fresh:
        if db.insert_article(art) is not None:
            stats["저장"] += 1

    return stats


def reanalyze(
    only_missing: bool = False,
    limit: int | None = None,
) -> dict[str, int]:
    """DB에 이미 있는 기사를 다시 분석해 결과를 덮어쓴다.

    only_missing=True면 아직 분석되지 않은 기사만 처리한다.
    """
    import processor

    db.init_db()
    targets = db.get_articles()
    if only_missing:
        targets = [a for a in targets if not a.get("summary")]
    if limit is not None:
        targets = targets[:limit]

    stats = {"대상": len(targets), "성공": 0, "실패": 0, "중단": 0}
    print(f"재분석 대상 {len(targets)}건")
    print(f"  공급자: {processor.provider_label()}"
          f" · 호출 간격 {config.LLM_REQUEST_DELAY}초")
    if targets:
        eta = len(targets) * config.LLM_REQUEST_DELAY / 60
        print(f"  예상 소요: 약 {eta:.1f}분\n")

    for i, art in enumerate(targets, 1):
        print(f"  ({i}/{len(targets)}) {art['title'][:45]}")
        try:
            analysis = processor.analyze_article(art["title"], art.get("summary") or art["title"])
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
    parser.add_argument("--reanalyze", action="store_true",
                        help="수집하지 않고, DB의 기존 기사를 다시 분석해 덮어쓰기")
    parser.add_argument("--only-missing", action="store_true",
                        help="--reanalyze와 함께: 아직 분석 안 된 기사만 처리")
    args = parser.parse_args()

    if args.reanalyze:
        try:
            stats = reanalyze(only_missing=args.only_missing, limit=args.limit)
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
