# RCA Agent 테스트

`monitoring/rca-agent/`의 RCA Agent가 Grafana Alerting webhook을 받아 원인 분석 후
Discord에 후속 메시지를 보내는 파이프라인을 검증한다. 배경은 `docs/adr/0002-anomaly-rca-agent.md`.

이 디렉터리는 ArgoCD/CI(`monitoring/**` 트리거) 대상이 아니다 — 수동으로만 실행한다.

## Phase 1 — 합성 webhook 스모크 테스트 (클러스터 무변경)

실제 장애 워크로드 없이, Grafana ngalert webhook 페이로드를 Agent의 `/webhook`에 직접 POST한다.
클러스터 상태를 바꾸지 않으므로 정리할 것이 없다.

### 사전 조건

- `rca-agent` 파드가 Running/Ready:
  ```
  kubectl -n monitoring get pods -l app=rca-agent
  ```
  `ImagePullBackOff`/`CrashLoopBackOff`면 여기서 멈추고 파드 로그부터 확인한다.
- Bedrock inference profile `global.anthropic.claude-sonnet-5` 모델 액세스가 활성화되어 있어야
  `crashloop-firing` 단계가 통과한다 (`monitoring/rca-agent/k8s/configmap.yaml`의 `BEDROCK_MODEL_ID`와 일치).
  (미활성 시 Agent 로그에 `AccessDeniedException` — 그 자체로 "모델 액세스 미승인"을 확인하는 결과)
- Tempo/OTel Collector 스택(`monitoring/tempo`, `monitoring/otel-collector`)이 배포돼 있고
  Agent가 `search_traces`/`get_trace` tool을 갖는다(CLIAR-207/238). 합성 페이로드에는 실제 trace가
  없으므로 이 tool은 빈 결과를 돌려주지만, tool 배선과 예외 처리 검증에는 그것으로 충분하다.

### 실행

실행 전 `kubectl config current-context`가 관측 스택이 있는 클러스터(`dpyb-dev`)를 가리키는지 확인.

1. 별도 터미널에서 port-forward:
   ```
   kubectl -n monitoring port-forward svc/rca-agent 8080:8080
   ```

2. 헬스 체크:
   ```
   curl -sS localhost:8080/healthz      # -> {"status":"ok"}
   ```

3. resolved 페이로드 — firing 필터가 걸러내는지 (Bedrock 호출·Discord 메시지 없음):
   ```
   ./send-webhook.sh resolved           # -> {"received":1,"queued":0}
   ```

4. firing 페이로드 — 전 구간:
   ```
   ./send-webhook.sh crashloop-firing   # -> {"received":1,"queued":1} (응답까지 수십 초 걸릴 수 있음)
   ```
   트레이스 tool 경로까지 확인하려면 `HTTP 5xx 에러율 초과` 페이로드도 보낸다 — system prompt가
   이 알림에서 `search_traces`/`get_trace`를 호출하도록 안내한다:
   ```
   ./send-webhook.sh http-5xx-firing    # -> {"received":1,"queued":1}
   ```

5. Agent 로그로 흐름 확인:
   ```
   kubectl -n monitoring logs -l app=rca-agent --tail=120
   ```
   `analyze()` 진입 → 도구 호출(`query_prometheus_range` / `query_loki`, 5xx 페이로드면
   `search_traces` / `get_trace`도) → Bedrock 응답이 보여야 한다.

6. Discord 채널에서 `RCA: 파드 CrashLoopBackOff`(및 `RCA: HTTP 5xx 에러율 초과`) 임베드 메시지 도착 확인.

### Windows PowerShell 주의

`Invoke-RestMethod -InFile`은 Windows PowerShell 5.1에서 페이로드의 한글(`파드 CrashLoopBackOff`)을
UTF-8로 전송하지 않아 서버의 `request.json()` 파싱이 깨진다(500). **`curl.exe`를 쓸 것**
(PowerShell의 `curl` 별칭이 아니라 `curl.exe`로 명시):

```powershell
curl.exe -sS -X POST http://localhost:8080/webhook `
  -H "Content-Type: application/json" `
  --data "@payloads/crashloop-firing.json" --max-time 300
```

### 트레이스 (Tempo)

CLIAR-207로 관측 스택에 OTel Collector + Tempo가 추가됐고, CLIAR-238로 Agent가
`search_traces`(TraceQL 검색) / `get_trace`(trace_id 하나의 span 트리 요약) tool을 갖게 됐다.

- Phase 1(합성 페이로드)에는 대응하는 실제 trace가 없다. `http-5xx-firing` 페이로드를 보내면
  Agent가 `search_traces { status = error }`를 시도하지만 `조건에 맞는 trace가 없습니다`를 받는다 —
  tool이 예외 없이 실패 문자열을 반환하고 분석이 계속되는지(부분 실패 허용)를 확인하는 것이 목적이다.
- 실제 trace를 근거로 쓰는지는 Phase 2에서 서비스 저장소 계측(`OTEL_EXPORTER_OTLP_ENDPOINT`,
  JSON 로그 `trace_id`)이 붙은 뒤 레이턴시/5xx 시나리오로 확인한다 — `.harness/PLAN.md` 참고.
- 로그↔트레이스 연결(로그 상세의 `trace_id` → Tempo trace 이동)은 Grafana에서 직접 확인한다
  (`.harness/PLAN.md` "CLIAR-207 tracing stack 배포 후 검증").

### 예상 한계

`rca-test`/`rca-test-svc` 네임스페이스·서비스는 실재하지 않으므로 Agent의 Prometheus/Loki/Tempo
쿼리는 모두 빈 결과를 돌려준다. 따라서 보고서는 "관련 메트릭/로그/trace 없음, 원인 확정 불가"
수준이다 — 파이프라인·tool 배선 검증에는 충분하다. 의미 있는 분석 품질은 Phase 2(실제 장애 주입)에서 확인한다.

### 비용

firing 페이로드 1회 = Bedrock(Claude Sonnet 5) 분석 1회 ≈ 수십 센트. `resolved`는 0.
반복 실행하지 않으면 부담 없다.

## Phase 2 — 실제 장애 주입 E2E

시나리오 A~D 검증 완료(2026-08-29). 절차와 시나리오 매니페스트는 `phase2/README.md` 참고.
트레이스를 근거로 쓰는 레이턴시/5xx 시나리오 추가는 서비스 저장소 계측 후 — `.harness/PLAN.md`.
