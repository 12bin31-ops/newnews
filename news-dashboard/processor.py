"""LLM으로 기사를 분류/요약/스코어링한다.

공급자는 config.LLM_PROVIDER("gemini" 또는 "anthropic")로 전환한다.
프롬프트·스키마·파싱·정규화는 공급자와 무관하게 공유한다.
"""

import json
import random
import re
import time
from typing import Any, Optional

import config

# ------------------------------------------------------------------ 예외


class AccountError(RuntimeError):
    """크레딧 부족·인증 실패 등 기사마다 재시도해도 소용없는 계정 단위 오류."""


class TransientError(RuntimeError):
    """rate limit·서버 오류 등 잠시 후 재시도하면 되는 오류."""

    def __init__(self, message: str, wait: Optional[float] = None):
        super().__init__(message)
        self.wait = wait


class FatalRequestError(RuntimeError):
    """요청 자체가 잘못돼서 재시도해도 동일한 오류."""


# ------------------------------------------------------------------ 스키마

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 3,
            "description": "기사 요약. 문장 3개를 배열 원소로 각각 담는다.",
        },
        "category": {
            "type": "array",
            "items": {"type": "string", "enum": config.CATEGORIES},
            "minItems": 1,
            "description": "해당하는 카테고리. 복수 선택 가능.",
        },
        "category_reason": {"type": "string", "description": "왜 이 카테고리인지 한 줄 설명"},
        "tag": {
            "type": "string",
            "enum": config.TAGS,
            "description": f"{config.OUR_COMPANY} 관점에서 기회/위협/중립",
        },
        "score": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5,
            "description": (
                "마케팅팀 기준 중요도. 시스템 프롬프트의 5단계 기준을 그대로 적용한다. "
                "애매하면 3점이 아니라 2점을 고른다."
            ),
        },
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 3,
            "maxItems": 5,
            "description": "핵심 키워드 3~5개",
        },
    },
    "required": ["summary", "category", "category_reason", "tag", "score", "keywords"],
    "additionalProperties": False,
}

CAMPAIGN_SCHEMA = {
    "type": "object",
    "properties": {
        "ideas": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "enum": ["LinkedIn", "X", "인스타그램"]},
                    "hook": {"type": "string", "description": "한 줄 후킹 문구"},
                    "format": {"type": "string", "description": "카드뉴스/영상/텍스트 등 형식"},
                    "message": {"type": "string", "description": "핵심 메시지 2~3문장"},
                },
                "required": ["channel", "hook", "format", "message"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["ideas"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = f"""당신은 반도체 업계를 담당하는 {config.OUR_COMPANY} 마케팅팀의 뉴스 분석가입니다.
기사를 읽고 마케팅팀이 바로 활용할 수 있도록 요약·분류·평가합니다.

판단 기준:
- 카테고리: {' / '.join(config.CATEGORIES)} 중에서 고릅니다. 해당하면 여러 개를 골라도 됩니다.
  · 자사언급: {config.OUR_COMPANY}가 기사 주제로 직접 다뤄진 경우
  · 경쟁사동향: 삼성전자, 마이크론 등 경쟁사의 전략·실적·투자
  · 고객사동향: NVIDIA, AMD, 빅테크 등 수요처 관련
  · 시장상황: 업황, 가격, 수급, 수출 지표
  · 기술트렌드: HBM, 공정, 신제품 등 기술 흐름
  · 규제정책: 정부 정책, 보조금, 수출 통제, 법률
태그 — {config.OUR_COMPANY} 사업에 미치는 방향으로 판단합니다. 기사의 논조가 아니라 자사에 미치는 영향이 기준입니다.

  기회 · 자사에 유리하게 작용하는 사안.
         자사 제품·기술의 우위나 채택 확대, 자사가 강한 영역의 수요 증가,
         경쟁사의 차질, 자사에 유리한 정책, 자사 수요처의 투자 확대

  위협 · 자사에 불리하게 작용하는 사안.
         경쟁사의 기술·고객 확보 진전, 자사 점유 영역에 대한 경쟁 진입,
         수요 둔화나 가격 하락, 자사에 불리한 규제, 고객사의 공급처 다변화

  중립 · 방향을 특정하기 어렵거나 업계 전반에 동일하게 작용하는 사안.
         단순 시황·주가 보도, 업계 공통 전망, 자사 언급이 없는 일반 기술 소개

중립은 "판단이 어려울 때 고르는 기본값"이 아닙니다. 자사에 유리한지 불리한지
방향이 조금이라도 보이면 기회나 위협을 고르세요. 경쟁사가 주제인 기사는
대부분 위협이거나(경쟁사의 진전) 기회입니다(경쟁사의 차질) — 습관적으로 중립을 쓰지 마세요.

중요도(score) — 아래 5단계를 그대로 적용합니다. "마케팅팀이 이 기사를 보고 실제로 무엇을 해야 하는가"로 판단합니다.

  5점 · 즉시 대응. 오늘 메시지·대응 방향을 검토해야 하는 사안.
        예) {config.OUR_COMPANY} 신제품의 고객사 인증 통과나 대형 수주 확정,
            자사 관련 사고·리콜·소송·규제 제재, 핵심 고객사의 공급처 교체 발표

  4점 · 이번 주 검토. 경쟁 구도나 시장 판도를 실제로 바꾸는 사안.
        예) 경쟁사의 대형 설비 투자나 고객사 확보 확정, 수출 통제·보조금 정책 확정,
            주요 고객사의 대형 발주 발표

  3점 · 팀 공유. 맥락 파악에 도움이 되지만 당장 할 일은 없는 업계 동향.
        예) 학회·컨퍼런스 기술 발표, 업계 전망 분석 기사, 기술 로드맵 소개

  2점 · 참고. 이미 알려진 사실의 재보도, 간접 언급, 시장 일반론.
        예) 주가 등락과 증시 시황, 애널리스트 목표주가 조정, ETF 상장,
            여러 기업을 나열만 한 종합 기사

  1점 · 무관. 마케팅 판단에 쓸 것이 없는 기사.
        예) 단순 지수·환율 보도, 인사·부고, 자사·업계와 연결이 희박한 기사

점수 분포 지침: 실제로 5점은 열 건에 한 건 이하이고, 2점이 가장 흔합니다.
3점을 기본값으로 쓰지 마세요. 확신이 없으면 3점이 아니라 2점을 고릅니다.
제목에 기업명이 나왔다는 이유만으로 점수를 올리지 마세요 — 그 기업이 기사의 주제여야 합니다.

주의: 기사 제목과 발췌만 주어질 수 있습니다. 주어진 정보 범위에서 판단하고, 추측으로 사실을 만들어내지 마세요.
반드시 지정된 JSON 스키마 형식으로만 답하고, 그 외 설명 문장은 붙이지 마세요."""

CAMPAIGN_SYSTEM = f"""당신은 {config.OUR_COMPANY} 마케팅팀의 SNS 콘텐츠 기획자입니다.
주어진 뉴스를 소재로 실제로 올릴 수 있는 SNS 포스팅 아이디어 3개를 제안하세요.
각 아이디어는 채널(LinkedIn/X/인스타그램 중 하나), 한 줄 후킹 문구, 콘텐츠 형식, 핵심 메시지를 포함합니다.
기사에 없는 사실을 지어내지 말고, 회사가 곤란해질 수 있는 표현은 피하세요."""

DEFAULT_ANALYSIS = {
    "summary": "",
    "category": "미분류",
    "category_reason": "자동 분석 실패",
    "tag": "중립",
    "score": 1,
    "keywords": "",
    "analysis_ok": False,
}


# ------------------------------------------------------------------ 공급자: Gemini

_gemini_client = None


def _gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini가 받지 않는 JSON Schema 키(additionalProperties)를 재귀적으로 제거한다."""
    if not isinstance(schema, dict):
        return schema
    cleaned = {k: v for k, v in schema.items() if k != "additionalProperties"}
    if "properties" in cleaned:
        cleaned["properties"] = {k: _gemini_schema(v) for k, v in cleaned["properties"].items()}
    if "items" in cleaned:
        cleaned["items"] = _gemini_schema(cleaned["items"])
    return cleaned


def _retry_delay(exc: Any, default: float = 30.0) -> float:
    """429 응답에 담긴 RetryInfo(retryDelay)를 읽어낸다. 없으면 기본값."""
    details = getattr(exc, "details", None)
    if isinstance(details, dict):
        for item in (details.get("error", {}) or {}).get("details", []) or []:
            raw = item.get("retryDelay") or item.get("retry_delay")
            if raw:
                try:
                    return float(str(raw).rstrip("s")) + 1.0
                except ValueError:
                    pass
    # details에 없으면 메시지 문자열에서 찾아본다
    m = re.search(r"retryDelay['\"]?[:=]\s*['\"]?(\d+(?:\.\d+)?)s", str(exc))
    if m:
        return float(m.group(1)) + 1.0
    return default


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai

        if not config.GEMINI_API_KEY:
            raise AccountError(
                "GEMINI_API_KEY가 설정되지 않았습니다. "
                "https://aistudio.google.com/apikey 에서 발급 후 .env에 넣으세요."
            )
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _gemini_client


def _call_gemini(system: str, user: str, schema: dict[str, Any], max_tokens: int) -> str:
    from google.genai import errors, types

    client = _get_gemini_client()
    try:
        response = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=_gemini_schema(schema),
                max_output_tokens=max_tokens,
                temperature=0.3,
                # 함수 호출을 쓰지 않으므로 자동 함수 호출(AFC)을 끈다
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            ),
        )
    except errors.ClientError as exc:
        code = getattr(exc, "code", None)
        msg = str(getattr(exc, "message", "") or exc)
        if code == 429 or "RESOURCE_EXHAUSTED" in msg:
            raise TransientError(
                f"Gemini 요청 한도 초과(RPM): {msg[:90]}",
                wait=_retry_delay(exc),
            ) from None
        if code in (401, 403) or "API_KEY_INVALID" in msg or "PERMISSION_DENIED" in msg:
            raise AccountError(
                "GEMINI_API_KEY가 유효하지 않거나 권한이 없습니다. "
                "https://aistudio.google.com/apikey 에서 키를 확인하세요."
            ) from None
        if code == 404:
            raise AccountError(f"모델을 찾을 수 없습니다: {config.GEMINI_MODEL}") from None
        raise FatalRequestError(f"Gemini 요청 오류 {code}: {msg[:150]}") from None
    except errors.ServerError as exc:
        raise TransientError(f"Gemini 서버 오류: {str(exc)[:100]}") from None
    except errors.APIError as exc:
        raise TransientError(f"Gemini API 오류: {str(exc)[:100]}") from None

    text = getattr(response, "text", None)
    if not text:
        # 안전 필터 등으로 응답이 비는 경우
        reason = ""
        for cand in (getattr(response, "candidates", None) or []):
            reason = str(getattr(cand, "finish_reason", "") or "")
            break
        raise FatalRequestError(f"Gemini 응답이 비어 있습니다 (finish_reason={reason or '알 수 없음'})")
    return text


# ------------------------------------------------------------------ 공급자: Anthropic

_anthropic_client = None


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        if not config.ANTHROPIC_API_KEY:
            raise AccountError("ANTHROPIC_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")
        _anthropic_client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _anthropic_client


def _call_anthropic(system: str, user: str, schema: dict[str, Any], max_tokens: int) -> str:
    import anthropic

    client = _get_anthropic_client()
    try:
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": schema},
            },
        )
    except anthropic.RateLimitError as exc:
        wait = int(exc.response.headers.get("retry-after", 0)) or None
        raise TransientError("Anthropic rate limit", wait=wait) from None
    except anthropic.AuthenticationError:
        raise AccountError("ANTHROPIC_API_KEY가 유효하지 않습니다.") from None
    except anthropic.PermissionDeniedError:
        raise AccountError("API 키에 권한이 없습니다. 콘솔에서 키 권한을 확인하세요.") from None
    except anthropic.NotFoundError:
        raise AccountError(f"모델을 찾을 수 없습니다: {config.ANTHROPIC_MODEL}") from None
    except anthropic.BadRequestError as exc:
        msg = str(getattr(exc, "message", "") or exc)
        if "credit balance" in msg.lower():
            raise AccountError(
                "Anthropic 크레딧 잔액이 부족합니다. "
                "console.anthropic.com → Plans & Billing 에서 충전하세요."
            ) from None
        raise FatalRequestError(f"잘못된 요청: {msg[:150]}") from None
    except anthropic.APIStatusError as exc:
        if exc.status_code >= 500:
            raise TransientError(f"Anthropic 서버 오류 {exc.status_code}") from None
        raise FatalRequestError(f"API 오류 {exc.status_code}") from None
    except anthropic.APIConnectionError:
        raise TransientError("네트워크 연결 실패") from None

    if response.stop_reason == "refusal":
        raise FatalRequestError("모델이 응답을 거부했습니다")
    return "".join(b.text for b in response.content if b.type == "text")


PROVIDERS = {"gemini": _call_gemini, "anthropic": _call_anthropic}


def _call_llm(system: str, user: str, schema: dict[str, Any], max_tokens: int) -> str:
    fn = PROVIDERS.get(config.LLM_PROVIDER)
    if fn is None:
        raise AccountError(
            f"알 수 없는 LLM_PROVIDER: {config.LLM_PROVIDER!r} "
            f"(사용 가능: {', '.join(PROVIDERS)})"
        )
    return fn(system, user, schema, max_tokens)


def provider_label() -> str:
    """현재 공급자/모델을 사람이 읽을 수 있게 표시한다."""
    if config.LLM_PROVIDER == "gemini":
        return f"Gemini ({config.GEMINI_MODEL})"
    if config.LLM_PROVIDER == "anthropic":
        return f"Anthropic ({config.ANTHROPIC_MODEL})"
    return config.LLM_PROVIDER


# ------------------------------------------------------------------ 파싱


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    """모델 응답에서 JSON 객체를 뽑아낸다. 구조화 출력이 우회된 경우의 방어선."""
    if not text:
        return None

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.DOTALL)
    if fence:
        try:
            parsed = json.loads(fence.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    return None


def _normalize(raw: dict[str, Any]) -> dict[str, Any]:
    """모델 출력을 DB 저장 형태로 정규화하고 값 범위를 검증한다."""
    result = dict(DEFAULT_ANALYSIS)

    summary = raw.get("summary")
    if isinstance(summary, list):
        summary = "\n".join(str(s) for s in summary)
    summary = (summary or "").strip()
    # 모델이 줄바꿈을 리터럴 백슬래시-n으로 내보내는 경우가 있어 실제 개행으로 되돌린다
    summary = summary.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n")
    result["summary"] = summary

    cats = raw.get("category") or []
    if isinstance(cats, str):
        cats = [c.strip() for c in cats.split(",")]
    valid = [c for c in cats if c in config.CATEGORIES]
    result["category"] = ", ".join(valid) if valid else "미분류"

    result["category_reason"] = str(raw.get("category_reason") or "").strip()

    tag = str(raw.get("tag") or "").strip()
    result["tag"] = tag if tag in config.TAGS else "중립"

    try:
        score = int(raw.get("score", 1))
    except (TypeError, ValueError):
        score = 1
    result["score"] = min(5, max(1, score))

    kws = raw.get("keywords") or []
    if isinstance(kws, str):
        kws = [k.strip() for k in kws.split(",")]
    result["keywords"] = ", ".join(str(k).strip() for k in kws if str(k).strip())

    result["analysis_ok"] = bool(result["summary"])
    return result


# ------------------------------------------------------------------ 분석


def analyze_article(title: str, content: str = "", max_retries: int = 3) -> dict[str, Any]:
    """기사 1건을 한 번의 프롬프트로 요약·분류·스코어링한다.

    반환 키: summary, category, category_reason, tag, score, keywords, analysis_ok
    계정 단위 오류(AccountError)만 예외로 올리고, 그 외 실패는 기본값을 반환한다.
    """
    user = f"제목: {title}\n\n본문/발췌:\n{content or '(본문 없음 — 제목만으로 판단)'}"
    last_error = ""

    for attempt in range(max_retries):
        try:
            text = _call_llm(SYSTEM_PROMPT, user, ANALYSIS_SCHEMA, max_tokens=2000)
        except TransientError as exc:
            wait = exc.wait or min(2**attempt + random.uniform(0, 1), 30)
            last_error = str(exc)
            print(f"    [재시도 {attempt + 1}/{max_retries}] {exc} — {wait:.0f}초 대기")
            time.sleep(wait)
            continue
        except FatalRequestError as exc:
            last_error = str(exc)
            break

        parsed = _extract_json(text)
        if parsed is None:
            last_error = f"JSON 파싱 실패 (응답 앞부분: {text[:80]!r})"
            time.sleep(1)
            continue

        return _normalize(parsed)

    print(f"    [!] 분석 실패: {last_error}")
    fallback = dict(DEFAULT_ANALYSIS)
    fallback["category_reason"] = f"자동 분석 실패: {last_error[:120]}"
    return fallback


def generate_campaign_ideas(title: str, summary: str = "", keywords: str = "") -> list[dict[str, str]]:
    """기사 기반 SNS 포스팅 아이디어 3개를 생성한다. 실패 시 빈 리스트."""
    user = (
        f"기사 제목: {title}\n"
        f"요약: {summary or '(없음)'}\n"
        f"키워드: {keywords or '(없음)'}"
    )
    try:
        text = _call_llm(CAMPAIGN_SYSTEM, user, CAMPAIGN_SCHEMA, max_tokens=3000)
    except (TransientError, FatalRequestError) as exc:
        print(f"    [!] 캠페인 아이디어 생성 실패: {exc}")
        return []
    # AccountError는 호출부(대시보드)가 사용자에게 보여줄 수 있도록 그대로 올린다

    parsed = _extract_json(text) or {}
    ideas = parsed.get("ideas", [])
    return ideas if isinstance(ideas, list) else []


# ------------------------------------------------------------------ 일별 브리핑

BRIEFING_SYSTEM = f"""당신은 {config.OUR_COMPANY} 마케팅팀에 매일 아침 뉴스 브리핑을 올리는 담당자입니다.
하루치 기사 목록을 받아, 팀이 30초 안에 파악할 수 있는 브리핑을 작성하세요.

- headline: 그날 업계를 한 문장으로 요약
- key_points: 묶어야 할 이슈 3~5개. 여러 기사가 같은 사안이면 하나로 합칩니다.
- watch_items: 마케팅팀이 실제로 챙겨야 할 액션이나 주목할 지점 2~3개

주어진 기사 범위를 벗어난 사실을 만들지 마세요. 이모지나 장식 문자는 쓰지 마세요."""

BRIEFING_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "그날을 한 문장으로 요약"},
        "key_points": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "이슈 제목 (짧게)"},
                    "detail": {"type": "string", "description": "1~2문장 설명"},
                    "tag": {"type": "string", "enum": config.TAGS},
                },
                "required": ["title", "detail", "tag"],
                "additionalProperties": False,
            },
        },
        "watch_items": {
            "type": "array",
            "minItems": 2,
            "maxItems": 3,
            "items": {"type": "string"},
            "description": "마케팅팀이 챙길 액션 포인트",
        },
    },
    "required": ["headline", "key_points", "watch_items"],
    "additionalProperties": False,
}


def generate_daily_briefing(articles: list[dict[str, Any]]) -> dict[str, Any]:
    """하루치 기사 목록으로 브리핑을 생성한다. 실패 시 빈 dict."""
    if not articles:
        return {}

    lines = []
    for a in articles:
        parts = [f"- 제목: {a.get('title', '')}"]
        if a.get("category"):
            parts.append(f"카테고리: {a['category']}")
        if a.get("tag"):
            parts.append(f"태그: {a['tag']}")
        if a.get("score"):
            parts.append(f"중요도: {a['score']}")
        lines.append(" | ".join(parts))
        if a.get("summary"):
            lines.append(f"  요약: {a['summary'].replace(chr(10), ' ')}")

    user = f"기사 {len(articles)}건:\n" + "\n".join(lines)

    try:
        text = _call_llm(BRIEFING_SYSTEM, user, BRIEFING_SCHEMA, max_tokens=4000)
    except (TransientError, FatalRequestError) as exc:
        print(f"    [!] 브리핑 생성 실패: {exc}")
        return {}

    parsed = _extract_json(text) or {}
    return parsed if isinstance(parsed, dict) and parsed.get("headline") else {}


if __name__ == "__main__":
    print(f"공급자: {provider_label()}\n")

    sample_title = "SK하이닉스, HBM4 12단 제품 엔비디아 인증 통과"
    sample_content = (
        "SK하이닉스가 차세대 고대역폭 메모리 HBM4 12단 제품의 엔비디아 품질 인증을 "
        "통과했다고 밝혔다. 내년 상반기부터 본격 공급이 시작될 전망이다."
    )

    print("=== analyze_article() 테스트 ===")
    result = analyze_article(sample_title, sample_content)
    for k, v in result.items():
        print(f"  {k:16}: {v}")

    print("\n=== generate_campaign_ideas() 테스트 ===")
    for i, idea in enumerate(
        generate_campaign_ideas(sample_title, result["summary"], result["keywords"]), 1
    ):
        print(f"  {i}. [{idea.get('channel')}] {idea.get('hook')}")
        print(f"     형식: {idea.get('format')}")
        print(f"     메시지: {idea.get('message')}")
