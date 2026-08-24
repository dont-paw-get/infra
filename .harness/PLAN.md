# PLAN

아직 끝나지 않은 계획과 체크리스트만 남긴다. 완료되면 항목을 지우고 `.harness/STATE.md`에 단계 한 줄로 반영한다.
배경/근거는 각 항목에 표시된 파일 참고 (주로 `docs/adr/0001-observability-stack.md`).

## 스토리지 / 보존 기간

- [ ] Prometheus 데이터 보존 기간·PVC 용량 확정 (현재 `monitoring/kube-prometheus-stack/values.yaml`의 `retention: 15d`, `storage: 20Gi`는 임시값)
- [ ] Loki 데이터 보존 기간·오브젝트 스토리지(S3 등) 연동 여부 확정 (현재 `monitoring/loki/values.yaml`의 `retention_period: 336h`(14d), `storage.type: filesystem`은 임시값)

## Grafana 노출 / 인증

- [ ] Grafana 외부 노출 방식(Ingress) 결정 — 도메인, TLS
- [ ] Grafana 접근 제어/인증 방식 결정 (SSO 연동 여부 등)
- [ ] 위 결정 후 `monitoring/kube-prometheus-stack/values.yaml`의 `grafana.ingress.enabled: false`를 실제 설정으로 교체

## 시크릿 관리

- [ ] 수동 `.env` + `kubectl create secret` 방식(현재) 대신 External Secrets Operator 등 도입할지 결정
- [ ] CI/CD 파이프라인에서 시크릿을 어떻게 주입할지 결정 (예: GitHub Actions secrets → `kubectl`/`scripts/install.sh` 연동)

## 알림 규칙 튜닝

- [ ] 트래픽 규모 파악 후 threshold 재조정 (현재 러프한 초기값):
  - `monitoring/alerting/rules/http-error-rate.yaml` — 5xx 에러율 5%
  - `monitoring/alerting/rules/latency.yaml` — p99 레이턴시 1초
  - `monitoring/alerting/rules/pvc-usage.yaml` — PVC 사용률 85%
  - `monitoring/alerting/rules/log-error-spike.yaml` — 분당 ERROR 로그 5건
- [ ] 알림이 늘어나면 `monitoring/alerting/policies/notification-policy.yaml`의 단일 라우팅을 서비스/심각도별로 세분화

## 이상탐지/근본원인분석(RCA) Agent 도입 (결정 완료 — ADR 작성 대기)

Strands SDK(AWS) + Amazon Bedrock으로 Grafana Alerting 발화를 트리거 받아 RCA를 수행하고 Discord에 보고하는 Agent를 `monitoring` 네임스페이스(공유 인프라)에 추가한다. 결정 근거와 배경은 `docs/adr/0002-anomaly-rca-agent.md` 참고.

**남은 작업 (구현 단계)**
- [ ] Grafana Alerting에 Agent용 webhook 통합 추가 (기존 `discord-webhook` contact point에 webhook 통합 추가하는 방식으로 시작, 문제 생기면 별도 contact point로 분리)
- [ ] Agent 배포 스캐폴딩: Strands SDK 애플리케이션 소스 + Dockerfile + K8s manifest/Helm values (`monitoring` 네임스페이스)
- [ ] IRSA 설정 (ServiceAccount ↔ IAM Role ↔ Bedrock 권한) — EKS 클러스터의 OIDC 프로바이더 정보 필요
- [ ] Agent → Prometheus/Loki 내부 접근: 기존 Alloy와 동일하게 클러스터 내부 서비스 DNS로 접근 (별도 인증 없음, 네임스페이스 내부 통신)

## GitOps 전환: ArgoCD 도입 (구현 완료 — 부트스트랩 전 남은 값 채우기만 대기)

결정/구현 내역은 `docs/adr/0003-argocd-gitops.md` 참고. `backend-auth` 저장소(ArgoCD+Kustomize, `targetRevision: develop`, `finalizers`)의 실제 컨벤션을 확인하고 동일하게 맞췄다.

**부트스트랩(최초 클러스터 적용) 전 채워야 하는 값**
- [ ] `monitoring/argocd/external-secrets.yaml`, `kube-prometheus-stack.yaml`, `loki.yaml`의 `targetRevision: "<CHART_VERSION>"`을 실제 Helm 차트 버전으로 고정 (`helm search repo <chart>`로 최신 안정 버전 확인)
- [ ] `monitoring/external-secrets/service-account.yaml`의 `eks.amazonaws.com/role-arn: "arn:aws:iam::<ACCOUNT_ID>:role/dpgy-infra-external-secrets"`를 실제 AWS 계정 ID로 교체 — RCA Agent(ADR-0002)의 IRSA와 함께 한 번에 정리 권장
- [ ] AWS Secrets Manager에 `dpgy-infra/grafana-admin-credentials`(JSON: admin-user/admin-password), `dpgy-infra/discord-webhook`(plaintext) 시크릿 값 생성 (AWS 콘솔/CLI, 이 저장소 범위 밖)
- [ ] `helm template`으로 `monitoring/kube-prometheus-stack/values.yaml` 렌더링 검증 — 로컬에 Helm CLI가 없어 이번 세션에서는 YAML 문법 검증만 수행함 (`kubectl kustomize`로 alerting Kustomize는 렌더링 검증 완료)

**추후 논의 (착수를 막지 않음)**
- [ ] 서비스 저장소(`backend-book` 등)까지 이 저장소의 ArgoCD Application으로 관리할지, 별도로 둘지

## 서비스 저장소 연동

- [ ] `ServiceMonitor`/`PodMonitor` CR을 실제로 각 서비스 저장소(`backend-book` 등)에 추가하도록 해당 팀에 전달 (이 저장소 범위 밖 — ADR-0001 참고)
- [ ] Book Service 등 서비스 쪽 계측(Micrometer `/actuator/prometheus` 노출, 구조화 로깅) 준비 여부 확인
