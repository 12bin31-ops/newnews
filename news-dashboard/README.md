# 📡 마케팅 뉴스 자동화 대시보드

반도체 업계 뉴스를 **자동 수집 → LLM 분류·요약 → 대시보드 제공**하는 사이드 프로젝트.
홍보팀이 수동으로 하던 뉴스 수집·정리를 자동화하고, 마케팅팀이 바로 액션 아이디어를 얻는 것이 목표입니다.

---

## 무엇을 해주나

- 구글 뉴스 RSS에서 키워드별 최신 기사 수집 (중복 자동 제거)
- 기사마다 **한 번의 LLM 호출**로 3줄 요약 · 카테고리 · 기회/위협 태그 · 중요도(1~5) · 키워드 생성
- 카테고리/태그/날짜/중요도로 필터링하며 보는 Streamlit 대시보드
- 기사별 **팀 코멘트** 작성
- 기사 기반 **SNS 캠페인 아이디어 3개** 즉석 생성

### 분류 체계

| 구분 | 값 |
|---|---|
| 카테고리 | 시장상황 · 경쟁사동향 · 자사언급 · 기술트렌드 · 규제정책 · 고객사동향 (복수 선택 가능) |
| 태그 | 🟢 기회 · 🔴 위협 · ⚪ 중립 |
| 중요도 | 1(참고) ~ 5(즉시 대응 필요) |

---

## 빠른 시작

### 1. 설치

```bash
cd news-dashboard
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. API 키 설정

```bash
cp .env.example .env
```

기본 분석 엔진은 **Google Gemini(무료 티어)** 입니다. [Google AI Studio](https://aistudio.google.com/apikey)에서
키를 발급받아 (신용카드 불필요) `.env`에 넣으세요:

```
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...
```

> `NEWS_API_KEY`는 비워둬도 됩니다. 기본 수집원인 구글 뉴스 RSS는 키가 필요 없습니다.

#### Claude로 바꾸려면

Anthropic 크레딧이 있다면 `.env` 두 줄만 바꾸면 됩니다. 코드 수정은 필요 없습니다:

```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

### 3. 뉴스 수집 + 분석

```bash
python main.py
```

```
[1/3] 뉴스 수집 (최근 48시간)
  · SK하이닉스      → 10건 수집 / 10건 신규
  ...
[2/3] 분석 대상 20건 (기존 DB 중복 0건 제외)
  (1/20) SK하이닉스, HBM4 12단 엔비디아 인증 통과
        → [기회] 자사언급, 기술트렌드 (5점)
[3/3] DB 저장
```

### 4. 대시보드 실행

```bash
streamlit run app.py
```

브라우저에서 http://localhost:8501 이 열립니다.

---

## `main.py` 실행 옵션

| 옵션 | 설명 |
|---|---|
| `--no-llm` | LLM 분석을 건너뛰고 수집·저장만 (API 비용 없이 배선 확인용) |
| `--limit N` | 분석할 기사 수 제한 (비용 통제) |
| `--keyword X` | 특정 키워드만 수집 (여러 번 지정 가능) |
| `--hours N` | 수집 윈도우 조정 (기본 48시간) |

```bash
python main.py --limit 5 --keyword HBM      # HBM 기사 5건만 분석
python main.py --no-llm                     # 수집만 (무료)
```

---

## 스크린샷

> _스크린샷 자리 — `streamlit run app.py` 실행 후 캡처해서 넣어주세요._

| 화면 | 이미지 |
|---|---|
| 대시보드 전체 | `docs/screenshot-dashboard.png` |
| 기사 카드 + 코멘트 | `docs/screenshot-card.png` |
| 캠페인 아이디어 생성 | `docs/screenshot-campaign.png` |

---

## 프로젝트 구조

```
news-dashboard/
├── collector.py     # 구글 뉴스 RSS 수집 (fetch_news / fetch_all)
├── processor.py     # LLM 분류·요약·스코어링 + 캠페인 아이디어 (Gemini/Anthropic 전환)
├── db.py            # SQLite 초기화 및 CRUD
├── main.py          # 수집 → 분석 → 저장 파이프라인
├── app.py           # Streamlit 대시보드
├── config.py        # 키워드/카테고리/API 키 로드
├── requirements.txt
├── .env.example
└── data/news.db     # SQLite (자동 생성, git 제외)
```

### DB 스키마

**articles** — `id`, `title`, `url`(UNIQUE), `source`, `published_at`, `collected_at`, `summary`, `category`, `category_reason`, `tag`, `score`, `keywords`

**comments** — `id`, `article_id`(FK), `author`, `comment`, `created_at`

---

## 설정 바꾸기

[config.py](config.py)에서 수정합니다:

```python
SEARCH_KEYWORDS = ["SK하이닉스", "삼성전자 반도체", "HBM", ...]   # 검색 키워드
COLLECT_WINDOW_HOURS = 48                                       # 수집 기간
MAX_ARTICLES_PER_KEYWORD = 10                                   # 키워드당 최대 건수
OUR_COMPANY = "SK하이닉스"                                       # 기회/위협 판단 기준
```

### 분석 엔진 바꾸기

| `.env` 항목 | 설명 |
|---|---|
| `LLM_PROVIDER` | `gemini`(무료, 기본) 또는 `anthropic` |
| `GEMINI_MODEL` | 기본 `gemini-2.5-flash` |
| `ANTHROPIC_MODEL` | 기본 `claude-opus-5`. 비용을 줄이려면 `claude-haiku-4-5` |
| `LLM_REQUEST_DELAY` | 연속 호출 간격(초). 미설정 시 gemini 6.5, anthropic 0.3 |

프롬프트·분류 체계·JSON 스키마는 두 공급자가 공유합니다. 공급자별로 다른 것은
API 호출 방식과 오류 처리뿐이라, 전환해도 결과 형식은 동일합니다.

---

## 비용 / 한도 관리

- 기사 1건 = LLM 호출 1회 (요약·분류·태그·스코어·키워드를 한 프롬프트로 처리)
- 이미 DB에 있는 URL은 **LLM 호출 전에** 걸러내므로, 재실행해도 신규 기사만 호출합니다
- 크레딧 부족·인증 실패 같은 계정 단위 오류는 첫 기사에서 **즉시 중단**하고,
  분석하지 못한 기사는 저장하지 않습니다. 문제를 해결한 뒤 다시 실행하면 이어서 처리됩니다

**Gemini 무료 티어** — 분당 요청 수 제한이 있어 호출 간격을 6.5초로 둡니다.
20건 분석에 약 2분 걸립니다. 일일 한도를 넘으면 `RESOURCE_EXHAUSTED`가 뜨고 재시도합니다.

**Anthropic** — 기사 1건당 입력 약 500토큰. `claude-opus-5` 기준 약 $0.013/건,
`claude-haiku-4-5` 기준 약 $0.003/건입니다.

---

## 알려진 제약

- **본문 전문 없음** — 구글 뉴스 RSS는 제목과 짧은 발췌만 제공합니다. LLM은 이 범위에서만 판단하므로 요약 깊이에 한계가 있습니다.
- **링크가 구글 리다이렉트** — `url`이 원문 주소가 아닌 `news.google.com` 링크입니다. 클릭 시 원문으로 이동은 정상 동작합니다.
- **로그인 없음** — 코멘트 작성자는 텍스트 입력이며 인증이 없습니다.
- **수동 갱신** — 대시보드는 DB를 읽기만 합니다. 갱신은 터미널에서 `python main.py`를 실행해야 합니다.
- **Gemini 무료 티어 한도** — 분당·일일 요청 수 제한이 있어 대량 수집에는 맞지 않습니다. 운영 단계에서는 유료 전환이 필요합니다.

---

## 향후 계획

**1차 — 자동화**
- [ ] GitHub Actions로 매일 아침 `main.py` 자동 실행
- [ ] 슬랙 알림 — 중요도 4~5 기사만 아침에 요약 전송

**2차 — 분석 품질**
- [ ] 원문 크롤링(`trafilatura` 등)으로 본문 확보 → 요약 정확도 개선
- [ ] NewsAPI 병행 수집으로 커버리지 확대
- [ ] 유사 기사 클러스터링 (같은 이슈를 다룬 기사 묶어서 표시)

**3차 — 대시보드**
- [ ] 주간/월간 트렌드 차트 (카테고리별 기사량, 기회/위협 추이)
- [ ] 키워드 워드클라우드
- [ ] 대시보드에서 바로 수집 트리거하는 버튼
- [ ] 코멘트 알림 및 담당자 멘션

**4차 — 운영**
- [ ] 로그인 / 팀 계정
- [ ] SQLite → PostgreSQL 이관
- [ ] 사내 배포 (Streamlit Community Cloud 또는 사내 서버)
