# PLAN

아직 끝나지 않은 계획과 체크리스트만 남긴다. 완료되면 항목을 지우고 `.harness/STATE.md`에 단계 한 줄로 반영한다.
배경/근거는 각 항목에 표시된 파일 참고 (주로 `docs/adr/0001-observability-stack.md`).

## Grafana HTTPS 전환 (도메인/ACM 인증서 확보 후)

ALB Ingress로 노출은 확정했지만(2026-08-26, 사용자 확인) 도메인/ACM 인증서가 없어 현재 HTTP만 열려 있다.

- [ ] 도메인 확보 후 `monitoring/kube-prometheus-stack/values.yaml`의 `grafana.ingress.hosts`에 실제 도메인 채우기
- [ ] ACM에서 해당 도메인 인증서 발급 (도메인 소유권/DNS 검증 필요, 이 저장소 범위 밖)
- [ ] 인증서 발급 후 `annotations`에 `alb.ingress.kubernetes.io/certificate-arn`, `alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}, {"HTTPS": 443}]'`, `alb.ingress.kubernetes.io/ssl-redirect: "443"` 추가
- [ ] SSO 연동이 필요해지면 별도로 재검토 (현재는 Grafana 기본 admin 계정 로그인만 사용하기로 확정)

## 알림 규칙 튜닝

- [ ] 트래픽 규모 파악 후 threshold 재조정 (현재 러프한 초기값):
  - `monitoring/alerting/rules/http-error-rate.yaml` — 5xx 에러율 5% (현재 배포 제외 상태, 아래 "서비스 저장소 연동" 참고)
  - `monitoring/alerting/rules/latency.yaml` — p99 레이턴시 1초 (현재 배포 제외 상태, 아래 "서비스 저장소 연동" 참고)
  - `monitoring/alerting/rules/pvc-usage.yaml` — PVC 사용률 85%
  - `monitoring/alerting/rules/log-error-spike.yaml` — 분당 ERROR 로그 5건
- [ ] 알림이 늘어나면 `monitoring/alerting/policies/notification-policy.yaml`의 단일 라우팅을 서비스/심각도별로 세분화

## 이상탐지/근본원인분석(RCA) Agent 도입 (스캐폴딩 + IRSA 완료 — 프롬프트 다듬기·이미지 파이프라인 대기)

Strands SDK(AWS) + Amazon Bedrock으로 Grafana Alerting 발화를 트리거 받아 RCA를 수행하고 Discord에 보고하는 Agent를 `monitoring` 네임스페이스(공유 인프라)에 추가했다. 결정 근거와 배경은 `docs/adr/0002-anomaly-rca-agent.md` 참고.

**남은 작업**
- [ ] Bedrock에서 `anthropic.claude-sonnet-5` 최초 호출 전 Anthropic use case 양식 제출 확인 — AWS가 2025-10 Model access 콘솔 페이지를 폐지, 모델은 첫 호출 시 자동 활성화되나 Anthropic 모델만 예외로 `PutUseCaseForModelAccess`(1회성 양식) 제출이 필요함. Bedrock 콘솔 Model catalog > Claude Sonnet 5 > Playground에서 첫 메시지를 보내 양식 제출/확인
  - 2026-08-26: 사용자 계정에 현재 권한 없음 확인 — 관리자에게 권한 요청 예정, 응답 대기 중 (blocked)
- [ ] (백로그) k8s 이벤트/describe pod 조회 tool 추가 — CrashLoopBackOff/OOMKilled 원인(재시작 사유, 리소스 limit 초과 등) 파악에 유용하나, `rca-agent-irsa` ServiceAccount에 새 Kubernetes RBAC(get/list pods, events) 부여가 필요해 별도 논의 후 진행. 현재는 Prometheus/Loki만 조회하는 순수 read 권한만 있음
- [ ] Agent 장애/타임아웃 시 재시도·알림 정책 (RCA 실패를 어떻게 가시화할지) — ADR-0002 미결정 항목

## RCA Agent 테스트

배경: `docs/adr/0002-anomaly-rca-agent.md`, Agent 코드 `monitoring/rca-agent/src/`.
산출물 위치: 신규 최상위 `test/rca-scenarios/` (ArgoCD/CI `monitoring/**` 트리거 밖, 수동 실행).
Bedrock `anthropic.claude-sonnet-5` 모델 액세스 확보됨(사용자 확인 2026-08-28).

### Phase 1 — 합성 webhook 스모크 테스트 (지금, 클러스터 무변경)

실제 장애 워크로드 없이, Grafana Alerting webhook 페이로드를 `rca-agent`의 `/webhook`에 직접 POST해서
webhook 수신 → firing 필터 → `analyze()` → Bedrock → Discord 후속 메시지까지 파이프라인이 도는지만 확인한다.
장애를 주입하지 않으므로 클러스터 상태 변화·정리 부담이 없다.

**디렉터리 (`test/rca-scenarios/`)**
- `README.md` — 실행 순서, 사전 조건, 비용 주의
- `payloads/crashloop-firing.json` — `alertname: 파드 CrashLoopBackOff`, 존재하지 않는 `rca-test` 네임스페이스/파드 라벨(클러스터에 영향 0). Grafana ngalert webhook 형식
- `payloads/resolved.json` — 같은 알림의 `status: resolved` — firing 필터가 skip하는지 확인용 (Bedrock 호출 0)
- `send-webhook.sh` — `kubectl -n monitoring port-forward svc/rca-agent 8080:8080` 전제로 `payloads/<이름>.json`을 POST (`bash`; README에 PowerShell `Invoke-RestMethod` 대안 병기)

**절차 (사용자가 실행)**
- [ ] `kubectl -n monitoring get pods -l app=rca-agent` — Running/Ready 확인 (이미지 pull 실패·CrashLoop 아닌지)
- [ ] `kubectl -n monitoring port-forward svc/rca-agent 8080:8080` (별도 터미널)
- [ ] `curl -sS localhost:8080/healthz` → `{"status":"ok"}`
- [ ] `./send-webhook.sh resolved` → 응답 `{"received":1}`, agent 로그에 skip, Discord 메시지 없음
- [ ] `./send-webhook.sh crashloop-firing` → 응답 `{"received":1}`, agent 로그에 `analyze()`·도구 호출·Bedrock 응답, Discord에 `RCA: 파드 CrashLoopBackOff` embed 도착
- [ ] `kubectl -n monitoring logs -l app=rca-agent --tail=120` 로 전체 흐름 확인

**예상 한계**: `rca-test` 네임스페이스에 실제 메트릭/로그가 없어 도구 쿼리는 빈 결과 → 보고서는 "데이터 없음, 원인 확정 불가" 수준. 파이프라인 검증엔 충분하고, 의미 있는 RCA 품질은 Phase 2에서 본다.

**Phase 1 실행 결과 (2026-08-28, dev 클러스터)**
- `/healthz` 200 OK 확인.
- `crashloop-firing` POST → webhook 수신 → `analyze()` → Strands → Bedrock `ConverseStream`까지 도달. **IRSA 인증·Bedrock 권한·webhook→analyze 경로 정상**.
- 단, Bedrock이 `ValidationException`: `Invocation of model ID anthropic.claude-sonnet-5 with on-demand throughput isn't supported. Retry ... with the ID or ARN of an inference profile`. → 아래 "발견된 이슈" 참고. 예외가 핸들러까지 전파돼 `/webhook`이 500, Discord 후속 메시지는 아직 미확인.
- `resolved` POST의 500은 별도 확인 필요(인코딩 의심 — Windows PowerShell `-InFile`). 모델 ID 수정 후 `curl.exe`로 재확인.

**발견된 이슈 — Bedrock 모델 ID는 inference profile이어야 함 (수정 적용됨, 배포·재테스트 대기)**

경위·결정은 `.harness/DECISIONS.md` 2026-08-28 항목 참고. `ap-northeast-2`엔 `global.anthropic.claude-sonnet-5` 하나뿐.
- [x] `monitoring/rca-agent/k8s/configmap.yaml` `BEDROCK_MODEL_ID` → `global.anthropic.claude-sonnet-5` (사용자 편집)
- [x] IAM Role `dpgy-infra-rca-agent` 정책을 inference profile + 라우팅 FM으로 확장 (사용자, AWS Console)
- [x] `docs/adr/0002` 결과/IRSA 서술, `.harness/DECISIONS.md`, `.harness/ARCHITECTURE.md` RCA Agent 섹션 갱신
- [x] `kubectl kustomize monitoring/rca-agent/k8s` 렌더링 확인 (`BEDROCK_MODEL_ID: global.anthropic.claude-sonnet-5`)
- [ ] 커밋(브랜치 `CLIAR-159-...`) → PR → `develop` 병합 → CI(`monitoring/**`) 이미지 재빌드 + `kustomization.yaml` newTag 갱신 → ArgoCD `rca-agent` sync로 파드 재기동
- [ ] 재기동 후 `curl.exe`로 `crashloop-firing` 재전송 → 로그에 Bedrock 응답 + `notifier` 전송, Discord에 `RCA: 파드 CrashLoopBackOff` embed 확인
- [ ] `resolved` POST 500 재현되는지 `curl.exe`로 재확인 (PowerShell `-InFile` 인코딩 문제였는지 판별)

즉시 검증이 필요하면 병합 전 라이브 패치도 가능: `kubectl -n monitoring set env deployment/rca-agent BEDROCK_MODEL_ID=global.anthropic.claude-sonnet-5`

**검증 (배포 전)**
- [x] `send-webhook.sh` `bash -n`, `payloads/*.json` `python -m json.tool` 문법 검증
- [x] `kubectl kustomize monitoring/rca-agent/k8s` 렌더링 확인

**함께 갱신**
- [x] `README.md` "구조"에 `test/rca-scenarios/` 한 줄 추가
- [ ] 재테스트 완료 후 → `.harness/STATE.md` 한 줄, `.harness/HANDOFF.md` 세션 로그, 이 Phase 1 블록 정리

### Phase 2 — 실제 장애 주입 E2E (나중, 별도 컨펌)

`rca-test` 네임스페이스에 의도적 장애 워크로드를 배포해 실제 알림 발화 → Discord 원본 알림 + RCA 후속 메시지를 확인.
시나리오: CrashLoopBackOff / OOMKilled / 로그 ERROR 급증 / PVC 사용률. 상세는 Phase 1 완료 후 이 섹션에 구체화한다.

**Phase 2 비용/리스크 (미리 검토됨)**
- Bedrock 호출이 유일한 유의미 비용. 분석 1회당 수십 센트, 전체 1회 통과 시 대략 $1~3.
- 진짜 위험은 정리 누락 — 워크로드를 `delete` 안 하면 알림이 계속 firing → `repeat_interval: 4h`마다 재분석.
- OOMKill은 OOMKilled + CrashLoopBackOff 둘 다 발화 가능(분석 2회). `pvc-usage` expr은 네임스페이스 필터가 없어 클러스터 전체 PVC 대상 — 사전에 85% 넘는 PVC 없는지 확인.
- `로그 ERROR 급증`은 `loki-0` Running 전제(현재 CrashLoopBackOff — `.harness/HANDOFF.md`).
- 티켓 번호 필요(브랜치 `{티켓}-rca-테스트`).

## dev 클러스터 배포 검증 (부트스트랩 중 실제 발견된 이슈)

2026-08-28 사용자 확인: `loki`를 제외한 모든 Application이 `Synced`/`Healthy`. 자세한 진단 경위는 `.harness/STATE.md`/`DECISIONS.md` 참고.

- [ ] `monitoring/loki/values.yaml`의 `compactor.delete_request_store: s3` 수정을 `develop`에 병합한 뒤, ArgoCD `loki` Sync → `kubectl -n monitoring get pod loki-0`가 `Running 2/2`로 전환되는지 확인. 아직 병합 전이라 `loki-0`는 계속 `CrashLoopBackOff` 상태다
- [ ] `loki-0`가 Running이 된 뒤 S3 접근이 실제로 되는지 확인 — IAM Role `arn:aws:iam::594532711953:role/dpgy-infra-loki`(IRSA) 생성 여부가 아직 검증되지 않았다. `kubectl -n monitoring logs loki-0 -c loki | grep -i "s3\|credential\|denied"`

## 서비스 저장소 연동

- [ ] `ServiceMonitor`/`PodMonitor` CR을 실제로 각 서비스 저장소(`backend-book` 등)에 추가하도록 해당 팀에 전달 (이 저장소 범위 밖 — ADR-0001 참고)
- [ ] Book Service 등 서비스 쪽 계측(Micrometer `/actuator/prometheus` 노출, 구조화 로깅) 준비 여부 확인
- [ ] 위 계측이 붙으면 `http-error-rate`/`latency` 알림(현재 `monitoring/alerting/kustomization.yaml`에서 배포 제외)을 다시 configMapGenerator에 추가
