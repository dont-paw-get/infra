# ADR-0005: CI(GitHub Actions) → AWS 인증을 GitHub OIDC로 통일

## 상태

대체됨 (2026-08-27) — `docs/adr/0006-ci-access-key-revert.md` 참고. 이 ADR은 "조직 레벨에도 Secrets가 없다"는 잘못된 전제(실제로는 저장소별 Secrets이며 확인이 안 됐을 뿐)로 작성되었다.

## 배경

`monitoring/rca-agent/`의 이미지를 ECR에 빌드/푸시하는 `.github/workflows/rca-agent-build-push.yml`은 애초에 `backend-auth` 저장소의 `build-push-ecr.yml`을 참고해 IAM 사용자 액세스 키(`secrets.AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`)를 `aws-actions/configure-aws-credentials@v4`에 주입하는 방식으로 작성했다.

이후 실제로 등록을 시도하는 과정에서, 조직(`dont-paw-get`) 레벨과 각 서비스 저장소(`backend-auth` 포함) 어디에도 해당 Secrets가 등록되어 있지 않다는 것을 확인했다(2026-08-27, 사용자 확인). 즉 이 정적 액세스 키 방식은 조직 어디에서도 실제로 동작 중인 전례가 없는 상태였다 — `backend-auth`의 워크플로 파일도 작성만 되어 있을 뿐 아직 시크릿이 없어 동작하지 않는 것으로 보인다.

이 저장소의 다른 모든 AWS 인증(External Secrets Operator, RCA Agent, Loki의 S3 접근)은 이미 IRSA(Kubernetes ServiceAccount ↔ IAM Role, OIDC 연합)를 사용한다. CI에서만 장기 수명의 IAM 사용자 액세스 키를 발급/보관/로테이션하는 것은 이 컨벤션과 어긋나고, 어차피 아무 데도 확립된 전례가 없으므로 지금 바로 GitHub Actions OIDC로 가는 것이 액세스 키를 만들었다가 나중에 다시 마이그레이션하는 것보다 낫다고 판단했다.

## 검토한 대안

| 항목 | 대안 | 비고 |
|---|---|---|
| CI → AWS 인증 | IAM 사용자 + 정적 액세스 키 (`backend-auth` 워크플로가 참고한 원안) | 액세스 키 발급/보관/로테이션 부담, 이 저장소의 다른 컴포넌트(IRSA)와 컨벤션 불일치, 조직 내 실제 동작 전례 없음 — 제외 |
| | GitHub Actions OIDC + `role-to-assume` | 장기 자격증명 없이 저장소/브랜치 단위로 스코프된 IAM Role을 임시 자격증명으로 발급. 이 저장소의 IRSA 컨벤션과 동일한 "OIDC 연합" 패턴 — 채택 |
| IAM Role 신뢰 정책 스코프 | 조직 전체(`repo:dont-paw-get/*`) | 다른 저장소가 이 Role을 가져다 쓸 수 있어 최소 권한 원칙에 어긋남 — 제외 |
| | 저장소+브랜치 단위(`repo:dont-paw-get/infra:ref:refs/heads/develop`) | 이 워크플로가 실제로 실행되는 조건과 정확히 일치 — 채택. 다른 브랜치/PR에서 도용 불가 |
| IAM Role 권한 범위 | ECR 전체(`*`) | 다른 저장소의 ECR 리포지토리까지 접근 가능해져 과도함 — 제외 |
| | `dpgy-infra-rca-agent` 리포지토리로 리소스 스코프 | 이 워크플로가 push하는 대상과 정확히 일치 — 채택 |

## 결정

1. **GitHub Actions → AWS 인증은 OIDC 연합(`role-to-assume`)으로 통일한다.** IAM 사용자 액세스 키는 발급하지 않는다.
2. **AWS 계정에 GitHub Actions OIDC 자격 증명 공급자(`token.actions.githubusercontent.com`)를 등록한다** — 계정에 아직 없다면 1회만 생성하면 이후 모든 저장소/워크플로가 재사용 가능하다(이 저장소 범위에서는 `infra` 저장소용 Role 하나만 만든다).
3. **IAM Role `dpgy-infra-github-actions-rca-agent`를 생성한다.** 신뢰 정책은 `token.actions.githubusercontent.com`을 발급자로, `repo:dont-paw-get/infra:ref:refs/heads/develop`로 `sub`를 스코프한다. 권한은 ECR 리포지토리 `dpgy-infra-rca-agent`에 대한 push(`ecr:GetAuthorizationToken`은 리소스 레벨 제약이 없어 `*`, 나머지 `ecr:BatchCheckLayerAvailability`/`PutImage`/`InitiateLayerUpload`/`UploadLayerPart`/`CompleteLayerUpload`/`BatchGetImage`는 해당 리포지토리 ARN으로 제한)만 부여한다.
4. **`.github/workflows/rca-agent-build-push.yml`을 OIDC 방식으로 변경한다.** `permissions.id-token: write`를 추가하고, `configure-aws-credentials`에서 `aws-access-key-id`/`aws-secret-access-key` 대신 `role-to-assume: arn:aws:iam::594532711953:role/dpgy-infra-github-actions-rca-agent`를 사용한다.
5. **`backend-auth` 등 다른 저장소의 정적 액세스 키 방식 전환은 이 저장소 범위 밖이다.** 필요하면 각 서비스 저장소가 독립적으로 결정한다. 다만 이 ADR의 패턴(저장소+브랜치 스코프 Role, 리소스 단위 최소 권한)을 참고 사례로 남긴다.

## 결과

- `docs/adr/0005-github-actions-oidc.md`(이 문서) 신규 작성.
- `.github/workflows/rca-agent-build-push.yml`의 인증 스텝이 `role-to-assume` 방식으로 변경된다.
- IAM Role `dpgy-infra-github-actions-rca-agent` 생성이 필요하다(AWS 콘솔/CLI, 이 저장소 범위 밖 — 사용자가 직접 수행).
- `.harness/PLAN.md`의 "CI 인증을 정적 액세스 키 대신 GitHub OIDC로 전환 검토" 백로그 항목이 이 ADR로 해소되고, "IAM Role 생성"이 새 실행 항목으로 남는다.

## 미결정 (추후 논의 필요)

- GitHub Actions OIDC 공급자가 이 AWS 계정에 이미 존재하는지 확인 필요(사용자가 AWS 콘솔에서 확인 예정) — 없으면 신규 생성.
