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

## RCA Agent 테스트 — Phase 2 (실제 장애 주입 E2E) — A·B 완료, C·D 진행 중

Phase 1(합성 webhook)은 완료 — `.harness/STATE.md` 참고. 산출물은 `test/rca-scenarios/phase2/`(A~D + README).
사용자 결정(2026-08-28): 시나리오 A/B/C/D 전부, 브랜치 `CLIAR-159` 재사용.

진행 과정에서 관측 스택 버그 4건이 드러나 먼저 고쳤다 — 경위는 `.harness/DECISIONS.md` 2026-08-29 항목 3개 참고:
알림 규칙 미로드(`relativeTimeRange`, PR #5) → contact point 결합(PR #6/#7) → Agent 블로킹 호출(PR #7) → argocd ApplicationSet CRD 누락(클러스터 조치).

**시나리오 결과**
- [x] **A (CrashLoopBackOff)** — 알림 `Pending`→`Alerting` 발화, webhook 수신, `query_prometheus_range`/`query_loki` 호출 후 분석 생성. `fatal: simulated crash, exiting non-zero` 로그와 재시작 추세(2→6)를 근거로 제시, 테스트 파드임까지 인지. 정리 완료
- [x] **B (OOMKilled)** — 발화·분석 정상. `kube_pod_container_resource_limits`로 32MiB limit 확인, `allocating memory until OOM` 로그 인용, `container_memory_working_set_bytes`가 빈 이유(이미 종료돼 수집 안 됨)까지 추론. 정리 완료
- [ ] **D (PVC 사용률)** — 2026-08-29 투입, PVC `Bound`·filler Job Running. `for: 10m` + interval 5m라 발화까지 15~20분. 결과 확인 후 `kubectl delete -f D-pvc-usage.yaml`
- [ ] **C (로그 ERROR 급증)** — 아래 log-error-spike 수정이 배포된 뒤 실행

**log-error-spike 규칙 수정 (버그 3) — 배포 대기**
RCA Agent가 `DatasourceError` 알림을 분석하며 원인을 정확히 짚었다: `looks like time series data, only reduced data can be alerted on.`
Loki 쿼리는 `instant: true`여도 시계열을 돌려주므로 threshold에 직결할 수 없다.
- [x] `monitoring/alerting/rules/log-error-spike.yaml`에 reduce 단계 추가 — `A(loki) → B(reduce/last) → C(threshold on B)`, `condition: C`. `kubectl kustomize` 렌더링 확인
- [ ] 병합 → ArgoCD `grafana-alerting` sync → 규칙 `health: ok` 확인(현재 `error`) → 시나리오 C 실행

**마무리**
- [ ] 전부 끝나면 `kubectl delete ns rca-test`, 결과를 `.harness/STATE.md`에 반영하고 이 섹션 제거

## RCA 실패 재시도 정책 (ADR-0002 미결정)

- [ ] 가시화는 2026-08-29 해소됨(`analyze()` 실패 시 Discord에 "RCA 분석 실패" 전송). 남은 건 **재시도** — 실패한 분석을 다시 돌릴 방법이 없다. Grafana `repeat_interval: 4h`에 기대는 것 외에 Agent 자체 재시도(백오프)를 둘지 논의 필요

## dev 클러스터 배포 검증 (부트스트랩 중 실제 발견된 이슈)

2026-08-28 사용자 확인: `loki`를 제외한 모든 Application이 `Synced`/`Healthy`. 자세한 진단 경위는 `.harness/STATE.md`/`DECISIONS.md` 참고.

- [ ] `monitoring/loki/values.yaml`의 `compactor.delete_request_store: s3` 수정을 `develop`에 병합한 뒤, ArgoCD `loki` Sync → `kubectl -n monitoring get pod loki-0`가 `Running 2/2`로 전환되는지 확인. 아직 병합 전이라 `loki-0`는 계속 `CrashLoopBackOff` 상태다
- [ ] `loki-0`가 Running이 된 뒤 S3 접근이 실제로 되는지 확인 — IAM Role `arn:aws:iam::594532711953:role/dpgy-infra-loki`(IRSA) 생성 여부가 아직 검증되지 않았다. `kubectl -n monitoring logs loki-0 -c loki | grep -i "s3\|credential\|denied"`

## 서비스 저장소 연동

- [ ] `ServiceMonitor`/`PodMonitor` CR을 실제로 각 서비스 저장소(`backend-book` 등)에 추가하도록 해당 팀에 전달 (이 저장소 범위 밖 — ADR-0001 참고)
- [ ] Book Service 등 서비스 쪽 계측(Micrometer `/actuator/prometheus` 노출, 구조화 로깅) 준비 여부 확인
- [ ] 위 계측이 붙으면 `http-error-rate`/`latency` 알림(현재 `monitoring/alerting/kustomization.yaml`에서 배포 제외)을 다시 configMapGenerator에 추가
