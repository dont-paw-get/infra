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

## 시크릿 관리

- [ ] 수동 `.env` + `kubectl create secret` 방식(현재) 대신 External Secrets Operator 등 도입할지 결정
- [ ] CI/CD 파이프라인에서 시크릿을 어떻게 주입할지 결정 (예: GitHub Actions secrets → `kubectl`/`scripts/install.sh` 연동)

## 알림 규칙 튜닝

- [ ] 트래픽 규모 파악 후 threshold 재조정 (현재 러프한 초기값):
  - `monitoring/alerting/rules/http-error-rate.yaml` — 5xx 에러율 5%
  - `monitoring/alerting/rules/latency.yaml` — p99 레이턴시 1초
  - `monitoring/alerting/rules/pvc-usage.yaml` — PVC 사용률 85%
  - `monitoring/alerting/rules/log-error-spike.yaml` — 분당 ERROR 로그 5건
- [ ] 알림이 늘어나면 `monitoring/alerting/policies/notification-policy.yaml`의 단일 라우팅을 서비스/심각도별로 세분화

## 배포 운영

- [ ] GitOps 도구(ArgoCD/Flux) 도입 여부 결정 — 현재는 `scripts/install.sh` 수동/CI 실행 전제
- [ ] `ServiceMonitor`/`PodMonitor` CR을 실제로 각 서비스 저장소(`backend-book` 등)에 추가하도록 해당 팀에 전달 (이 저장소 범위 밖 — ADR-0001 참고)
- [ ] Book Service 등 서비스 쪽 계측(Micrometer `/actuator/prometheus` 노출, 구조화 로깅) 준비 여부 확인
