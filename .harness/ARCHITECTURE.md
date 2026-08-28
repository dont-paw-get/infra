# ARCHITECTURE

지금의 관측 스택 구성과 컨벤션 (현재 상태 스냅샷). 왜 이렇게 정했는지는 `docs/adr/0001-observability-stack.md` 참고, 진행 상황은 `STATE.md` 참고.

## 배포 방식 (ArgoCD GitOps)

Git 커밋이 곧 배포다. ArgoCD 자체 설치는 이 저장소 범위 밖(클러스터에 이미 준비됨) — 이 저장소는 `monitoring/argocd/`의 `Application` CR과 배포 대상 매니페스트만 소유한다. App-of-Apps 루트 없이 개별(flat) 등록이며, 최초 1회만 `scripts/install.sh`(또는 `kubectl apply -f monitoring/argocd/`)로 등록하면 이후는 ArgoCD가 자동 동기화(`automated: selfHeal + prune`)한다. `backend-auth` 저장소의 ArgoCD+Kustomize 컨벤션을 따른다 — 모든 `Application`은 `targetRevision: develop`(dev/prod로 나뉘지 않는 단일 인프라이므로 실사용 브랜치를 그대로 추적)과 `finalizers: [resources-finalizer.argocd.argoproj.io]`를 둔다. 결정 배경은 `docs/adr/0003-argocd-gitops.md` 참고.

`sync-wave`로 동기화 순서를 보장한다: External Secrets Operator·StorageClass(-2) → ClusterSecretStore/ExternalSecret(-1) → kube-prometheus-stack/Loki/Alloy/alerting(0).

`monitoring/storage-class/`(`monitoring/argocd/storage-class.yaml`, wave -2)는 EKS Auto Mode용 EBS StorageClass(`auto-ebs-sc`)를 배포한다 — kube-prometheus-stack/Loki의 PVC가 이를 참조하므로 그보다 먼저 동기화되어야 한다. external-secrets와 같은 이유(순수 K8s 매니페스트 디렉터리)로 Kustomize 없이 둔다.

`external-secrets`, `kube-prometheus-stack` Application은 `syncOptions: [ServerSideApply=true]`를 둔다 — 두 차트가 설치하는 CRD(ClusterSecretStore/SecretStore, Prometheus/Alertmanager/PrometheusRule 등)가 client-side apply의 `last-applied-configuration` 어노테이션 한도(262144 bytes)를 넘어 동기화가 실패하기 때문(2026-08-27 실제 발생 확인). Loki/Alloy는 자체 CRD가 없어 이 옵션이 필요 없다.

`external-secrets-config`(wave -1)는 `syncPolicy.retry`(limit 5, backoff 10s~3m)를 둔다 — `external-secrets`(wave -2)가 CRD를 설치한 직후 API 서버의 discovery 캐시가 즉시 갱신되지 않아 `could not find the requested resource`로 실패하는 사례가 있어(2026-08-27 실제 발생 확인), 재시도로 discovery 캐시 갱신을 기다리게 한다. 이미 이 에러로 멈춰있다면 `argocd app get external-secrets-config --hard-refresh`(또는 UI의 Hard Refresh)로 즉시 재시도할 수 있다.

## 네임스페이스 / Helm 릴리스

| 릴리스 이름 | 차트 | repo | values | ArgoCD Application |
|---|---|---|---|---|
| `external-secrets` | `external-secrets/external-secrets` | https://charts.external-secrets.io | (기본값, `installCRDs=true`) | `monitoring/argocd/external-secrets.yaml` (ns: `external-secrets`) |
| `kube-prometheus-stack` | `prometheus-community/kube-prometheus-stack` | prometheus-community | `monitoring/kube-prometheus-stack/values.yaml` | `monitoring/argocd/kube-prometheus-stack.yaml` |
| `loki` | `grafana/loki` | grafana | `monitoring/loki/values.yaml` | `monitoring/argocd/loki.yaml` |
| `alloy` | `grafana/alloy` | grafana | `monitoring/alloy/values.yaml` | `monitoring/argocd/alloy.yaml` |

3종 모두 `monitoring` 네임스페이스(`monitoring/namespace.yaml`)에 설치한다(`external-secrets`만 자체 네임스페이스). Helm 차트는 ArgoCD 멀티소스(`sources`)로 업스트림 repo에서, values는 이 저장소 git 경로에서 가져온다. 차트 `targetRevision`은 실제 버전으로 고정됨(external-secrets 2.9.0, kube-prometheus-stack 88.5.4, loki 7.3.0, alloy 1.11.1 — 2026-08-24 기준, artifacthub.io).

`monitoring/alerting/`(`monitoring/argocd/alerting.yaml`)는 `kustomization.yaml`의 `configMapGenerator`로 Grafana Alerting provisioning ConfigMap을 생성한다. `monitoring/external-secrets/`(`monitoring/argocd/external-secrets-config.yaml`)는 이미 유효한 K8s 매니페스트(ServiceAccount/ClusterSecretStore/ExternalSecret)라 Kustomize 없이 순수 YAML 디렉터리로 둔다.

## 메트릭

- Prometheus가 `serviceMonitorSelectorNilUsesHelmValues: false`로 설정되어 전 네임스페이스의 `ServiceMonitor`/`PodMonitor`를 스크레이핑 대상으로 인식한다.
- Alertmanager는 비활성화(`alertmanager.enabled: false`) — 알림은 Grafana Alerting이 담당.
- Prometheus 보존/스토리지 확정값: 15d / PVC 20Gi. `storageClassName: auto-ebs-sc`(`monitoring/storage-class/`) 명시 — `gp2`(in-tree `kubernetes.io/aws-ebs`)는 CSI 마이그레이션으로 실제론 표준 AWS EBS CSI 드라이버(`ebs.csi.aws.com`)를 기다리는데 이 클러스터(EKS Auto Mode)엔 그 드라이버가 없어 PVC가 영원히 Pending으로 남는다(2026-08-27 실제 발생 확인) — Auto Mode 전용 드라이버(`ebs.csi.eks.amazonaws.com`)를 쓰는 `auto-ebs-sc`로 전환.

## 로그

- Loki는 SingleBinary 모드, `singleBinary.persistence.storageClass: auto-ebs-sc` 명시(위 Prometheus와 같은 이유), 오브젝트 스토리지는 S3(`dpgy-infra-loki-logs`, `ap-northeast-2`, IRSA 인증), 보존 336h(14d) 확정 — 결정 배경은 `docs/adr/0004-loki-s3-storage.md` 참고. `compactor.retention_enabled: true`가 있어야 보존 기간이 실제로 적용되고, 이를 켜면 `compactor.delete_request_store: s3`도 함께 지정해야 한다(없으면 Loki가 config 검증에서 기동을 거부한다 — 2026-08-28 실제 발생 확인). SimpleScalable 타겟(`read`/`write`/`backend`)은 차트 기본 replicas(3)와 SingleBinary 모드가 충돌하므로 명시적으로 0으로 둔다.
- Loki의 S3 접근은 IRSA(`arn:aws:iam::594532711953:role/dpgy-infra-loki`) — IAM Role 생성은 아직 안 됨, `.harness/PLAN.md` 참고.
- Alloy가 DaemonSet으로 모든 노드에서 컨테이너 stdout을 수집해 `loki-gateway.monitoring.svc.cluster.local`로 전송한다.
- 애플리케이션은 stdout에 JSON 구조화 로그(`level` 필드 포함)를 출력해야 `monitoring/alerting/rules/log-error-spike.yaml`의 LogQL이 동작한다.

## Grafana

- Unified Alerting 활성화, legacy alerting 비활성화.
- 기본 Prometheus 데이터소스(차트 기본 uid `prometheus`) + 추가 Loki 데이터소스(uid `loki`, `additionalDataSources`로 등록).
- admin 계정은 `existingSecret: grafana-admin-credentials` 참조 (값은 ExternalSecret이 AWS Secrets Manager에서 동기화).
- ALB(AWS Load Balancer Controller) Ingress로 외부 노출 확정 — 도메인/ACM 인증서가 아직 없어 HTTP만 열려 있다(ALB 기본 DNS 이름으로 접근, `hosts: []`로 catch-all). 인증은 Grafana 기본 admin 계정 로그인만. 도메인+ACM 인증서 확보 후 HTTPS 전환은 `.harness/PLAN.md` 참고.
- `sidecar.alerts` 활성화, `label: grafana_alert`, `labelValue: "1"`, `searchNamespace: monitoring` — 이 라벨의 ConfigMap을 자동으로 provisioning에 반영.

## 알림 (Grafana Alerting)

- Contact point: `discord-webhook` (`monitoring/alerting/contact-points/discord.yaml`), 값은 `$__env{DISCORD_WEBHOOK_URL}`(Grafana 자체 provisioning 환경변수 확장 문법)로 참조. 이 env var는 `grafana.envValueFrom`(values.yaml)이 `discord-webhook` Secret에서 주입.
- 같은 contact point에 `rca-agent-webhook-receiver`(webhook, `disableResolveMessage: true`)가 추가되어 있다 — 알림 발화 시 원본 Discord 알림과 별개로 RCA Agent(`http://rca-agent.monitoring.svc.cluster.local:8080/webhook`)를 트리거한다. 두 receiver는 독립 경로라 Agent 장애가 원본 알림에 영향을 주지 않는다.
- Notification policy: 전체 알림을 `discord-webhook`으로 라우팅 (`monitoring/alerting/policies/notification-policy.yaml`).
- Rules 5종 파일 존재(`monitoring/alerting/rules/`): HTTP 5xx 에러율, p99 레이턴시, CrashLoopBackOff/OOMKilled, PVC 사용률, 로그 ERROR 급증. threshold는 모두 임시값.
- 이 중 **HTTP 5xx 에러율/p99 레이턴시(app-level, Micrometer 메트릭 의존)는 서비스 저장소 계측 전까지 배포 제외** — `monitoring/alerting/kustomization.yaml`의 `configMapGenerator`에서 뺐다(파일은 남아있음). 나머지 3종(파드 생존/자원, 로그)만 실제 배포됨. 계측 완료 후 재추가 조건은 `.harness/PLAN.md`의 "서비스 저장소 연동" 참고.
- provisioning 배포 메커니즘: `monitoring/alerting/kustomization.yaml`(`configMapGenerator`)이 각 YAML을 `grafana_alert=1` 라벨의 ConfigMap으로 만들고, ArgoCD(`monitoring/argocd/alerting.yaml`)가 이를 동기화 → Grafana sidecar가 읽어감.

## 시크릿

- External Secrets Operator + AWS Secrets Manager, 인증은 IRSA. `grafana-admin-credentials`, `discord-webhook` K8s Secret을 `ExternalSecret` CR이 자동 생성/갱신.
- 상세 정책·매니페스트 경로는 `secrets/README.md` 참고. 과거 `.env` + `scripts/install.sh` 수동 방식은 폐지됨(`docs/adr/0003-argocd-gitops.md`).

## RCA Agent (`monitoring/rca-agent/`)

Grafana Alerting 발화(webhook)를 받아 Bedrock 기반으로 원인을 분석하고 Discord에 후속 메시지를 보고하는 read-only Agent. 결정 배경은 `docs/adr/0002-anomaly-rca-agent.md` 참고.

- `src/`: FastAPI 서버(`main.py`, `/webhook`)가 Grafana 알림을 받아 `analyzer.py`(Strands SDK `Agent` + Bedrock + Prometheus/Loki 쿼리 tool)를 호출하고, 결과를 `notifier.py`가 Discord webhook으로 전송. system prompt가 알림 5종별 라벨/조사 순서를 안내하고, `query_prometheus`(instant)/`query_prometheus_range`(추세)/`query_loki` 3개 tool을 제공한다. 각 tool은 실패해도 예외를 던지지 않고 실패 문자열을 반환(부분 실패 허용), 응답은 8000자로 truncate. k8s 이벤트/describe pod 조회는 RBAC 확장이 필요해 아직 없음(`.harness/PLAN.md` 백로그).
- 배포: `monitoring/rca-agent/k8s/`(Kustomize) — IRSA `ServiceAccount`(`rca-agent-irsa`), `ConfigMap`(Bedrock 리전/모델, Prometheus/Loki 엔드포인트), `Deployment`(image는 ECR placeholder), `Service`(`rca-agent:8080`). `monitoring/argocd/rca-agent.yaml`(sync-wave 0)로 동기화.
- Prometheus/Loki는 Alloy와 동일하게 클러스터 내부 서비스 DNS(`prometheus-operated`, `loki-gateway`)로 별도 인증 없이 접근.
- Bedrock 인증은 IRSA(`arn:aws:iam::594532711953:role/dpgy-infra-rca-agent`, 생성 완료 — 권한은 `foundation-model/anthropic.claude-sonnet-5`로 스코프). 모델은 `anthropic.claude-sonnet-5`로 확정.
- 클러스터 쓰기 권한 없음 (read-only 분석/보고 전용).

## CI (GitHub Actions)

- `.github/workflows/rca-agent-build-push.yml`: `monitoring/**` 변경이 `develop`에 push되면 이미지를 빌드해 ECR(`dpgy-infra-rca-agent`)에 push하고, `monitoring/rca-agent/k8s/kustomization.yaml`의 `images.newTag`를 커밋 SHA로 갱신(GitOps) — ArgoCD가 이 커밋을 감지해 재배포한다. 트리거 경로는 원래 `monitoring/rca-agent/**`였으나 사용자 결정(2026-08-27)으로 `monitoring/**` 전체로 넓혔다 — RCA Agent 소스가 안 바뀐 monitoring 변경(alerting/argocd/values 등)에도 이미지가 재빌드/재배포되는 트레이드오프를 감수하기로 함.
- push 성공 후 `kustomization.yaml` 갱신 커밋이 non-fast-forward로 거부될 경우 `fetch`+`rebase` 후 최대 5회 재시도한다 — 트리거 범위가 넓어져 동시 실행 가능성이 커진 만큼 이 재시도 로직이 중요하다.
- CI → AWS 인증은 IAM 사용자 액세스 키(`secrets.AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, `infra` 저장소 repo-level Secrets) 방식이다. 이 조직은 Secrets를 조직 레벨이 아니라 저장소별로 등록하는 컨벤션이라, `infra` 저장소도 자체적으로 ECR push 전용 IAM 사용자의 키를 등록한다 — 결정 배경은 `docs/adr/0006-ci-access-key-revert.md` 참고(한때 GitHub OIDC로 전환을 검토했으나 `docs/adr/0005-github-actions-oidc.md`는 대체됨).

## 서비스 저장소와의 경계

- 이 저장소는 수집·저장·시각화·알림 파이프라인만 소유한다.
- `ServiceMonitor`/`PodMonitor` CR, 메트릭 엔드포인트 노출, 구조화 로깅은 각 서비스 저장소(`backend-book` 등) 책임 — 이 저장소에는 두지 않는다.
