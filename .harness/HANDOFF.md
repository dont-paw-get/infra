# HANDOFF

세션마다 무엇을 했는지 (append-only 서술형 로그, 최신이 위). 단계별 완료 요약은 `STATE.md`, 결정 이유는 `DECISIONS.md`/`docs/adr/` 참고.

## 2026-08-24 — ArgoCD GitOps 전환 구현 세션

- PLAN.md의 미결정 항목 중 사용자가 "ArgoCD GitOps 전환"을 선택. External Secrets Operator 백엔드는 AWS Secrets Manager로 확정(사용자 확인).
- 사용자가 세션 중간에 `backend-auth` 저장소(develop 브랜치)를 참고하라고 지시 — 임시 클론해 실제 컨벤션(`targetRevision: develop`, `finalizers: [resources-finalizer.argocd.argoproj.io]`, ArgoCD+Kustomize, 시크릿은 아직 수동)을 확인 후 모든 Application 매니페스트에 반영, 클론은 작업 후 삭제.
- `docs/adr/0003-argocd-gitops.md` 작성 (ArgoCD + ESO 결정, backend-auth 컨벤션 근거 포함).
- 구현: `monitoring/argocd/` Application 6종, `monitoring/external-secrets/`(ClusterSecretStore/ServiceAccount/ExternalSecret 2종), `monitoring/alerting/kustomization.yaml`, `discord.yaml`의 `$__env{}` 전환, `kube-prometheus-stack/values.yaml`의 `envValueFrom`, `scripts/install.sh` 축소. 상세는 `STATE.md`.
- 검증: `kubectl kustomize monitoring/alerting/` 로컬 렌더링 성공, 모든 신규/수정 YAML 파이썬 `yaml.safe_load`로 문법 검증. Helm CLI가 로컬에 없어 `helm template`은 미실행 — 사용자에게 보고 필요.
- ADR-0001의 "시크릿 관리"·"GitOps 도구" 미결정 항목을 ADR-0003 참조로 갱신.
- **커밋되지 않음** — 사용자가 커밋을 요청하면 진행.

**다음 세션이 이어받을 것:** `.harness/PLAN.md`의 "부트스트랩 전 채워야 하는 값" — Helm 차트 버전 고정(`<CHART_VERSION>` 플레이스홀더 3곳), IAM Role ARN(`<ACCOUNT_ID>` 플레이스홀더), AWS Secrets Manager 실제 시크릿 값 생성, 가능하면 `helm template`로 values.yaml 재검증. 그 외 스토리지/보존기간, Grafana 노출, 알림 threshold 미결정은 그대로 남아있음.

## 2026-08-23 — 초기 스캐폴딩 세션

- 배경 문서(`backend-book` 저장소 논의 정리본)를 바탕으로 관측 스택 방향을 결정: Prometheus+Grafana+Loki(VictoriaMetrics/EFK/SigNoz/Grafana Cloud와 비교 후) 자체 호스팅, Grafana Alerting(Discord), `ServiceMonitor`는 서비스 저장소 소유. → `docs/adr/0001-observability-stack.md`
- `monitoring/`, `secrets/`, `scripts/` 스캐폴딩 완료 (상세는 `STATE.md`).
- 저장소에 이미 존재하던 `CLAUDE.md`가 `backend-book`(Book Service) 내용으로 오염되어 있던 것을 발견 — infra 저장소 기준으로 재작성. 재작성 도중 다른 도구/세션이 같은 파일을 동시 수정 중인 정황 발견, 사용자 확인 후 덮어씀.
- 시크릿 값 자리를 `.env`로 만들고 `scripts/install.sh`가 이를 소비하도록 연동 (`DECISIONS.md` 2026-08-23 항목).
- `.harness/` 6종 파일 생성, 저장소 전역의 TODO/미결정 항목을 `.harness/PLAN.md`에 체크리스트로 정리.

**다음 세션이 이어받을 것:** `.harness/PLAN.md`의 미결정 항목들 — 특히 보존기간/스토리지, Grafana 외부 노출, 시크릿 관리 최종 방식 결정이 우선순위 높음. 아직 커밋되지 않았으니 사용자가 커밋을 요청하면 진행.
