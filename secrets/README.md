# 시크릿 관리 정책

이 저장소에는 실제 시크릿 값(Discord 웹훅 URL, Grafana admin 비밀번호 등)을 커밋하지 않는다 — `backend-book`과 동일한 원칙.

## 현재 방식: External Secrets Operator (AWS Secrets Manager)

시크릿은 AWS Secrets Manager에 저장하고, 클러스터의 External Secrets Operator(ESO)가 `ExternalSecret` CR을 통해 K8s Secret으로 동기화한다. 인증은 IRSA(ServiceAccount ↔ IAM Role)를 사용하며 AWS 액세스 키를 시크릿으로 관리하지 않는다. 결정 배경은 `docs/adr/0003-argocd-gitops.md` 참고.

| AWS Secrets Manager 키 | 형식 | 동기화 대상 K8s Secret | 매니페스트 |
|---|---|---|---|
| `dpgy-infra/grafana-admin-credentials` | JSON (`admin-user`, `admin-password` 키) | `grafana-admin-credentials` | `monitoring/external-secrets/grafana-admin-credentials.yaml` |
| `dpgy-infra/discord-webhook` | plaintext (웹훅 URL) | `discord-webhook` (key: `url`) | `monitoring/external-secrets/discord-webhook.yaml` |

`ClusterSecretStore`(`monitoring/external-secrets/cluster-secret-store.yaml`)와 IRSA용 `ServiceAccount`(`monitoring/external-secrets/service-account.yaml`)가 이 동기화를 위한 인증/연결을 담당한다. `role-arn`은 실제 AWS 계정 ID/Role 이름으로 교체가 필요하다(현재 플레이스홀더 — `docs/adr/0003-argocd-gitops.md`의 미결정 참고).

Grafana Alerting의 Discord 웹훅 URL은 K8s Secret → Grafana 파드 환경변수(`grafana.envValueFrom`, `monitoring/kube-prometheus-stack/values.yaml`) → provisioning YAML의 `$__env{DISCORD_WEBHOOK_URL}` 순으로 전달된다.

시크릿 값 자체(AWS Secrets Manager에 넣을 값)를 최초로 생성/교체하는 작업은 AWS 콘솔/CLI로 수행하며 이 저장소의 범위 밖이다.

## 이전 방식 (폐지됨)

과거에는 루트 `.env`(gitignore됨)를 `scripts/install.sh`가 읽어 `kubectl create secret`으로 직접 Secret을 생성했다. ArgoCD GitOps 전환(`docs/adr/0003-argocd-gitops.md`) 이후 이 방식은 더 이상 사용하지 않는다 — 로컬에 `.env` 파일이 남아 있다면 삭제해도 된다.

## 미결정 항목

시크릿 관리 관련 미결정 항목은 `.harness/PLAN.md`의 "GitOps 전환" 섹션에서 관리한다 (중복 기록 방지).
