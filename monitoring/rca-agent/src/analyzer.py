import time

import httpx
from strands import Agent, tool
from strands.models import BedrockModel

import config

# Loki/Prometheus range query 결과가 크면 토큰을 낭비하니 프롬프트에 넣기 전에 자른다.
_MAX_RESULT_CHARS = 8000


@tool
def query_prometheus(promql: str) -> str:
    """Prometheus에 instant query를 실행하고 결과를 반환한다. 현재 시점의 값만 필요할 때 사용한다."""
    try:
        resp = httpx.get(f"{config.PROMETHEUS_URL}/api/v1/query", params={"query": promql}, timeout=10)
        resp.raise_for_status()
        return resp.text[:_MAX_RESULT_CHARS]
    except httpx.HTTPError as e:
        return f"Prometheus instant query 실패: {e}"


@tool
def query_prometheus_range(promql: str, lookback_minutes: int = 30, step_seconds: int = 60) -> str:
    """Prometheus에 range query를 실행해 지금부터 lookback_minutes 전까지의 추세를 반환한다.
    알림 발화 원인이 급증인지 완만한 증가인지 확인할 때 가장 먼저 사용한다."""
    now = time.time()
    try:
        resp = httpx.get(
            f"{config.PROMETHEUS_URL}/api/v1/query_range",
            params={"query": promql, "start": now - lookback_minutes * 60, "end": now, "step": step_seconds},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.text[:_MAX_RESULT_CHARS]
    except httpx.HTTPError as e:
        return f"Prometheus range query 실패: {e}"


@tool
def query_loki(logql: str, limit: int = 100) -> str:
    """Loki에 LogQL query_range를 실행하고 최근 로그를 반환한다."""
    try:
        resp = httpx.get(
            f"{config.LOKI_URL}/loki/api/v1/query_range",
            params={"query": logql, "limit": limit},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.text[:_MAX_RESULT_CHARS]
    except httpx.HTTPError as e:
        return f"Loki query 실패: {e}"


_SYSTEM_PROMPT = """당신은 관측 스택(Prometheus, Loki)에서 Grafana 알림의 근본 원인을 조사하는 SRE 어시스턴트입니다.
전달받은 알림(labels, annotations, startsAt, valueString)을 바탕으로 관련 메트릭과 로그를 조회하고,
Discord에 게시할 한국어 요약(원인 후보, 근거, 다음 확인 사항)을 작성하세요. 클러스터에 쓰기 작업은 수행하지 않습니다.

알림 제목(labels.alertname)별로 아래 라벨과 조사 순서를 따르세요. Loki 라벨은 namespace/app/pod/container이고
Prometheus 알림 라벨(application 등)과 이름이 다를 수 있으니 혼동하지 마세요:

- "파드 CrashLoopBackOff", "파드 OOMKilled": labels에 namespace, pod가 있습니다.
  1) query_prometheus_range로 kube_pod_container_status_restarts_total{{namespace="...", pod="..."}} 추세를 확인해
     재시작이 급증했는지 반복적인지 파악합니다.
  2) query_loki로 {{namespace="...", pod="..."}} 라벨의 재시작 직전 로그를 확인합니다.

- "PVC 사용률 초과": labels에 namespace, persistentvolumeclaim이 있습니다.
  1) query_prometheus_range로 kubelet_volume_stats_used_bytes{{namespace="...", persistentvolumeclaim="..."}}의
     증가 추세(급증 vs 완만한 증가)를 확인합니다. 이 알림은 로그와의 연관성이 낮으니 Loki 조회 우선순위는 낮춥니다.

- "로그 ERROR 급증": labels에 app이 있습니다.
  1) query_loki로 {{app="...", namespace=~".+"}} | json | level="ERROR" 패턴의 실제 에러 메시지를 확인합니다.
  2) query_prometheus_range로 같은 앱의 재시작/리소스 메트릭에 이상이 없는지 교차 확인합니다.

- "HTTP 5xx 에러율 초과", "p99 레이턴시 초과": labels에 application이 있습니다.
  1) query_prometheus_range로 http_server_requests_seconds_count/bucket{{application="..."}} 추세를 확인합니다.
  2) query_loki로 {{app="...", namespace=~".+"}} | json | level="ERROR"도 함께 조회해 에러 로그와의 상관관계를 확인합니다.

공통 원칙: 먼저 query_prometheus_range로 알림 발화 시점(startsAt) 전후 추세를 파악한 뒤, 필요하면
query_prometheus(instant)나 query_loki로 세부를 파고드세요. 도구 호출이 실패하면 실패 사실을 보고서에 명시하고
남은 근거로 결론을 내리세요."""


def analyze(alert: dict) -> str:
    agent = Agent(
        model=BedrockModel(model_id=config.BEDROCK_MODEL_ID, region_name=config.BEDROCK_REGION),
        tools=[query_prometheus, query_prometheus_range, query_loki],
        system_prompt=_SYSTEM_PROMPT,
    )
    result = agent(f"다음 알림의 근본 원인을 분석해주세요:\n{alert}")
    return str(result)
