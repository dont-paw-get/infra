# PLAN

아직 끝나지 않은 계획과 체크리스트만 남긴다. 완료되면 항목을 지우고 `.harness/STATE.md`에 단계 한 줄로 반영한다.
배경/근거는 각 항목에 표시된 파일 참고 (주로 `docs/adr/0001-observability-stack.md`).

## 스토리지 / 보존 기간

- [ ] Prometheus 데이터 보존 기간·PVC 용량 확정 (현재 `monitoring/kube-prometheus-stack/values.yaml`의 `retention: 15d`, `storage: 20Gi`는 임시값)
- [ ] Loki 데이터 보존 기간·오브젝트 스토리지(S3 등) 연동 여부 확정 (현재 `monitoring/loki/values.yaml`의 `retention_period: 336h`(14d), `storage.type: filesystem`은 임시값)

## Grafana 노출 / 인증

- [ ] Grafana 외부 노출 방식(Ingress) 결정 — 도메인, TLS
- [ ] Grafana 접근 제어/인증 방식 결정 (SSO 연동 여부 등)
- [ ] 위 결정 후 `monitoring/kube-prometheus-stack/values.yaml`의 `grafana.ingress.enabled: false`를 실제 설정으로 교체

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
- [ ] Bedrock 프롬프트/도구(PromQL·LogQL 조사 전략) 다듬기 — `monitoring/rca-agent/src/analyzer.py`는 최소 동작 스켈레톤 수준
- [ ] Bedrock 콘솔에서 `anthropic.claude-sonnet-5` 모델 액세스(Model access) 승인 여부 확인
- [ ] 이미지 빌드/푸시 파이프라인(ECR 저장소, CI) 구성 — 이 저장소에 아직 없음. `monitoring/rca-agent/k8s/deployment.yaml`의 image는 placeholder
- [ ] Agent 장애/타임아웃 시 재시도·알림 정책 (RCA 실패를 어떻게 가시화할지) — ADR-0002 미결정 항목

## 서비스 저장소 연동

- [ ] `ServiceMonitor`/`PodMonitor` CR을 실제로 각 서비스 저장소(`backend-book` 등)에 추가하도록 해당 팀에 전달 (이 저장소 범위 밖 — ADR-0001 참고)
- [ ] Book Service 등 서비스 쪽 계측(Micrometer `/actuator/prometheus` 노출, 구조화 로깅) 준비 여부 확인
- [ ] 위 계측이 붙으면 `http-error-rate`/`latency` 알림(현재 `monitoring/alerting/kustomization.yaml`에서 배포 제외)을 다시 configMapGenerator에 추가
