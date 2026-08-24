# STATE

지금까지 끝난 것의 단계 단위 요약. 세션별 서술은 `HANDOFF.md`에 남긴다.

- [x] 관측 스택 결정: Prometheus + Grafana + Loki(`kube-prometheus-stack`), 자체 호스팅, Grafana Alerting(Discord), `ServiceMonitor`는 서비스 저장소 소유 — `docs/adr/0001-observability-stack.md`
- [x] `monitoring/` 스캐폴딩: kube-prometheus-stack / Loki / Alloy Helm values, Discord contact point·알림 정책·알림 규칙 5종(5xx 에러율, p99 레이턴시, CrashLoopBackOff/OOMKilled, PVC 사용률, 로그 ERROR 급증)
- [x] ~~시크릿 관리 임시 방식(`.env` → `scripts/install.sh`)~~ → 아래 GitOps 전환에서 External Secrets Operator로 대체됨
- [x] ~~`scripts/install.sh`(`.env` 검증 → Secret/ConfigMap 생성 → Helm 3종 설치)~~ → 아래 GitOps 전환에서 부트스트랩 전용으로 축소됨
- [x] `CLAUDE.md` 크로스 툴 하네스 워크플로 문서 작성 (backend-book 오염 내용 제거, infra 저장소 기준으로 재작성)
- [x] `.harness/` 스캐폴딩 (이 문서 포함 6종)
- [x] 이상탐지/RCA Agent 도입 결정: Strands SDK + Amazon Bedrock, Grafana Alerting webhook 트리거 기반, read-only 분석/보고 전용, `monitoring` 네임스페이스에 소스 포함 배포, Bedrock 인증은 IRSA — `docs/adr/0002-anomaly-rca-agent.md`
- [x] GitOps 전환(ArgoCD + External Secrets Operator) 구현 — `docs/adr/0003-argocd-gitops.md`. `backend-auth` 저장소의 실제 컨벤션(targetRevision: develop, finalizers)을 확인해 반영
  - `monitoring/argocd/` Application CR 6종 (external-secrets, external-secrets-config, kube-prometheus-stack, loki, alloy, alerting), sync-wave로 순서 보장(-2/-1/0)
  - `monitoring/external-secrets/`: ClusterSecretStore(AWS Secrets Manager, IRSA), IRSA ServiceAccount, ExternalSecret 2종(grafana-admin-credentials, discord-webhook)
  - `monitoring/alerting/kustomization.yaml`: provisioning YAML → `grafana_alert=1` ConfigMap (configMapGenerator, `kubectl kustomize`로 렌더링 검증 완료)
  - `discord.yaml`: `${DISCORD_WEBHOOK_URL}` envsubst → Grafana `$__env{DISCORD_WEBHOOK_URL}` + `grafana.envValueFrom`으로 전환
  - `scripts/install.sh`: 네임스페이스 생성 + `monitoring/argocd/` 최초 1회 apply로 축소 (Helm 설치/Secret 생성/envsubst 로직 제거)
  - `secrets/README.md`, `README.md`, `.harness/ARCHITECTURE.md`, `docs/adr/0001-observability-stack.md`(미결정 해소 표시) 갱신
  - Helm 차트 버전 고정 완료(artifacthub.io 기준 2026-08-24): external-secrets 2.9.0, kube-prometheus-stack 88.5.4, loki 7.3.0, alloy 1.11.1
  - IRSA role-arn 계정 ID 확정(594532711953, 사용자 확인) — `monitoring/external-secrets/service-account.yaml`
  - 로컬에 Helm CLI 설치 후 4개 차트 모두 `helm template` 렌더링 검증 완료. `monitoring/loki/values.yaml`에서 발견한 버그(SimpleScalable 타겟 read/write/backend의 기본 replicas=3과 SingleBinary 모드 충돌) 수정 — `read.replicas`/`write.replicas`/`backend.replicas`를 0으로 명시
  - 부트스트랩 전 남은 값(IAM Role 실제 생성, AWS Secrets Manager 실값)은 `.harness/PLAN.md` 참고
