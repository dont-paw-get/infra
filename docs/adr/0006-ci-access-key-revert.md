# ADR-0006: CI(GitHub Actions) → AWS 인증은 저장소별 액세스 키로 되돌림

## 상태

승인됨 (2026-08-27)

## 배경

`docs/adr/0005-github-actions-oidc.md`는 "조직 레벨과 서비스 저장소 어디에도 `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` Secrets가 없다"는 관찰을 근거로 GitHub OIDC(`role-to-assume`)로 전환하기로 했다.

이후 사용자가 확인한 결과, 이 조직의 Secrets 관리 방식은 애초에 **조직 레벨 공유가 아니라 저장소별(repo-level) 개별 등록**이었다. 즉 `backend-auth` 등 다른 저장소가 각자 자기 저장소에 Secrets를 등록해 쓰고 있을 뿐이고, `infra` 저장소에는 아직 등록이 안 되어 있었던 것뿐이다 — "조직 어디에도 전례가 없다"는 ADR-0005의 전제가 틀렸다.

## 검토한 대안

| 항목 | 대안 | 비고 |
|---|---|---|
| CI → AWS 인증 | GitHub Actions OIDC (`role-to-assume`, ADR-0005 결정) | IRSA와 컨벤션은 맞지만, 전제였던 "조직 내 전례 없음"이 틀렸으므로 이걸 뒤집을 이유가 사라짐. 이 저장소만 별도 방식을 쓰면 오히려 다른 서비스 저장소(`backend-auth` 등)의 실제 컨벤션과 어긋남 — 제외 |
| | 저장소별 IAM 사용자 액세스 키 (`infra` 저장소에 자체 등록) | 조직의 실제 확립된 컨벤션(각 저장소가 자기 Secrets를 가짐)과 일치. 추가 인프라(OIDC 공급자, Role) 없이 바로 등록 가능 — 채택 |

## 결정

1. **`.github/workflows/rca-agent-build-push.yml`을 IAM 사용자 액세스 키 방식으로 되돌린다.** `configure-aws-credentials` 스텝은 `aws-access-key-id`/`aws-secret-access-key`를 `secrets.AWS_ACCESS_KEY_ID`/`secrets.AWS_SECRET_ACCESS_KEY`에서 읽는다. `permissions.id-token: write`는 제거한다.
2. **Secrets는 `infra` 저장소(`dont-paw-get/infra`) 자체에 repo-level로 등록한다.** 조직 레벨이나 다른 저장소와 공유하지 않는다.
3. **ECR push 전용 IAM 사용자를 새로 만든다** (기존 사용자 재사용 금지 — 다른 용도의 자격증명과 섞이지 않도록). 권한은 ECR 리포지토리 `dpgy-infra-rca-agent`에 대한 push로 최소화한다: `ecr:GetAuthorizationToken`(리소스 레벨 제약 불가, `*`) + `ecr:BatchCheckLayerAvailability`/`PutImage`/`InitiateLayerUpload`/`UploadLayerPart`/`CompleteLayerUpload`/`BatchGetImage`(리포지토리 ARN으로 제한).
4. **액세스 키는 `infra` 저장소 Settings → Secrets and variables → Actions → Repository secrets에 등록한다.**
5. GitHub OIDC 전환(ADR-0005)은 폐기하되, 향후 이 저장소를 포함해 여러 저장소가 CI 인증 방식을 재검토할 때 참고 사례로 남긴다.

## 결과

- `.github/workflows/rca-agent-build-push.yml`이 ADR-0005 이전 형태(액세스 키)로 되돌아간다.
- `docs/adr/0005-github-actions-oidc.md`의 상태가 "대체됨"으로 갱신된다.
- IAM 사용자 생성 + 액세스 키 발급 + repo-level Secrets 등록이 실행 항목으로 남는다(`.harness/PLAN.md`).

## 미결정 (추후 논의 필요)

(현재 없음)
