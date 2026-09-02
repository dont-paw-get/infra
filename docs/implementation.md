# 관측 스택 & RCA Agent 구현 기록

Kubernetes(EKS) 클러스터에 메트릭·로그 수집부터 Discord 알림, LLM 기반 자동 근본원인분석(RCA)까지
구축한 과정을 정리한 문서다.

> **이 문서의 위치**
> 결정의 *근거*는 `docs/adr/`(ADR)가, *현재 구성 상태*는 `.harness/ARCHITECTURE.md`가,
> *진행 상황*은 `.harness/STATE.md`가 소유한다. 이 문서는 그것들을 중복하지 않고
> **"무엇을 왜 어떻게 만들었는가"를 처음 읽는 사람이 따라갈 수 있게** 엮은 서술형 기록이다.
> 세부 값이 필요하면 각 절에 표시된 원본 파일을 참고할 것.

---

## 1. 왜 Prometheus + Grafana + Loki 인가

전체 근거는 [ADR-0001](adr/0001-observability-stack.md). 요약하면 다음과 같다.

### 검토한 대안과 트레이드오프

| 스택 | 강점 | 채택하지 않은 이유 |
|---|---|---|
| **A. Prometheus + Grafana + Loki** | K8s 관측의 사실상 표준. CRD(`ServiceMonitor`) 기반 설정, 최대 커뮤니티 | — **채택** |
| B. VictoriaMetrics + VictoriaLogs | 리소스 효율이 우수하고 Prometheus API 호환 | 효율 이점이 절실한 규모가 아직 아님. 필요해지면 전환 가능(아래 "탈출 경로") |
| C. Elastic/OpenSearch (EFK) | 로그 전문 검색이 강력 | 메트릭과의 결합이 어색하고, 팀 규모 대비 운영 부담이 큼 |
| D. SigNoz (OTel + ClickHouse) | 로그·메트릭·트레이스 단일 뷰 | 상대적으로 신생이라 트러블슈팅 레퍼런스가 얇음 |
| E. Grafana Cloud (매니지드) | 운영 부담 없음 | 데이터가 클러스터 밖으로 나가고 비용이 트래픽에 연동됨 |

### 채택 이유 세 가지

**1) 레퍼런스 밀도가 곧 문제 해결 속도다.**
이번 구축에서 실제로 마주친 문제만 10건이 넘는다(5절 참고). PromQL·Grafana·Loki는
같은 증상을 먼저 겪은 사람이 반드시 있는 생태계라, 에러 메시지 하나로 원인에 도달할 수 있었다.
신생 스택이었다면 각 이슈마다 소스를 읽어야 했을 것이다.

**2) `ServiceMonitor` CRD가 책임 경계를 강제한다.**
"무엇을 수집할지"를 각 서비스 저장소가 자기 매니페스트로 선언하고, 인프라 저장소는
수집·저장·시각화·알림 파이프라인만 소유한다. database-per-service와 같은 결의 분리이며,
스택 자체가 이 구조를 표준으로 지원한다.

**3) 탈출 경로를 확보한 채로 시작할 수 있다.**
카디널리티나 리소스 문제가 실제로 터지면 Prometheus API 호환인 VictoriaMetrics로 옮길 수 있다.
그래서 쿼리는 PromQL 표준을 벗어나지 않게 유지한다. "지금 최선"과 "나중에 바꿀 수 있음"을 동시에 만족한다.

### 함께 내린 결정

- **자체 호스팅**: 데이터가 클러스터를 벗어나지 않고, 비용이 클러스터 리소스로 예측 가능하다.
- **Alertmanager 대신 Grafana Alerting**: Discord contact point를 네이티브 지원해 릴레이 컴포넌트
  (`alertmanager-discord` 등)가 필요 없다. `alertmanager.enabled: false`로 꺼둔다.
- **로그 수집 에이전트는 Alloy**: Promtail의 후속. DaemonSet으로 모든 노드의 컨테이너 stdout을 수집한다.

---

## 2. Kubernetes에 모니터링 구축하기

### 2.1 전체 구성

```
monitoring 네임스페이스
├── kube-prometheus-stack (Helm)
│   ├── Prometheus        메트릭 수집·저장 (15d, PVC 20Gi)
│   ├── Grafana           시각화 + Alerting + Discord 발송
│   ├── kube-state-metrics  파드/디플로이먼트 등 오브젝트 상태 메트릭
│   └── node-exporter     노드 리소스 메트릭
├── Loki (Helm)           로그 저장 (S3, 14d)
├── Alloy (Helm)          DaemonSet — 컨테이너 stdout 수집 → Loki
├── Tempo (Helm)          트레이스 저장·조회 (dev single binary, PVC 5Gi)
├── OTel Collector (Helm) OTLP HTTP/protobuf 수신 → Tempo export
└── rca-agent             알림 수신 → LLM 분석 → Discord 보고
```

배포는 전부 **ArgoCD GitOps**다 — Git 커밋이 곧 배포. 자세한 배경은 [ADR-0003](adr/0003-argocd-gitops.md).

### 2.2 배포 파이프라인 (ArgoCD)

`monitoring/argocd/`에 릴리스별 `Application` CR을 두고 최초 1회만 등록한다.

```bash
./scripts/install.sh    # 네임스페이스 생성 + kubectl apply -f monitoring/argocd/
```

이후로는 이 저장소 `develop` 브랜치에 커밋하면 ArgoCD가 자동 동기화(`automated: selfHeal + prune`)한다.

**sync-wave로 순서를 보장한다** — 의존 관계가 있기 때문이다:

| wave | 대상 | 이유 |
|---|---|---|
| -2 | External Secrets Operator, StorageClass | CRD와 StorageClass가 먼저 있어야 함 |
| -1 | ClusterSecretStore, ExternalSecret | Secret이 만들어져야 Grafana가 뜸 |
| 0 | kube-prometheus-stack, Loki, Alloy, Tempo, OTel Collector, alerting, rca-agent | 위 두 단계에 의존 |

3rd-party Helm 차트는 **멀티소스**로 구성한다 — 차트는 업스트림 repo에서, `values`는 이 저장소
git 경로에서 가져온다. 차트를 벤더링하지 않아 업스트림 추적이 쉽다.

### 2.3 메트릭 (Prometheus)

핵심 설정은 `monitoring/kube-prometheus-stack/values.yaml`:

```yaml
prometheus:
  prometheusSpec:
    serviceMonitorSelectorNilUsesHelmValues: false   # 전 네임스페이스의 ServiceMonitor 인식
    podMonitorSelectorNilUsesHelmValues: false
    retention: 15d
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: auto-ebs-sc              # EKS Auto Mode 전용 (5.1절 참고)
          resources: { requests: { storage: 20Gi } }
```

`...NilUsesHelmValues: false`가 핵심이다. 기본값이면 Helm 릴리스가 붙인 라벨을 가진
`ServiceMonitor`만 인식하는데, 서비스 저장소들이 각자 네임스페이스에 두는 CR을 잡으려면 꺼야 한다.

### 2.4 로그 (Loki + Alloy)

Loki는 **SingleBinary 모드 + S3 백엔드**다 ([ADR-0004](adr/0004-loki-s3-storage.md)).
로컬 파일시스템은 PVC 용량 제약과 파드 장애 시 유실 위험이 있어 전환했다.

```yaml
# monitoring/loki/values.yaml
deploymentMode: SingleBinary
loki:
  storage:
    type: s3
    bucketNames: { chunks: dpgy-infra-loki-logs, ... }
  limits_config:
    retention_period: 336h        # 14d
  compactor:
    retention_enabled: true       # 이게 없으면 retention_period가 동작하지 않는다
    delete_request_store: s3      # retention을 켜면 필수 (5.4절)
serviceAccount:
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::...:role/dpgy-infra-loki   # IRSA
```

Alloy는 DaemonSet으로 각 노드에서 컨테이너 stdout을 수집하고 Loki 라벨을 붙인다:

```
__meta_kubernetes_namespace              → namespace
__meta_kubernetes_pod_label_app_kubernetes_io_name → app
__meta_kubernetes_pod_name               → pod
__meta_kubernetes_pod_container_name     → container
```

`app` 라벨이 파드의 `app.kubernetes.io/name`에서 온다는 점이 중요하다 — 알림 규칙과 RCA Agent가
이 라벨로 서비스를 식별한다. **애플리케이션은 stdout에 JSON 구조화 로그(`level` 필드 포함)를
출력해야** LogQL의 `| json | level="ERROR"` 파싱이 동작한다.

`trace_id`는 로그와 트레이스를 잇기 위해 JSON 필드로 남기되 Loki label로 승격하지 않는다.
high cardinality 값이라 label로 만들면 Loki 인덱스 비용과 쿼리 부담이 커진다. Grafana는 Loki
datasource의 derived field로 `"trace_id"`를 추출해 Tempo trace 링크를 만들고, Tempo datasource의
`tracesToLogsV2` custom query로 같은 trace id의 로그를 다시 조회한다.

`service`, `level`, `logger`, `trace_id`는 Loki label이 아니라 JSON 필드 기준으로 검색한다:

```logql
{namespace=~".+"} | json | service="backend-book" | level="ERROR"
{namespace=~".+"} | json | trace_id="<trace-id>"
```

### 2.4.1 트레이스 (OpenTelemetry Collector + Tempo)

Trace 계층은 기존 metrics/logs 경로를 바꾸지 않고 추가한다([ADR-0007](adr/0007-otel-tempo-tracing.md)).

```
backend-book / backend-auth
    -> OTLP HTTP/protobuf :4318
    -> OpenTelemetry Collector
    -> Tempo
    -> Grafana Explore
```

Collector는 `monitoring/otel-collector/values.yaml`로 배포되는 Deployment 1 replica다. Service는
ClusterIP이며 외부 Ingress/LoadBalancer가 없다.

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.monitoring.svc.cluster.local:4318
```

Collector pipeline은 traces만 활성화한다. `memory_limiter`와 `batch`로 Collector/Tempo 지연이
애플리케이션 요청 경로에 영향을 덜 주게 하고, `k8sattributes`로 `k8s.namespace.name`,
`k8s.pod.name`, `k8s.node.name`, `k8s.deployment.name` resource attribute를 보강한다.
`/health`, `/ready`, `/readiness`, `/live`, `/liveness`는 Collector filter processor에서 보완적으로
제외하지만, probe trace는 애플리케이션 SDK에서 생성 자체를 막는 것이 1순위다.

Tempo는 `monitoring/tempo/values.yaml`로 배포되는 single binary 1 replica다. dev에서는 PVC 5Gi
(`auto-ebs-sc`) 로컬 backend와 24h retention을 사용한다. 소규모 개발/시연 환경에서 S3, Kafka,
distributed topology는 과하므로 피했다. prod로 확장할 때는 S3/object storage, retention, topology를
별도 ADR로 정한다.

장애 시 확인 순서:

```bash
kubectl -n argocd get applications.argoproj.io tempo otel-collector
kubectl -n monitoring get pod,svc,pvc -l app.kubernetes.io/name=tempo
kubectl -n monitoring get pod,svc -l app.kubernetes.io/name=opentelemetry-collector
kubectl -n monitoring logs deploy/otel-collector
kubectl -n monitoring logs statefulset/tempo
```

Grafana에서는 datasource 목록에 Prometheus, Loki, Tempo가 함께 있어야 하고, Tempo Explore에서
trace id 직접 조회와 `service.name=backend-book`/`service.name=backend-auth` TraceQL 검색을 확인한다.

### 2.5 알림 (Grafana Alerting)

provisioning YAML → ConfigMap → sidecar 자동 반영 구조다:

```
monitoring/alerting/*.yaml
  → kustomization.yaml의 configMapGenerator (label: grafana_alert=1)
  → ArgoCD 동기화
  → Grafana sidecar(grafana-sc-alerts)가 /etc/grafana/provisioning/alerting/ 에 기록
  → Grafana reload API 호출
```

**알림 규칙 5종** (`monitoring/alerting/rules/`):

| 규칙 | 조건 | for | 배포 |
|---|---|---|---|
| 파드 CrashLoopBackOff | `kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"} == 1` | 2m | ✅ |
| 파드 OOMKilled | `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} == 1` | 0m | ✅ |
| PVC 사용률 초과 | `used_bytes / capacity_bytes > 0.85` | 10m | ✅ |
| 로그 ERROR 급증 | `sum by (app) (count_over_time({...} \| json \| level="ERROR" [5m])) > 5` | 5m | ✅ |
| HTTP 5xx 에러율 / p99 레이턴시 | Micrometer 메트릭 기반 | 5m | ⏸ 서비스 계측 대기 |

마지막 2종은 서비스 저장소가 `/actuator/prometheus`를 노출하기 전까지는 `NoData`만 발생시키므로
`kustomization.yaml`의 `configMapGenerator`에서 제외해 두었다(파일은 남아있다).

**규칙 작성 시 주의점 2가지** — 둘 다 실제로 밟은 함정이다:

1. 모든 `data[]` 쿼리에 **`relativeTimeRange`가 필수**다. 없으면 프로비저닝 전체가 거부된다(5.5절).
2. Loki 쿼리는 `instant: true`여도 시계열을 돌려주므로 **reduce 단계를 거쳐야** threshold에 연결된다(5.8절).

**contact point는 2개로 분리**한다 — Grafana가 contact point 단위로 성공/실패를 판정하기 때문이다(5.7절):

```yaml
contactPoints:
  - name: discord-webhook      # 사람이 보는 알림
  - name: rca-agent-webhook    # RCA Agent 트리거 (disableResolveMessage: true)

policies:
  - receiver: discord-webhook
    routes:
      - receiver: rca-agent-webhook
        continue: true          # 계속 평가 → 아래 route도 실행
      - receiver: discord-webhook
```

### 2.6 시크릿

External Secrets Operator + AWS Secrets Manager, 인증은 **IRSA**(정적 액세스 키 없음).
`ExternalSecret` CR이 `grafana-admin-credentials`, `discord-webhook` K8s Secret을 자동 생성·갱신한다.

Grafana provisioning 파일에서는 Grafana 자체 문법 `$__env{DISCORD_WEBHOOK_URL}`로 참조하고,
그 환경변수는 `grafana.envValueFrom`이 Secret에서 주입한다. 상세는 `secrets/README.md`.

---

## 3. RCA Agent 구축

알림이 울린 뒤 "왜 발생했는지"를 사람이 매번 파고드는 부담을 줄이기 위해, 알림을 트리거로
메트릭·로그를 자동 조사하고 Discord에 한국어 리포트를 남기는 Agent를 만들었다.
결정 배경은 [ADR-0002](adr/0002-anomaly-rca-agent.md).

### 3.1 설계 결정

| 항목 | 선택 | 이유 |
|---|---|---|
| 프레임워크 | **Strands SDK + Amazon Bedrock** | Bedrock 네이티브 통합. LLM 백엔드는 이미 Bedrock으로 확정 |
| 트리거 | **Grafana Alerting webhook** | 기존 알림 규칙을 탐지 계층으로 재사용. 폴링하면 탐지 로직이 이원화되고 매 주기 LLM 비용 발생 |
| 출력 | **같은 채널에 원본 알림 + RCA 후속 메시지** | 두 경로가 독립이라 Agent 장애 시에도 원본 알림은 보존 |
| 권한 | **read-only** | 클러스터 쓰기 권한 없음 — blast radius 최소화 |
| 인증 | **IRSA** | AWS 액세스 키를 시크릿으로 관리하지 않음 |

### 3.2 구조

```
monitoring/rca-agent/
├── src/
│   ├── main.py       FastAPI — POST /webhook, GET /healthz
│   ├── analyzer.py   Strands Agent + Bedrock + 조회 도구 3종
│   ├── notifier.py   Discord webhook 전송
│   └── config.py     환경변수
├── Dockerfile
└── k8s/              ServiceAccount(IRSA) / ConfigMap / Deployment / Service
```

**Agent가 쓰는 도구 5종** (`analyzer.py`):

| 도구 | 용도 |
|---|---|
| `query_prometheus_range` | 발화 시점 전후 추세 — 급증인지 완만한 증가인지 |
| `query_prometheus` | 현재 시점 값(instant) |
| `query_loki` | 관련 로그 |
| `search_traces` | Tempo TraceQL 검색 — 느린/실패한 trace 목록(레이턴시·5xx 알림) |
| `get_trace` | trace_id 하나의 span 트리 요약 — 병목/실패 span, exception 메시지 |

모든 도구가 예외를 던지지 않고 **실패 문자열을 반환**한다. 하나가 실패해도 분석 전체가 죽지 않고,
"이 조회는 실패했다"를 근거에 포함해 보고서를 쓴다. 응답은 8000자로 truncate해 토큰 낭비를 막는다.
`get_trace`는 Tempo 원본 JSON(span 하나에 수십 KB)을 그대로 넣지 않고 span 트리 텍스트로 압축한다 —
service/name/소요시간/status와 에러 span의 exception type·message만 남긴다.

system prompt는 알림 종류별로 **어떤 라벨을 보고 어떤 순서로 조사할지** 안내한다.
Prometheus 알림 라벨(`application`)과 Loki 라벨(`app`)이 다르다는 점을 명시해 혼동을 방지한다.

### 3.3 webhook 핸들러 — 반드시 비동기여야 한다

```python
@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.json()
    for alert in body.get("alerts", []):
        if alert.get("status") != "firing":
            continue
        background_tasks.add_task(_run_analysis, alert)   # 큐에 넣고
    return {"received": len(alerts), "queued": queued}    # 즉시 200

async def _run_analysis(alert):
    await asyncio.to_thread(_analyze_and_report, alert)   # 워커 스레드에서 실행
```

이렇게 하지 않으면 파드가 계속 죽는다 — 자세한 경위는 5.6절. Bedrock 호출은 30~60초가 걸리는데
그동안 이벤트 루프가 막히면 `/healthz`가 응답하지 못하고 liveness probe가 파드를 kill한다.

분석이 예외로 실패하면 Discord에 "RCA 분석 실패" 메시지를 보낸다 — 조용히 실패하면 RCA가
돌았는지조차 알 수 없기 때문이다.

### 3.4 배포 파이프라인

```
monitoring/** 변경이 develop에 push
  → GitHub Actions (rca-agent-build-push.yml)
  → docker build → ECR push
  → kustomization.yaml의 images.newTag를 커밋 SHA로 갱신 [skip ci]
  → ArgoCD가 이 커밋을 감지 → 파드 재배포
```

이미지 태그 갱신 커밋이 non-fast-forward로 거부될 수 있어 `fetch` + `rebase` 후 최대 5회 재시도한다.

**Bedrock 모델은 inference profile ID를 써야 한다** — `global.anthropic.claude-sonnet-5`.
베어 모델 ID로는 on-demand 호출이 거부된다(5.3절).

---

## 4. 동작 흐름

### 4.1 정상 경로

```
① 장애 발생          파드가 CrashLoopBackOff / OOMKilled / 로그 ERROR 급증 / PVC 포화
        ↓
② 수집               kube-state-metrics·node-exporter → Prometheus (15s 주기)
                     컨테이너 stdout → Alloy(DaemonSet) → Loki
        ↓
③ 평가               Grafana Alerting이 규칙을 주기 평가 (interval 1m)
                     조건이 `for` 시간만큼 유지 → Pending → Alerting
        ↓
④ 라우팅             notification policy가 두 route로 분기 (continue: true)
        ├─────────────────────────────┐
        ↓                             ↓
⑤ Discord 원본 알림          ⑥ rca-agent POST /webhook
   (사람이 즉시 인지)              → 즉시 200 반환
                                   → 백그라운드 스레드에서 분석 시작
                                      ├ query_prometheus_range (추세)
                                      ├ query_loki            (로그)
                                      ├ query_prometheus      (현재값)
                                      ├ search_traces         (Tempo 검색)
                                      └ get_trace             (span 트리)
                                   → Bedrock(Claude Sonnet 5)이 근거 종합
                                      ↓
                              ⑦ Discord에 "RCA: <알림명>" 후속 메시지
                                 (원인 후보 / 근거 / 다음 확인 사항)
```

두 경로(⑤, ⑥)는 **독립된 contact point**다. RCA Agent가 죽어도 원본 알림은 정상 발송된다.

### 4.2 실제 동작 예시

`rca-test` 네임스페이스에 의도적으로 OOM 파드를 띄웠을 때 Agent가 낸 결론:

> **원인 후보**: 애플리케이션의 의도적/비정상적 메모리 과다 할당으로 인한 컨테이너 memory limit 초과
> **근거**
> 1. `kube_pod_container_resource_limits{resource="memory"}` = 33,554,432 bytes (32MiB)로 매우 타이트
> 2. `container_memory_working_set_bytes` 조회 결과 없음 — 이미 OOMKilled로 종료돼 수집되지 않은 것으로 보임
> 3. 로그에서 `{"level":"INFO","msg":"allocating memory until OOM"}` 반복 확인
> **다음 확인 사항**: 실제 서비스라면 메모리 할당 로직 검토 및 limit 상향 조정

메트릭 조회 → 로그 교차 확인 → 오답(리소스 부족·네트워크) 배제까지 사람이 하던 절차를 그대로 밟는다.

### 4.3 해소(resolved) 경로

문제가 해결되면 알림이 `Alerting → Normal`로 바뀌고 Discord에 `[RESOLVED]` 메시지가 간다.
**RCA Agent는 해소 알림을 받지 않는다**(`disableResolveMessage: true`) — 해소된 문제를 분석할
이유가 없고, 불필요한 LLM 비용을 막는다.

---

## 5. 트러블슈팅

구축 중 실제로 마주친 문제들이다. 대부분 "배포는 성공했는데 동작하지 않는" 유형이라
기록해 둘 가치가 있다. 각 항목의 전체 경위는 `.harness/DECISIONS.md`에 있다.

### 5.1 PVC가 영원히 Pending — EKS Auto Mode의 CSI 드라이버

**증상**: Loki/Prometheus 파드가 `Pending`. `kubectl describe pvc`에
`ExternalProvisioning: Waiting for a volume to be created by the external provisioner 'ebs.csi.aws.com'`

**원인**: 클러스터에 default StorageClass가 없어 레거시 `gp2`(in-tree `kubernetes.io/aws-ebs`)를
지정했는데, Kubernetes 1.23+ CSI 마이그레이션으로 이 요청이 표준 EBS CSI 드라이버(`ebs.csi.aws.com`)로
넘어간다. 그런데 이 클러스터는 **EKS Auto Mode**라 Auto Mode 전용 드라이버(`ebs.csi.eks.amazonaws.com`)만
실행 중이다. 요청이 영원히 처리되지 않는다.

**해결**: `auto-ebs-sc` StorageClass를 직접 만들어(`monitoring/storage-class/`, provisioner
`ebs.csi.eks.amazonaws.com`, gp3) 참조하도록 전환.

### 5.2 StatefulSet의 `volumeClaimTemplates`는 불변이다

**증상**: StorageClass를 git에서 바꿨는데 ArgoCD sync가
`Forbidden: updates to statefulset spec for fields other than ...`로 계속 실패.

**원인**: `volumeClaimTemplates`는 생성 후 수정 불가능한 필드다. git만 고쳐서는 절대 반영되지 않는다.

**해결**: StatefulSet과 그 PVC를 수동 삭제 후 재생성.
```bash
kubectl -n monitoring delete statefulset loki
kubectl -n monitoring delete pvc storage-loki-0
# ArgoCD sync로 재생성
```
스토리지 관련 values를 바꿀 때는 항상 이 절차가 필요하다.

### 5.3 Bedrock 모델 ID — inference profile이 필요하다

**증상**: `ValidationException: Invocation of model ID anthropic.claude-sonnet-5 with on-demand
throughput isn't supported. Retry your request with the ID or ARN of an inference profile.`

**원인**: 최신 Claude 모델은 베어 foundation-model ID로 on-demand 호출이 불가능하고
cross-region inference profile을 요구한다.

**해결**:
```bash
aws bedrock list-inference-profiles --region ap-northeast-2
# → global.anthropic.claude-sonnet-5 (ap-northeast-2엔 apac. 프로파일 없음)
```
`BEDROCK_MODEL_ID`를 profile ID로 바꾸고, **IAM 정책도 함께 확장**해야 한다 —
profile ARN만으로는 부족하고 그 profile이 라우팅하는 foundation-model ARN 권한도 필요하다.

### 5.4 Loki가 config 검증에서 기동 거부

**증상**: `CONFIG ERROR: invalid compactor config: compactor.delete-request-store should be
configured when retention is enabled`

**원인**: `compactor.retention_enabled: true`를 켜면 Loki가 삭제 요청을 보관할 오브젝트 스토어를
반드시 요구한다. PVC가 Pending이던 동안은 파드가 기동조차 못 해 이 오류가 드러나지 않았을 뿐이다.

**해결**: `compactor.delete_request_store: s3` 추가.

### 5.5 알림 규칙이 하나도 로드되지 않음 ⚠️ 가장 치명적이었던 문제

**증상**: 파드를 일부러 CrashLoopBackOff로 만들고 메트릭까지 `=1`로 확인했는데 알림이 오지 않음.
`GET /api/v1/provisioning/alert-rules` → `[]`

**원인**: Grafana 로그에
```
POST /api/admin/provisioning/alerting/reload  status=500
errorMessageID=alerting.alert-rule.invalidRelativeTime
error="Invalid alert rule query A: invalid relative time range [From: 0s, To: 0s]"
```
규칙 YAML의 `data[]`에 `relativeTimeRange`가 없었다. Grafana는 이를 `[From: 0s, To: 0s]`로 보고
유효하지 않다고 판단하며, **파일 하나가 아니라 프로비저닝 reload 배치 전체를 거부**한다.
그래서 contact point와 notification policy만 로드되고 규칙은 0개가 됐다.

**배포 이후 알림이 한 번도 동작한 적이 없었다.** "배포 성공 = 동작"이 아니라는 걸 보여준 사례다.

**해결**: 모든 규칙의 각 쿼리와 표현식에 `relativeTimeRange: {from: 600, to: 0}` 추가.

**교훈 — 배포 후 반드시 확인할 것**:
```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
curl -u admin:<pw> localhost:3000/api/v1/provisioning/alert-rules   # []이면 안 됨
```

### 5.6 RCA Agent가 알림을 받을 때마다 자살

**증상**: `rca-agent` 파드 `RESTARTS 53`, CrashLoopBackOff.
이벤트에 `Liveness probe failed: Get "http://.../healthz": context deadline exceeded`

**원인**: `async def webhook`이 블로킹 `analyze()`(Bedrock 30~60초)를 직접 호출했다.
그동안 이벤트 루프가 멈춰 `/healthz`가 응답하지 못하고, liveness probe(`timeoutSeconds: 1`,
`failureThreshold: 3`)가 3회 실패해 kubelet이 파드를 죽인다. Grafana의 webhook 전송도 같은 이유로 타임아웃.

> 합성 webhook 스모크 테스트(Phase 1)는 통과했었다 — `curl`이 오래 기다려줬고 probe 타이밍이
> 우연히 맞았기 때문이다. **부하 없는 테스트가 통과했다고 안심하면 안 된다.**

**해결**: `BackgroundTasks` + `asyncio.to_thread`로 분석을 워커 스레드로 분리하고,
probe도 완화(readiness `timeout 3s/failure 3`, liveness `initialDelay 15s/timeout 5s/failure 6`).

### 5.7 Discord 알림 중복 — contact point 결합

**증상**: 같은 알림이 5분, 2분 간격으로 번갈아 도착. Grafana 로그에
`Notify for alerts failed ... discord-webhook/webhook[0]: context deadline exceeded`

**원인**: 하나의 `discord-webhook` contact point 안에 `discord[0]`(실제 Discord)과
`webhook[0]`(rca-agent) 두 receiver를 함께 뒀다. Grafana는 **contact point 단위로 notify
성공/실패를 판정**하므로, rca-agent 전송이 실패하면 Discord 전송이 성공했어도 contact point
전체를 실패로 보고 재시도한다 → Discord 중복 발송, 재시도 소진 시 그룹 전체 드롭.

ADR-0002가 의도한 "두 경로 독립"이 **같은 contact point 안에서는 성립하지 않는다**.

**해결**: contact point를 2개로 분리하고 notification policy의 `continue: true` 하위 route로
양쪽에 라우팅(2.5절 참고).

### 5.8 Loki 기반 규칙만 `health: error`

**증상**: `로그 ERROR 급증` 규칙만 평가 실패하며 `DatasourceError` 알림을 계속 발화.

**원인**:
```
invalid format of evaluation results for the alert definition C:
looks like time series data, only reduced data can be alerted on.
```
Loki 쿼리는 `instant: true`를 줘도 시계열(matrix)을 돌려주므로 threshold 표현식에 바로 물릴 수 없다.
Prometheus 쿼리는 instant일 때 스칼라를 돌려줘서 같은 구조가 동작했고, 그래서 Loki 규칙만 실패했다.

**해결**: reduce 단계를 끼운다 — `A(loki) → B(reduce, reducer: last) → C(threshold on B)`.

> 이 원인은 **RCA Agent가 해당 `DatasourceError` 알림을 분석하며 스스로 진단했다.**
> 에러 메시지를 인용하고 "Query C에 Reduce 단계 추가 필요"라는 처방까지 제시했다.

### 5.9 ArgoCD 동기화 실패 — CRD annotation 크기 한도

**증상**: `CustomResourceDefinition ... metadata.annotations: Too long: must have at most 262144 bytes`

**원인**: 큰 CRD를 client-side `kubectl apply`로 적용하면 `last-applied-configuration`
어노테이션이 262144 bytes 한도를 넘는다.

**해결**: `syncOptions: [ServerSideApply=true]` (external-secrets, kube-prometheus-stack Application).

**같은 함정을 ArgoCD 자체 설치에서도 밟았다** — `applicationsets.argoproj.io` CRD가 누락된 채
`argocd-applicationset-controller`만 배포돼 있었고, 컨트롤러가 캐시 sync 타임아웃 → 종료를
7분 주기로 439회 반복했다. 이 플래핑이 알림의 발화/해소 메시지를 쌍으로 만들어
"중복 알림"처럼 보이게 했다.

```bash
kubectl apply --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.1/manifests/crds/applicationset-crd.yaml
kubectl -n argocd rollout restart deploy/argocd-applicationset-controller
```

### 5.10 그 외

| 증상 | 원인 / 해결 |
|---|---|
| prometheus-operator가 Prometheus CR을 무시 | 오퍼레이터가 CRD보다 먼저 기동하면 컨트롤러를 등록하지 않고 **자가 회복하지 않는다**. `rollout restart`로 해소 |
| `ExternalSecret` sync 실패 | 차트가 설치한 CRD가 `v1`만 서빙하는데 매니페스트는 `v1beta1`이었다. apiVersion 수정 |
| ArgoCD sync가 27시간째 `Running` | 진행 중 operation이 있으면 새 sync를 받지 않는다. `kubectl patch application ... --type json -p '[{"op":"remove","path":"/operation"}]'` |
| Windows에서 webhook 테스트 시 500 | PowerShell `Invoke-RestMethod -InFile`이 한글 페이로드를 UTF-8로 보내지 않는다. `curl.exe` 사용 |

### 5.11 검증 체크리스트

배포 후 "동작한다"를 확인하려면 다음을 직접 봐야 한다:

```bash
# 1. 알림 규칙이 실제로 로드됐는가 (배포 성공만으로는 알 수 없다)
curl -u admin:<pw> localhost:3000/api/v1/provisioning/alert-rules      # []이면 실패

# 2. 규칙 평가가 정상인가
curl -u admin:<pw> localhost:3000/api/prometheus/grafana/api/v1/rules  # health: ok 확인

# 3. 알림 전송이 실패하고 있지 않은가
kubectl -n monitoring logs <grafana-pod> -c grafana | grep "Notify for alerts failed"

# 4. RCA Agent가 재시작을 반복하지 않는가
kubectl -n monitoring get pods -l app=rca-agent                        # RESTARTS 증가 여부
```

실제 장애를 주입해 전 구간을 검증하는 시나리오는 `test/rca-scenarios/`에 있다
(합성 webhook 스모크 테스트 + 장애 주입 4종).

---

## 6. 향후 계획 — 다른 MSA 서버로 확장

현재는 **인프라 레벨 관측**(파드 생존·리소스·PVC·로그)만 동작한다.
애플리케이션 레벨로 넓히려면 각 서비스 저장소의 계측이 선행되어야 한다.

### 6.1 책임 경계

| 대상 | 소유자 |
|---|---|
| 수집·저장·시각화·알림 파이프라인 | **이 저장소** (`dpgy-infra`) |
| 메트릭 엔드포인트 노출, 구조화 로깅, `ServiceMonitor` CR | **각 서비스 저장소** (`backend-book`, `backend-auth` 등) |

이 경계는 database-per-service와 같은 원칙이다. 인프라 저장소가 각 서비스의 스크레이핑 대상을
알고 있으면 서비스가 늘어날 때마다 인프라 저장소를 고쳐야 한다.

### 6.2 1단계 — 메트릭 (서비스별 적용)

각 서비스 저장소에서:

```yaml
# Spring Boot: build.gradle + application.yml
# implementation 'io.micrometer:micrometer-registry-prometheus'
management:
  endpoints.web.exposure.include: prometheus,health
  metrics.tags.application: ${spring.application.name}   # 알림 규칙이 이 라벨을 쓴다
```

```yaml
# 서비스 저장소의 배포 매니페스트에 함께 둔다
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: backend-book
  namespace: <서비스 네임스페이스>
spec:
  selector:
    matchLabels: { app: backend-book }
  endpoints:
    - port: http
      path: /actuator/prometheus
      interval: 15s
```

Prometheus는 이미 `serviceMonitorSelectorNilUsesHelmValues: false`라 **인프라 저장소 변경 없이**
자동으로 인식한다.

계측이 붙으면 인프라 저장소에서 할 일:
- `monitoring/alerting/kustomization.yaml`의 `configMapGenerator`에 `http-error-rate`,
  `latency` 규칙을 다시 추가
- 실제 트래픽을 보고 threshold 재조정 (현재 5xx 5%, p99 1초는 러프한 초기값)

### 6.3 2단계 — 로그 (서비스별 적용)

Alloy가 이미 모든 노드의 컨테이너 stdout을 수집하므로 **서비스는 형식만 맞추면 된다**:

```json
{"level":"ERROR","msg":"...","ts":"2026-08-29T02:07:45Z","trace_id":"..."}
```

- `level` 필드가 있어야 `| json | level="ERROR"` 파싱이 동작한다
- 파드에 `app.kubernetes.io/name` 라벨이 있어야 Loki `app` 라벨이 채워진다
- `trace_id`를 함께 남기면 3단계(트레이싱)에서 로그↔트레이스 연결이 가능해진다

### 6.4 3단계 — 분산 트레이싱

dev 스택에 OpenTelemetry Collector와 Tempo를 추가했다. MSA에서 서비스 간 호출 지연이나 실패 전파를 추적할 때 사용한다.

역할 구분:

| 구성 요소 | 후보 | 비고 |
|---|---|---|
| 계측 | OpenTelemetry SDK / Java auto-instrumentation agent | 각 서비스 저장소 책임 |
| 수집 | OpenTelemetry Collector Deployment | OTLP HTTP `:4318`, traces pipeline만 활성화 |
| 저장 | Grafana Tempo single binary | dev는 PVC 로컬 저장, prod는 S3/object storage 검토 |
| 조회 | Grafana Explore | Tempo trace 조회 + Loki 로그 상관관계 |

서비스 저장소 dev overlay에 넣을 값:

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.monitoring.svc.cluster.local:4318
```

Grafana에서는 `service.name=backend-book`, `service.name=backend-auth` TraceQL 검색과 trace_id 직접
조회가 가능해야 한다. Loki JSON 로그에 `trace_id`가 있으면 로그 상세의 TraceID 링크로 Tempo trace로
이동하고, Tempo 화면에서는 같은 trace_id의 Loki 로그를 `tracesToLogsV2` query로 조회한다.

RCA Agent는 이 trace를 `search_traces`(TraceQL 검색) / `get_trace`(span 트리 요약) 도구로 조회한다 —
레이턴시 알림이면 `{ resource.service.name="<svc>" && duration > <threshold> }`로 느린 요청을 찾아 병목 span을,
5xx·ERROR 알림이면 로그의 `trace_id`나 `{ status = error }` 검색으로 실패 span의 exception 메시지를 근거로 삼는다.

### 6.5 그 외 예정 작업

`.harness/PLAN.md`에서 추적 중인 항목:

- **Grafana HTTPS 전환** — 도메인/ACM 인증서 확보 후 ALB에 `certificate-arn` 추가
- **알림 라우팅 세분화** — 현재는 전체를 단일 경로로 보낸다. 알림이 늘면 서비스/심각도별 route 분리
- **RCA Agent에 k8s 이벤트 조회 도구 추가** — 지금은 종료 사유를 메트릭으로 우회 추론한다.
  `describe pod`/이벤트를 직접 보려면 ServiceAccount에 RBAC(get/list pods, events) 부여 필요
- **RCA 실패 재시도 정책** — 실패 시 Discord 통지는 하지만 재시도 메커니즘은 없다
- **동시 분석 수 제한** — 알림이 몰리면 Bedrock 호출이 동시에 터진다. 큐 + 워커 전환 검토

---

## 참고 문서

| 문서 | 내용 |
|---|---|
| [ADR-0001](adr/0001-observability-stack.md) | 관측 스택 선정 |
| [ADR-0002](adr/0002-anomaly-rca-agent.md) | RCA Agent 도입 |
| [ADR-0003](adr/0003-argocd-gitops.md) | ArgoCD GitOps + External Secrets |
| [ADR-0004](adr/0004-loki-s3-storage.md) | Loki S3 전환 |
| [ADR-0006](adr/0006-ci-access-key-revert.md) | CI → AWS 인증 방식 |
| [ADR-0007](adr/0007-otel-tempo-tracing.md) | dev 분산 트레이싱 스택 |
| `.harness/ARCHITECTURE.md` | 현재 구성 상태 스냅샷 |
| `.harness/DECISIONS.md` | 운영 결정·트러블슈팅 상세 경위 |
| `.harness/PLAN.md` | 남은 작업 |
| `test/rca-scenarios/` | 검증 시나리오 (스모크 테스트 + 장애 주입 4종) |
