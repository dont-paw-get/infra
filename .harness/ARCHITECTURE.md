# ARCHITECTURE

지금의 관측 스택 구성과 컨벤션 (현재 상태 스냅샷). 왜 이렇게 정했는지는 `docs/adr/0001-observability-stack.md` 참고, 진행 상황은 `STATE.md` 참고.

## 네임스페이스 / Helm 릴리스

| 릴리스 이름 | 차트 | repo | values |
|---|---|---|---|
| `kube-prometheus-stack` | `prometheus-community/kube-prometheus-stack` | prometheus-community | `monitoring/kube-prometheus-stack/values.yaml` |
| `loki` | `grafana/loki` | grafana | `monitoring/loki/values.yaml` |
| `alloy` | `grafana/alloy` | grafana | `monitoring/alloy/values.yaml` |

모두 `monitoring` 네임스페이스(`monitoring/namespace.yaml`)에 설치한다.

## 메트릭

- Prometheus가 `serviceMonitorSelectorNilUsesHelmValues: false`로 설정되어 전 네임스페이스의 `ServiceMonitor`/`PodMonitor`를 스크레이핑 대상으로 인식한다.
- Alertmanager는 비활성화(`alertmanager.enabled: false`) — 알림은 Grafana Alerting이 담당.
- Prometheus 보존/스토리지는 임시값(15d/20Gi) — `.harness/PLAN.md`의 미결정 항목.

## 로그

- Loki는 SingleBinary 모드, filesystem 스토리지(임시), 보존 336h(14d) — `.harness/PLAN.md`의 미결정 항목.
- Alloy가 DaemonSet으로 모든 노드에서 컨테이너 stdout을 수집해 `loki-gateway.monitoring.svc.cluster.local`로 전송한다.
- 애플리케이션은 stdout에 JSON 구조화 로그(`level` 필드 포함)를 출력해야 `monitoring/alerting/rules/log-error-spike.yaml`의 LogQL이 동작한다.

## Grafana

- Unified Alerting 활성화, legacy alerting 비활성화.
- 기본 Prometheus 데이터소스(차트 기본 uid `prometheus`) + 추가 Loki 데이터소스(uid `loki`, `additionalDataSources`로 등록).
- admin 계정은 `existingSecret: grafana-admin-credentials` 참조 (값은 `.env` → `scripts/install.sh`가 생성).
- Ingress 비활성화 — 외부 노출 방식 미정 (`.harness/PLAN.md`).
- `sidecar.alerts` 활성화, `label: grafana_alert`, `labelValue: "1"`, `searchNamespace: monitoring` — 이 라벨의 ConfigMap을 자동으로 provisioning에 반영.

## 알림 (Grafana Alerting)

- Contact point: `discord-webhook` (`monitoring/alerting/contact-points/discord.yaml`), 값은 `${DISCORD_WEBHOOK_URL}` 자리표시자를 `scripts/install.sh`가 `envsubst`로 치환.
- Notification policy: 전체 알림을 `discord-webhook`으로 라우팅 (`monitoring/alerting/policies/notification-policy.yaml`).
- Rules 5종 (`monitoring/alerting/rules/`): HTTP 5xx 에러율, p99 레이턴시, CrashLoopBackOff/OOMKilled, PVC 사용률, 로그 ERROR 급증. threshold는 모두 임시값.
- provisioning 배포 메커니즘: `scripts/install.sh`가 각 YAML을 `grafana_alert=1` 라벨의 ConfigMap으로 만들어 적용 → Grafana sidecar가 읽어감.

## 시크릿

- 루트 `.env`(gitignore됨)에 `GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`, `DISCORD_WEBHOOK_URL`.
- `scripts/install.sh`가 `.env`를 source해 `grafana-admin-credentials`, `discord-webhook` K8s Secret을 생성/갱신 (재실행 안전, `--dry-run=client -o yaml | kubectl apply -f -` 패턴).
- 상세 정책은 `secrets/README.md` 참고.

## 서비스 저장소와의 경계

- 이 저장소는 수집·저장·시각화·알림 파이프라인만 소유한다.
- `ServiceMonitor`/`PodMonitor` CR, 메트릭 엔드포인트 노출, 구조화 로깅은 각 서비스 저장소(`backend-book` 등) 책임 — 이 저장소에는 두지 않는다.
