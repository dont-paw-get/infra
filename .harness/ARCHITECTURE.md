# ARCHITECTURE

지금의 관측 스택 구성과 컨벤션 (현재 상태 스냅샷). 왜 이렇게 정했는지는 `docs/adr/0001-observability-stack.md` 참고, 진행 상황은 `STATE.md` 참고.

## 배포 방식 (ArgoCD GitOps)

Git 커밋이 곧 배포다. ArgoCD 자체 설치는 이 저장소 범위 밖(클러스터에 이미 준비됨) — 이 저장소는 `monitoring/argocd/`의 `Application` CR과 배포 대상 매니페스트만 소유한다. App-of-Apps 루트 없이 개별(flat) 등록이며, 최초 1회만 `scripts/install.sh`(또는 `kubectl apply -f monitoring/argocd/`)로 등록하면 이후는 ArgoCD가 자동 동기화(`automated: selfHeal + prune`)한다. `backend-auth` 저장소의 ArgoCD+Kustomize 컨벤션을 따른다 — 모든 `Application`은 `targetRevision: develop`(dev/prod로 나뉘지 않는 단일 인프라이므로 실사용 브랜치를 그대로 추적)과 `finalizers: [resources-finalizer.argocd.argoproj.io]`를 둔다. 결정 배경은 `docs/adr/0003-argocd-gitops.md` 참고.

`sync-wave`로 동기화 순서를 보장한다: External Secrets Operator·StorageClass(-2) → ClusterSecretStore/ExternalSecret(-1) → kube-prometheus-stack/Loki/Alloy/Tempo/OpenTelemetry Collector/alerting(0).

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
| `tempo` | `grafana-community/tempo` | grafana-community | `monitoring/tempo/values.yaml` | `monitoring/argocd/tempo.yaml` |
| `otel-collector` | `open-telemetry/opentelemetry-collector` | open-telemetry | `monitoring/otel-collector/values.yaml` | `monitoring/argocd/otel-collector.yaml` |

모니터링 컴포넌트는 `monitoring` 네임스페이스(`monitoring/namespace.yaml`)에 설치한다(`external-secrets`만 자체 네임스페이스). Helm 차트는 ArgoCD 멀티소스(`sources`)로 업스트림 repo에서, values는 이 저장소 git 경로에서 가져온다. 차트 `targetRevision`은 실제 버전으로 고정됨(external-secrets 2.9.0, kube-prometheus-stack 88.5.4, loki 7.3.0, alloy 1.11.1 — 2026-08-24 기준, tempo 2.3.0, opentelemetry-collector 0.170.0 — 2026-09-01 기준, artifacthub.io).

`monitoring/alerting/`(`monitoring/argocd/alerting.yaml`)는 `kustomization.yaml`의 `configMapGenerator`로 Grafana Alerting provisioning ConfigMap을 생성한다. `monitoring/external-secrets/`(`monitoring/argocd/external-secrets-config.yaml`)는 이미 유효한 K8s 매니페스트(ServiceAccount/ClusterSecretStore/ExternalSecret)라 Kustomize 없이 순수 YAML 디렉터리로 둔다.

## 메트릭

- Prometheus가 `serviceMonitorSelectorNilUsesHelmValues: false`로 설정되어 전 네임스페이스의 `ServiceMonitor`/`PodMonitor`를 스크레이핑 대상으로 인식한다.
- Alertmanager는 비활성화(`alertmanager.enabled: false`) — 알림은 Grafana Alerting이 담당.
- Prometheus 보존/스토리지 확정값: 15d / PVC 20Gi. `storageClassName: auto-ebs-sc`(`monitoring/storage-class/`) 명시 — `gp2`(in-tree `kubernetes.io/aws-ebs`)는 CSI 마이그레이션으로 실제론 표준 AWS EBS CSI 드라이버(`ebs.csi.aws.com`)를 기다리는데 이 클러스터(EKS Auto Mode)엔 그 드라이버가 없어 PVC가 영원히 Pending으로 남는다(2026-08-27 실제 발생 확인) — Auto Mode 전용 드라이버(`ebs.csi.eks.amazonaws.com`)를 쓰는 `auto-ebs-sc`로 전환.

## 로그

- Loki는 SingleBinary 모드, `singleBinary.persistence.storageClass: auto-ebs-sc` 명시(위 Prometheus와 같은 이유), 오브젝트 스토리지는 S3(`dpgy-infra-loki-logs`, `ap-northeast-2`, IRSA 인증), 보존 336h(14d) 확정 — 결정 배경은 `docs/adr/0004-loki-s3-storage.md` 참고. `compactor.retention_enabled: true`가 있어야 보존 기간이 실제로 적용되고, 이를 켜면 `compactor.delete_request_store: s3`도 함께 지정해야 한다(없으면 Loki가 config 검증에서 기동을 거부한다 — 2026-08-28 실제 발생 확인). SimpleScalable 타겟(`read`/`write`/`backend`)은 차트 기본 replicas(3)와 SingleBinary 모드가 충돌하므로 명시적으로 0으로 둔다.
- Loki의 S3 접근은 IRSA(`arn:aws:iam::594532711953:role/dpgy-infra-loki`).
- Alloy가 DaemonSet으로 모든 노드에서 컨테이너 stdout을 수집해 `loki-gateway.monitoring.svc.cluster.local`로 전송한다.
- 애플리케이션은 stdout에 JSON 구조화 로그(`level` 필드 포함)를 출력해야 `monitoring/alerting/rules/log-error-spike.yaml`의 LogQL이 동작한다.
- trace/log correlation을 위해 애플리케이션 JSON 로그에는 `trace_id` 필드를 둔다. `trace_id`는 high cardinality 값이므로 Alloy/Loki label로 승격하지 않고, Grafana Loki datasource의 derived field와 `| json` LogQL 파싱으로만 사용한다.

## 트레이스

- OpenTelemetry Collector(`otel-collector`)가 Kubernetes 내부 전용 ClusterIP Service로 OTLP trace를 받는다. 서비스 DNS/포트: `http://otel-collector.monitoring.svc.cluster.local:4318`(OTLP HTTP/protobuf). 사용하지 않는 inbound OTLP gRPC `4317`은 열지 않는다.
- Collector는 deployment 1 replica이며 traces pipeline만 활성화한다: `otlp` receiver(HTTP only) → `memory_limiter` → `k8sattributes` → `filter/probes` → `batch` → `otlphttp/tempo` exporter.
- `k8sattributes`는 `k8s.namespace.name`, `k8s.pod.name`, `k8s.node.name`, `k8s.deployment.name`을 span resource에 보강한다. 이를 위해 Collector chart의 Kubernetes attributes preset/RBAC를 사용한다.
- `/health`, `/ready`, `/readiness`, `/live`, `/liveness` path는 Collector filter processor에서 보완적으로 제외한다. 우선순위는 여전히 애플리케이션 SDK에서 probe trace 생성 자체를 막는 것이다.
- Grafana Tempo(`tempo`)는 dev용 single binary 1 replica다. Tempo HTTP API는 `http://tempo.monitoring.svc.cluster.local:3200`, Collector export는 내부 OTLP HTTP `http://tempo.monitoring.svc.cluster.local:4318`을 사용한다. Tempo gRPC `4317`은 열지 않는다.
- Tempo dev storage는 PVC 5Gi(`auto-ebs-sc`) 로컬 backend이며 retention은 24h다. prod 확장 시 S3/object storage, retention, topology는 별도 ADR로 재검토한다.
- Tempo 리소스: request 512Mi / limit 1Gi(`monitoring/tempo/values.yaml`). 초기값 512Mi는 single-binary(distributor+ingester+querier+compactor 한 프로세스) + `memBallastSizeMbs: 128` 조합에서 trace 유입이 조금만 늘어도 OOM됐다(2026-09-02 `tempo-0` OOMKilled 실발생, CLIAR-254로 상향). 밸러스트 제거+`GOMEMLIMIT` 전환은 `.harness/BACKLOG.md`.

## Grafana

- Unified Alerting 활성화, legacy alerting 비활성화.
- 기본 Prometheus 데이터소스(차트 기본 uid `prometheus`) + 추가 Loki 데이터소스(uid `loki`) + Tempo 데이터소스(uid `tempo`, `additionalDataSources`로 등록).
- Loki datasource는 JSON 로그의 `"trace_id"`를 regex로 추출하는 derived field를 가지고, 해당 값을 Tempo trace 링크로 연결한다. Tempo datasource는 `tracesToLogsV2` custom query(`{namespace=~".+"} | json | trace_id="$${__trace.traceId}"`)로 trace에서 같은 trace_id의 Loki 로그를 조회한다.
- admin 계정은 `existingSecret: grafana-admin-credentials` 참조 (값은 ExternalSecret이 AWS Secrets Manager에서 동기화).
- ALB(AWS Load Balancer Controller) Ingress로 외부 노출 확정 — 도메인/ACM 인증서가 아직 없어 HTTP만 열려 있다(ALB 기본 DNS 이름으로 접근, `hosts: []`로 catch-all). 인증은 Grafana 기본 admin 계정 로그인만. 도메인+ACM 인증서 확보 후 HTTPS 전환은 `.harness/PLAN.md` 참고.
- `sidecar.alerts` 활성화, `label: grafana_alert`, `labelValue: "1"`, `searchNamespace: monitoring` — 이 라벨의 ConfigMap을 자동으로 provisioning에 반영.

## 알림 (Grafana Alerting)

- Contact point: `discord-webhook` (`monitoring/alerting/contact-points/discord.yaml`), 값은 `$__env{DISCORD_WEBHOOK_URL}`(Grafana 자체 provisioning 환경변수 확장 문법)로 참조. 이 env var는 `grafana.envValueFrom`(values.yaml)이 `discord-webhook` Secret에서 주입.
- Contact point는 **2개로 분리**되어 있다: `discord-webhook`(사람이 보는 알림)과 `rca-agent-webhook`(RCA Agent 트리거, `http://rca-agent.monitoring.svc.cluster.local:8080/webhook`, `disableResolveMessage: true`). Grafana는 contact point 단위로 notify 성공/실패를 판정하므로 한 contact point에 두 receiver를 넣으면 rca-agent 전송 실패가 Discord 알림의 중복 재시도·드롭으로 번진다 — ADR-0002 결정 #3의 "두 경로 독립"은 분리해야만 실제로 성립한다(2026-08-29 실제 발생, `.harness/DECISIONS.md` 참고).
- Notification policy(`monitoring/alerting/policies/notification-policy.yaml`): 루트 아래에 matcher 없는 하위 route 2개를 두어 모든 알림을 양쪽에 보낸다 — `rca-agent-webhook`(`continue: true`) → `discord-webhook`. `group_by`/타이밍은 루트에서 상속한다.
- Rules 5종 파일 존재(`monitoring/alerting/rules/`): HTTP 5xx 에러율, p99 레이턴시, CrashLoopBackOff/OOMKilled, PVC 사용률, 로그 ERROR 급증. threshold는 모두 임시값.
- 5종 **전부 `monitoring/alerting/kustomization.yaml`의 `configMapGenerator`에 등록되어 배포된다**(ConfigMap 7개 = 규칙 5 + discord + notification-policy). HTTP 5xx 에러율/p99 레이턴시는 2026-08-25~09-02 동안 서비스 저장소 계측이 없어 제외돼 있었으나, `backend-*` 5개 서비스(auth/book/librarian/record/discovery)가 Micrometer(`http_server_requests_seconds_*`, `application` 라벨) 노출 + dev overlay `ServiceMonitor`를 추가하면서 재등록했다(CLIAR-238). 5개 모두 Micrometer 표준 메트릭 이름이라 규칙 쿼리(`by (application)`, `status=~"5.."`, `_bucket` + `le`)는 수정하지 않았다 — 아래 "서비스 저장소와의 경계" 표 참고.
- 각 규칙의 `data[]` 쿼리에는 `relativeTimeRange`(from>to)가 반드시 있어야 한다. 없으면 Grafana가 `[From: 0s, To: 0s]`로 간주해 `alerting.alert-rule.invalidRelativeTime`으로 프로비저닝 reload 전체(POST `/api/admin/provisioning/alerting/reload` → 500)를 거부한다 — contact point/notification policy만 로드되고 규칙은 0개가 된다(2026-08-29 실제 발생, `.harness/DECISIONS.md` 참고). instant 쿼리든 `__expr__`든 `from: 600, to: 0`을 둔다.
- provisioning 배포 메커니즘: `monitoring/alerting/kustomization.yaml`(`configMapGenerator`)이 각 YAML을 `grafana_alert=1` 라벨의 ConfigMap으로 만들고, ArgoCD(`monitoring/argocd/alerting.yaml`)가 이를 동기화 → Grafana sidecar(`grafana-sc-alerts` 컨테이너)가 `/etc/grafana/provisioning/alerting/`에 쓰고 Grafana가 reload API를 호출한다.
- 규칙이 실제 로드됐는지 확인: `curl -u admin:<pw> localhost:3000/api/v1/provisioning/alert-rules`(포트포워드 후) 가 `[]`가 아니어야 한다. Grafana 컨테이너 로그의 `logger=provisioning.alerting`/`errorMessageID=alerting.*`도 확인.
- `pod-oom-killed` 규칙은 최근성 바운드를 갖는다: `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}`는 파드 오브젝트가 살아있는 한 계속 1이라, `and on (namespace, pod, container) (time() - kube_pod_container_status_last_terminated_timestamp < 900)`로 최근 15분 내 OOM 종료만 발화하도록 제한한다(2026-09-02 `tempo-0`가 하루 넘게 정상 Running인데도 계속 firing한 문제, CLIAR-254). 복구 15분 후 series A가 비어 `noDataState: OK`로 자동 해소되고, 반복 OOM은 timestamp가 갱신되며 재발화한다.

## 시크릿

- External Secrets Operator + AWS Secrets Manager, 인증은 IRSA. `grafana-admin-credentials`, `discord-webhook` K8s Secret을 `ExternalSecret` CR이 자동 생성/갱신.
- 상세 정책·매니페스트 경로는 `secrets/README.md` 참고. 과거 `.env` + `scripts/install.sh` 수동 방식은 폐지됨(`docs/adr/0003-argocd-gitops.md`).

## RCA Agent (`monitoring/rca-agent/`)

Grafana Alerting 발화(webhook)를 받아 Bedrock 기반으로 원인을 분석하고 Discord에 후속 메시지를 보고하는 read-only Agent. 결정 배경은 `docs/adr/0002-anomaly-rca-agent.md`, 트레이스(Tempo) 소스 추가는 `docs/adr/0008-rca-agent-tempo-source.md` 참고.

- `src/`: FastAPI 서버(`main.py`, `/webhook`)가 Grafana 알림을 받아 `analyzer.py`(Strands SDK `Agent` + Bedrock + Prometheus/Loki/Tempo 쿼리 tool)를 호출하고, 결과를 `notifier.py`가 Discord webhook으로 전송. system prompt가 알림 5종별 라벨/조사 순서를 안내하고, tool 5개를 제공한다: `query_prometheus`(instant)/`query_prometheus_range`(추세)/`query_loki`/`search_traces`(Tempo TraceQL 검색)/`get_trace`(trace_id 하나의 span 트리 요약). 각 tool은 실패해도 예외를 던지지 않고 실패 문자열을 반환(부분 실패 허용), 응답은 8000자로 truncate. `get_trace`는 Tempo `/api/traces` 원본 OTLP JSON(span당 수십 KB)을 그대로 넣지 않고 span 트리 텍스트(service/name/duration/status + 에러 span의 exception type·message)로 압축한다 — `_MAX_SPANS_RENDERED=80`, span 메시지 300자. Tempo 접근은 Prometheus/Loki와 동일하게 무인증 내부 DNS(`TEMPO_URL`=`http://tempo.monitoring.svc.cluster.local:3200`, `configmap.yaml`). k8s 이벤트/describe pod 조회는 RBAC 확장이 필요해 아직 없음(`.harness/PLAN.md` 백로그).
- `/webhook`은 firing 알림을 `BackgroundTasks`에 넘기고 **즉시 200을 반환**한다. 분석 본체(`analyze()` + Discord 전송)는 `asyncio.to_thread`로 워커 스레드에서 돈다 — 이벤트 루프에서 직접 돌리면 Bedrock 호출(수십 초) 동안 `/healthz`가 응답하지 못해 liveness probe가 파드를 죽이고, Grafana의 webhook 전송도 타임아웃된다(2026-08-29 실제 발생). 분석이 예외로 실패하면 Discord에 "RCA 분석 실패" 메시지를 보내 실패 자체를 가시화한다.
- Probe는 기본값보다 느슨하게 둔다: readiness `period 10s/timeout 3s/failure 3`, liveness `initialDelay 15s/period 20s/timeout 5s/failure 6`.
- 배포: `monitoring/rca-agent/k8s/`(Kustomize) — IRSA `ServiceAccount`(`rca-agent-irsa`), `ConfigMap`(Bedrock 리전/모델, Prometheus/Loki 엔드포인트), `Deployment`(image 태그는 CI가 갱신), `Service`(`rca-agent:8080`). `monitoring/argocd/rca-agent.yaml`(sync-wave 0)로 동기화.
- Prometheus/Loki는 Alloy와 동일하게 클러스터 내부 서비스 DNS(`prometheus-operated`, `loki-gateway`)로 별도 인증 없이 접근.
- Bedrock 인증은 IRSA(`arn:aws:iam::594532711953:role/dpgy-infra-rca-agent`). 모델 ID는 **inference profile** `global.anthropic.claude-sonnet-5`(`configmap.yaml`의 `BEDROCK_MODEL_ID`) — Sonnet 5는 베어 모델 ID로 on-demand 호출이 안 되고 `ap-northeast-2`엔 `apac.` 프로파일이 없어 `global.` 하나뿐이다(2026-08-28 실제 발생). IAM 권한은 `bedrock:InvokeModel*`를 `inference-profile/global.anthropic.claude-sonnet-5`와 `arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-5`(라우팅 대상)로 스코프.
- 클러스터 쓰기 권한 없음 (read-only 분석/보고 전용).

## CI (GitHub Actions)

- `.github/workflows/rca-agent-build-push.yml`: `monitoring/**` 변경이 `develop`에 push되면 이미지를 빌드해 ECR(`dpgy-infra-rca-agent`)에 push하고, `monitoring/rca-agent/k8s/kustomization.yaml`의 `images.newTag`를 커밋 SHA로 갱신(GitOps) — ArgoCD가 이 커밋을 감지해 재배포한다. 트리거 경로는 원래 `monitoring/rca-agent/**`였으나 사용자 결정(2026-08-27)으로 `monitoring/**` 전체로 넓혔다 — RCA Agent 소스가 안 바뀐 monitoring 변경(alerting/argocd/values 등)에도 이미지가 재빌드/재배포되는 트레이드오프를 감수하기로 함.
- push 성공 후 `kustomization.yaml` 갱신 커밋이 non-fast-forward로 거부될 경우 `fetch`+`rebase` 후 최대 5회 재시도한다 — 트리거 범위가 넓어져 동시 실행 가능성이 커진 만큼 이 재시도 로직이 중요하다.
- CI → AWS 인증은 IAM 사용자 액세스 키(`secrets.AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`, `infra` 저장소 repo-level Secrets) 방식이다. 이 조직은 Secrets를 조직 레벨이 아니라 저장소별로 등록하는 컨벤션이라, `infra` 저장소도 자체적으로 ECR push 전용 IAM 사용자의 키를 등록한다 — 결정 배경은 `docs/adr/0006-ci-access-key-revert.md` 참고(한때 GitHub OIDC로 전환을 검토했으나 `docs/adr/0005-github-actions-oidc.md`는 대체됨).

## 서비스 저장소와의 경계

- 이 저장소는 수집·저장·시각화·알림 파이프라인만 소유한다.
- `ServiceMonitor`/`PodMonitor` CR, 메트릭 엔드포인트 노출, 구조화 로깅, OpenTelemetry SDK 설정은 각 서비스 저장소(`backend-book` 등) 책임 — 이 저장소에는 두지 않는다.
- **dev trace endpoint (전 서비스 공통):** `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.monitoring.svc.cluster.local:4318`, `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`, `OTEL_METRICS_EXPORTER=none`/`OTEL_LOGS_EXPORTER=none`(Collector는 traces pipeline만). `OTEL_SERVICE_NAME`은 각 서비스의 `application` 메트릭 태그·JSON 로그 `service` 필드와 동일하게 맞춘다.
- **서비스별 `ServiceMonitor`/메트릭 현황** (2026-09-02, CLIAR-238 회신 — 각 서비스 dev overlay에만 존재, base/prod 불변). 5개 모두 Micrometer 표준(`http_server_requests_seconds_count`/`_bucket`/`_sum`, 라벨 `application`/`method`/`uri`/`status`/`outcome`)이라 `http-error-rate`/`latency` 규칙 쿼리는 무수정:

  | 서비스 | `application` | ServiceMonitor (name / ns) | 메트릭 포트·경로 | 실 스크레이핑 확인 |
  |---|---|---|---|---|
  | backend-auth | `backend-auth` | `backend-auth` / `dpyb-auth-dev` | port `http`(8000) · `/metrics` | ❌ dev 배포 후 확인 |
  | backend-book | `backend-book` | `backend-book` / `dpyb-book-dev` | port `metrics`(8081, 별도 관리 포트 · ALB 미노출) · `/actuator/prometheus` | ❌ dev 배포 후 확인 |
  | backend-librarian | `backend-librarian` | `backend-librarian` / `dpyb-librarian-dev` | `/actuator/prometheus` (비-Spring, Micrometer 호환 이름) | ❌ dev 배포 후 확인 |
  | backend-record | `backend-record` | `backend-record` / `dpyb-record-dev` | `/actuator/prometheus` (Micrometer 호환) | ❌ dev 배포 후 확인 |
  | backend-discovery | `backend-discovery` | `backend-discovery` / `dpyb-discovery-dev` | `/actuator/prometheus` (Micrometer 모방) | ❌ dev 배포 후 확인 |

  Prometheus는 `serviceMonitorSelectorNilUsesHelmValues: false`라 이 네임스페이스들의 ServiceMonitor를 라벨 제약 없이 인식한다. 배포 후 `Status > Targets`에서 `serviceMonitor/<ns>/<name>` 이 `UP`인지, Grafana에서 `http_server_requests_seconds_bucket{application="<svc>"}` 이 조회되는지 확인이 남아 있다(`.harness/PLAN.md`).
- **미해결:** Loki 스트림 라벨 `app`(Alloy가 `app.kubernetes.io/name`에서 채움)이 각 서비스에서 `<svc>`와 일치하는지는 미확인 — `로그 ERROR 급증` 규칙이 `by (app)`로 집계하므로 서비스 파드에 `app.kubernetes.io/name: <svc>` 라벨이 필요하다. `trace_id`는 JSON 로그 필드로만 존재(라벨 승격 안 함).
