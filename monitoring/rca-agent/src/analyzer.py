import time

import httpx
from strands import Agent, tool
from strands.models import BedrockModel

import config

# Loki/Prometheus range query 결과가 크면 토큰을 낭비하니 프롬프트에 넣기 전에 자른다.
_MAX_RESULT_CHARS = 8000

# Tempo 원본 trace JSON은 span 하나에 수십 KB까지 커진다. 그대로 프롬프트에 넣지 않고
# span 트리로 요약할 때 렌더링할 최대 span 수와 메시지 길이.
_MAX_SPANS_RENDERED = 80
_MAX_SPAN_MSG_CHARS = 300


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


def _attr_value(value: dict):
    """OTLP AnyValue({"stringValue": ...} / {"intValue": "500"} ...)에서 실제 값을 꺼낸다."""
    for key in ("stringValue", "boolValue", "doubleValue"):
        if key in value:
            return value[key]
    if "intValue" in value:
        return int(value["intValue"])
    return value


def _attrs_to_dict(attributes: list) -> dict:
    return {a["key"]: _attr_value(a.get("value", {})) for a in attributes or []}


def _summarize_trace(trace: dict) -> str:
    """Tempo /api/traces 응답(OTLP JSON)을 span 트리 텍스트로 압축한다.
    각 span은 service / name / duration / status 를, 에러 span은 exception 이벤트의
    type·message 를 함께 남긴다. 원본 JSON을 그대로 반환하면 토큰을 수만 개 낭비한다."""
    spans = []  # (start_ns, service, span)
    for batch in trace.get("batches", []):
        res = _attrs_to_dict(batch.get("resource", {}).get("attributes", []))
        service = res.get("service.name", "?")
        for scope in batch.get("scopeSpans", batch.get("instrumentationLibrarySpans", [])):
            for span in scope.get("spans", []):
                spans.append((int(span.get("startTimeUnixNano", 0)), service, span))
    if not spans:
        return "trace에 span이 없습니다 (retention 만료 또는 잘못된 trace_id)."

    spans.sort(key=lambda x: x[0])
    children: dict[str, list] = {}
    for start_ns, service, span in spans:
        children.setdefault(span.get("parentSpanId", ""), []).append((start_ns, service, span))
    span_ids = {span.get("spanId") for _, _, span in spans}
    roots = [t for t in spans if not t[2].get("parentSpanId") or t[2].get("parentSpanId") not in span_ids]

    lines: list[str] = []
    rendered = 0
    truncated = False

    def walk(node, depth: int):
        nonlocal rendered, truncated
        if rendered >= _MAX_SPANS_RENDERED:
            truncated = True
            return
        start_ns, service, span = node
        rendered += 1
        dur_ms = (int(span.get("endTimeUnixNano", start_ns)) - start_ns) / 1e6
        status = span.get("status", {}) or {}
        is_err = status.get("code") in (2, "STATUS_CODE_ERROR")
        attrs = _attrs_to_dict(span.get("attributes", []))
        picked = {
            k: attrs[k]
            for k in ("http.status_code", "http.route", "rpc.method", "gen_ai.request.model",
                      "db.system", "db.statement", "error.type")
            if k in attrs
        }
        head = f"{'  ' * depth}- {service} | {span.get('name', '?')} | {dur_ms:.0f}ms"
        if is_err:
            head += " | ERROR"
        if picked:
            head += " | " + ", ".join(f"{k}={str(v)[:120]}" for k, v in picked.items())
        lines.append(head)
        exc_msgs = []
        for event in span.get("events", []):
            if event.get("name") == "exception":
                ev = _attrs_to_dict(event.get("attributes", []))
                etype = ev.get("exception.type", "")
                emsg = str(ev.get("exception.message", ""))
                exc_msgs.append(emsg)
                lines.append(f"{'  ' * depth}    exception: {etype}: {emsg[:_MAX_SPAN_MSG_CHARS]}")
        # status.message는 대개 exception.message와 겹치므로, 새 정보일 때만 추가한다.
        smsg = status.get("message", "")
        if is_err and smsg and not any(smsg[:60] in m for m in exc_msgs):
            lines.append(f"{'  ' * depth}    status: {smsg[:_MAX_SPAN_MSG_CHARS]}")
        for child in sorted(children.get(span.get("spanId", ""), []), key=lambda x: x[0]):
            walk(child, depth + 1)

    for root in roots:
        walk(root, 0)
    if truncated:
        lines.append(f"... (span {len(spans)}개 중 {_MAX_SPANS_RENDERED}개만 표시)")
    return "\n".join(lines)


@tool
def search_traces(traceql: str, lookback_minutes: int = 60, limit: int = 20) -> str:
    """Tempo에 TraceQL 검색을 실행해 조건에 맞는 trace 목록(traceID, 루트 서비스/이름, 소요시간)을 반환한다.
    레이턴시 알림이면 '{ resource.service.name="<svc>" && duration > 1s }', 5xx 알림이면
    '{ status = error }' 또는 '{ span.http.status_code >= 500 }' 처럼 쓴다. 반환된 traceID로 get_trace를 호출한다."""
    now = time.time()
    try:
        resp = httpx.get(
            f"{config.TEMPO_URL}/api/search",
            params={"q": traceql, "start": int(now - lookback_minutes * 60), "end": int(now), "limit": limit},
            headers={"Accept": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return f"Tempo search 실패: {e}"
    traces = resp.json().get("traces", [])
    if not traces:
        return f"조건에 맞는 trace가 없습니다: {traceql}"
    rows = []
    for t in traces:
        dur = t.get("durationMs", "?")
        rows.append(
            f"{t.get('traceID')}  {t.get('rootServiceName', '?')}/{t.get('rootTraceName', '?')}  {dur}ms"
        )
    return "\n".join(rows)[:_MAX_RESULT_CHARS]


@tool
def get_trace(trace_id: str) -> str:
    """Tempo에서 trace_id 하나의 전체 span 트리를 조회해 요약한다. 각 span의 service/name/소요시간/status와
    에러 span의 exception 메시지를 보여준다. 느린 요청의 병목 span이나 실패 span의 원인을 특정할 때 사용한다.
    Loki 에러 로그의 trace_id 필드를 그대로 넘기면 서비스 간 요청 흐름을 재구성할 수 있다."""
    try:
        resp = httpx.get(
            f"{config.TEMPO_URL}/api/traces/{trace_id}",
            headers={"Accept": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
    except httpx.HTTPError as e:
        return f"Tempo trace 조회 실패: {e}"
    try:
        return _summarize_trace(resp.json())[:_MAX_RESULT_CHARS]
    except (ValueError, KeyError) as e:
        return f"Tempo trace 파싱 실패: {e}"


_SYSTEM_PROMPT = """당신은 관측 스택(Prometheus, Loki, Tempo)에서 Grafana 알림의 근본 원인을 조사하는 SRE 어시스턴트입니다.
전달받은 알림(labels, annotations, startsAt, valueString)을 바탕으로 관련 메트릭과 로그를 조회하고,
Discord에 게시할 한국어 요약(원인 후보, 근거, 다음 확인 사항)을 작성하세요. 클러스터에 쓰기 작업은 수행하지 않습니다.

사용 가능한 도구: query_prometheus, query_prometheus_range(메트릭), query_loki(로그),
search_traces·get_trace(Tempo 분산 추적). 애플리케이션 JSON 로그에는 trace_id 필드가 있고
그 값은 Tempo의 trace_id와 같습니다. get_trace의 TraceQL 서비스 이름(resource.service.name)은
Prometheus의 application 라벨이나 Loki의 app 라벨과 다를 수 있으니, 먼저 로그/메트릭으로 서비스명을
확인한 뒤 사용하세요.

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
  2) 에러 로그에 trace_id가 있으면 get_trace로 해당 요청의 span 트리를 열어 어느 서비스/호출에서
     실패가 시작됐는지 확인합니다 (앱 로그가 메시지를 누락해도 span의 exception 이벤트에는 원문이 남습니다).
  3) query_prometheus_range로 같은 앱의 재시작/리소스 메트릭에 이상이 없는지 교차 확인합니다.

- "HTTP 5xx 에러율 초과": labels에 application이 있습니다.
  1) query_prometheus_range로 http_server_requests_seconds_count{{application="..."}} 추세를 확인합니다.
  2) search_traces로 '{{ resource.service.name="<svc>" && status = error }}' (또는 '{{ span.http.status_code >= 500 }}')
     를 검색하고, 나온 traceID를 get_trace로 열어 실패 span의 status/exception 메시지로 원인을 특정합니다.
  3) query_loki로 {{app="...", namespace=~".+"}} | json | level="ERROR"도 함께 조회해 상관관계를 확인합니다.

- "p99 레이턴시 초과": labels에 application이 있습니다.
  1) query_prometheus_range로 histogram_quantile로 어느 시점부터 느려졌는지 추세를 확인합니다.
  2) search_traces로 '{{ resource.service.name="<svc>" && duration > <threshold> }}'를 검색해 느린 요청을 찾고,
     get_trace로 열어 전체 소요시간을 지배하는 child span(DB 쿼리, 외부 HTTP, LLM 호출 등)을 특정합니다.

공통 원칙: 먼저 query_prometheus_range로 알림 발화 시점(startsAt) 전후 추세를 파악한 뒤, 필요하면
query_prometheus(instant)나 query_loki로 세부를 파고드세요. 에러/지연이 여러 서비스에 걸친 것으로 보이면
로그의 trace_id로 get_trace를 호출해 요청 흐름 전체를 재구성하세요. 도구 호출이 실패하면 실패 사실을
보고서에 명시하고 남은 근거로 결론을 내리세요."""


def analyze(alert: dict) -> str:
    agent = Agent(
        model=BedrockModel(model_id=config.BEDROCK_MODEL_ID, region_name=config.BEDROCK_REGION),
        tools=[query_prometheus, query_prometheus_range, query_loki, search_traces, get_trace],
        system_prompt=_SYSTEM_PROMPT,
    )
    result = agent(f"다음 알림의 근본 원인을 분석해주세요:\n{alert}")
    return str(result)
