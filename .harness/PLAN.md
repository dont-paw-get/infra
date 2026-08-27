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
- [ ] CI 파이프라인 실제 동작 확인 — `infra` 저장소에 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` 등록 완료(2026-08-27, 사용자). `monitoring/rca-agent/**` 변경을 `develop`에 push하거나 Actions 탭에서 `rca-agent-build-push.yml`을 workflow_dispatch로 수동 실행해 ECR push/이미지 태그 갱신 커밋이 성공하는지 확인 필요
- [ ] Agent 장애/타임아웃 시 재시도·알림 정책 (RCA 실패를 어떻게 가시화할지) — ADR-0002 미결정 항목

## dev 클러스터 배포 검증 (부트스트랩 중 실제 발견된 이슈)

2026-08-27 사용자 확인: `rca-agent`를 제외한 모든 Application이 `Synced`/`Healthy`. 자세한 진단 경위는 `.harness/STATE.md` 참고.

- [ ] IAM 사용자 `gha-ecr-pusher`에 ECR push 권한(`ecr:BatchCheckLayerAvailability`/`InitiateLayerUpload`/`UploadLayerPart`/`CompleteLayerUpload`/`PutImage`/`BatchGetImage`, 리소스는 `dpgy-infra-rca-agent` 리포지토리로 스코프) 추가 후 CI 재실행(Actions 탭에서 Re-run failed jobs) → 이미지 push 성공 확인
- [ ] 이미지 push 성공 후 `rca-agent` Application이 새 이미지를 pull해 `Synced`/`Healthy`로 전환되는지 확인 (현재 `ImagePullBackOff`)

## 서비스 저장소 연동

- [ ] `ServiceMonitor`/`PodMonitor` CR을 실제로 각 서비스 저장소(`backend-book` 등)에 추가하도록 해당 팀에 전달 (이 저장소 범위 밖 — ADR-0001 참고)
- [ ] Book Service 등 서비스 쪽 계측(Micrometer `/actuator/prometheus` 노출, 구조화 로깅) 준비 여부 확인
- [ ] 위 계측이 붙으면 `http-error-rate`/`latency` 알림(현재 `monitoring/alerting/kustomization.yaml`에서 배포 제외)을 다시 configMapGenerator에 추가
