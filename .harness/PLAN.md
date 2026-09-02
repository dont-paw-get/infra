# PLAN

아직 끝나지 않은 계획과 체크리스트만 남긴다. 완료되면 항목을 지우고 `.harness/STATE.md`에 단계 한 줄로 반영한다.
배경/근거는 각 항목에 표시된 파일 참고 (주로 `docs/adr/0001-observability-stack.md`).

## CLIAR-207 tracing stack 배포 후 검증

구현과 로컬 렌더링 검증은 완료되어 `STATE.md`로 이동했다. 남은 항목은 실제 dev 클러스터 반영 후 확인이 필요한 검증이다.

- [ ] ArgoCD sync 후 `tempo`/`otel-collector` Application이 `Synced`/`Healthy`인지 확인
- [ ] `kubectl -n monitoring get svc otel-collector tempo`로 Collector `4318`, Tempo `3200`/`4318` 내부 Service port 확인
- [ ] synthetic OTLP trace를 `http://otel-collector.monitoring.svc.cluster.local:4318/v1/traces`로 보내고 Grafana Tempo datasource에서 trace_id 조회 확인
- [ ] Grafana datasource provisioning에서 기존 Prometheus/Loki datasource와 신규 Tempo datasource가 함께 유지되는지 확인
- [ ] Loki 로그 상세에서 JSON `trace_id` derived field 클릭 → Tempo trace 이동 확인
- [ ] Tempo trace 화면의 logs query가 같은 `trace_id`의 Loki 로그를 반환하는지 확인
- [ ] backend-book/backend-auth dev overlay에 `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.monitoring.svc.cluster.local:4318` 반영 후 실제 서비스 요청 E2E 확인

## app-level 알림 재배포 배포 후 검증 (CLIAR-238 브랜치 계속)

**배경:** CLIAR-238로 RCA Agent trace tool·트레이스 소스 ADR(`docs/adr/0008`)·시나리오 테스트 손질(A·C)
완료. `backend-*` 5개 서비스(auth/book/librarian/record/discovery)가 Micrometer 계측 + dev overlay
`ServiceMonitor`를 각 저장소에서 구현 완료(2026-09-02 회신, 5개 모두 Micrometer 표준 이름 → 알림 규칙
쿼리 무수정). 이 저장소 쪽 반영(B·D)도 2026-09-02 완료 — 남은 건 dev 배포 후 실측 검증뿐.

**이 저장소에서 한 것 (미커밋):**

- B: `monitoring/alerting/kustomization.yaml`에 `grafana-alerting-http-error-rate`/`grafana-alerting-latency`
  configMapGenerator 재등록(ConfigMap 5→7, `kubectl kustomize` 확인). 규칙 파일(`rules/*.yaml`)은 무수정.
  `.harness/ARCHITECTURE.md` 알림 절 "배포 제외" 서술 → "5종 전부 배포"로 갱신.
- D: `docs/adr/0001` "결과"에 알림/트레이스 요구사항 구체화, `.harness/ARCHITECTURE.md` "서비스 저장소와의
  경계"에 서비스별 ServiceMonitor/메트릭 현황 표 추가.

**남은 검증 (dev 배포 후 — 커밋·머지 후 서비스들이 auto-sync되면):**

- [ ] Prometheus `Status > Targets`에서 `serviceMonitor/dpyb-<svc>-dev/backend-<svc>` 5개가 `UP`인지 확인
  (auth `:8000/metrics`, book `:8081/actuator/prometheus`, librarian/record/discovery `/actuator/prometheus`)
- [ ] Grafana Explore에서 `http_server_requests_seconds_bucket{application="backend-book"}` 등 조회 확인
- [ ] `curl -u admin:<pw> localhost:3000/api/v1/provisioning/alert-rules`에 `http-5xx-error-rate`/
  `http-p99-latency` 2종이 추가돼 규칙 6종이 되고 `health: ok`인지 확인
- [ ] 각 서비스 파드에 `app.kubernetes.io/name: backend-<svc>` 라벨이 있어 Loki 스트림 라벨 `app`이
  `<svc>`로 잡히는지 (`로그 ERROR 급증` 규칙이 `by (app)` 집계 — 없으면 서비스 저장소에 요청)
- [ ] threshold(5xx 5% / p99 1s)는 러프한 초기값 — 트래픽 실측 후 "알림 규칙 튜닝" 섹션에서 조정
- [ ] 실제 trace를 근거로 쓰는 레이턴시/5xx Phase 2 시나리오 추가 — "RCA Agent 후속 개선"의
  "Tempo 연동 배포 후 검증" 항목이 소유

### 커밋 분할 (제안, 미커밋 — 사용자 요청 시)

1. `feat(alerting): [CLIAR-238] HTTP 5xx·p99 레이턴시 알림 재배포` — `kustomization.yaml` + ARCHITECTURE 알림 절
2. `docs: [CLIAR-238] RCA Agent Tempo 소스 ADR + 서비스 저장소 계측 요구 반영` — ADR-0008/0002/0007/0001,
   ARCHITECTURE 서비스 경계 표
3. `test(rca-scenarios): [CLIAR-238] 트레이스 시나리오 추가 및 문서 갱신` — `test/rca-scenarios/*`

(prod overlay의 trace endpoint는 서비스 저장소가 관례 기본값을 두고 있음 — prod 클러스터에 Collector가
배포되면 실제 값 전달 필요. 이 저장소 범위 밖, `.harness/BACKLOG.md`에 기록)

## Grafana HTTPS 전환 (도메인/ACM 인증서 확보 후)

ALB Ingress로 노출은 확정했지만(2026-08-26, 사용자 확인) 도메인/ACM 인증서가 없어 현재 HTTP만 열려 있다.

- [ ] 도메인 확보 후 `monitoring/kube-prometheus-stack/values.yaml`의 `grafana.ingress.hosts`에 실제 도메인 채우기
- [ ] ACM에서 해당 도메인 인증서 발급 (도메인 소유권/DNS 검증 필요, 이 저장소 범위 밖)
- [ ] 인증서 발급 후 `annotations`에 `alb.ingress.kubernetes.io/certificate-arn`, `alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}, {"HTTPS": 443}]'`, `alb.ingress.kubernetes.io/ssl-redirect: "443"` 추가
- [ ] SSO 연동이 필요해지면 별도로 재검토 (현재는 Grafana 기본 admin 계정 로그인만 사용하기로 확정)

## 알림 규칙 튜닝

- [ ] 트래픽 규모 파악 후 threshold 재조정 (현재 러프한 초기값):
  - `monitoring/alerting/rules/http-error-rate.yaml` — 5xx 에러율 5%
  - `monitoring/alerting/rules/latency.yaml` — p99 레이턴시 1초
  - `monitoring/alerting/rules/pvc-usage.yaml` — PVC 사용률 85%
  - `monitoring/alerting/rules/log-error-spike.yaml` — 분당 ERROR 로그 5건
- [ ] 알림이 늘어나면 `monitoring/alerting/policies/notification-policy.yaml`의 단일 라우팅을 서비스/심각도별로 세분화

## RCA Agent 후속 개선

Agent는 Phase 1·2 검증을 마치고 실사용 가능한 상태다(`.harness/STATE.md`). 남은 개선 항목만 둔다.
결정 근거와 배경은 `docs/adr/0002-anomaly-rca-agent.md` 참고.

- [ ] k8s 이벤트/`describe pod` 조회 tool 추가 — CrashLoopBackOff/OOMKilled의 종료 사유·리소스 limit을 지금은 Prometheus 메트릭으로 우회 추론하고 있다. `rca-agent-irsa` ServiceAccount에 Kubernetes RBAC(get/list pods, events) 부여가 필요해 별도 논의 후 진행
- [ ] Tempo 연동(CLIAR-238) 배포 후 검증 — `search_traces`/`get_trace` tool은 dev Tempo의 실제 trace로 로컬 렌더링까지 확인됐고, Phase 1 합성 스모크(`test/rca-scenarios/payloads/http-5xx-firing.json`)로 tool 배선·부분 실패 허용도 검증 가능하다. 남은 건 실사용: 서비스 저장소 계측(위 D)이 붙은 뒤 레이턴시/5xx/로그ERROR 알림이 실제로 발화했을 때 Agent가 trace를 조회해 병목/실패 span을 근거에 포함하는지 확인 + `test/rca-scenarios/phase2/`에 실제 지연·5xx 장애 주입 시나리오(OTLP span + `trace_id` 로그 생성) 추가
- [ ] (선택) trace 기반 알림 규칙 — 현재 알림 5종은 모두 메트릭/로그 기반. Tempo metrics-generator(span RED/service graph)를 켜면 span error rate·레이턴시 알림을 trace에서 직접 낼 수 있으나, 현재 `monitoring/tempo/values.yaml`은 dev single-binary 최소 구성이라 generator 미활성 — 필요해지면 별도 논의
- [ ] 분석 품질 튜닝 — Phase 2에서 Agent가 매번 "테스트 워크로드로 추정"을 결론에 포함했다. 실제 운영 알림에서도 유효한 판단인지, system prompt에 운영/테스트 구분 힌트를 줄지 검토
- [ ] 동시 분석 수 제한 — 현재 `BackgroundTasks`로 무제한 병렬 실행. 알림이 한꺼번에 몰리면 Bedrock 호출이 동시에 터진다. `asyncio.Queue` + 워커로 전환할지 검토(`.harness/DECISIONS.md` 2026-08-29 참고)

## RCA 실패 재시도 정책 (ADR-0002 미결정)

- [ ] 가시화는 2026-08-29 해소됨(`analyze()` 실패 시 Discord에 "RCA 분석 실패" 전송). 남은 건 **재시도** — 실패한 분석을 다시 돌릴 방법이 없다. Grafana `repeat_interval: 4h`에 기대는 것 외에 Agent 자체 재시도(백오프)를 둘지 논의 필요

## 서비스 저장소 연동

`backend-*` 5개 서비스의 `ServiceMonitor`/Micrometer/트레이스/구조화 로그 구현은 2026-09-02 완료
(각 서비스 저장소, `.harness/STATE.md`·`.harness/ARCHITECTURE.md` 표). `http-error-rate`/`latency`
알림도 재배포됨. dev 실측 검증만 위 "app-level 알림 재배포 배포 후 검증" 섹션에 남아 있다.

- [ ] 신규 HTTP 서비스가 추가되면 같은 계측(Micrometer `application` 태그 + `ServiceMonitor` +
  OTLP endpoint + JSON 로그 `trace_id`/`level`)을 요청 — 명령 text는 2026-09-02 세션 응답 참고
