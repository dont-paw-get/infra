# infra

Organization의 Kubernetes 클러스터를 대상으로 하는 공유 관측(Observability) 인프라 저장소.
메트릭/로그 수집, 시각화, Discord 알림 파이프라인을 소유한다. 각 서비스 저장소(`backend-book` 등)는
계측 지점(메트릭 엔드포인트 노출, 구조화 로깅)과 자신의 `ServiceMonitor` CR만 책임진다.

결정 배경과 근거는 [docs/adr/0001-observability-stack.md](docs/adr/0001-observability-stack.md) 참고.

## 스택

- **메트릭**: Prometheus + Grafana + kube-state-metrics + node-exporter (`kube-prometheus-stack` Helm 차트)
- **로그**: Loki + Alloy (DaemonSet, 모든 노드의 컨테이너 stdout 수집)
- **알림**: Grafana Alerting → Discord contact point (Alertmanager 미사용)

## 구조

```
docs/adr/                      아키텍처 결정 기록
monitoring/
  namespace.yaml                monitoring 네임스페이스
  kube-prometheus-stack/        Prometheus + Grafana Helm values
  loki/                         Loki Helm values
  alloy/                        Alloy(로그 수집 에이전트) Helm values
  alerting/
    contact-points/discord.yaml Discord 연락처 프로비저닝
    policies/                   알림 라우팅 정책
    rules/                      알림 규칙 (5xx 에러율, p99 레이턴시, 파드 상태, PVC, 로그 ERROR 급증)
secrets/README.md               시크릿 관리 정책 (실제 시크릿은 커밋하지 않음)
scripts/install.sh              설치/업그레이드 스크립트
```

## 빠른 시작

1. `secrets/README.md`에 따라 `monitoring` 네임스페이스와 Secret(Grafana admin, Discord 웹훅)을 생성한다.
2. `./scripts/install.sh` 실행.
3. 각 서비스 저장소에 `/actuator/prometheus`(또는 동등한 엔드포인트) 노출 + `ServiceMonitor` CR 추가.

## 미해결 이슈

체크리스트는 `.harness/PLAN.md` 참고 — 데이터 보존 기간, Grafana 외부 노출/인증, 시크릿 관리 최종 방식,
알림 threshold 튜닝, GitOps 도입 여부. 결정 배경/근거는 `docs/adr/0001-observability-stack.md`.
