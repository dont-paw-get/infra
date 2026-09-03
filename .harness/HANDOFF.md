# HANDOFF

세션마다 무엇을 했는지 (append-only 서술형 로그, 최신이 위). 단계별 완료 요약은 `STATE.md`, 결정 이유는 `DECISIONS.md`/`docs/adr/` 참고.

## 2026-09-03 (2) — CLIAR-207·254 배포 후 실측 + CLIAR-261 p99/5xx 최소 트래픽 게이트

CLIAR-238 실측(같은 날 앞 항목, 별도 브랜치 `CLIAR-238-app-level-알림-실측-반영`) 이어서. 사용자가 PLAN의 CLIAR-207(tracing 스택)·CLIAR-254(OOM 규칙+Tempo 메모리) "배포 후 검증"을 둘 다 실측 요청.

**CLIAR-254 — 전부 통과:** `tempo-0` limit 1Gi/request 512Mi로 재기동·`restarts=0`·01:23:49부터 안정. `pod-oom-killed` 규칙 `health: ok`(게이트 `and on ...` 쿼리 파싱 OK)·`noDataState: OK`·`for: 0s`. `kube_pod_container_status_last_terminated_timestamp` KSM 노출 확인(폴백 불필요). 09-02 tempo-0 OOM 알림은 재기동 15분 후 `state: inactive`(인스턴스 `Normal (NoData)`)로 자동 해소.

**CLIAR-207 — 전부 통과:** `tempo`/`otel-collector` app Synced/Healthy. svc `otel-collector` `4318`, `tempo` `3200`(+차트 기본 9411/55680/55681/4318 — STATE의 "4318만 노출"은 렌더 기준, 라이브는 기본 리시버 포트도 열림, 무해). Grafana 데이터소스 Prometheus/Loki/Tempo 공존. synthetic OTLP trace `POST otel-collector:4318/v1/traces`→200→Tempo `/api/search` 조회 성공. Tempo `service.name` 태그값에 backend-auth/book/librarian/record/discovery **5개 전부** = 실서비스 trace E2E 동작. Loki `TraceID` derived field·Tempo `tracesToLogsV2` 확인, Loki 실 trace_id가 Tempo `/api/traces/`에서 200.

**부수 발견 → CLIAR-261로 처리:** `p99 레이턴시 초과` 규칙이 idle 서비스(backend-discovery)에 `Pending`. 트래픽이 적으면 느린 요청 1건이 5분 윈도우 p99를 통째로 끌어올림. 5xx 에러율도 동일 취약. 사용자에게 설명 후 "2번 방식(최소 트래픽 게이트)"으로 고치기로 결정. 사용자가 티켓 261로 브랜치 `CLIAR-261-p99-레이턴시-초과-설정-완화`를 develop에서 새로 만들어 전환.

**CLIAR-261 구현(이 브랜치):** `monitoring/alerting/rules/latency.yaml`·`http-error-rate.yaml` 두 규칙 refId A에 `and sum(rate(http_server_requests_seconds_count[5m])) by (application) >= 0.2` 게이트 추가(5xx는 division을 괄호로 묶음), 두 규칙 `noDataState: NoData`→`OK`. 규칙 파일 상단에 CLIAR-261 주석. 검증: `kubectl kustomize monitoring/alerting` ConfigMap 7개 유지·쿼리 반영, 두 게이트 쿼리를 라이브 Prometheus에 실행 `status: success`(현재 전 서비스 `<0.2 req/s`라 빈 결과 = 의도대로).

**커밋(이 브랜치, `CLIAR-261-...`):** 규칙 2파일 + `.harness/STATE.md`(CLIAR-207·254 실측 완료 + CLIAR-261 항목) + `.harness/PLAN.md`(CLIAR-207·254 배포 후 검증 섹션 제거, "알림 규칙 튜닝"에 CLIAR-261 항목) + `.harness/ARCHITECTURE.md`(알림 절 최소 트래픽 게이트 서술) + 이 HANDOFF. CLIAR-238 실측 문서 변경은 별도 브랜치 `CLIAR-238-app-level-알림-실측-반영`에 커밋됨(별도 PR).

**다음 세션이 이어받을 것:** (1) 두 브랜치 각각 PR → develop 머지(HANDOFF.md prepend가 겹쳐 2번째 머지 시 사소한 충돌 가능 — 트리비얼). (2) 머지 후 `grafana-alerting` sync → 두 규칙 `health: ok`, 게이트 동작, `DatasourceNoData` 미발생 확인. (3) 게이트값 0.2·threshold는 실트래픽 쌓인 뒤 튜닝.

## 2026-09-02 (3) — 서비스 저장소 5곳 계측 회신 반영 + app-level 알림 재배포(B·D)

사용자가 5개 서비스(backend-auth/book/librarian/record/discovery) Claude Code의 계측 구현 회신을 붙여넣음. 요지: **5곳 모두 Micrometer 표준 메트릭 이름**(`http_server_requests_seconds_count`/`_bucket`/`_sum`, 라벨 `application`/`method`/`uri`/`status`/`outcome`)이라 **알림 규칙 쿼리 수정 불필요**. 각 저장소 dev overlay에만 `ServiceMonitor` 존재(base/prod 불변). backend-book은 별도 관리 포트 `:8081/actuator/prometheus`(ALB에 `/`로 8080만 노출되므로 actuator 분리 — 앞서 사용자와 논의한 대로), backend-auth는 `:8000/metrics`. 5곳 다 아직 dev 실스크레이핑 미확인(배포 후 Prometheus Targets 확인 예정).

반영(미커밋): `monitoring/alerting/kustomization.yaml`에 `http-error-rate`/`latency` configMapGenerator 재등록(`kubectl kustomize` → ConfigMap 7개 확인, 규칙 파일 무수정). `.harness/ARCHITECTURE.md` 알림 절 "배포 제외"→"5종 전부 배포", "서비스 저장소와의 경계"에 서비스별 ServiceMonitor 표(name/ns/포트/경로) + trace endpoint 공통 서술. `docs/adr/0001` "결과"에 `application` 라벨·`OTEL_SERVICE_NAME` 일치·`trace_id`/`level` 요구 구체화. `.harness/PLAN.md` B·D를 "배포 후 검증"으로 축소, "서비스 저장소 연동" 섹션 정리. `.harness/STATE.md` 갱신. `.harness/BACKLOG.md`에 prod trace endpoint 전달 항목.

**다음 세션이 이어받을 것:** (1) 커밋 — A(ADR)·C(테스트)·B(알림)·D(문서). 커밋 3분할 제안은 `.harness/PLAN.md`. `scripts/aws-mfa-login.sh` 미커밋분은 앞 세션 인수인계대로 별도 판단. (2) **dev 배포 후 실측** — Prometheus `Status > Targets`에서 `serviceMonitor/dpyb-<svc>-dev/backend-<svc>` 5개 `UP`, Grafana에서 `http_server_requests_seconds_bucket{application=...}` 조회, `/api/v1/provisioning/alert-rules`에 규칙 6종·`health: ok`. (3) **Loki 라벨 `app` 확인** — 서비스 파드에 `app.kubernetes.io/name: backend-<svc>`가 있어야 `로그 ERROR 급증` 규칙(`by (app)`)이 서비스별로 집계됨. 없으면 서비스 저장소에 요청. (4) threshold(5xx 5%/p99 1s) 실측 후 튜닝.

## 2026-09-02 (2) — CLIAR-238 후속: 트레이스 소스 ADR + 시나리오 테스트 손질 + app-level 알림 계획

사용자가 "RCA Agent에 트레이스 추가됐는데 시나리오 테스트 손볼 것 보고"라고 요청. 조사 결과 CLIAR-238(같은 날 앞 세션, PR #11 머지)로 tool 코드는 이미 들어갔으나 (1) 그 세션이 판단한 "ADR 불필요"와 사용자 의사가 배치, (2) 시나리오 테스트에 trace 케이스 전무, (3) HTTP 5xx/p99 알림이 여전히 배포 제외임을 확인. `.harness/PLAN.md`에 초안 작성 → 사용자가 A(ADR)·B(알림)·C(테스트)·D(서비스 저장소 전달) 4덩어리로 컨펌.

**사용자 결정:** 브랜치는 `CLIAR-238-RCA-Agent-Tempo-연동` 계속(이미 머지됐지만 재사용, 커밋 티켓 `CLIAR-238` 유지) / B는 옵션1(D가 dev에 반영된 뒤 머지) / D는 전체 HTTP 서비스로 확장. D의 서비스 저장소 Claude Code 전달용 명령 text는 세션 응답으로 사용자에게 전달함(메트릭: actuator/prometheus + percentiles-histogram + `application` 공통태그 + ServiceMonitor / 트레이스: OTLP endpoint·`OTEL_SERVICE_NAME`·JSON 로그 `trace_id`·`level`·probe 제외 / 베어 Bedrock ID → inference profile / 회신값 3종).

**구현한 것 (A·C, 미커밋):**
- A: `docs/adr/0008-rca-agent-tempo-source.md` 신규 — CLIAR-238을 소급 기록. Tempo 3번째 소스, `search_traces`+`get_trace`, 무인증 내부 DNS(ADR-0002 #8 연장 → IRSA/RBAC 무변경), span 트리 요약, 알림별 trace 사용 시점, `resource.service.name` ≠ `application`/`app`. 대안(raw `query_tempo` 기각, Grafana 프록시 기각). ADR-0002·0007 "결과"에 상호참조 한 줄씩, `.harness/ARCHITECTURE.md` RCA Agent 절 헤더에 ADR-0008 링크.
- C: `test/rca-scenarios/README.md` — Phase 1 사전조건 모델 ID를 `global.anthropic.claude-sonnet-5`로 정정, Tempo 전제·"트레이스(Tempo)" 항목 신설, `http-5xx-firing` 실행 절차 추가, `{"received","queued"}` 응답 예시 정정, Phase 2 완료 반영. `test/rca-scenarios/payloads/http-5xx-firing.json` 신규(합성 payload는 trace가 없어 `search_traces` 빈 결과 → 부분 실패 허용 검증용). `test/rca-scenarios/phase2/README.md` — 5xx/p99는 서비스 계측 필요라 A~D에서 제외임을 명시, C 확인 단계에 `get_trace` 인용 여부 추가.
- `.harness/STATE.md`에 A·C 반영, `.harness/PLAN.md`에서 A·C 제거하고 B·D만 남김.

검증: 새 JSON payload 3종 `json.load` 통과. ADR/문서 변경뿐이라 helm/kustomize 렌더링 영향 없음.

**다음 세션이 이어받을 것:** (1) A·C + CLIAR-238 앞 세션의 미커밋분 커밋 여부(사용자 요청 시). (2) **B는 아직 진행 불가** — D의 서비스 저장소 계측이 dev에 반영되고 `http_server_requests_seconds_*` 메트릭이 올라오는 것을 확인한 뒤 `monitoring/alerting/kustomization.yaml`에 `http-error-rate`/`latency` configMapGenerator 재추가 + ARCHITECTURE/ADR-0001 서술 갱신 + `kubectl kustomize`(ConfigMap 7개) 검증. (3) 서비스 저장소들의 회신값(ServiceMonitor 이름/ns, `application` 태그, `OTEL_SERVICE_NAME`)을 받아 Agent system prompt 라벨 매핑에 반영. (4) `scripts/aws-mfa-login.sh` 미커밋분·`--profile mfa` 표기 정정은 앞 세션 인수인계 그대로.

## 2026-09-02 — CLIAR-238 RCA Agent Tempo 연동 + trace/log correlation 분석

사용자가 "trace 로그 분석해서 같은 TraceID 찾아봐" 요청 → dev(dpyb-dev) Loki/Tempo를 port-forward로 조회. AWS 자격증명이 만료돼 있어 `scripts/aws-mfa-login.sh`(신규, 미커밋)를 만들었다 — OTP 6자리만 입력받고 자격증명 값은 화면에 안 찍고 `dpgy-mfa` 프로파일에 바로 주입 + kubeconfig 갱신. **실제 프로파일명은 `dpgy-infra`(장기 키, user/kosa12) / `dpgy-mfa`(임시)** — `.harness/HANDOFF.md`·운영 메모의 `--profile mfa` 표기는 아직 안 고침(사용자 확인 대기).

분석 결과: trace↔log correlation(ADR-0007)은 정상 동작. 최근 6h Loki 로그 659줄에 `trace_id` 존재, 그중 7개가 크로스 서비스. 발견한 서비스 저장소 버그(이 저장소 범위 밖, 각 레포 Claude Code에 넘길 명령문 작성해 전달):
- **backend-librarian**: Bedrock `ConverseStream` → `UnrecognizedClientException: security token invalid`(403). 파드 AWS 자격증명 문제(static 만료 토큰이 IRSA 덮어썼을 가능성). chat 24h 전면 장애. 모델도 베어 ID `anthropic.claude-3-5-sonnet-20240620-v1:0`. 앱 로그가 `exception: null`이라 원인이 안 보였는데 **Tempo span의 exception 이벤트에 원문이 그대로** 있었다.
- **backend-discovery**: Sonnet 5 `ValidationException` ×2 — `top_p is deprecated` / `assistant message prefill 미지원`. `[BEDROCK_FALLBACK]` 경로.
- backend-record→auth: `users/me` 401 전파, 24h 2건, 정상 거절로 추정.

이어서 사용자가 "RCA Agent에 트레이스 추가로 넣을 것" 요청 → **바로 구현**(계획 문서 절차는 사용자가 앞선 대화에서 권장 항목 리스트를 검토·승인한 것으로 갈음, 브랜치 `CLIAR-238-RCA-Agent-Tempo-연동`).

구현: `monitoring/rca-agent/src/analyzer.py`에 `search_traces`(Tempo `/api/search` TraceQL)/`get_trace`(`/api/traces/<id>` → `_summarize_trace`로 span 트리 압축) tool 추가, Agent tools 3→5개, system prompt에 레이턴시/5xx/로그ERROR 시나리오별 trace 활용 + trace_id 피벗 안내. `config.py`·`k8s/configmap.yaml`에 `TEMPO_URL` 추가(무인증 내부 DNS, deployment.yaml은 `envFrom`이라 무변경). 문서: `.harness/ARCHITECTURE.md`(RCA Agent 항목), `.harness/STATE.md`, `.harness/PLAN.md`(RCA Agent 후속 개선에 배포 후 검증·trace 알림 항목 추가), `docs/implementation.md`(tool 표 3→5, 흐름도, 6.4절) 갱신. ADR는 신규 결정 없음(ADR-0007 tracing + ADR-0002 결정 #8 무인증 내부 접근 원칙의 연장) — 수정 안 함.

검증: `python -m py_compile` 통과. dev Tempo에서 받은 실제 cross-service trace(73 span, exception 이벤트 포함)로 `_summarize_trace` 렌더링 확인 — librarian `UnrecognizedClientException`이 트리에 그대로 드러남, 출력 8305자→8000자 truncate. `search_traces`의 `{ status = error }` 실검색 정상. `kubectl kustomize monitoring/rca-agent/k8s`에 `TEMPO_URL` 반영 확인. 커밋은 안 함(사용자 요청 시).

**다음 세션이 이어받을 것:** (1) 커밋 여부 — CLIAR-238 브랜치에 rca-agent 변경 + 문서, `scripts/aws-mfa-login.sh`는 별도 판단. (2) `.harness/PLAN.md` "Tempo 연동 배포 후 검증" — 실제 알림 발화 시 Agent가 trace를 근거에 넣는지. (3) 사용자가 원하면 HANDOFF 운영 메모의 `--profile mfa` → `dpgy-infra`/`dpgy-mfa` 정정. (4) 서비스 저장소 3건(librarian/discovery/record) 이슈는 각 레포에서 처리 — 이 저장소는 추적만.

## 2026-09-01 — CLIAR-207 OpenTelemetry Collector + Tempo dev tracing stack 구현

사용자가 "기존 dev 모니터링 구조를 유지하면서 OpenTelemetry Collector와 Grafana Tempo를 추가" 요청. 하네스 규칙에 따라 `.harness/PLAN.md`에 초안 작성 → 사용자 "컨펌" 후 구현 진행.

구현: `monitoring/tempo/values.yaml` 추가(grafana-community/tempo chart 2.3.0, single binary, PVC 5Gi `auto-ebs-sc`, local trace storage, retention 24h, ClusterIP), `monitoring/otel-collector/values.yaml` 추가(open-telemetry/opentelemetry-collector chart 0.170.0, Deployment 1 replica, inbound OTLP HTTP 4318만 노출(gRPC 4317 비활성화), traces pipeline만 활성화, `memory_limiter`/`k8sattributes`/probe filter/`batch` → Tempo OTLP HTTP 4318), `monitoring/argocd/tempo.yaml`/`otel-collector.yaml` 추가(기존 멀티소스 Helm + `targetRevision: develop`, wave 0). `fullnameOverride`로 Service DNS를 `tempo`, `otel-collector`로 고정했다.

Grafana 연동: `monitoring/kube-prometheus-stack/values.yaml`에 Tempo datasource(uid `tempo`, URL `http://tempo.monitoring.svc.cluster.local:3200`) 추가. 기존 Loki datasource(uid `loki`)는 유지하면서 JSON 로그의 `"trace_id"` derived field를 Tempo 링크로 연결. Tempo `tracesToLogsV2` custom query는 `{namespace=~".+"} | json | trace_id="$${__trace.traceId}"`. `trace_id`는 Loki label로 승격하지 않았다.

문서/하네스: `docs/adr/0007-otel-tempo-tracing.md` 신규 작성, `README.md`, `docs/implementation.md`, `.harness/ARCHITECTURE.md`, `.harness/STATE.md`, `.harness/PLAN.md` 갱신. 서비스 저장소 dev overlay 값은 둘 다 `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.monitoring.svc.cluster.local:4318`.

검증: 전체 `monitoring/**/*.yaml` PyYAML 파싱 성공(34개), `kubectl kustomize monitoring/alerting` 렌더링 성공(일반 sandbox에서는 Access denied라 외부 권한으로 실행), Docker Helm 컨테이너(`alpine/helm:3.19.0`)로 `helm template` 성공. 렌더된 Collector Service/컨테이너 포트/receiver config는 ClusterIP 4318만 노출하고, `k8sattributes` preset 때문에 ClusterRole/ClusterRoleBinding이 `monitoring:otel-collector` ServiceAccount에 생성됨을 확인했다. Tempo config는 OTLP HTTP 4318 receiver만 endpoint가 남도록 OTLP gRPC와 Jaeger endpoint를 비웠다. Tempo Service는 ClusterIP이며 HTTP API 3200과 OTLP HTTP 4318만 실제 trace 경로로 사용한다(외부 노출 없음). `kubectl apply --dry-run=client -f monitoring/argocd`는 kubeconfig 인증 만료(`the server has asked for the client to provide credentials`)로 완료하지 못했다.

다음 세션이 이어받을 것: `.harness/PLAN.md`의 "CLIAR-207 tracing stack 배포 후 검증". dev 클러스터 credential 갱신 후 ArgoCD sync, `tempo`/`otel-collector` Healthy 확인, Service port 확인, synthetic OTLP trace 전송, Grafana datasource/derived field/tracesToLogs 검증, backend-book/backend-auth dev overlay에 endpoint 반영 후 E2E 확인.

## 2026-08-29 (3) — Phase 2 시나리오 A~D 전부 검증 완료 (CLIAR-159)

버그 수정(PR #6·#7)과 argocd CRD 조치가 배포된 뒤 Phase 2를 재개해 시나리오 4종을 모두 통과시켰다. 각 시나리오는 하나씩 apply → 발화 확인 → RCA 분석 확인 → delete 순으로 진행했고, 마지막에 `kubectl delete ns rca-test`로 정리했다.

**A(CrashLoopBackOff)**: 알림 `Pending`→`Alerting`(95초), webhook 수신, Agent가 `fatal: simulated crash, exiting non-zero` 로그와 재시작 추세(2→6)를 인용. **B(OOMKilled)**: `kube_pod_container_resource_limits`로 32MiB limit 확인, `allocating memory until OOM` 로그 인용, `container_memory_working_set_bytes`가 빈 이유(이미 종료돼 수집 안 됨)까지 추론. **D(PVC)**: 900MB/973MB=92.5%를 직접 계산해 알림값과 대조, `dd` 출력 인용, 같은 네임스페이스의 다른 테스트 파드까지 발견해 테스트 환경으로 추론. **C(로그 ERROR 급증)**: `simulated error 67~79`를 5초 간격으로 확인, 재시작 0건 교차 확인으로 크래시가 아님을 짚음 — Alloy→Loki 수집 경로와 `app` 라벨 리라벨링도 함께 검증됐다.

**Agent가 우리 인프라 버그 2건을 스스로 진단한 것이 이번 세션의 수확이다.** (1) `DatasourceError` 알림을 분석하며 `로그 ERROR 급증` 규칙의 reduce 누락을 정확히 짚었고(`looks like time series data, only reduced data can be alerted on`), 처방까지 제시해 그대로 PR #8로 반영했다. (2) argocd CrashLoop 알림을 분석하며 `failed to get restmapping: no matches for kind "ApplicationSet"` 로그를 찾아내 CRD 누락을 특정했다 — 사람이 수동으로 도달한 결론과 일치했고, 심지어 메모리 사용량을 확인해 OOM 가능성을 배제하는 과정까지 거쳤다.

Discord "중복 알림"의 최종 원인은 알림 설정이 아니라 `argocd-applicationset-controller`가 7분 주기로 플래핑한 것이었다(CRD 누락 → 캐시 sync 타임아웃 → 종료 반복, 439회). 메트릭이 나타났다 사라지며 발화/해소 메시지가 쌍으로 발송됐다. `kubectl apply --server-side`로 CRD를 설치해 해결(`RESTARTS 0` 안정, 알림 중단 확인). ArgoCD는 이 저장소 소유가 아니라 파일 변경은 없다.

부수 확인: Loki S3 연동이 실제로 동작 중임을 확인했다(20시간 `Running 2/2`, IRSA 주입됨, 자격증명 에러 없음, ingester가 청크 flush 중) — `PLAN.md`의 "dev 클러스터 배포 검증" 섹션을 제거했다.

**운영 메모:** AWS MFA 임시 자격증명은 12시간이라 세션 중간에 만료됐다(`You must be logged in to the server (Unauthorized)`). 갱신은 `aws sts get-session-token --serial-number arn:aws:iam::594532711953:mfa/otp-cli --token-code <6자리>` 후 `aws configure set ... --profile mfa` 3줄, `update-kubeconfig` 재실행은 불필요.

**다음 세션이 이어받을 것:** `.harness/PLAN.md`의 "RCA Agent 후속 개선"(k8s 이벤트 조회 tool·RBAC, 분석 품질 튜닝, 동시 분석 수 제한)과 "RCA 실패 재시도 정책". 알림 threshold 튜닝과 서비스 저장소 계측 연동도 그대로 남아있다.

## 2026-08-29 (2) — 알림 규칙 수정 배포 후 Phase 2 재시도, 버그 3개 추가 발견 (CLIAR-159)

PR #5(`relativeTimeRange` 수정) 병합 → ArgoCD `grafana-alerting` sync → `/api/v1/provisioning/alert-rules`가 규칙 4종 반환, reload 500 소멸 확인. **알림 레이어가 저장소 배포 이후 처음으로 동작 시작.**

시나리오 A(`rca-test` crashloop) 재배포 → `파드 CrashLoopBackOff` 규칙이 `namespace="rca-test"`로 정상 발화(Grafana 로그 aggrGroup 확인). 규칙은 문제없음. 그런데 RCA 후속 메시지가 안 왔고, 파봤더니 버그 3개:

1. **RCA Agent가 liveness probe로 계속 죽음** — `main.py`의 `async def webhook`이 블로킹 `analyze()`를 직접 호출 → 이벤트 루프 정지 → `/healthz` 무응답 → liveness(`timeout=1s failure=3`) 3회 실패 → kubelet kill. `RESTARTS 53`. Grafana webhook도 ~30s 타임아웃. (Phase 1이 됐던 건 curl이 오래 기다렸고 운). 수정: `/webhook` 즉시 200 + `analyze()` 백그라운드 스레드, probe 완화.
2. **contact point 결합** — `discord.yaml`의 `discord-webhook` receiver 하나에 Discord + rca-agent webhook이 같이 있어, webhook 실패 시 Grafana가 receiver 전체 notify를 실패 처리 → Discord 중복 발송 + 결국 드롭. 수정: rca-agent webhook을 별도 contact point로 분리 + `notification-policy.yaml`에서 `continue: true` 라우팅.
3. **`로그 ERROR 급증` 규칙 `health: error`** (`DatasourceError` 알림 유발) — Loki 쿼리 A → threshold C 직결이 평가 실패. reduce 단계 필요 추정. 시나리오 C 블로커.

상세·수정안은 `.harness/PLAN.md` "RCA Agent 테스트 — Phase 2" 섹션. 시나리오 A 워크로드·`rca-test` ns 정리 완료. rca-agent는 현재 CrashLoopBackOff(Grafana 재시도 피드백 루프) — 즉시 완화안 2가지 PLAN에 기재.

argocd `argocd-applicationset-controller` CrashLoop(ApplicationSet 캐시 sync 타임아웃, 저장소 범위 밖)은 `.harness/BACKLOG.md`.

**다음 세션이 이어받을 것:** PLAN의 버그 1·2·3 수정. 버그 1·2가 RCA Agent E2E의 실질 블로커. 수정 → PR → 병합 → 배포 후 Phase 2 A~D 재개. 미커밋: `.harness/*`(PLAN/STATE/HANDOFF/BACKLOG).

## 2026-08-29 — Phase 2 시작, 알림 규칙 미로드 발견 (CLIAR-159)

사용자가 "병합 없이 Phase 2 실행 가능하면 해봐"라고 요청. `test/rca-scenarios/phase2/`는 ArgoCD 대상이 아니라 로컬 작업 트리에서 바로 `kubectl apply` 가능 — Claude가 사용자 머신의 kubeconfig(`--profile mfa`, dpyb-dev)로 직접 실행했다.

시나리오 A(`A-crashloop.yaml`) 배포 → 파드가 CrashLoopBackOff 진입, `kube_pod_container_status_waiting_reason{namespace="rca-test", reason="CrashLoopBackOff"}=1`까지 Prometheus로 확인. 그런데 10분 넘게 기다려도 RCA Agent 로그에 `POST /webhook`이 없었다(로그는 kubelet probe의 `GET /healthz`만).

**원인: Grafana에 알림 규칙이 0개 로드돼 있었다.** `/api/v1/provisioning/alert-rules` → `[]`. Grafana 컨테이너 로그에 `errorMessageID=alerting.alert-rule.invalidRelativeTime`, `error="Invalid alert rule query A: invalid relative time range [From: 0s, To: 0s]"`, `POST /api/admin/provisioning/alerting/reload status=500`. `monitoring/alerting/rules/*.yaml`의 `data[]`에 `relativeTimeRange`가 없어서 Grafana가 프로비저닝 reload 배치 전체를 거부 — contact point(`discord.yaml`)와 notification policy만 로드되고 규칙 3종은 전부 누락. sidecar(`grafana-sc-alerts` 컨테이너, 이름에 s 있음)는 파일을 `/etc/grafana/provisioning/alerting/`에 정상적으로 쓰고 있었고, 데이터소스 uid(`prometheus`/`loki`)도 정상. **저장소 배포 이후 알림이 한 번도 동작한 적 없다.**

**수정:** `monitoring/alerting/rules/` 5개 파일 모두 `refId: A`와 `refId: C`에 `relativeTimeRange: {from: 600, to: 0}` 추가. `kubectl kustomize monitoring/alerting/`로 렌더링에 8개 들어가는 것 확인(배포 대상 pod-health 4 + pvc 2 + log 2). **아직 커밋 안 함.** `kubectl apply`로 라이브 검증은 auto-mode classifier가 차단(git 앞서는 클러스터 변경) — 병합 후 검증해야 한다.

시나리오 A 워크로드와 `rca-test` 네임스페이스는 정리 완료.

**다음 세션이 이어받을 것:** (1) `monitoring/alerting/rules/*.yaml` `relativeTimeRange` 수정 커밋 → PR → `develop` 병합 → ArgoCD `alerting` sync → 포트포워드 후 `curl -u admin:<pw> localhost:3000/api/v1/provisioning/alert-rules`로 규칙 로드 확인 + Grafana 로그 reload 500 사라짐 확인. admin 비번은 `kubectl -n monitoring get secret grafana-admin-credentials -o jsonpath='{.data.admin-password}' | base64 -d`. (2) 그 다음 `test/rca-scenarios/phase2/`의 A→B→C→D를 하나씩 실행하며 Discord에 원본 알림 + RCA 후속 메시지 확인. 상세 절차는 `test/rca-scenarios/phase2/README.md`. 미커밋 변경: `.harness/*` 4개 + `monitoring/alerting/rules/*` 5개.

## 2026-08-28 — RCA Agent Phase 1 스모크 테스트 (CLIAR-159)

사용자가 "모니터링 배포 완료, 장애 시나리오로 RCA Agent 테스트하고 싶다"고 요청. 가장 안전한 방법으로 좁혀, 실제 장애 워크로드 없이 합성 Grafana webhook 페이로드를 `rca-agent`의 `/webhook`에 직접 POST하는 Phase 1 스모크 테스트를 만들었다. 산출물: `test/rca-scenarios/` (`payloads/crashloop-firing.json`, `payloads/resolved.json`, `send-webhook.sh`, `README.md`) — ArgoCD/CI 대상 아님(수동).

**로컬 kubectl 접근 세팅에 시간이 걸렸다.** 사용자가 그동안 CloudShell에서만 클러스터를 만졌음. IAM 사용자 `kosa12`에 `kosa-edu-mfa-pol`(MFA 없으면 전부 deny) 정책이 걸려 있고 기존 MFA는 U2F 패스키뿐이라 CLI `get-session-token`을 못 썼다. 사용자가 콘솔에서 TOTP 인증앱 MFA(`arn:.../mfa/otp-cli`)를 추가 → `aws sts get-session-token`으로 12h 임시 자격증명 발급 → `--profile mfa`에 저장 → `aws eks update-kubeconfig --profile mfa`로 해결. (세션 만료 시 `get-session-token` + `aws configure set ... --profile mfa` 3줄 재실행)

**첫 테스트에서 실제 버그 발견.** webhook→`analyze()`→Strands→Bedrock `ConverseStream`까지 도달(IRSA·권한 정상)한 뒤 `ValidationException: Invocation of model ID anthropic.claude-sonnet-5 with on-demand throughput isn't supported. Retry ... with an inference profile`. Sonnet 5는 베어 모델 ID on-demand 불가. `aws bedrock list-inference-profiles --region ap-northeast-2` → Sonnet 5용은 `global.anthropic.claude-sonnet-5` 하나뿐(`apac.` 없음). `configmap.yaml`의 `BEDROCK_MODEL_ID`를 그걸로 바꾸고, IAM Role `dpgy-infra-rca-agent` 정책을 `inference-profile/global.anthropic.claude-sonnet-5` + `arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-5`로 확장(사용자가 콘솔에서). 경위는 `DECISIONS.md` 2026-08-28 항목.

**커밋 2개(`feat` 테스트 시나리오, `fix` 모델 ID)를 CLIAR-159 브랜치에 만들고 사용자가 PR #4로 develop 병합.** CI가 이미지 재빌드 + `kustomization.yaml` 태그 갱신(`f36c680`) → ArgoCD `rca-agent` Synced/Healthy, 새 파드가 `global.anthropic.claude-sonnet-5`로 기동. 재테스트 → **Discord에 `RCA: 파드 CrashLoopBackOff` 임베드 정상 도착, 파이프라인 전 구간 확인.** `rca-test` 네임스페이스가 실재하지 않아 도구 쿼리는 빈 결과지만 Agent가 스모크 테스트임을 스스로 인지하고 합리적 보고서 작성.

부수 확인: (1) `resolved` 페이로드의 500은 Windows PowerShell `Invoke-RestMethod -InFile`이 한글을 UTF-8로 안 보낸 탓 — `curl.exe`로는 정상. README에 반영. (2) `analyze()` 예외가 `/webhook` 500으로만 나오고 Discord 통지가 없음 — RCA 실패 가시성 부재, `PLAN.md`에 후속 항목으로.

**다음 세션이 이어받을 것:** `.harness/PLAN.md`의 "RCA Agent 테스트 — Phase 2"(실제 장애 주입 E2E, 별도 컨펌 필요) + "RCA 실패 가시성" 후속 항목. `test/rca-scenarios/send-webhook.sh`는 CRLF로 커밋됨(Windows) — Linux에서 실행 시 주의, 필요하면 `.gitattributes` 검토.

## 2026-08-28 — kube-prometheus-stack / loki Progressing 진단 세션

사용자가 "kube-prometheus-stack과 loki 두 애플리케이션만 processing 상태"라고 요청. 코드 변경 없이 클러스터 진단부터 시작했다(에이전트 쪽에 kubeconfig·유효한 AWS 자격증명이 없어, 명령은 사용자가 실행하고 출력을 붙여주는 방식으로 진행).

**클러스터 특정에 시간이 걸렸다.** 사용자의 kubectl 컨텍스트가 처음엔 다른 클러스터, 다음엔 `dpyb-prod`를 가리켜 `argocd`/`monitoring` 네임스페이스가 없었다. `argocd-cluster`라는 별칭 컨텍스트가 실제로는 `dpyb-prod`를 가리키고 있었던 것도 혼선 요인. 관측 스택은 `dpyb-dev`에 있다.

**Loki — 두 단계 문제였다.**
1. STS `loki`의 `volumeClaimTemplates.storageClassName`이 `gp2`로 굳어 있어 ArgoCD sync가 `Forbidden: updates to statefulset spec ...`으로 5회 재시도 후 실패. 이미 `DECISIONS.md`(2026-08-27 정정 항목)에 예고돼 있던 불변 필드 문제다. `kubectl delete statefulset loki` + `kubectl delete pvc storage-loki-0`(Pending이라 데이터 없음) 후 ArgoCD sync로 재생성 → `auto-ebs-sc`로 20Gi `Bound` 성공.
   - sync 트리거 시 주의: hard refresh 어노테이션은 비교만 다시 할 뿐 sync를 실행하지 않는다. `argocd` CLI는 서버 주소 미설정으로 못 썼고, `kubectl -n argocd patch application loki --type merge -p '{"operation":{...}}'`로 sync를 직접 넣어 해결했다.
2. PVC가 붙자 그동안 가려져 있던 config 오류가 드러남 — `compactor.delete-request-store should be configured when retention is enabled`. `monitoring/loki/values.yaml`에 `compactor.delete_request_store: s3` 추가로 수정하고 `helm template`로 렌더링 검증 완료. **아직 커밋/푸시 안 됨 — 병합 전까지 `loki-0`는 CrashLoopBackOff.**

**Prometheus — 오퍼레이터가 CRD보다 먼저 떠서 컨트롤러를 등록하지 못한 상태였다.** 자세한 내용은 `DECISIONS.md` 2026-08-28 항목. ArgoCD sync가 27시간째 `Running`으로 매달려 새 sync를 받지 못하던 교착까지 겹쳐 있었다. 매달린 operation 제거 + `rollout restart deployment/kube-prometheus-stack-operator`로 해소 → Prometheus `RECONCILED: True`/`AVAILABLE: True`, STS가 `auto-ebs-sc`로 생성, Application `Synced`/`Healthy`.

진단 과정에서 유용했던 명령: `kubectl -n argocd get application <name> -o jsonpath='{.status.operationState.phase}{.status.operationState.message}'`(교착 확인), 오퍼레이터 로그를 `grep -v "Endpoints is deprecated"`로 걸러 기동 로그 확인(3분 주기 경고에 밀려 `--tail=100`으로는 안 보인다).

**다음 세션이 이어받을 것:** `monitoring/loki/values.yaml` 수정 커밋·푸시·병합(작업 트리에만 있음, 티켓 브랜치 미생성 — 사용자에게 티켓 번호 확인 필요) → ArgoCD `loki` Sync → `loki-0` Running 확인 → 그다음 IRSA(`dpgy-infra-loki` IAM Role) 실제 존재 여부 확인. `.harness/PLAN.md`의 "dev 클러스터 배포 검증" 섹션 참고. 재발 방지 항목 2건은 `BACKLOG.md`에 있다.

## 2026-08-24 — ArgoCD GitOps 전환 구현 세션

- PLAN.md의 미결정 항목 중 사용자가 "ArgoCD GitOps 전환"을 선택. External Secrets Operator 백엔드는 AWS Secrets Manager로 확정(사용자 확인).
- 사용자가 세션 중간에 `backend-auth` 저장소(develop 브랜치)를 참고하라고 지시 — 임시 클론해 실제 컨벤션(`targetRevision: develop`, `finalizers: [resources-finalizer.argocd.argoproj.io]`, ArgoCD+Kustomize, 시크릿은 아직 수동)을 확인 후 모든 Application 매니페스트에 반영, 클론은 작업 후 삭제.
- `docs/adr/0003-argocd-gitops.md` 작성 (ArgoCD + ESO 결정, backend-auth 컨벤션 근거 포함).
- 구현: `monitoring/argocd/` Application 6종, `monitoring/external-secrets/`(ClusterSecretStore/ServiceAccount/ExternalSecret 2종), `monitoring/alerting/kustomization.yaml`, `discord.yaml`의 `$__env{}` 전환, `kube-prometheus-stack/values.yaml`의 `envValueFrom`, `scripts/install.sh` 축소. 상세는 `STATE.md`.
- 검증: `kubectl kustomize monitoring/alerting/` 로컬 렌더링 성공, 모든 신규/수정 YAML 파이썬 `yaml.safe_load`로 문법 검증. Helm CLI가 로컬에 없어 `helm template`은 미실행 — 사용자에게 보고 필요.
- ADR-0001의 "시크릿 관리"·"GitOps 도구" 미결정 항목을 ADR-0003 참조로 갱신.
- **커밋되지 않음** — 사용자가 커밋을 요청하면 진행.

**다음 세션이 이어받을 것:** `.harness/PLAN.md`의 "부트스트랩 전 채워야 하는 값" — Helm 차트 버전 고정(`<CHART_VERSION>` 플레이스홀더 3곳), IAM Role ARN(`<ACCOUNT_ID>` 플레이스홀더), AWS Secrets Manager 실제 시크릿 값 생성, 가능하면 `helm template`로 values.yaml 재검증. 그 외 스토리지/보존기간, Grafana 노출, 알림 threshold 미결정은 그대로 남아있음.

## 2026-08-23 — 초기 스캐폴딩 세션

- 배경 문서(`backend-book` 저장소 논의 정리본)를 바탕으로 관측 스택 방향을 결정: Prometheus+Grafana+Loki(VictoriaMetrics/EFK/SigNoz/Grafana Cloud와 비교 후) 자체 호스팅, Grafana Alerting(Discord), `ServiceMonitor`는 서비스 저장소 소유. → `docs/adr/0001-observability-stack.md`
- `monitoring/`, `secrets/`, `scripts/` 스캐폴딩 완료 (상세는 `STATE.md`).
- 저장소에 이미 존재하던 `CLAUDE.md`가 `backend-book`(Book Service) 내용으로 오염되어 있던 것을 발견 — infra 저장소 기준으로 재작성. 재작성 도중 다른 도구/세션이 같은 파일을 동시 수정 중인 정황 발견, 사용자 확인 후 덮어씀.
- 시크릿 값 자리를 `.env`로 만들고 `scripts/install.sh`가 이를 소비하도록 연동 (`DECISIONS.md` 2026-08-23 항목).
- `.harness/` 6종 파일 생성, 저장소 전역의 TODO/미결정 항목을 `.harness/PLAN.md`에 체크리스트로 정리.

**다음 세션이 이어받을 것:** `.harness/PLAN.md`의 미결정 항목들 — 특히 보존기간/스토리지, Grafana 외부 노출, 시크릿 관리 최종 방식 결정이 우선순위 높음. 아직 커밋되지 않았으니 사용자가 커밋을 요청하면 진행.
