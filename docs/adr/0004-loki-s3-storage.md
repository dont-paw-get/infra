# ADR-0004: Loki 오브젝트 스토리지를 S3로 전환

## 상태

승인됨 (2026-08-25)

## 배경

`docs/adr/0001-observability-stack.md`에서 Loki 스토리지 백엔드(로컬 파일시스템 vs 오브젝트 스토리지)를 미결정 항목으로 남겨두고, 초기값은 로컬 파일시스템(`storage.type: filesystem`)으로 시작했다. PVC 용량 제약과 파드 재시작/장애 시 로그 유실 위험이 있어 재검토가 필요했다.

## 결정

1. **Loki 청크/룰러/어드민 스토리지를 AWS S3로 전환**한다. 버킷: `dpgy-infra-loki-logs` (리전 `ap-northeast-2`).
2. **인증은 IRSA**를 사용한다 (`monitoring/loki/values.yaml`의 `serviceAccount.annotations`) — 다른 컴포넌트(External Secrets, RCA Agent)와 동일한 패턴이며, 정적 AWS 액세스 키를 시크릿으로 관리하지 않는다.
3. **로그 보존 기간은 336h(14d)로 유지**한다 (ADR-0001 미결정 항목 해소). S3 전환으로 보존 기간을 늘리는 것 자체는 용이해졌지만, 현재는 14d로 시작하고 트래픽/비용을 보고 재조정한다.
4. `compactor.retention_enabled: true`를 명시한다 — 이 값이 없으면 `retention_period`가 설정돼 있어도 실제로 오래된 로그가 삭제되지 않는다 (기존 filesystem 구성에도 있던 잠재 문제로, 이번에 함께 수정).

## 결과

- `monitoring/loki/values.yaml`: `storage.type: s3`, `schemaConfig.configs[].object_store: s3`, `serviceAccount` 블록 추가.
- S3 버킷(`dpgy-infra-loki-logs`) 생성은 AWS 콘솔/CLI로 사용자가 직접 수행 (이 저장소 범위 밖).
- IAM Role(`dpgy-infra-loki`) 생성이 필요하다 — 신뢰 정책은 `system:serviceaccount:monitoring:loki`(chart 릴리스 이름 `loki`의 기본 ServiceAccount)로 스코프, 권한은 `s3:GetObject`/`PutObject`/`DeleteObject`/`ListBucket`을 `dpgy-infra-loki-logs`/`dpgy-infra-loki-logs/*`로 스코프. `.harness/PLAN.md`에서 추적.
- Prometheus 보존 기간/스토리지(15d/20Gi)는 이번에 함께 확정했다 (오브젝트 스토리지 전환 없이 PVC 그대로 유지) — ADR-0001 미결정 항목 해소.

## 미결정 (추후 논의 필요)

- S3 수명주기 정책(Lifecycle, 예: Glacier 전환)으로 장기 아카이빙할지 여부 — 현재는 `retention_period`로만 삭제 관리
