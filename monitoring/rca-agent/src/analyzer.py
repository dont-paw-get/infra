import httpx
from strands import Agent, tool
from strands.models import BedrockModel

import config


@tool
def query_prometheus(promql: str) -> str:
    """Prometheus에 instant query를 실행하고 결과를 반환한다."""
    resp = httpx.get(f"{config.PROMETHEUS_URL}/api/v1/query", params={"query": promql}, timeout=10)
    resp.raise_for_status()
    return resp.text


@tool
def query_loki(logql: str, limit: int = 100) -> str:
    """Loki에 LogQL query_range를 실행하고 최근 로그를 반환한다."""
    resp = httpx.get(
        f"{config.LOKI_URL}/loki/api/v1/query_range",
        params={"query": logql, "limit": limit},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.text


# 프롬프트/도구 구성은 초기 스캐폴딩 수준이며, 실제 알림 유형별 조사 전략은 이후 반복 작업에서 다듬는다.
_SYSTEM_PROMPT = """당신은 관측 스택(Prometheus, Loki)에서 알림의 근본 원인을 조사하는 SRE 어시스턴트입니다.
전달받은 Grafana 알림(alertname, labels, annotations)을 바탕으로 관련 메트릭과 로그를 조회하고,
Discord에 게시할 한국어 요약(원인 후보, 근거, 다음 확인 사항)을 작성하세요. 클러스터에 쓰기 작업은 수행하지 않습니다."""


def analyze(alert: dict) -> str:
    agent = Agent(
        model=BedrockModel(model_id=config.BEDROCK_MODEL_ID, region_name=config.BEDROCK_REGION),
        tools=[query_prometheus, query_loki],
        system_prompt=_SYSTEM_PROMPT,
    )
    result = agent(f"다음 알림의 근본 원인을 분석해주세요:\n{alert}")
    return str(result)
