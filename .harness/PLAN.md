# PLAN

아직 끝나지 않은 계획과 체크리스트만 남긴다. 완료되면 항목을 지우고 `.harness/STATE.md`에 단계 한 줄로 반영한다.
배경/근거는 각 항목에 표시된 파일 참고 (주로 `docs/adr/0001-observability-stack.md`).

## RCA Agent 시나리오 테스트 커버리지 완성 (우선순위: 최상)

**상태: 확정 (2026-09-06 사용자 컨펌) — 티켓 `CLIAR-272`, 단계 1~4 한 번에 진행.**

**배경 (2026-09-06 점검):** 배포된 알림 규칙 7개(CrashLoopBackOff / OOMKilled / PVC 80%·90% /
로그 ERROR 급증 / HTTP 5xx 에러율 / p99 레이턴시) 중 실제로 Discord 알림 + RCA 후속 메시지까지
재현 가능한 것은 4종(CrashLoop / OOM / PVC / 로그ERROR)뿐이다.

- **HTTP 5xx / p99 레이턴시**: 규칙은 배포됐고 backend 5개 서비스도 계측됐으나 (1) 최소 트래픽
  게이트 `>= 0.5 req/s`를 넘기는 부하가 dev에 없고(전 서비스 idle `< 0.2 req/s`) (2) 실제 5xx/지연을
  내는 워크로드가 없어 발화시킬 수 없다. Phase 2 매니페스트도 없다.
- **Phase 1 합성 payload**: `crashloop-firing` / `http-5xx-firing` 2종뿐 — OOMKilled / PVC /
  로그ERROR / p99는 RCA→Discord 경로 스모크조차 안 된다.

**목표:** 배포된 알림 규칙 7개 전부에 대해 (a) Phase 1 합성 스모크 또는 (b) Phase 2 실제 발화 중
최소 하나로 Discord 알림 + RCA 후속 메시지를 재현할 수 있게 한다. **알림 규칙 파일은 변경하지
않는다** (기존 규칙을 그대로 발화시키는 것이 목적).

### 1. Phase 1 합성 payload 커버리지 완성 (클러스터 무변경, 저비용 — 빠른 성과)

- [ ] `test/rca-scenarios/payloads/oomkilled-firing.json` — `alertname: 파드 OOMKilled`, 라벨
      namespace/pod/container
- [ ] `test/rca-scenarios/payloads/pvc-usage-firing.json` — `alertname: PVC 사용률 초과`, 라벨
      namespace/persistentvolumeclaim
- [ ] `test/rca-scenarios/payloads/log-error-spike-firing.json` — `alertname: 로그 ERROR 급증`, 라벨 app
- [ ] `test/rca-scenarios/payloads/p99-latency-firing.json` — `alertname: p99 레이턴시 초과`, 라벨 application
- [ ] `test/rca-scenarios/payloads/http-5xx-firing.json` summary 문구 `5%` → `2%` 정정(규칙 현행값)
- [ ] 4종 `json.load` 검증, `test/rca-scenarios/README.md` Phase 1 실행 절차에 반영

### 2. Phase 2 — HTTP 5xx / p99 레이턴시 실제 발화 시나리오

알림 발화에는 Prometheus가 테스트 서비스를 스크레이핑해야 하므로 `ServiceMonitor`/`PodMonitor` CR이
필요하다. 관측 스택 정책상 이 CR은 서비스 저장소 소유이나, 여기서 만들 CR은
`test/rca-scenarios/phase2/`에 두는 **테스트 전용·수동 apply·확인 후 삭제** 리소스다(ArgoCD/CI 대상
아님). 이 예외는 2026-09-06 사용자 컨펌으로 허용됨 — `docs/adr/0001` 미결정/경계 항목에 한 줄 명시.

- [ ] `test/rca-scenarios/phase2/E-http-5xx.yaml` — 의도적으로 HTTP 500을 반환하는 최소 서비스
      (Deployment + Service) + Micrometer 호환 `http_server_requests_seconds_*` 노출 +
      `ServiceMonitor` + 부하 생성 Job(≥ 1 req/s 지속으로 게이트 초과)
- [ ] `test/rca-scenarios/phase2/F-p99-latency.yaml` — 응답을 ~2초 지연시키는 최소 서비스 + 동일
      계측 + 부하 Job. `application` 라벨은 규칙 제외 목록(`backend-librarian|backend-discovery`)과
      겹치지 않게 지정
- [ ] `test/rca-scenarios/phase2/README.md` 시나리오 표에 E·F 추가, "5xx/p99 제외" 서술 갱신
- [ ] `docs/adr/0001-observability-stack.md`에 테스트 전용 `ServiceMonitor` 예외를 한 줄 기록

### 3. (2의 후속) trace 근거 포함 검증

- [ ] E·F 테스트 서비스가 OTLP span(`otel-collector.monitoring.svc.cluster.local:4318`) +
      `trace_id` JSON 로그를 emit하도록 확장 (busybox 불가 — 경량 앱 이미지 필요)
- [ ] 발화 시 RCA Agent가 `search_traces` → `get_trace`로 병목·예외 span을 근거에 인용하는지 확인
- [ ] "RCA Agent 후속 개선"의 "Tempo 연동(CLIAR-238) 배포 후 검증" 항목과 통합

### 4. 문서 정합성 정리

- [ ] `test/rca-scenarios/phase2/C-log-error-spike.yaml` 주석 `> 5`·"분당 5건" → 5분 10건
- [ ] `test/rca-scenarios/phase2/D-pvc-usage.yaml` 주석 `> 0.85` → 80%/90% 2단계, 900Mi fill이
      두 규칙 다 발화시킴을 명시

### 검증

- payload: `python -c "import json"` 로드 / 매니페스트: `kubectl apply --dry-run=client` + YAML 문법
- 알림 규칙 파일 무변경 → helm/kustomize 렌더링 영향 없음
- 실제 발화(Phase 2)는 사용자가 dev에서 수행 — 실제 Discord 알림 발생
- 작업 브랜치: `CLIAR-272-RCA-Agent-후속-개선` (현재 브랜치, 신규 분기 없음)

## Grafana HTTPS 전환 (도메인/ACM 인증서 확보 후)

ALB Ingress로 노출은 확정했지만(2026-08-26, 사용자 확인) 도메인/ACM 인증서가 없어 현재 HTTP만 열려 있다.

- [ ] 도메인 확보 후 `monitoring/kube-prometheus-stack/values.yaml`의 `grafana.ingress.hosts`에 실제 도메인 채우기
- [ ] ACM에서 해당 도메인 인증서 발급 (도메인 소유권/DNS 검증 필요, 이 저장소 범위 밖)
- [ ] 인증서 발급 후 `annotations`에 `alb.ingress.kubernetes.io/certificate-arn`, `alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}, {"HTTPS": 443}]'`, `alb.ingress.kubernetes.io/ssl-redirect: "443"` 추가
- [ ] SSO 연동이 필요해지면 별도로 재검토 (현재는 Grafana 기본 admin 계정 로그인만 사용하기로 확정)

## 알림 규칙 튜닝

### p99 / 5xx 최소 트래픽 게이트 — 배포 후 검증 (CLIAR-261, 구현 완료)

구현·로컬 검증 완료(`STATE.md`). 브랜치 `CLIAR-261-p99-레이턴시-초과-설정-완화`. 남은 건 dev 반영 후 확인.

- [ ] `grafana-alerting` sync 후 `http-p99-latency`/`http-5xx-error-rate` 규칙이 `health: ok`로 로드되는지(게이트 `and` 쿼리 파싱)
- [ ] 트래픽 `< 0.2 req/s`인 서비스가 두 규칙 평가에서 빠지고 `DatasourceNoData` 알림이 안 뜨는지(`noDataState: OK`)
- [ ] 실트래픽(`>= 0.2 req/s`)이 붙은 서비스에서는 정상 평가되는지

### 러프한 초기값 SLO 기준 재조정 — 배포 후 검증 (구현 완료)

구현·로컬 검증 완료(`STATE.md`, `.harness/DECISIONS.md` 2026-09-03). 브랜치 `alerting-threshold-SLO-재조정`(Jira 티켓 없음). 남은 건 dev 반영 후 확인.

- [ ] `grafana-alerting` sync 후 규칙 7개(PVC 2단계 포함)가 `health: ok`로 로드되는지 — `curl -u admin:<pw> localhost:3000/api/v1/provisioning/alert-rules`에 `pvc-usage-critical` 신규 uid 확인
- [ ] p99 규칙 쿼리의 `application!~"backend-librarian|backend-discovery"` 필터가 파싱 OK, 두 서비스가 대상에서 빠지는지
- [ ] 게이트 `>= 0.5` 상향 후에도 `DatasourceNoData`가 안 뜨는지(`noDataState: OK`)

### 실측 후 재검증 (트래픽 쌓인 뒤)

- [ ] 실트래픽 분포(요청률·실제 p99·5xx 비율·ERROR 로그율) 확인 후 위 SLO 기준값을 경험값으로 보정
- [ ] librarian·discovery URI 단위 레이턴시 SLO 규칙 신설 (LLM 경로 제외한 일반 API만 별도 임계)
- [ ] 알림이 늘어나면 `monitoring/alerting/policies/notification-policy.yaml`의 단일 라우팅을 서비스/심각도별로 세분화 (PVC critical 등 severity 분기 활용)

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
