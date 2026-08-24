# ARCHITECTURE

지금의 관측 스택 구성과 컨벤션 (현재 상태 스냅샷). 왜 이렇게 정했는지는 `docs/adr/0001-observability-stack.md` 참고, 진행 상황은 `STATE.md` 참고.

## 배포 방식 (ArgoCD GitOps)

Git 커밋이 곧 배포다. ArgoCD 자체 설치는 이 저장소 범위 밖(클러스터에 이미 준비됨) — 이 저장소는 `monitoring/argocd/`의 `Application` CR과 배포 대상 매니페스트만 소유한다. App-of-Apps 루트 없이 개별(flat) 등록이며, 최초 1회만 `scripts/install.sh`(또는 `kubectl apply -f monitoring/argocd/`)로 등록하면 이후는 ArgoCD가 자동 동기화(`automated: selfHeal + prune`)한다. `backend-auth` 저장소의 ArgoCD+Kustomize 컨벤션을 따른다 — 모든 `Application`은 `targetRevision: develop`(dev/prod로 나뉘지 않는 단일 인프라이므로 실사용 브랜치를 그대로 추적)과 `finalizers: [resources-finalizer.argocd.argoproj.io]`를 둔다. 결정 배경은 `docs/adr/0003-argocd-gitops.md` 참고.

`sync-wave`로 동기화 순서를 보장한다: External Secrets Operator(-2) → ClusterSecretStore/ExternalSecret(-1) → kube-prometheus-stack/Loki/Alloy/alerting(0).

## 네임스페이스 / Helm 릴리스

| 릴리스 이름 | 차트 | repo | values | ArgoCD Application |
|---|---|---|---|---|
| `external-secrets` | `external-secrets/external-secrets` | https://charts.external-secrets.io | (기본값, `installCRDs=true`) | `monitoring/argocd/external-secrets.yaml` (ns: `external-secrets`) |
| `kube-prometheus-stack` | `prometheus-community/kube-prometheus-stack` | prometheus-community | `monitoring/kube-prometheus-stack/values.yaml` | `monitoring/argocd/kube-prometheus-stack.yaml` |
| `loki` | `grafana/loki` | grafana | `monitoring/loki/values.yaml` | `monitoring/argocd/loki.yaml` |
| `alloy` | `grafana/alloy` | grafana | `monitoring/alloy/values.yaml` | `monitoring/argocd/alloy.yaml` |

3종 모두 `monitoring` 네임스페이스(`monitoring/namespace.yaml`)에 설치한다(`external-secrets`만 자체 네임스페이스). Helm 차트는 ArgoCD 멀티소스(`sources`)로 업스트림 repo에서, values는 이 저장소 git 경로에서 가져온다. 차트 `targetRevision`은 현재 플레이스홀더(`<CHART_VERSION>`) — 최초 부트스트랩 시 고정 필요(`docs/adr/0003-argocd-gitops.md` 미결정).

`monitoring/alerting/`(`monitoring/argocd/alerting.yaml`)는 `kustomization.yaml`의 `configMapGenerator`로 Grafana Alerting provisioning ConfigMap을 생성한다. `monitoring/external-secrets/`(`monitoring/argocd/external-secrets-config.yaml`)는 이미 유효한 K8s 매니페스트(ServiceAccount/ClusterSecretStore/ExternalSecret)라 Kustomize 없이 순수 YAML 디렉터리로 둔다.

## 메트릭

- Prometheus가 `serviceMonitorSelectorNilUsesHelmValues: false`로 설정되어 전 네임스페이스의 `ServiceMonitor`/`PodMonitor`를 스크레이핑 대상으로 인식한다.
- Alertmanager는 비활성화(`alertmanager.enabled: false`) — 알림은 Grafana Alerting이 담당.
- Prometheus 보존/스토리지는 임시값(15d/20Gi) — `.harness/PLAN.md`의 미결정 항목.

## 로그

- Loki는 SingleBinary 모드, filesystem 스토리지(임시), 보존 336h(14d) — `.harness/PLAN.md`의 미결정 항목.
- Alloy가 DaemonSet으로 모든 노드에서 컨테이너 stdout을 수집해 `loki-gateway.monitoring.svc.cluster.local`로 전송한다.
- 애플리케이션은 stdout에 JSON 구조화 로그(`level` 필드 포함)를 출력해야 `monitoring/alerting/rules/log-error-spike.yaml`의 LogQL이 동작한다.

## Grafana

- Unified Alerting 활성화, legacy alerting 비활성화.
- 기본 Prometheus 데이터소스(차트 기본 uid `prometheus`) + 추가 Loki 데이터소스(uid `loki`, `additionalDataSources`로 등록).
- admin 계정은 `existingSecret: grafana-admin-credentials` 참조 (값은 ExternalSecret이 AWS Secrets Manager에서 동기화).
- Ingress 비활성화 — 외부 노출 방식 미정 (`.harness/PLAN.md`).
- `sidecar.alerts` 활성화, `label: grafana_alert`, `labelValue: "1"`, `searchNamespace: monitoring` — 이 라벨의 ConfigMap을 자동으로 provisioning에 반영.

## 알림 (Grafana Alerting)

- Contact point: `discord-webhook` (`monitoring/alerting/contact-points/discord.yaml`), 값은 `$__env{DISCORD_WEBHOOK_URL}`(Grafana 자체 provisioning 환경변수 확장 문법)로 참조. 이 env var는 `grafana.envValueFrom`(values.yaml)이 `discord-webhook` Secret에서 주입.
- Notification policy: 전체 알림을 `discord-webhook`으로 라우팅 (`monitoring/alerting/policies/notification-policy.yaml`).
- Rules 5종 (`monitoring/alerting/rules/`): HTTP 5xx 에러율, p99 레이턴시, CrashLoopBackOff/OOMKilled, PVC 사용률, 로그 ERROR 급증. threshold는 모두 임시값.
- provisioning 배포 메커니즘: `monitoring/alerting/kustomization.yaml`(`configMapGenerator`)이 각 YAML을 `grafana_alert=1` 라벨의 ConfigMap으로 만들고, ArgoCD(`monitoring/argocd/alerting.yaml`)가 이를 동기화 → Grafana sidecar가 읽어감.

## 시크릿

- External Secrets Operator + AWS Secrets Manager, 인증은 IRSA. `grafana-admin-credentials`, `discord-webhook` K8s Secret을 `ExternalSecret` CR이 자동 생성/갱신.
- 상세 정책·매니페스트 경로는 `secrets/README.md` 참고. 과거 `.env` + `scripts/install.sh` 수동 방식은 폐지됨(`docs/adr/0003-argocd-gitops.md`).

## 서비스 저장소와의 경계

- 이 저장소는 수집·저장·시각화·알림 파이프라인만 소유한다.
- `ServiceMonitor`/`PodMonitor` CR, 메트릭 엔드포인트 노출, 구조화 로깅은 각 서비스 저장소(`backend-book` 등) 책임 — 이 저장소에는 두지 않는다.
