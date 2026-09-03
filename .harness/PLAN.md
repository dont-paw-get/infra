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

## CLIAR-254 OOMKilled 알림 수정 + Tempo 메모리 상향 배포 후 검증

구현·로컬 검증 완료(`STATE.md`). 남은 건 dev 반영 후 확인.

- [ ] `grafana-alerting` ArgoCD app sync 후 `pod-oom-killed` 규칙이 `health: ok`로 로드되는지(새 `and on ...` 쿼리가 파싱 에러 없이) 확인
- [ ] `kube_pod_container_status_last_terminated_timestamp` 메트릭이 클러스터 KSM에서 노출되는지 확인(`curl` Prometheus `/api/v1/query`) — 없으면 `rate(kube_pod_container_status_restarts_total[15m]) > 0` AND 방식으로 대체
- [ ] `tempo-0`가 OOM된 지 15분+ 경과 후 `파드 OOMKilled` 알림이 자동 해소(resolved)되는지 Discord/Grafana에서 확인
- [ ] `tempo` ArgoCD app sync 후 `tempo-0`가 limit 1Gi로 재기동(`kubectl -n monitoring get pod tempo-0 -o jsonpath='{.spec.containers[0].resources}'`)되고 Running 안정 확인

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
알림도 재배포됐고 dev 실측 검증(5개 ServiceMonitor `UP`, 규칙 6종 `health: ok`, Loki `app` 라벨)도
2026-09-03 완료 — `.harness/STATE.md` 참고.

- [ ] 신규 HTTP 서비스가 추가되면 같은 계측(Micrometer `application` 태그 + `ServiceMonitor` +
  OTLP endpoint + JSON 로그 `trace_id`/`level`)을 요청 — 명령 text는 2026-09-02 세션 응답 참고
