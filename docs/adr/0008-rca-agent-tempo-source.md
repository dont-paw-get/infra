# ADR-0008: RCA Agent 트레이스(Tempo) 소스 추가

## 상태

승인됨 (2026-09-02)

`docs/adr/0002-anomaly-rca-agent.md`(RCA Agent 도입), `docs/adr/0007-otel-tempo-tracing.md`(dev 분산 트레이싱 스택)를 확장한다.

## 배경

ADR-0002의 RCA Agent는 Grafana 알림 발화 시 Prometheus/Loki를 조회해 원인을 분석한다. ADR-0007로 dev 클러스터에 OpenTelemetry Collector + Grafana Tempo가 추가되어 `backend-*` 서비스의 분산 추적이 수집·저장되고 있고, Grafana에서는 로그의 `trace_id`로 trace를 오갈 수 있게 됐다.

그러나 Agent는 여전히 메트릭/로그만 본다. 실제로 다음 한계가 확인됐다(2026-09-02 trace 분석 세션):

- 애플리케이션 로그가 예외를 삼켜(`exception: null`) 원인이 안 보이는데, 같은 요청의 Tempo span에는 예외 원문(`UnrecognizedClientException: ...`)이 그대로 남아 있었다.
- 레이턴시/5xx 알림에서 "어느 서비스 호출(DB, 외부 HTTP, LLM)이 병목/실패의 원인인지"는 trace 없이는 메트릭으로 우회 추론만 가능하다.
- 에러가 여러 서비스에 걸쳐 전파될 때 `trace_id`로 요청 흐름을 재구성하면 근본 원인 서비스를 특정할 수 있다.

구현은 CLIAR-238(commit `4b43a93`, PR #11)로 먼저 이뤄졌다. 그 세션은 이를 ADR-0007 + ADR-0002 결정 #8의 연장으로 보아 별도 ADR을 두지 않았으나, 결정 이력을 남기기 위해 이 ADR을 소급 작성한다.

## 검토한 대안

| 항목 | 대안 | 비고 |
|---|---|---|
| trace 조회 tool | 단일 `query_tempo` — 임의 Tempo API 경로/응답을 그대로 반환 | 검색(TraceQL 입력)과 상세(traceID 입력)는 입력·출력 형태가 완전히 달라 한 tool로 묶으면 프롬프트가 모호해짐 |
| | `search_traces` + `get_trace` 2개로 분리 | 채택 — "조건으로 후보 trace 찾기 → 하나를 골라 상세 분석" 흐름을 tool 경계로 그대로 표현 |
| trace 상세 반환 형태 | Tempo `/api/traces/<id>` 원본 OTLP JSON을 그대로 반환 | span 하나가 수십 KB, trace 하나가 수만 토큰 — Bedrock 컨텍스트/비용이 폭증하고 truncate하면 뒷부분 span이 잘림 |
| | span 트리 텍스트로 요약 (service/name/duration/status + 에러 span의 exception) | 채택 — 원인 분석에 필요한 정보만 남기고 8000자 상한에 안정적으로 들어옴 |
| Tempo 접근 경로 | Grafana의 Tempo 프록시 API 경유 | Grafana 인증 필요, 불필요한 홉 |
| | Tempo HTTP API를 클러스터 내부 DNS로 직접 호출 | 채택 — Prometheus/Loki와 동일 패턴 |

## 결정

1. **RCA Agent에 Tempo를 세 번째 조회 소스로 추가한다.** tool 2개:
   - `search_traces(traceql, lookback_minutes, limit)` — Tempo `/api/search`에 TraceQL 검색, 조건에 맞는 traceID·루트 서비스/이름·소요시간 목록 반환.
   - `get_trace(trace_id)` — Tempo `/api/traces/<id>` 응답을 span 트리 텍스트로 요약 반환.
2. **Tempo 접근은 무인증 클러스터 내부 DNS**(`TEMPO_URL` = `http://tempo.monitoring.svc.cluster.local:3200`, `monitoring/rca-agent/k8s/configmap.yaml`). ADR-0002 결정 #8의 "네임스페이스 내부 통신 전제, 별도 인증 없음"을 Tempo로 연장한다. Tempo는 read 전용 HTTP API이고 Bedrock IAM과 무관하므로 **IRSA/RBAC 변경 없음**. `deployment.yaml`은 `envFrom: configMapRef`라 변경 불필요.
3. **`get_trace`는 원본 OTLP JSON을 반환하지 않고 span 트리로 요약한다.** span별 service/name/duration/status + 에러 span의 exception type·message만 남긴다. 상한: `_MAX_RESULT_CHARS`(8000자), `_MAX_SPANS_RENDERED`(80 span), span 메시지 300자. 다른 tool과 동일하게 실패 시 예외 대신 실패 문자열을 반환한다(부분 실패 허용).
4. **system prompt가 알림별 trace 사용 시점을 안내한다.**
   - `p99 레이턴시 초과`: `search_traces`로 `{ resource.service.name="<svc>" && duration > <threshold> }` → `get_trace`로 소요시간을 지배하는 child span 특정.
   - `HTTP 5xx 에러율 초과`: `search_traces`로 `{ status = error }` / `{ span.http.status_code >= 500 }` → 실패 span의 exception으로 원인 특정.
   - `로그 ERROR 급증`: 에러 로그의 `trace_id`로 `get_trace` 피벗 (앱 로그가 메시지를 누락해도 span exception에는 원문이 남음).
5. **TraceQL의 `resource.service.name`이 Prometheus `application`·Loki `app` 라벨과 다를 수 있으므로**, 먼저 로그/메트릭으로 서비스명을 확인한 뒤 검색하도록 프롬프트에 명시한다. (세 값을 서비스 저장소에서 일치시키는 것은 별도 과제 — `.harness/PLAN.md`.)

## 결과

- `monitoring/rca-agent/src/analyzer.py`: `search_traces`/`get_trace` tool과 `_summarize_trace`/`_attrs_to_dict`/`_attr_value` 헬퍼 추가, `analyze()`의 `tools` 3개 → 5개, system prompt에 Tempo 도구·알림별 trace 단계 추가.
- `monitoring/rca-agent/src/config.py`·`monitoring/rca-agent/k8s/configmap.yaml`: `TEMPO_URL` 추가.
- 검증(CLIAR-238): `python -m py_compile` 통과. dev Tempo에서 받은 실제 cross-service trace(73 span, exception 이벤트 포함)로 `_summarize_trace` 렌더링 확인 — `UnrecognizedClientException`이 span 트리에 그대로 드러남. `search_traces`의 `{ status = error }` 실검색 정상. `kubectl kustomize monitoring/rca-agent/k8s`에 `TEMPO_URL` 반영 확인.
- 실사용 검증(실제 알림 발화 시 Agent가 trace를 근거에 포함하는지)은 `.harness/PLAN.md` "RCA Agent 후속 개선"에 남아 있다.

## 미결정 (추후 논의 필요)

- **Tempo retention이 dev 24h**라, 알림이 `repeat_interval`(4h) 후 재분석될 때 원본 trace가 이미 만료됐을 수 있다. prod에서 retention을 재검토한다 (ADR-0007 미결정 항목과 연결).
- **`search_traces`의 `lookback_minutes` 기본 60분**이 알림의 `for` 지속시간 + 평가 주기와 어긋날 수 있다 — 실사용 후 튜닝.
- trace 기반 알림 규칙(Tempo metrics-generator의 span RED/service graph metrics)은 이번 범위 밖. 현재 `monitoring/tempo/values.yaml`은 dev single-binary 최소 구성이라 generator 미활성 — `.harness/PLAN.md` 참고.
