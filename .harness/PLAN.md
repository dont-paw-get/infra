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

## GitOps 전환: ArgoCD 도입 (결정 완료 — 계획 초안, 구현 착수 전 컨펌 대기)

결정 사항 (사용자 확인 완료):
- ArgoCD 자체 설치는 이 저장소 범위 밖 — 클러스터에 이미 준비됨/별도 관리
- Application 매니페스트는 이 저장소 안에 두되, App-of-Apps 루트 없이 **개별(flat) 등록** — 릴리스별 Application CR을 각각 직접 `kubectl apply`(최초 1회)로 등록
- Sync 정책: automated (self-heal + prune)
- 시크릿(Discord 웹훅 URL, Grafana admin 비밀번호)은 External Secrets Operator를 도입해 선언적으로 관리 — `.env` + `install.sh` 수동 생성 방식 폐지
- 서비스 저장소(`backend-book` 등)도 추후 ArgoCD로 전환할 계획 (범위·시점은 별도 논의 — 아래 미결정 참고). Flat으로 시작하지만 앱 개수가 늘어나면 ApplicationSet 전환도 후보 (지금은 3개 릴리스라 불필요)

**구현 체크리스트 (초안)**
- [ ] `docs/adr/0003-argocd-gitops.md` 작성 — ADR-0001의 "GitOps 도구 도입 여부"·"시크릿 관리 방식" 미결정 항목을 이 결정으로 해소, flat Application 등록 방식 선택 근거 포함
- [ ] External Secrets Operator 도입: `SecretStore`/`ClusterSecretStore` 연동 대상(AWS Secrets Manager 등) 확정 → `monitoring/`에 `ExternalSecret` 리소스 추가해 `grafana-admin-credentials`, `discord-webhook` Secret을 대체
- [ ] 알림 provisioning YAML(`monitoring/alerting/*/*.yaml`)의 `${DISCORD_WEBHOOK_URL}` envsubst 치환 방식을 ExternalSecret 참조로 교체
- [ ] `monitoring/argocd/`에 릴리스별 Application CR 3종 작성 (`kube-prometheus-stack.yaml`, `loki.yaml`, `alloy.yaml`, 루트 없음) — 각각 기존 `monitoring/*/values.yaml`을 `valueFiles`로 참조, syncPolicy는 automated+selfHeal+prune
- [ ] `scripts/install.sh` 폐지 또는 대폭 축소 — 네임스페이스 생성 정도만 남기고 Helm 설치·Secret 생성·envsubst 로직 제거 (ArgoCD+ESO가 대체). 대신 최초 1회 `monitoring/argocd/*.yaml` 3종을 `kubectl apply`하는 안내/스크립트 필요
- [ ] `.harness/ARCHITECTURE.md` 갱신: 배포 방식(ArgoCD 관리, flat Application), 시크릿 관리 방식(ESO) 반영
- [ ] `secrets/README.md` 갱신: `.env` 방식 → ESO 방식으로 정책 변경

**구현 전 추가로 확인이 필요한 점 (사용자 결정 필요, 착수 시점에 재논의):**
- [ ] External Secrets Operator가 참조할 외부 시크릿 저장소 확정 (AWS Secrets Manager / Parameter Store 등 — 클러스터가 EKS인지, IRSA 연동 가능한지 확인 필요. RCA Agent 항목에서 IRSA를 이미 전제하고 있어 같은 방식 재사용 가능해 보임)
- [ ] 서비스 저장소까지 포함할 때 Application을 어디(이 저장소/별도 저장소)에 어떤 방식(flat 유지/ApplicationSet 전환)으로 둘지 — 서비스 저장소 전환 착수 시점에 결정 (지금 관측 스택 전환 자체를 막는 항목은 아님)

## 서비스 저장소 연동

- [ ] `ServiceMonitor`/`PodMonitor` CR을 실제로 각 서비스 저장소(`backend-book` 등)에 추가하도록 해당 팀에 전달 (이 저장소 범위 밖 — ADR-0001 참고)
- [ ] Book Service 등 서비스 쪽 계측(Micrometer `/actuator/prometheus` 노출, 구조화 로깅) 준비 여부 확인
