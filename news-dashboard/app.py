"""마케팅 뉴스 대시보드 — 수집 일자별 달력 뷰."""

import calendar
from datetime import date, datetime, timedelta

import streamlit as st

import config
import db

st.set_page_config(page_title="뉴스 대시보드", layout="wide")

# ---------------------------------------------------------------- 스타일

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

CATEGORY_TINTS = {
    "시장상황": ("#EEF2FF", "#3B4FCB"),
    "경쟁사동향": ("#FFF1E8", "#B54708"),
    "자사언급": ("#E9F8F1", "#046C4E"),
    "기술트렌드": ("#F3EEFF", "#5B34C4"),
    "규제정책": ("#FDF0F5", "#A11552"),
    "고객사동향": ("#E8F6F9", "#0B6B7D"),
    "미분류": ("#F2F3F5", "#5B6270"),
}
TAG_TINTS = {
    "기회": ("#E9F8F1", "#046C4E"),
    "위협": ("#FDECEC", "#B42318"),
    "중립": ("#F2F3F5", "#5B6270"),
}

st.markdown("""
<style>
/* 폰트는 .streamlit/config.toml 의 theme.font / theme.codeFont 로 로드한다.
   여기서 font-family를 전역에 !important로 덮으면 Streamlit 아이콘 폰트
   (Material Symbols)까지 잡혀 ligature가 글자로 노출되므로 하지 않는다. */
:root {
  --sans:"Inter","Noto Sans KR","Malgun Gothic","맑은 고딕",
         -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  --mono:"JetBrains Mono","D2Coding",Consolas,"DejaVu Sans Mono",
         "Courier New",monospace;

  --ink:#16191D;
  --ink-2:#4A5160;
  --ink-3:#858C99;
  --line:#E4E7EC;
  --line-2:#F0F2F5;
  --surface:#FFFFFF;
  --surface-2:#F8F9FB;
  --accent:#1F6FEB;
}

html, body { -webkit-font-smoothing: antialiased; }


/* 기본 여백 정리 */
.block-container { padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1180px; }
[data-testid="stHeader"] { background: transparent; }
hr { margin: 1.4rem 0; border-color: var(--line-2); }

/* ---------- 헤더 ---------- */
.page-head { margin-bottom: 1.6rem; }
.page-head h1 {
  font-size: 1.65rem; font-weight: 700; letter-spacing: -0.02em;
  color: var(--ink); margin: 0 0 .25rem 0;
}
.page-head p { font-size: .875rem; color: var(--ink-3); margin: 0; }

/* ---------- 통계 스트립 ---------- */
.statrow { display:flex; gap:0; border:1px solid var(--line);
           border-radius:10px; overflow:hidden; background:var(--surface);
           margin-bottom:1.8rem; }
.stat { flex:1; padding:.85rem 1.1rem; border-right:1px solid var(--line-2); }
.stat:last-child { border-right:none; }
.stat .k { font-size:.72rem; font-weight:500; color:var(--ink-3);
           letter-spacing:.02em; margin-bottom:.3rem; }
.stat .v { font-family:var(--mono); font-size:1.45rem; font-weight:500;
           color:var(--ink); line-height:1.1; }
.stat .v small { font-family:var(--sans); font-size:.8rem; font-weight:400;
                 color:var(--ink-3); margin-left:.15rem; }

/* ---------- 섹션 라벨 ---------- */
.seclabel { font-size:.75rem; font-weight:600; letter-spacing:.06em;
            text-transform:uppercase; color:var(--ink-3);
            margin:0 0 .7rem 0; }

/* ---------- 달력 ---------- */
.calmonth { font-family:var(--mono); font-size:1.05rem; font-weight:500;
            color:var(--ink); text-align:center; padding-top:.35rem; }
.calhead { display:grid; grid-template-columns:repeat(7,1fr); gap:6px;
           margin:.55rem 0 .3rem 0; }
.calhead div { text-align:center; font-size:.72rem; font-weight:600;
               color:var(--ink-3); padding-bottom:.2rem; }
.calhead div.sat { color:#3B6FD4; }
.calhead div.sun { color:#C03636; }

/* 달력 셀 버튼 */
div[class*="st-key-calday-"] button {
  width:100%; height:58px; padding:.35rem .5rem 0 .5rem;
  display:flex; flex-direction:column; align-items:flex-start;
  justify-content:flex-start;
  border:1px solid var(--line); border-radius:8px;
  background:var(--surface); color:var(--ink-2);
  font-family:var(--mono) !important; font-size:.82rem; font-weight:400;
  transition:border-color .12s, background .12s;
}
div[class*="st-key-calday-"] button:hover:not(:disabled) {
  border-color:var(--accent); background:#F5F9FF; color:var(--ink);
}
div[class*="st-key-calday-"] button code {
  font-size:.72rem; font-weight:500; background:transparent;
  color:var(--accent); padding:0; margin-top:.15rem;
}
div[class*="st-key-calday-"] button:disabled {
  background:var(--surface-2); border-color:var(--line-2);
  color:#C3C8D1; cursor:default;
}
/* 선택된 날짜 */
div[class*="st-key-calday-"] button[kind="primary"],
div[class*="st-key-calday-"] button[data-testid="stBaseButton-primary"] {
  background:var(--accent); border-color:var(--accent); color:#fff;
}
div[class*="st-key-calday-"] button[kind="primary"] code,
div[class*="st-key-calday-"] button[data-testid="stBaseButton-primary"] code {
  color:rgba(255,255,255,.85);
}
/* 빈 칸 */
.calblank { height:58px; border:1px dashed var(--line-2); border-radius:8px; }

/* 최근 수집일 목록 */
div[class*="st-key-daylist-"] button {
  width:100%; height:36px; justify-content:flex-start;
  border:1px solid var(--line-2); border-radius:7px;
  background:var(--surface); color:var(--ink-2);
  font-family:var(--mono) !important; font-size:.78rem; font-weight:400;
  padding:0 .7rem;
}
div[class*="st-key-daylist-"] button:hover {
  border-color:var(--accent); background:#F5F9FF; color:var(--ink);
}
div[class*="st-key-daylist-"] button code {
  background:transparent; color:var(--accent); font-size:.74rem;
  padding:0; margin-left:auto;
}
div[class*="st-key-daylist-"] button[kind="primary"],
div[class*="st-key-daylist-"] button[data-testid="stBaseButton-primary"] {
  background:var(--accent); border-color:var(--accent); color:#fff;
}
div[class*="st-key-daylist-"] button[kind="primary"] code,
div[class*="st-key-daylist-"] button[data-testid="stBaseButton-primary"] code {
  color:rgba(255,255,255,.85);
}

/* 달력 이동 버튼 */
div[class*="st-key-nav-"] button {
  font-family:var(--mono) !important; font-size:.8rem;
  border:1px solid var(--line); border-radius:7px; background:var(--surface);
  color:var(--ink-2); height:34px;
}
div[class*="st-key-nav-"] button:hover { border-color:var(--accent); color:var(--accent); }

/* ---------- 선택일 헤더 ---------- */
.dayhead { display:flex; align-items:baseline; gap:.7rem;
           padding-bottom:.7rem; border-bottom:2px solid var(--ink);
           margin-bottom:1.3rem; }
.dayhead .d { font-family:var(--mono); font-size:1.3rem; font-weight:500;
              color:var(--ink); letter-spacing:-0.01em; }
.dayhead .n { font-size:.82rem; color:var(--ink-3); }

/* ---------- 기사 카드 ---------- */
.card-title { font-size:1.02rem; font-weight:600; line-height:1.45;
              letter-spacing:-0.01em; margin:0 0 .4rem 0; }
.card-title a { color:var(--ink); text-decoration:none;
                border-bottom:1px solid transparent; }
.card-title a:hover { color:var(--accent); border-bottom-color:var(--accent); }
.card-meta { font-family:var(--mono); font-size:.73rem; color:var(--ink-3);
             margin-bottom:.6rem; }
.card-summary { font-size:.885rem; line-height:1.72; color:var(--ink-2);
                white-space:pre-line; margin:.7rem 0 .55rem 0; }
.card-reason { font-size:.775rem; color:var(--ink-3); line-height:1.55;
               padding-left:.65rem; border-left:2px solid var(--line);
               margin-bottom:.65rem; }

.pill { display:inline-block; padding:.16rem .55rem; border-radius:5px;
        font-size:.725rem; font-weight:600; margin:0 .3rem .3rem 0;
        letter-spacing:.01em; }
.score { display:inline-block; font-family:var(--mono); font-size:.73rem;
         color:var(--ink-3); margin-left:.15rem; letter-spacing:.08em; }
.score b { color:var(--accent); font-weight:500; }
.kw { display:inline-block; font-family:var(--mono); font-size:.715rem;
      color:var(--ink-3); background:var(--surface-2);
      border:1px solid var(--line-2); border-radius:4px;
      padding:.1rem .4rem; margin:0 .28rem .28rem 0; }

/* ---------- 브리핑 ---------- */
.brief { border:1px solid var(--line); border-left:3px solid var(--accent);
         border-radius:8px; background:var(--surface-2);
         padding:1.1rem 1.25rem; margin-bottom:1.5rem; }
.brief .bh { font-size:1rem; font-weight:600; line-height:1.55;
             color:var(--ink); margin-bottom:.9rem; }
.brief .bp { padding:.55rem 0; border-top:1px solid var(--line-2); }
.brief .bp .t { font-size:.845rem; font-weight:600; color:var(--ink); }
.brief .bp .x { font-size:.82rem; color:var(--ink-2); line-height:1.62;
                margin-top:.15rem; }
.brief .wt { margin-top:.9rem; padding-top:.75rem;
             border-top:1px solid var(--line-2); }
.brief .wt .l { font-size:.71rem; font-weight:600; letter-spacing:.05em;
                text-transform:uppercase; color:var(--ink-3);
                margin-bottom:.35rem; }
.brief .wt li { font-size:.82rem; color:var(--ink-2); line-height:1.68; }
.brief .wt ul { margin:0; padding-left:1.1rem; }

/* ---------- 코멘트 ---------- */
.cmt { padding:.6rem 0; border-bottom:1px solid var(--line-2); }
.cmt:last-child { border-bottom:none; }
.cmt .who { font-size:.79rem; font-weight:600; color:var(--ink); }
.cmt .when { font-family:var(--mono); font-size:.7rem; color:var(--ink-3);
             margin-left:.45rem; }
.cmt .what { font-size:.845rem; color:var(--ink-2); line-height:1.6;
             margin-top:.15rem; }

/* Streamlit 기본 요소 다듬기 */
[data-testid="stExpander"] details { border:1px solid var(--line);
                                     border-radius:8px; }
[data-testid="stExpander"] summary { font-size:.82rem; font-weight:500; }
[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"] {
  gap:.35rem;
}
section[data-testid="stSidebar"] { border-right:1px solid var(--line); }
section[data-testid="stSidebar"] .block-container { padding-top:1.6rem; }

/* ---------- 아이콘 폰트 보호 (반드시 스타일시트 마지막) ----------
   Streamlit 아이콘은 Material Symbols ligature로 그려진다. 앞선 규칙이
   font-family를 덮으면 ligature가 형성되지 못해 아이콘 이름(arrow_right 등)이
   글자로 노출된다. 마지막에 두어 어떤 규칙보다 우선하게 한다. */
[data-testid="stIconMaterial"],
span[data-testid="stIconMaterial"],
[data-testid="stIconMaterial"] * {
  font-family: "Material Symbols Rounded" !important;
  font-weight: normal !important;
}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------- 헬퍼

def pill(text: str, tints: dict) -> str:
    bg, fg = tints.get(text, ("#F2F3F5", "#5B6270"))
    return f'<span class="pill" style="background:{bg};color:{fg}">{text}</span>'


def fmt_dt(value: str) -> str:
    if not value:
        return ""
    return value[:16].replace("T", " ")


def render_article(article: dict, scope: str) -> None:
    """기사 카드 하나. scope는 위젯 key 충돌을 막기 위한 접두사."""
    aid = article["id"]
    wkey = f"{scope}-{aid}"

    with st.container(border=True):
        st.markdown(
            f'<div class="card-title"><a href="{article["url"]}" target="_blank">'
            f'{article["title"]}</a></div>',
            unsafe_allow_html=True,
        )

        src = article.get("source") or "출처 미상"
        when = fmt_dt(article.get("published_at") or article.get("collected_at"))
        st.markdown(f'<div class="card-meta">{src} · {when}</div>', unsafe_allow_html=True)

        pills = "".join(
            pill(c.strip(), CATEGORY_TINTS)
            for c in (article.get("category") or "미분류").split(",")
            if c.strip()
        )
        tag = article.get("tag") or "중립"
        pills += pill(tag, TAG_TINTS)
        score = article.get("score") or 0
        pills += f'<span class="score"><b>{"●" * score}</b>{"○" * (5 - score)} {score}/5</span>'
        st.markdown(pills, unsafe_allow_html=True)

        if article.get("summary"):
            st.markdown(
                f'<div class="card-summary">{article["summary"]}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="card-reason">분석 전입니다. 터미널에서 python main.py 를 실행하세요.</div>',
                unsafe_allow_html=True,
            )

        if article.get("category_reason"):
            st.markdown(
                f'<div class="card-reason">{article["category_reason"]}</div>',
                unsafe_allow_html=True,
            )

        if article.get("keywords"):
            kws = "".join(
                f'<span class="kw">{k.strip()}</span>'
                for k in article["keywords"].split(",") if k.strip()
            )
            st.markdown(kws, unsafe_allow_html=True)

        # --- 캠페인 아이디어 ---
        idea_key = f"ideas_{aid}"
        if st.button("캠페인 아이디어 생성", key=f"idea-{wkey}"):
            try:
                import processor
                with st.spinner("생성 중"):
                    st.session_state[idea_key] = processor.generate_campaign_ideas(
                        article["title"], article.get("summary", ""), article.get("keywords", "")
                    )
            except RuntimeError as exc:
                st.session_state[idea_key] = {"error": str(exc)}

        if idea_key in st.session_state:
            data = st.session_state[idea_key]
            with st.expander("SNS 포스팅 아이디어", expanded=True):
                if isinstance(data, dict) and "error" in data:
                    st.error(data["error"])
                elif not data:
                    st.warning("아이디어를 생성하지 못했습니다. 잠시 후 다시 시도하세요.")
                else:
                    for i, idea in enumerate(data, 1):
                        st.markdown(
                            f'<div class="bp"><div class="t">{i}. '
                            f'{idea.get("channel", "")} — {idea.get("hook", "")}</div>'
                            f'<div class="x">{idea.get("message", "")}</div>'
                            f'<div class="card-meta">형식: {idea.get("format", "")}</div></div>',
                            unsafe_allow_html=True,
                        )

        # --- 코멘트 ---
        comments = db.get_comments(aid)
        with st.expander(f"코멘트 {len(comments)}", expanded=False):
            for c in comments:
                st.markdown(
                    f'<div class="cmt"><span class="who">{c["author"]}</span>'
                    f'<span class="when">{fmt_dt(c["created_at"])}</span>'
                    f'<div class="what">{c["comment"]}</div></div>',
                    unsafe_allow_html=True,
                )
            with st.form(key=f"cf-{wkey}", clear_on_submit=True):
                ca, cb = st.columns([1, 3])
                author = ca.text_input("이름", key=f"ca-{wkey}", placeholder="홍길동")
                body = cb.text_input("코멘트", key=f"cb-{wkey}", placeholder="의견을 남겨주세요")
                if st.form_submit_button("등록"):
                    if db.add_comment(aid, author, body) is None:
                        st.warning("코멘트 내용을 입력해주세요.")
                    else:
                        st.rerun()


def render_calendar(year: int, month: int, counts: dict, selected: str) -> None:
    """월 달력을 버튼 그리드로 그린다. 건수가 있는 날만 클릭 가능."""
    nav_l, mid, nav_r = st.columns([1, 3, 1])
    with nav_l:
        if st.button("이전", key="nav-prev", use_container_width=True):
            st.session_state.cal_month = (
                date(year, month, 1) - timedelta(days=1)
            ).replace(day=1).isoformat()
            st.rerun()
    with mid:
        st.markdown(f'<div class="calmonth">{year}. {month:02d}</div>', unsafe_allow_html=True)
    with nav_r:
        if st.button("다음", key="nav-next", use_container_width=True):
            last = calendar.monthrange(year, month)[1]
            st.session_state.cal_month = (
                date(year, month, last) + timedelta(days=1)
            ).replace(day=1).isoformat()
            st.rerun()

    head = "".join(
        f'<div class="{"sat" if i == 5 else "sun" if i == 6 else ""}">{w}</div>'
        for i, w in enumerate(WEEKDAYS)
    )
    st.markdown(f'<div class="calhead">{head}</div>', unsafe_allow_html=True)

    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        cols = st.columns(7, gap="small")
        for col, day in zip(cols, week):
            with col:
                if day.month != month:
                    st.markdown('<div class="calblank"></div>', unsafe_allow_html=True)
                    continue
                iso = day.isoformat()
                n = counts.get(iso, {}).get("총계", 0)
                # 라벨의 인라인 코드가 건수 — mono 폰트로 구분된다
                label = f"{day.day} `{n}`" if n else f"{day.day}"
                st.button(
                    label,
                    key=f"calday-{iso}",
                    disabled=(n == 0),
                    type="primary" if iso == selected else "secondary",
                    use_container_width=True,
                    on_click=lambda d=iso: st.session_state.update(sel_date=d),
                )


# ---------------------------------------------------------------- 본문

db.init_db()

st.markdown(
    '<div class="page-head"><h1>뉴스 대시보드</h1>'
    f'<p>{config.OUR_COMPANY} 마케팅팀 · 반도체 업계 뉴스 자동 수집 및 분류</p></div>',
    unsafe_allow_html=True,
)

# --- 사이드바 ---
with st.sidebar:
    st.markdown('<div class="seclabel">날짜 기준</div>', unsafe_allow_html=True)
    basis_label = st.radio(
        "날짜 기준",
        ["수집일", "발행일"],
        index=0,
        horizontal=True,
        label_visibility="collapsed",
        help="수집일은 스크랩한 날, 발행일은 기사가 나온 날입니다.",
    )
    date_basis = "collected_at" if basis_label == "수집일" else "published_at"

    st.markdown('<div class="seclabel">필터</div>', unsafe_allow_html=True)
    sel_categories = st.multiselect("카테고리", config.CATEGORIES, default=[])
    sel_tags = st.multiselect("태그", config.TAGS, default=[])
    min_score = st.slider("최소 중요도", 1, 5, 1)

    st.divider()
    try:
        import processor
        st.caption(f"분석 엔진 {processor.provider_label()}")
    except Exception:
        pass
    st.caption("데이터 갱신")
    st.code("python main.py", language="bash")

flt = dict(
    category=sel_categories or None,
    tag=sel_tags or None,
    min_score=min_score if min_score > 1 else None,
)

counts = db.get_daily_counts(date_basis=date_basis, **flt)
total_stats = db.get_stats()

# --- 통계 스트립 ---
today_iso = date.today().isoformat()
today_n = counts.get(today_iso, {}).get("총계", 0)
st.markdown(
    f'''<div class="statrow">
      <div class="stat"><div class="k">전체 기사</div>
        <div class="v">{total_stats["총계"]}<small>건</small></div></div>
      <div class="stat"><div class="k">오늘</div>
        <div class="v">{today_n}<small>건</small></div></div>
      <div class="stat"><div class="k">기회</div>
        <div class="v">{total_stats["기회"]}<small>건</small></div></div>
      <div class="stat"><div class="k">위협</div>
        <div class="v">{total_stats["위협"]}<small>건</small></div></div>
      <div class="stat"><div class="k">수집 일수</div>
        <div class="v">{len(counts)}<small>일</small></div></div>
    </div>''',
    unsafe_allow_html=True,
)

if not total_stats["총계"]:
    st.info("아직 수집된 기사가 없습니다. 터미널에서 python main.py 를 실행하세요.")
    st.stop()

if not counts:
    st.warning("필터 조건에 맞는 기사가 없습니다. 사이드바 필터를 조정해보세요.")
    st.stop()

# --- 선택 상태 초기화 ---
available = sorted(counts.keys(), reverse=True)
if st.session_state.get("sel_date") not in counts:
    st.session_state.sel_date = available[0]
selected = st.session_state.sel_date

if "cal_month" not in st.session_state:
    st.session_state.cal_month = selected[:8] + "01"
cal_anchor = date.fromisoformat(st.session_state.cal_month)

# --- 달력 ---
left, right = st.columns([1.05, 1.6], gap="large")

with left:
    st.markdown('<div class="seclabel">수집 달력</div>' if date_basis == "collected_at"
                else '<div class="seclabel">발행 달력</div>', unsafe_allow_html=True)
    render_calendar(cal_anchor.year, cal_anchor.month, counts, selected)

    month_prefix = f"{cal_anchor.year}-{cal_anchor.month:02d}"
    if not any(d.startswith(month_prefix) for d in counts):
        st.caption(f"{cal_anchor.year}년 {cal_anchor.month}월에는 수집된 기사가 없습니다.")

    st.markdown('<div class="seclabel" style="margin-top:1.4rem">최근 수집일</div>',
                unsafe_allow_html=True)
    for iso in available[:7]:
        c = counts[iso]
        d = date.fromisoformat(iso)
        st.button(
            f"{d.month:02d}.{d.day:02d} ({WEEKDAYS[d.weekday()]})  `{c['총계']}`",
            key=f"daylist-{iso}",
            use_container_width=True,
            type="primary" if iso == selected else "secondary",
            on_click=lambda d=iso: st.session_state.update(sel_date=d),
        )

# --- 선택일 상세 ---
with right:
    sel = date.fromisoformat(selected)
    day_stats = counts[selected]
    st.markdown(
        f'<div class="dayhead"><span class="d">{sel.year}. '
        f'{sel.month:02d}. {sel.day:02d}</span>'
        f'<span class="n">{WEEKDAYS[sel.weekday()]}요일 · 전체 {day_stats["총계"]}건 · '
        f'기회 {day_stats["기회"]} · 위협 {day_stats["위협"]} · 중립 {day_stats["중립"]}</span></div>',
        unsafe_allow_html=True,
    )

    day_articles = db.get_articles(on_date=selected, date_basis=date_basis, **flt)

    # 일별 브리핑
    brief_key = f"brief_{selected}_{date_basis}"
    analyzed = [a for a in day_articles if a.get("summary")]

    bcol1, bcol2 = st.columns([1, 2])
    with bcol1:
        if st.button("이 날의 브리핑 생성", key=f"brf-{selected}",
                     use_container_width=True, disabled=not analyzed):
            try:
                import processor
                with st.spinner("브리핑 작성 중"):
                    st.session_state[brief_key] = processor.generate_daily_briefing(analyzed)
            except RuntimeError as exc:
                st.session_state[brief_key] = {"error": str(exc)}
    with bcol2:
        if not analyzed:
            st.caption("분석된 기사가 없어 브리핑을 만들 수 없습니다.")

    if brief_key in st.session_state:
        b = st.session_state[brief_key]
        if isinstance(b, dict) and b.get("error"):
            st.error(b["error"])
        elif not b:
            st.warning("브리핑을 생성하지 못했습니다. 잠시 후 다시 시도하세요.")
        else:
            points = "".join(
                f'<div class="bp"><div class="t">{p.get("title","")} '
                f'{pill(p.get("tag","중립"), TAG_TINTS)}</div>'
                f'<div class="x">{p.get("detail","")}</div></div>'
                for p in b.get("key_points", [])
            )
            watch = "".join(f"<li>{w}</li>" for w in b.get("watch_items", []))
            st.markdown(
                f'<div class="brief"><div class="bh">{b.get("headline","")}</div>'
                f'{points}'
                f'<div class="wt"><div class="l">챙길 것</div><ul>{watch}</ul></div></div>',
                unsafe_allow_html=True,
            )

    st.markdown(f'<div class="seclabel">기사 {len(day_articles)}건 · 중요도 순</div>',
                unsafe_allow_html=True)

    if not day_articles:
        st.info("이 날짜에 조건을 만족하는 기사가 없습니다.")
    for art in day_articles:
        render_article(art, scope=f"d{selected}")
