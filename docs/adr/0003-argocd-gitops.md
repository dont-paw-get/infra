# ADR-0003: GitOps 전환 (ArgoCD + External Secrets Operator)

## 상태

승인됨 (2026-08-24)

## 배경

`docs/adr/0001-observability-stack.md`는 "GitOps 도구(ArgoCD/Flux) 도입 여부"와 "시크릿 관리 방식 최종 확정"을 미결정으로 남겼다. 지금까지는 `scripts/install.sh`가 `.env`를 읽어 `kubectl`/`helm upgrade --install`을 수동 실행하는 방식이었다. `backend-auth` 저장소(`https://github.com/dont-paw-get/backend-auth`, `develop` 브랜치 기준)가 이미 ArgoCD + Kustomize 기반 Git 자동 배포(GitOps)를 도입해 운영 중이며, 이 저장소도 동일한 배포 방식을 따르기로 한다.

`backend-auth`에서 확인한 실제 컨벤션(`argocd/application-dev.yaml`, `docs/deploy-eks-argocd.md`):
- ArgoCD 자체는 클러스터에 별도 설치(이 저장소 범위 밖과 동일한 전제).
- `Application`의 `targetRevision`은 실제 사용 중인 환경의 브랜치를 그대로 추적한다 — 현재 유일하게 쓰는 개발 환경은 `develop` 브랜치를 추적하고, `main`/prod는 아직 주석 처리된 미사용 상태다.
- `Application.metadata.finalizers: [resources-finalizer.argocd.argoproj.io]`로 Application 삭제 시 하위 리소스가 함께 정리되도록 한다.
- `syncPolicy.automated: {prune: true, selfHeal: true}` + `syncOptions: [CreateNamespace=true]`.
- 시크릿은 아직 `kubectl create secret` 수동 생성이며, 문서에는 "Git으로 관리하고 싶다면 SealedSecrets 또는 External Secrets Operator"를 옵션으로만 언급한다 — 즉 ESO를 이 저장소보다 먼저 도입해 확립한 컨벤션은 없다. 이 저장소의 ESO 채택은 별개의 결정이며 아래 "시크릿 관리" 항목 참고.

이 저장소는 관측 스택이 dev/prod로 나뉘지 않는 클러스터 공유 인프라이므로, `backend-auth`의 dev 환경과 동일하게 실제 배포에 쓰이는 브랜치(`develop`)를 추적한다.

## 검토한 대안

| 항목 | 대안 | 비고 |
|---|---|---|
| GitOps 도구 | ArgoCD | 이미 클러스터에 준비되어 있고 다른 서비스 저장소가 동일하게 사용 중 — 채택 |
| | Flux | 클러스터에 준비되어 있지 않음, 도구 통일 이점이 없어 제외 |
| Application 등록 방식 | App-of-Apps 루트 | 앱이 늘어나면 유리하나, 지금은 릴리스 5개(External Secrets, kube-prometheus-stack, Loki, Alloy, alerting)뿐이라 루트 관리 오버헤드가 이점보다 큼 |
| | 개별(flat) Application 등록 | 릴리스별 Application CR을 저장소에 두고 최초 1회 `kubectl apply`로 등록 — 채택. 앱 개수가 늘어나면 ApplicationSet 전환 후보 |
| 3rd-party Helm 차트 배포 방식 | ArgoCD 네이티브 Helm 소스(`sources` + `$values` ref) | 차트는 원격 Helm repo에서, values는 이 저장소 git 경로에서 가져오는 멀티소스 구성. 차트 자체를 벤더링하지 않아 업스트림 추적이 쉬움 — kube-prometheus-stack/Loki/Alloy/External Secrets Operator에 채택 |
| | Kustomize `helmCharts` 인플레이터 | repo-server에 `--enable-helm` 활성화가 추가로 필요하고 CRD 처리 등 제약이 있어 이번엔 채택하지 않음 |
| 이 저장소 소유 리소스(Grafana Alerting ConfigMap, ExternalSecret/ClusterSecretStore) 배포 방식 | Kustomize | 순수 YAML 매니페스트/`configMapGenerator`로 구성 — 다른 서비스 저장소의 YAML/Kustomize 컨벤션과 동일 — 채택 |
| 시크릿 관리 | External Secrets Operator (AWS Secrets Manager, IRSA) | `.env` 수동 방식을 대체, GitOps와 궁합(선언적 `ExternalSecret` CR) — 채택. RCA Agent(ADR-0002)가 이미 EKS+IRSA를 전제하므로 인증 방식 재사용 |
| | AWS Systems Manager Parameter Store | 저장소 규모(시크릿 2~3개)엔 충분하지만 Secrets Manager와 동일한 노력으로 도입 가능해 로테이션 등 부가 기능이 있는 Secrets Manager를 선택 |
| | `.env` + `scripts/install.sh` 수동 방식 유지 | GitOps 자동 동기화와 맞지 않음(사람이 수동 실행해야 갱신됨) — 폐지 |

## 결정

1. **ArgoCD를 GitOps 도구로 사용한다.** ArgoCD 자체의 설치/운영은 이 저장소 범위 밖(클러스터에 이미 준비됨)이며, 이 저장소는 `Application` CR과 배포 대상 매니페스트만 소유한다.
2. **Application은 App-of-Apps 루트 없이 개별(flat) 등록.** `monitoring/argocd/`에 릴리스별 `Application` CR을 두고 최초 1회 `kubectl apply -f monitoring/argocd/`로 등록한다. 이후 변경은 Git 커밋 → ArgoCD 자동 동기화(`automated: selfHeal + prune`)로 반영된다. 앱 개수가 늘어나면 ApplicationSet 전환을 재검토한다.
3. **소스 타입은 리소스 성격에 따라 구분한다.**
   - 3rd-party Helm 차트(kube-prometheus-stack, Loki, Alloy, External Secrets Operator): ArgoCD 멀티소스 — 차트는 업스트림 Helm repo에서, `valueFiles`는 이 저장소의 `monitoring/*/values.yaml`을 `$values` ref로 가져온다.
   - 원본 그대로는 K8s 매니페스트가 아닌 리소스(Grafana Alerting provisioning YAML): Kustomize. `monitoring/alerting/kustomization.yaml`이 기존 provisioning YAML을 `configMapGenerator`로 감싸 `grafana_alert=1` 라벨의 ConfigMap을 생성한다(기존 `scripts/install.sh`의 `envsubst`+`kubectl create configmap` 로직을 대체). `kubectl kustomize monitoring/alerting/`로 로컬 렌더링 검증 완료.
   - 그 자체로 이미 유효한 K8s 매니페스트인 리소스(ServiceAccount, ClusterSecretStore, ExternalSecret): `kustomization.yaml` 없이 순수 YAML 디렉터리로 둔다. ArgoCD가 디렉터리 타입으로 자동 인식해 그대로 적용한다.
   - 세 방식 모두 "Git 커밋이 곧 배포"인 GitOps 원칙과 `backend-auth`의 ArgoCD+Kustomize 컨벤션을 따른다.
4. **동기화 순서**: ArgoCD `sync-wave` 어노테이션으로 External Secrets Operator(wave -2) → ClusterSecretStore/ExternalSecret(wave -1) → kube-prometheus-stack/Loki/Alloy/alerting(wave 0) 순서를 보장한다. Grafana(Secret `grafana-admin-credentials`)와 alerting(env var `DISCORD_WEBHOOK_URL`)이 ExternalSecret이 만든 Secret에 의존하기 때문이다.
5. **시크릿 관리: External Secrets Operator + AWS Secrets Manager.** `ClusterSecretStore`가 IRSA(ServiceAccount ↔ IAM Role)로 AWS Secrets Manager에 접근하고, `ExternalSecret` CR이 `grafana-admin-credentials`, `discord-webhook` K8s Secret을 생성/갱신한다. 루트 `.env` + `scripts/install.sh`의 수동 Secret 생성 방식은 폐지한다.
6. **Grafana Alerting의 시크릿 참조 방식 변경.** 기존에는 `scripts/install.sh`가 셸 `envsubst`로 `${DISCORD_WEBHOOK_URL}`을 치환했다. GitOps 환경에서는 이 수동 스크립트 실행이 사라지므로, Grafana의 자체 provisioning 파일 환경변수 확장 문법(`$__env{VARNAME}`)을 사용한다. `discord-webhook` Secret의 `url` 키를 kube-prometheus-stack 차트의 `grafana.envValueFrom`으로 Grafana 파드 환경변수(`DISCORD_WEBHOOK_URL`)에 주입하고, provisioning YAML은 `$__env{DISCORD_WEBHOOK_URL}`을 참조한다.
7. **`scripts/install.sh`는 최초 부트스트랩 전용으로 대폭 축소.** `monitoring` 네임스페이스 생성과 `monitoring/argocd/*.yaml` 최초 1회 `kubectl apply`만 남긴다. Helm 설치, Secret 생성, envsubst 로직은 모두 제거한다(ArgoCD + ESO가 대체).
8. **`backend-auth` 컨벤션을 그대로 따른다.** 모든 `Application`은 `targetRevision: develop`(이 저장소는 dev/prod로 나뉘지 않는 단일 클러스터 공유 인프라이므로, `backend-auth`의 실사용 환경과 동일하게 `develop`을 추적한다)과 `metadata.finalizers: [resources-finalizer.argocd.argoproj.io]`(Application 삭제 시 하위 리소스 cascade 정리)를 둔다. 릴리스 승격이 필요해지면(예: `main` 별도 추적) 이 항목을 갱신한다.
9. **서비스 저장소(`backend-book` 등)는 이 저장소의 ArgoCD Application으로 관리하지 않는다.** 이 저장소는 관측 스택(공유 인프라)만 소유하며, 서비스 저장소의 GitOps 전환은 각 서비스 저장소가 독립적으로 결정·소유한다.

## 결과

- `monitoring/argocd/`에 Application CR 5종(external-secrets, external-secrets-config, kube-prometheus-stack, loki, alloy, alerting — 실제로는 6개 파일, external-secrets-config가 ClusterSecretStore/ExternalSecret 매니페스트를 감싸는 Application)이 추가된다.
- `monitoring/external-secrets/`에 `ClusterSecretStore`, IRSA용 `ServiceAccount`, `ExternalSecret` 2종이 추가된다.
- `monitoring/alerting/kustomization.yaml`이 추가되고 `contact-points/discord.yaml`의 시크릿 참조 문법이 변경된다.
- `scripts/install.sh`, `secrets/README.md`, `.harness/ARCHITECTURE.md`, `README.md`가 새 배포/시크릿 방식에 맞게 갱신된다.
- ADR-0001의 "GitOps 도구 도입 여부"·"시크릿 관리 방식 최종 확정" 미결정 항목이 이 ADR로 해소된다.

## 미결정 (추후 논의 필요)

(현재 없음 — Helm `targetRevision` 고정, IAM Role(IRSA) 생성 모두 완료. `.harness/STATE.md` 참고)
