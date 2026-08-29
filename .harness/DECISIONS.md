# DECISIONS

`docs/adr/`에 없는 소규모/운영 결정의 역사 (append-only, 최신이 위). 아키텍처 수준 결정(스택 선정, 호스팅 방식 등)은 여기가 아니라 `docs/adr/`에 기록한다.

## 2026-08-29 — `로그 ERROR 급증` 규칙에 reduce 단계 추가

Phase 2 실행 중 `로그 ERROR 급증` 규칙이 계속 `health: error`로 남아 `DatasourceError` 알림을 발화했다. 공교롭게 그 알림이 RCA Agent로 전달됐고, **Agent가 원인을 정확히 진단했다**:

```
invalid format of evaluation results for the alert definition C:
looks like time series data, only reduced data can be alerted on.
```

Loki 쿼리는 `instant: true`를 줘도 시계열(matrix)을 돌려주기 때문에 threshold 표현식에 바로 물릴 수 없다. Prometheus 쿼리는 instant일 때 스칼라를 돌려줘서 같은 구조가 동작했고, 그래서 Loki 규칙만 실패했다.

**결정:** `monitoring/alerting/rules/log-error-spike.yaml`에 reduce 단계를 끼운다 — `A(loki 쿼리) → B(reduce, reducer: last) → C(threshold on B)`, `condition: C`. 다른 4개 규칙(Prometheus 기반)은 그대로 둔다.

**영향받은 파일:** `monitoring/alerting/rules/log-error-spike.yaml`.

## 2026-08-29 — 누락된 `applicationsets.argoproj.io` CRD 설치 (Discord 알림 중복의 진짜 원인)

RCA Agent 비동기화·contact point 분리(아래 항목)를 배포한 뒤에도 사용자가 "Discord 알림이 여전히 중복 도착한다"고 보고했다. Grafana 로그를 다시 보니 `Notify for alerts failed`는 완전히 사라졌고(= contact point 분리는 유효했다) 전송은 매번 성공하고 있었다. 그런데 전송 시각이 `22:28 → 22:33(5분) → 22:35(2분)` 패턴으로 계속됐다.

원인은 알림 설정이 아니라 **알림 대상 파드가 실제로 7분 주기로 플래핑**하는 것이었다. `argocd/argocd-applicationset-controller`가 439회 재시작 중이었고, 로그는 `failed to wait for applicationset caches to sync kind source: *v1alpha1.ApplicationSet: timed out waiting for cache to be synced`. `kubectl get crd | grep argoproj` 결과 `applications`/`appprojects`만 있고 **`applicationsets.argoproj.io`가 없었다**. 컨트롤러 Deployment와 RBAC(`applicationsets` 권한 포함)는 정상 존재 — CRD만 빠진 상태.

파드 사이클(기동 → 2분 대기 → 타임아웃 종료 → ~5분 backoff)이 메트릭에 그대로 반영된다: backoff 중에는 `kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"}=1`, 실행 중에는 시계열이 사라진다. 규칙의 `noDataState: OK` 때문에 시계열이 사라지면 알림이 해소되고, 돌아오면 다시 발화한다 — 7분마다 발화+해소 메시지 한 쌍이 Discord에 도착하는 것이 "중복"의 정체였다. **알림 스택은 정상 동작하며 실제로 고장난 파드를 정확히 보고하고 있었다.**

CRD가 빠진 경위는 이 저장소가 이미 겪은 함정과 같은 것으로 추정된다 — ApplicationSet CRD는 용량이 커서 client-side `kubectl apply`로는 `metadata.annotations: Too long`(262144 bytes)에 걸린다(`.harness/ARCHITECTURE.md`의 `ServerSideApply=true` 항목 참고).

**결정:** ArgoCD 설치는 이 저장소 범위 밖(ADR-0003)이지만 알림 노이즈의 원인이므로 사용자 확인 후 누락 CRD를 설치한다:

```
kubectl apply --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.1/manifests/crds/applicationset-crd.yaml
kubectl -n argocd rollout restart deploy/argocd-applicationset-controller
```

`--server-side`를 쓰는 것이 핵심 — client-side면 같은 이유로 다시 실패한다. 컨트롤러를 0으로 스케일하는 안(이 저장소는 flat Application만 쓰고 ApplicationSet을 쓰지 않음)도 검토했으나, ArgoCD 설치를 온전한 상태로 되돌리는 쪽을 택했다.

**영향받은 파일:** 없음(클러스터 조치 — ArgoCD는 이 저장소가 소유하지 않는다).

## 2026-08-29 — RCA Agent 분석을 백그라운드로 분리하고 webhook을 별도 contact point로 재도입

바로 아래 항목(임시 제거)의 2단계. 두 가지를 함께 고쳤다.

**1) `analyze()`가 이벤트 루프를 막던 문제.** `main.py`의 `async def webhook`이 블로킹 `analyze()`(Strands 동기 호출 + Bedrock 30~60s)를 직접 호출했다. 그동안 이벤트 루프가 멈춰 `/healthz`가 응답하지 못하고, liveness probe(기본 `timeoutSeconds: 1`, `failureThreshold: 3`)가 3회 실패해 kubelet이 파드를 죽였다(`RESTARTS 53`). Grafana의 webhook 전송도 같은 이유로 타임아웃됐다. Phase 1 스모크 테스트가 통과했던 건 `curl`이 오래 기다려줬고 probe 타이밍이 우연히 맞았기 때문이다.

**결정:** `/webhook`은 firing 알림을 `BackgroundTasks`에 넘기고 즉시 200을 반환한다. 분석 본체는 `asyncio.to_thread`로 워커 스레드에서 실행해 이벤트 루프를 비워 둔다. 큐잉 방식(`asyncio.Queue` + 워커)도 검토했으나 동시 분석 수 제한이 지금 필요하지 않고 코드가 복잡해져 채택하지 않았다 — 필요해지면 그때 전환한다. 함께 probe를 완화한다: readiness `period 10s/timeout 3s/failure 3`, liveness `initialDelay 15s/period 20s/timeout 5s/failure 6`(liveness를 readiness보다 느슨하게).

부수 효과로 ADR-0002 미결정 항목 "Agent 장애/타임아웃 시 RCA 실패를 어떻게 가시화할지"가 최소한으로 해소됐다 — `analyze()`가 예외를 던지면 Discord에 "RCA 분석 실패" 메시지를 보낸다. 재시도 정책은 여전히 없다.

**2) contact point 분리.** `discord-webhook`(Discord)과 `rca-agent-webhook`(RCA 트리거)을 별도 contact point로 나누고, `notification-policy.yaml`의 루트 아래에 matcher 없는 하위 route 2개(`rca-agent-webhook` `continue: true` → `discord-webhook`)를 두어 모든 알림을 양쪽에 보낸다. 이렇게 해야 Grafana가 두 경로의 성공/실패를 독립적으로 판정한다. 하위 route는 `group_by`/타이밍을 루트에서 상속한다.

**영향받은 파일:** `monitoring/rca-agent/src/main.py`, `monitoring/rca-agent/k8s/deployment.yaml`, `monitoring/alerting/contact-points/discord.yaml`, `monitoring/alerting/policies/notification-policy.yaml`.

## 2026-08-29 — RCA Agent webhook을 `discord-webhook` contact point에서 임시 제거

`relativeTimeRange` 수정으로 알림이 처음 동작하기 시작하자마자, Grafana가 알림을 못 보내기 시작했다:

```
level=error component=dispatcher msg="Notify for alerts failed"
  err="discord-webhook/webhook[0]: notify retry canceled due to unrecoverable error after 1 attempts:
       Post \"<redacted>\": context deadline exceeded (Client.Timeout exceeded while awaiting headers)"
```

`monitoring/alerting/contact-points/discord.yaml`의 `discord-webhook` contact point 하나에 `discord[0]`(실제 Discord)과 `webhook[0]`(rca-agent) 두 receiver가 함께 들어 있었다. Grafana는 **contact point 단위로 notify 성공/실패를 판정**하므로, rca-agent 전송이 실패하면 Discord 전송이 성공했더라도 그 contact point 전체를 실패로 보고 재시도한다 — Discord에 같은 알림이 중복 발송되고, 재시도가 소진되면 그룹 전체가 드롭된다. ADR-0002 결정 #3이 의도한 "두 경로 독립"은 **같은 contact point 안에서는 성립하지 않는다**는 것이 실제로 확인됐다.

rca-agent 쪽 실패의 근본 원인은 별개다 — `main.py`의 `async def webhook`이 블로킹 `analyze()`(Bedrock 30~60s)를 직접 호출해 이벤트 루프가 멈추고, `/healthz`가 응답하지 못해 liveness probe(`timeoutSeconds: 1`, `failureThreshold: 3`)가 파드를 죽인다(`RESTARTS 53`). Grafana의 webhook 요청도 같은 이유로 타임아웃된다.

**결정(1단계, 완화):** `discord.yaml`에서 `rca-agent-webhook-receiver`를 제거해 Discord 알림 경로를 먼저 정상화한다. RCA 트리거는 일시 중단된다.

**결정(2단계, 예정):** rca-agent webhook을 **별도 contact point**로 분리하고 `notification-policy.yaml`에서 `continue: true` route로 양쪽에 라우팅해 재도입한다. 이렇게 해야 Grafana가 두 경로의 성공/실패를 독립적으로 판정한다. 함께 `main.py`의 `analyze()` 백그라운드 실행 + probe 파라미터 완화도 적용한다 — `.harness/PLAN.md` 참고.

**영향받은 파일:** `monitoring/alerting/contact-points/discord.yaml`.

## 2026-08-29 — Grafana 알림 규칙에 `relativeTimeRange` 추가 (규칙이 하나도 로드 안 되던 문제)

Phase 2(실제 장애 주입) 첫 시나리오에서 `rca-test` 파드를 CrashLoopBackOff로 만들었는데(`kube_pod_container_status_waiting_reason{reason="CrashLoopBackOff"}=1` 확인) RCA Agent에 webhook이 오지 않았다. 조사 결과 Grafana에 **알림 규칙이 하나도 로드돼 있지 않았다**(`/api/v1/provisioning/alert-rules` → `[]`). Grafana 컨테이너 로그:

```
logger=provisioning.alerting msg="starting to provision alerting"
level=error ... POST /api/admin/provisioning/alerting/reload status=500
  errorMessageID=alerting.alert-rule.invalidRelativeTime
  error="Invalid alert rule query A: invalid relative time range [From: 0s, To: 0s]"
```

`monitoring/alerting/rules/*.yaml`의 각 `data[]` 항목에 `relativeTimeRange`가 없었다. 이 Grafana 버전은 `relativeTimeRange`가 없으면 `[From: 0s, To: 0s]`로 보고 datasource 쿼리에 대해 유효하지 않다고 판단하며, **프로비저닝 reload 전체를 실패**시킨다(파일 하나가 아니라 배치 전체). 그래서 contact point(`discord.yaml`)와 notification policy만 로드되고 규칙 3종(pod-health 2개, pvc-usage, log-error-spike)은 전부 누락됐다. sidecar(`grafana-sc-alerts`)는 파일을 정상적으로 `/etc/grafana/provisioning/alerting/`에 쓰고 있었다 — 문제는 Grafana의 파싱 단계.

이 저장소 배포 이후 실제 알림이 한 번도 동작하지 않았다는 뜻이다. "관측 스택 배포 완료"의 사각지대였다.

**결정:** `monitoring/alerting/rules/`의 5개 파일 모두, 각 쿼리(`refId: A`)와 표현식(`refId: C`)에 `relativeTimeRange: {from: 600, to: 0}`를 추가한다. `instant: true` 쿼리도 필드 자체는 있어야 하고 from>to면 된다. `kubectl kustomize monitoring/alerting/`로 렌더링에 `relativeTimeRange` 8개(배포 대상 pod-health 4 + pvc 2 + log 2)가 들어가는 것을 확인했다.

배포 후 확인: 병합 → ArgoCD `alerting` sync → sidecar 반영 → `curl -u admin:<pw> .../api/v1/provisioning/alert-rules`가 규칙을 반환하는지, Grafana 로그에 reload 500이 사라졌는지.

**영향받은 파일:** `monitoring/alerting/rules/{pod-health,pvc-usage,log-error-spike,http-error-rate,latency}.yaml`.

## 2026-08-28 — RCA Agent의 Bedrock 모델 ID를 inference profile로 전환

Phase 1 스모크 테스트(합성 webhook)에서 `analyze()`가 Bedrock `ConverseStream` 호출까지 도달한 뒤 죽었다:

```
ValidationException: Invocation of model ID anthropic.claude-sonnet-5 with on-demand throughput
isn't supported. Retry your request with the ID or ARN of an inference profile that contains this model.
```

Claude Sonnet 5는 Bedrock에서 베어 foundation-model ID로 on-demand 호출이 불가능하고 cross-region inference profile을 요구한다. `aws bedrock list-inference-profiles --region ap-northeast-2` 결과 Sonnet 5용 프로파일은 `global.anthropic.claude-sonnet-5` 하나뿐(`apac.` 없음)이었다.

**결정:**
- `monitoring/rca-agent/k8s/configmap.yaml`의 `BEDROCK_MODEL_ID`를 `anthropic.claude-sonnet-5` → `global.anthropic.claude-sonnet-5`.
- IAM Role `dpgy-infra-rca-agent` 정책을 `bedrock:InvokeModel(WithResponseStream)` on `inference-profile/global.anthropic.claude-sonnet-5` + `arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-5`(profile이 라우팅하는 실제 모델)로 확장 — profile ARN만으로는 부족하고 대상 FM 권한도 필요하다. `global.` 프로파일은 리전 범위가 넓어 ARN 리전을 `*`로 둔다. (사용자가 AWS Console에서 적용, 2026-08-28)

`global.`은 전 리전 라우팅이라 데이터가 `ap-northeast-2` 밖으로 나갈 수 있으나, `ap-northeast-2`에 리전 한정 프로파일이 없어 대안이 없다.

부수 확인: 이 예외가 FastAPI 핸들러(`main.py`의 `webhook`)까지 전파돼 `/webhook`이 500을 반환했다 — `analyze()` 실패를 삼키고 부분 보고하는 처리가 없다(ADR-0002 "미결정: Agent 장애/타임아웃 시 정책"과 연결, `.harness/PLAN.md` 백로그).

**영향받은 파일:** `monitoring/rca-agent/k8s/configmap.yaml`. (IAM은 콘솔 — 저장소 밖)

## 2026-08-28 — Loki compactor에 `delete_request_store: s3` 추가

StorageClass 문제가 풀려 `loki-0`가 처음으로 스케줄된 직후, config 검증 단계에서 죽었다: `CONFIG ERROR: invalid compactor config: compactor.delete-request-store should be configured when retention is enabled`. Loki 3.x는 `compactor.retention_enabled: true`를 켜면 삭제 요청을 보관할 오브젝트 스토어를 반드시 함께 요구한다. 그동안 PVC가 Pending이라 파드가 기동조차 못 해 이 오류가 드러나지 않았을 뿐, 처음부터 있던 설정 누락이다.

**결정:** `loki.storage.type`과 동일한 `s3`를 `loki.compactor.delete_request_store`로 지정한다. 이미 `dpgy-infra-loki-logs` 버킷을 chunks/ruler/admin에 함께 쓰고 있으므로 별도 버킷을 만들지 않는다.

`helm template loki grafana/loki --version 7.3.0 -f monitoring/loki/values.yaml`로 렌더링된 config에 `compactor.delete_request_store: s3`와 `limits_config.retention_period: 336h`가 함께 들어가는 것을 확인했다.

**영향받은 파일:** `monitoring/loki/values.yaml`.

## 2026-08-28 — prometheus-operator가 CRD보다 먼저 기동하면 자가 회복하지 않는다

Prometheus CR이 27시간 동안 status가 통째로 비어 있었고(`READY`/`RECONCILED`/`AVAILABLE` 공란, `Events: <none>`) StatefulSet이 생성되지 않았다. 오퍼레이터 기동 로그 첫 부분에 원인이 있었다:

```
2026-08-26T18:40:10 level=warn msg="resource \"prometheuses\" (group: \"monitoring.coreos.com/v1\") not installed in the cluster"
```

prometheus-operator는 **기동 시점에 한 번만** CRD 존재 여부를 확인하고, 없으면 해당 컨트롤러를 아예 등록하지 않은 채 계속 실행된다. 나중에 CRD가 설치돼도 재확인하지 않는다. kube-prometheus-stack Application 하나가 CRD와 오퍼레이터 Deployment를 같은 sync에 적용하므로, 오퍼레이터 파드가 CRD 등록보다 먼저 뜨면 이 상태에 빠진다. 버전 불일치가 아님도 확인했다 — CRD 어노테이션 `operator.prometheus.io/version: 0.93.1` = 오퍼레이터 이미지 `v0.93.1`, 네임스페이스 필터도 비어 있음(전체 watch).

여기에 ArgoCD 교착이 겹쳐 있었다. sync operation이 `waiting for healthy state of monitoring.coreos.com/Prometheus/...`에서 27시간째 `Running`으로 매달려 있었고, ArgoCD는 진행 중인 operation이 있으면 새 sync를 받지 않는다(`kubectl patch`가 `patched (no change)`로 무시됨). 그래서 `auto-ebs-sc` 커밋이 CR에 영원히 반영되지 않았다 — Prometheus는 오퍼레이터 없이 Healthy가 될 수 없고, 오퍼레이터는 sync 없이 살아나지 않는 상호 대기.

**해법(운영 조치):** 매달린 operation을 제거(`kubectl -n argocd patch application kube-prometheus-stack --type json -p '[{"op":"remove","path":"/operation"}]'`)하고 새 sync를 건 뒤, `kubectl -n monitoring rollout restart deployment/kube-prometheus-stack-operator`로 오퍼레이터를 재시작한다. 재시작 즉시 컨트롤러가 등록되고(`successfully synced all caches`, `sync prometheus key=monitoring/kube-prometheus-stack-prometheus`) STS가 `auto-ebs-sc`로 생성되면서 매달려 있던 sync까지 함께 완료됐다.

**재발 방지책은 아직 미적용** — CRD를 별도 Application으로 분리하거나 sync-wave를 나누는 안을 `.harness/BACKLOG.md`에 남겼다.

**영향받은 파일:** 없음(운영 조치).

## 2026-08-27 (정정) — Loki/Prometheus PVC StorageClass를 `gp2`에서 `auto-ebs-sc`로 재전환

바로 아래 항목("`gp2`로 유지")은 잘못된 결정이었다. 실제로 `gp2`(레거시 in-tree `kubernetes.io/aws-ebs`)로 배포해보니, PVC가 `Pending`에서 `ExternalProvisioning: Waiting for a volume to be created by the external provisioner 'ebs.csi.aws.com'` 이벤트로 멈췄다. Kubernetes 1.23+의 CSI 마이그레이션 때문에 in-tree `gp2` 요청이 실제로는 표준 AWS EBS CSI 드라이버(`ebs.csi.aws.com`, self-managed 애드온)로 넘어가는데, 이 클러스터(EKS Auto Mode)는 그 애드온 대신 Auto Mode 전용 드라이버(`ebs.csi.eks.amazonaws.com`)만 실행 중이라 요청이 영원히 처리되지 않는다.

**정정된 결정:** `monitoring/storage-class/storage-class.yaml`(신규)로 `auto-ebs-sc`(provisioner `ebs.csi.eks.amazonaws.com`, gp3, default 지정) StorageClass를 만들고, Loki/Prometheus 모두 이걸 참조하도록 전환한다. `monitoring/argocd/storage-class.yaml`(wave -2)로 kube-prometheus-stack/Loki(wave 0)보다 먼저 배포되도록 한다.

또한 Loki의 StatefulSet은 `volumeClaimTemplates`가 Kubernetes에서 생성 후 수정 불가능한 필드라, git의 storageClass 값을 바꿔도 기존 STS에는 절대 반영되지 않는다는 것도 확인했다(ArgoCD sync가 "Forbidden: updates to statefulset spec for fields other than ..." 에러로 계속 실패) — StorageClass를 바꿀 때는 관련 StatefulSet(+그 PVC)을 수동으로 삭제해 재생성해야 한다. Prometheus는 Operator가 아직 StatefulSet 자체를 생성하지 못한 상태라 이 문제와는 무관.

**영향받은 파일:** `monitoring/storage-class/storage-class.yaml`(신규), `monitoring/argocd/storage-class.yaml`(신규), `monitoring/loki/values.yaml`, `monitoring/kube-prometheus-stack/values.yaml`.

## 2026-08-27 — Loki/Prometheus PVC StorageClass는 `gp2`로 유지

Loki(`loki-0`)와 Prometheus 파드가 PVC Pending으로 멈춰있던 원인은 클러스터(EKS Auto Mode)에 default StorageClass가 없어서였다. 조사 결과 이 클러스터는 `storageConfig.blockStorage.enabled: true`로 Auto Mode 블록스토리지 기능 자체는 켜져 있었지만, AWS 문서상 Auto Mode는 `auto-ebs-sc` StorageClass 리소스를 자동으로 만들어주지 않고 사용자가 직접 생성해야 한다 — 그래서 존재하지 않았다. 대안으로 `auto-ebs-sc`(gp3, CSI 드라이버 `ebs.csi.eks.amazonaws.com`)를 새로 만들어 전환하는 안을 검토했으나, 사용자가 이미 존재하는 레거시 `gp2`(in-tree `kubernetes.io/aws-ebs`) StorageClass를 그대로 쓰기로 결정 — 이미 동작하고 dev 클러스터 규모에 충분하며 추가 리소스 생성이 필요 없음.

**영향받은 파일:** `monitoring/loki/values.yaml`(`singleBinary.persistence.storageClass: gp2`), `monitoring/kube-prometheus-stack/values.yaml`(`storageClassName: gp2`).

## 2026-08-23 — 시크릿을 `.env` + `scripts/install.sh` 자동 생성으로 통합

기존에는 `secrets/README.md`에만 수동 `kubectl create secret` 절차가 있었고 `scripts/install.sh`는 이미 Secret이 존재한다고 가정했다. 사용자가 값 채울 자리(.env)를 원해 루트에 `.env`(값 비움, gitignore됨)를 만들고, `scripts/install.sh`가 이를 source해 `grafana-admin-credentials`/`discord-webhook` Secret을 직접 생성·갱신하도록 변경했다.

**이유:** 수동 2단계(Secret 먼저 생성 → install.sh 실행)보다 `.env` 채우고 스크립트 한 번 실행으로 끝나는 편이 더 명확하고 재실행에도 안전(`--dry-run=client | kubectl apply`)하다.

**영향받은 파일:** `.env`(신규), `scripts/install.sh`, `secrets/README.md`.
