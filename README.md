# 마케팅 뉴스 자동화 대시보드

반도체 업계 뉴스를 **자동 수집 → LLM 분류·요약 → 달력 기반 대시보드**로 제공하는 사이드 프로젝트.
홍보팀이 수동으로 하던 뉴스 수집·정리를 자동화하고, 마케팅팀이 바로 액션 아이디어를 얻는 것이 목표입니다.

## 무엇을 해주나

- 구글 뉴스 RSS에서 키워드별 최신 기사 수집 (URL·제목 기준 중복 자동 제거)
- 기사마다 **한 번의 LLM 호출**로 3줄 요약 · 카테고리 · 기회/위협 태그 · 중요도(1~5) · 키워드 생성
- **달력에서 날짜를 눌러** 그날 수집된 기사를 모아 보기
- 그날치 기사를 묶은 **일별 브리핑** 생성 (헤드라인 + 핵심 이슈 + 챙길 것)
- 기사별 팀 **코멘트**, 기사 기반 **SNS 캠페인 아이디어** 생성
- **GitHub Actions로 매일 아침 자동 수집**

## 분류 체계

| 구분 | 값 |
|---|---|
| 카테고리 | 시장상황 · 경쟁사동향 · 자사언급 · 기술트렌드 · 규제정책 · 고객사동향 (복수 가능) |
| 태그 | 기회 · 위협 · 중립 |
| 중요도 | 1(무관) ~ 5(즉시 대응) |

## 빠른 시작

```bash
cd news-dashboard
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # GEMINI_API_KEY 입력 (무료, 카드 불필요)
python main.py            # 수집 → 분석 → 저장
streamlit run app.py      # 대시보드 실행
```

Gemini 키는 [Google AI Studio](https://aistudio.google.com/apikey)에서 무료로 발급받습니다.

## 기술 스택

Python 3.11 · SQLite · Streamlit · Google Gemini (Anthropic Claude 전환 가능) · GitHub Actions

## 문서

- **[상세 문서](news-dashboard/README.md)** — 설치, 실행 옵션, 자동 수집 설정, 비용 관리, 향후 계획
- [프로젝트 스펙](PROJECT_SPEC.md) — 최초 요구사항 정의

## 프로젝트 구조

```
├── .github/workflows/collect-news.yml   # 매일 아침 자동 수집
├── PROJECT_SPEC.md
└── news-dashboard/
    ├── collector.py     # 구글 뉴스 RSS 수집
    ├── processor.py     # LLM 분류·요약·스코어링
    ├── db.py            # SQLite CRUD, 날짜별 집계
    ├── main.py          # 수집 → 분석 → 저장 파이프라인
    ├── app.py           # Streamlit 대시보드
    └── config.py        # 키워드, 카테고리, API 키
```

## 라이선스

MIT
