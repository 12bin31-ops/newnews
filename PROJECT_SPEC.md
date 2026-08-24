# 마케팅 뉴스 자동화 대시보드 — 프로젝트 스펙

## 프로젝트 개요
반도체 업계(SK하이닉스/삼성전자 벤치마킹) 뉴스를 자동 수집 → 분류/요약 → 마케팅팀이 보기 편한 대시보드로 제공하는 사이드 프로젝트.
현재 홍보팀이 수동으로 하는 "뉴스 수집·정리"를 자동화하고, 마케팅팀이 바로 액션 아이디어를 얻을 수 있게 하는 것이 목표.

**목표: 최대한 빠르게 MVP 완성 → 이후 기능 확장**

---

## 기술 스택
- Python 3.11+
- 뉴스 수집: `requests` + NewsAPI (또는 구글 뉴스 RSS `feedparser`)
- LLM 처리: Anthropic API (`anthropic` 패키지) — 요약/분류/스코어링
- DB: SQLite (`sqlite3` 표준 라이브러리)
- 대시보드: Streamlit
- 스케줄링(1차 완성본 단계에서): GitHub Actions

---

## 폴더 구조 (이 구조로 생성해줘)
```
news-dashboard/
├── collector.py        # 뉴스 수집
├── processor.py        # LLM 분류/요약/스코어링
├── db.py                # DB 초기화 및 CRUD 함수
├── app.py                # Streamlit 대시보드
├── config.py            # 키워드 리스트, API 키 로드 등
├── requirements.txt
├── .env.example
├── README.md
└── data/
    └── news.db           # SQLite 파일 (자동 생성)
```

---

## DB 스키마

### articles 테이블
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INTEGER PK | |
| title | TEXT | 기사 제목 |
| url | TEXT UNIQUE | 원문 링크 (중복 수집 방지용 UNIQUE) |
| source | TEXT | 언론사 |
| published_at | TEXT | 발행일 |
| collected_at | TEXT | 수집일 (기본값 now) |
| summary | TEXT | LLM 3줄 요약 |
| category | TEXT | 시장상황 / 경쟁사동향 / 자사언급 / 기술트렌드 / 규제정책 / 고객사동향 |
| category_reason | TEXT | 왜 이 카테고리인지 한 줄 설명 |
| tag | TEXT | 기회 / 위협 / 중립 |
| score | INTEGER | 1~5 중요도 |
| keywords | TEXT | 콤마 구분 키워드 |

### comments 테이블
| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | INTEGER PK | |
| article_id | INTEGER FK | articles.id 참조 |
| author | TEXT | 작성자 (일단 텍스트 입력, 로그인 없음) |
| comment | TEXT | 코멘트 내용 |
| created_at | TEXT | 작성일 |

---

## 기능 요구사항

### 1. collector.py
- NewsAPI 또는 구글 뉴스 RSS로 키워드 검색 (`config.py`의 `SEARCH_KEYWORDS` 리스트 사용: "SK하이닉스", "삼성전자 반도체", "HBM", "NVIDIA AI칩" 등)
- 중복 URL은 건너뛰기 (DB의 UNIQUE 제약 활용)
- 최근 24~48시간 이내 기사만 수집
- 함수형으로: `fetch_news(keyword: str) -> list[dict]`

### 2. processor.py
- Anthropic API 호출해서 기사 하나당 아래 정보를 **한 번의 프롬프트**로 생성 (API 호출 비용 절감):
  - 3줄 요약
  - 카테고리 (시장상황/경쟁사동향/자사언급/기술트렌드/규제정책/고객사동향 중 하나 이상, 다중 가능)
  - 카테고리 선정 이유 (한 줄)
  - 기회/위협/중립 태그
  - 중요도 스코어 1~5
  - 핵심 키워드 3~5개
- **출력은 JSON 형식으로 강제** (system prompt에 "JSON만 출력, 다른 텍스트 없이"라고 명시)
- 함수: `analyze_article(title: str, content: str) -> dict`

### 3. db.py
- `init_db()`: 테이블 없으면 생성
- `insert_article(article: dict)`: UNIQUE 위반 시 무시하고 넘어가기
- `get_articles(category=None, tag=None, date_from=None) -> list[dict]`: 필터링 조회
- `add_comment(article_id, author, comment)`
- `get_comments(article_id) -> list[dict]`

### 4. app.py (Streamlit 대시보드)
- 사이드바 필터: 카테고리(다중선택), 태그(기회/위협/중립), 날짜 범위
- 탭 구성: "전체" / "경쟁사동향" / "자사언급" / "시장상황" 등 카테고리별
- 기사 카드 UI에 포함할 것:
  - 제목 (클릭 시 원문 링크)
  - 3줄 요약
  - 카테고리 뱃지 + 태그(기회/위협) 뱃지 + 중요도 별점
  - 키워드 태그들
  - **코멘트 섹션**: 기존 코멘트 리스트 표시 + 새 코멘트 입력 폼 (이름 + 내용)
  - "캠페인 아이디어 생성" 버튼 → 누르면 해당 기사 기반으로 Anthropic API 호출해서 SNS 포스팅 아이디어 3개 생성해서 expander로 표시
- 상단에 요약 통계: 오늘 수집된 기사 수, 기회 태그 수, 위협 태그 수

### 5. config.py
- `.env`에서 `ANTHROPIC_API_KEY`, `NEWS_API_KEY` 로드 (`python-dotenv` 사용)
- `SEARCH_KEYWORDS` 리스트 정의

---

## 구현 순서 (이 순서대로 단계별로 진행해줘, 각 단계마다 실행 확인 후 다음 단계로)

1. 폴더 구조 및 `requirements.txt`, `.env.example` 생성
2. `db.py` 작성 및 테스트 (더미 데이터로 insert/get 확인)
3. `collector.py` 작성 — 우선 구글 뉴스 RSS(`feedparser`)로 시작 (무료, API 키 불필요라 빠름)
4. `processor.py` 작성 — Anthropic API 연동, JSON 파싱 에러 핸들링 포함
5. `collector.py` + `processor.py` + `db.py` 연결하는 `main.py` (또는 `collector.py`에 통합) 작성 — 실제로 뉴스 수집 → 분석 → DB 저장까지 한 번에 도는 파이프라인
6. `app.py` Streamlit 대시보드 작성 (리스트/필터 먼저, 그다음 코멘트 기능, 그다음 캠페인 생성 버튼)
7. `README.md` 작성 (프로젝트 설명, 실행 방법, 스크린샷 자리, 향후 계획 섹션 포함)

---

## 주의사항
- API 키는 절대 코드에 하드코딩하지 말고 `.env`에서 로드
- LLM 응답이 JSON이 아닐 경우를 대비한 예외처리 필수 (파싱 실패 시 재시도 또는 기본값 처리)
- 초기 버전은 에러 핸들링을 최소화해도 되지만, API 호출 실패/rate limit은 반드시 처리
- 커밋 전 `.env`, `data/news.db`는 `.gitignore`에 추가

---

## MVP 완료 기준 (Definition of Done)
- [ ] 뉴스 10~20건 수집되어 DB에 저장됨
- [ ] 각 기사에 카테고리/태그/요약이 붙어있음
- [ ] Streamlit에서 필터링하며 기사 확인 가능
- [ ] 코멘트 작성 가능
- [ ] "캠페인 아이디어 생성" 버튼 동작
- [ ] `streamlit run app.py` 한 줄로 로컬 실행 가능
