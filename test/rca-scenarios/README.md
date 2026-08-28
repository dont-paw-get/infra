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
- Bedrock `anthropic.claude-sonnet-5` 모델 액세스가 활성화되어 있어야 `crashloop-firing` 단계가 통과한다.
  (미활성 시 Agent 로그에 `AccessDeniedException` — 그 자체로 "모델 액세스 미승인"을 확인하는 결과)

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
   ./send-webhook.sh resolved           # -> {"received":1}
   ```

4. firing 페이로드 — 전 구간:
   ```
   ./send-webhook.sh crashloop-firing   # -> {"received":1} (응답까지 수십 초 걸릴 수 있음)
   ```

5. Agent 로그로 흐름 확인:
   ```
   kubectl -n monitoring logs -l app=rca-agent --tail=120
   ```
   `analyze()` 진입 → `query_prometheus_range` / `query_loki` 등 도구 호출 → Bedrock 응답이 보여야 한다.

6. Discord 채널에서 `RCA: 파드 CrashLoopBackOff` 임베드 메시지 도착 확인.

### Windows PowerShell 주의

`Invoke-RestMethod -InFile`은 Windows PowerShell 5.1에서 페이로드의 한글(`파드 CrashLoopBackOff`)을
UTF-8로 전송하지 않아 서버의 `request.json()` 파싱이 깨진다(500). **`curl.exe`를 쓸 것**
(PowerShell의 `curl` 별칭이 아니라 `curl.exe`로 명시):

```powershell
curl.exe -sS -X POST http://localhost:8080/webhook `
  -H "Content-Type: application/json" `
  --data "@payloads/crashloop-firing.json" --max-time 300
```

### 예상 한계

`rca-test` 네임스페이스/파드는 실재하지 않으므로 Agent의 Prometheus/Loki 쿼리는 빈 결과를 돌려준다.
따라서 보고서는 "관련 메트릭/로그 없음, 원인 확정 불가" 수준이다 — 파이프라인 검증에는 충분하다.
의미 있는 분석 품질은 Phase 2(실제 장애 주입)에서 확인한다.

### 비용

`crashloop-firing` 1회 = Bedrock(Claude Sonnet 5) 분석 1회 ≈ 수십 센트. `resolved`는 0.
반복 실행하지 않으면 부담 없다.

## Phase 2 — 실제 장애 주입 E2E

아직 미구현. `.harness/PLAN.md`의 "RCA Agent 테스트 > Phase 2" 참고. 별도 컨펌 후 진행.
