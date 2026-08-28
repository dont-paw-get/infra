# PLAN

아직 끝나지 않은 계획과 체크리스트만 남긴다. 완료되면 항목을 지우고 `.harness/STATE.md`에 단계 한 줄로 반영한다.
배경/근거는 각 항목에 표시된 파일 참고 (주로 `docs/adr/0001-observability-stack.md`).

## Grafana HTTPS 전환 (도메인/ACM 인증서 확보 후)

ALB Ingress로 노출은 확정했지만(2026-08-26, 사용자 확인) 도메인/ACM 인증서가 없어 현재 HTTP만 열려 있다.

- [ ] 도메인 확보 후 `monitoring/kube-prometheus-stack/values.yaml`의 `grafana.ingress.hosts`에 실제 도메인 채우기
- [ ] ACM에서 해당 도메인 인증서 발급 (도메인 소유권/DNS 검증 필요, 이 저장소 범위 밖)
- [ ] 인증서 발급 후 `annotations`에 `alb.ingress.kubernetes.io/certificate-arn`, `alb.ingress.kubernetes.io/listen-ports: '[{"HTTP": 80}, {"HTTPS": 443}]'`, `alb.ingress.kubernetes.io/ssl-redirect: "443"` 추가
- [ ] SSO 연동이 필요해지면 별도로 재검토 (현재는 Grafana 기본 admin 계정 로그인만 사용하기로 확정)

## 알림 규칙 튜닝

- [ ] 트래픽 규모 파악 후 threshold 재조정 (현재 러프한 초기값):
  - `monitoring/alerting/rules/http-error-rate.yaml` — 5xx 에러율 5% (현재 배포 제외 상태, 아래 "서비스 저장소 연동" 참고)
  - `monitoring/alerting/rules/latency.yaml` — p99 레이턴시 1초 (현재 배포 제외 상태, 아래 "서비스 저장소 연동" 참고)
  - `monitoring/alerting/rules/pvc-usage.yaml` — PVC 사용률 85%
  - `monitoring/alerting/rules/log-error-spike.yaml` — 분당 ERROR 로그 5건
- [ ] 알림이 늘어나면 `monitoring/alerting/policies/notification-policy.yaml`의 단일 라우팅을 서비스/심각도별로 세분화

## 이상탐지/근본원인분석(RCA) Agent 도입 (스캐폴딩 + IRSA 완료 — 프롬프트 다듬기·이미지 파이프라인 대기)

Strands SDK(AWS) + Amazon Bedrock으로 Grafana Alerting 발화를 트리거 받아 RCA를 수행하고 Discord에 보고하는 Agent를 `monitoring` 네임스페이스(공유 인프라)에 추가했다. 결정 근거와 배경은 `docs/adr/0002-anomaly-rca-agent.md` 참고.

**남은 작업**
- [ ] Bedrock에서 `anthropic.claude-sonnet-5` 최초 호출 전 Anthropic use case 양식 제출 확인 — AWS가 2025-10 Model access 콘솔 페이지를 폐지, 모델은 첫 호출 시 자동 활성화되나 Anthropic 모델만 예외로 `PutUseCaseForModelAccess`(1회성 양식) 제출이 필요함. Bedrock 콘솔 Model catalog > Claude Sonnet 5 > Playground에서 첫 메시지를 보내 양식 제출/확인
  - 2026-08-26: 사용자 계정에 현재 권한 없음 확인 — 관리자에게 권한 요청 예정, 응답 대기 중 (blocked)
- [ ] (백로그) k8s 이벤트/describe pod 조회 tool 추가 — CrashLoopBackOff/OOMKilled 원인(재시작 사유, 리소스 limit 초과 등) 파악에 유용하나, `rca-agent-irsa` ServiceAccount에 새 Kubernetes RBAC(get/list pods, events) 부여가 필요해 별도 논의 후 진행. 현재는 Prometheus/Loki만 조회하는 순수 read 권한만 있음
- [ ] Agent 장애/타임아웃 시 재시도·알림 정책 (RCA 실패를 어떻게 가시화할지) — ADR-0002 미결정 항목

## RCA Agent 테스트 — Phase 2 (실제 장애 주입 E2E) — 매니페스트 작성됨, 실행 대기

Phase 1(합성 webhook 스모크 테스트)은 완료 — `.harness/STATE.md` 참고.
사용자 결정(2026-08-28): 시나리오 A/B/C/D 전부, 브랜치 `CLIAR-159` 재사용.

**산출물 `test/rca-scenarios/phase2/` (작성 완료)**
- [x] `namespace.yaml` — `rca-test` (라벨 `rca-test: "true"`)
- [x] `A-crashloop.yaml` — busybox 10초 뒤 `exit 1` 반복 → `파드 CrashLoopBackOff` (for 2m)
- [x] `B-oomkill.yaml` — mem limit 32Mi + `tail /dev/zero` → `파드 OOMKilled` (for 0m). CrashLoop 부수 발화 가능(분석 2회)
- [x] `C-log-error-spike.yaml` — 5초마다 JSON `level=ERROR` stdout(분당 12건). 파드 `app.kubernetes.io/name: rca-test-logspike` → Loki `app` 라벨. `로그 ERROR 급증` (for 5m). loki-0 Running 전제
- [x] `D-pvc-usage.yaml` — `auto-ebs-sc` 1Gi PVC + Job이 `dd` 900MiB 채우고 `sleep 3600`으로 마운트 유지. `PVC 사용률 초과` (for 10m + interval 5m → 15~20분). expr에 네임스페이스 필터 없음(클러스터 전체 대상)
- [x] `README.md` — 실행 순서, 대기 시간, **정리 명령**, Discord 공지 안내, 알림 안 뜰 때 디버깅
- [x] `kubectl apply --dry-run=client -f test/rca-scenarios/phase2/` 전부 통과, UTF-8 YAML 로드 확인

**실행 전 사용자 확인 (README에도 있음)**
- [ ] `kubectl -n monitoring get pod loki-0` → `Running 2/2`? 아니면 C 스킵
- [ ] `kubectl get pvc -A` / Grafana에서 이미 85% 넘는 PVC 있는지 → 있으면 D가 노이즈에 묻힘
- [ ] 팀에 Discord 알림 6~8건 발생 공지

**실행 절차 (시나리오 하나씩)**
1. `kubectl apply -f test/rca-scenarios/phase2/namespace.yaml` (최초 1회)
2. `kubectl apply -f test/rca-scenarios/phase2/<A|B|C|D>-*.yaml`
3. 발화 확인 (Grafana Alerting > Active) → Discord에 **원본 알림 + `RCA: <알림명>`** 둘 다, RCA가 실제 메트릭/로그 인용하는지
4. `kubectl delete -f test/rca-scenarios/phase2/<파일>` (즉시)
5. 다음 시나리오
6. 끝나면 `kubectl delete ns rca-test`

**비용/리스크**: 분석 1회당 수십 센트, 전체 ~$1~2. 최대 리스크는 정리 누락(firing 유지 시 4h마다 재분석).

**실행 후**: 결과를 `.harness/STATE.md`에 반영하고 이 섹션 제거. RCA 품질 이슈(빈 결과 처리, 라벨 혼동 등) 발견 시 `monitoring/rca-agent/src/analyzer.py` 조정 항목으로.

## RCA 실패 가시성 (Phase 1 파생 후속)

- [ ] `analyze()`가 예외를 던지면 `main.py`의 `/webhook`이 500만 반환하고 Discord엔 아무 것도 안 간다 — 원본 알림과 독립 경로라 사용자는 RCA가 실패했는지조차 모른다. ADR-0002 "미결정: Agent 장애/타임아웃 시 정책"과 직결. 최소한 실패 시 Discord에 "RCA 분석 실패" 짧은 메시지라도 보내는 처리 검토 (`monitoring/rca-agent/src/main.py` / `notifier.py`)

## dev 클러스터 배포 검증 (부트스트랩 중 실제 발견된 이슈)

2026-08-28 사용자 확인: `loki`를 제외한 모든 Application이 `Synced`/`Healthy`. 자세한 진단 경위는 `.harness/STATE.md`/`DECISIONS.md` 참고.

- [ ] `monitoring/loki/values.yaml`의 `compactor.delete_request_store: s3` 수정을 `develop`에 병합한 뒤, ArgoCD `loki` Sync → `kubectl -n monitoring get pod loki-0`가 `Running 2/2`로 전환되는지 확인. 아직 병합 전이라 `loki-0`는 계속 `CrashLoopBackOff` 상태다
- [ ] `loki-0`가 Running이 된 뒤 S3 접근이 실제로 되는지 확인 — IAM Role `arn:aws:iam::594532711953:role/dpgy-infra-loki`(IRSA) 생성 여부가 아직 검증되지 않았다. `kubectl -n monitoring logs loki-0 -c loki | grep -i "s3\|credential\|denied"`

## 서비스 저장소 연동

- [ ] `ServiceMonitor`/`PodMonitor` CR을 실제로 각 서비스 저장소(`backend-book` 등)에 추가하도록 해당 팀에 전달 (이 저장소 범위 밖 — ADR-0001 참고)
- [ ] Book Service 등 서비스 쪽 계측(Micrometer `/actuator/prometheus` 노출, 구조화 로깅) 준비 여부 확인
- [ ] 위 계측이 붙으면 `http-error-rate`/`latency` 알림(현재 `monitoring/alerting/kustomization.yaml`에서 배포 제외)을 다시 configMapGenerator에 추가
