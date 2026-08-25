# infra

Organization의 Kubernetes 클러스터를 대상으로 하는 공유 관측(Observability) 인프라 저장소.
메트릭/로그 수집, 시각화, Discord 알림 파이프라인을 소유한다. 각 서비스 저장소(`backend-book` 등)는
계측 지점(메트릭 엔드포인트 노출, 구조화 로깅)과 자신의 `ServiceMonitor` CR만 책임진다.

결정 배경과 근거는 [docs/adr/0001-observability-stack.md](docs/adr/0001-observability-stack.md) 참고.

## 스택

- **메트릭**: Prometheus + Grafana + kube-state-metrics + node-exporter (`kube-prometheus-stack` Helm 차트)
- **로그**: Loki + Alloy (DaemonSet, 모든 노드의 컨테이너 stdout 수집)
- **알림**: Grafana Alerting → Discord contact point (Alertmanager 미사용)

## 구조

```
docs/adr/                      아키텍처 결정 기록
monitoring/
  namespace.yaml                monitoring 네임스페이스
  argocd/                       ArgoCD Application CR (flat 등록, GitOps 진입점)
  kube-prometheus-stack/        Prometheus + Grafana Helm values
  loki/                         Loki Helm values
  alloy/                        Alloy(로그 수집 에이전트) Helm values
  alerting/
    kustomization.yaml          provisioning YAML → ConfigMap 생성(Kustomize)
    contact-points/discord.yaml Discord 연락처 프로비저닝
    policies/                   알림 라우팅 정책
    rules/                      알림 규칙 (5xx 에러율, p99 레이턴시, 파드 상태, PVC, 로그 ERROR 급증)
  external-secrets/             ClusterSecretStore, IRSA ServiceAccount, ExternalSecret 2종
  rca-agent/                    이상탐지/RCA Agent (Strands SDK + Bedrock) 소스 + Dockerfile + K8s manifest
secrets/README.md               시크릿 관리 정책 (실제 시크릿은 커밋하지 않음)
scripts/install.sh              최초 부트스트랩 스크립트 (네임스페이스 + ArgoCD Application 등록)
```

## 빠른 시작

배포는 ArgoCD GitOps로 자동화되어 있다 (`docs/adr/0003-argocd-gitops.md`). 클러스터에 ArgoCD가 이미 준비되어 있다고 가정한다.

1. `./scripts/install.sh` 실행 — `monitoring` 네임스페이스 생성 + `monitoring/argocd/`의 Application CR을 최초 1회 등록.
2. 이후 이 저장소에 대한 변경은 커밋 → ArgoCD 자동 동기화로 반영된다. 시크릿(Grafana admin, Discord 웹훅)은 AWS Secrets Manager에 값을 넣어두면 External Secrets Operator가 자동 동기화한다 (`secrets/README.md`).
3. 각 서비스 저장소에 `/actuator/prometheus`(또는 동등한 엔드포인트) 노출 + `ServiceMonitor` CR 추가.

## 미해결 이슈

체크리스트는 `.harness/PLAN.md` 참고 — 데이터 보존 기간, Grafana 외부 노출/인증, 알림 threshold 튜닝,
RCA Agent 이미지 빌드 파이프라인. 결정 배경/근거는
`docs/adr/0001-observability-stack.md`, `docs/adr/0002-anomaly-rca-agent.md`, `docs/adr/0003-argocd-gitops.md`.
