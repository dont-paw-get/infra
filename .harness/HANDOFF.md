# HANDOFF

세션마다 무엇을 했는지 (append-only 서술형 로그, 최신이 위). 단계별 완료 요약은 `STATE.md`, 결정 이유는 `DECISIONS.md`/`docs/adr/` 참고.

## 2026-08-29 — Phase 2 시작, 알림 규칙 미로드 발견 (CLIAR-159)

사용자가 "병합 없이 Phase 2 실행 가능하면 해봐"라고 요청. `test/rca-scenarios/phase2/`는 ArgoCD 대상이 아니라 로컬 작업 트리에서 바로 `kubectl apply` 가능 — Claude가 사용자 머신의 kubeconfig(`--profile mfa`, dpyb-dev)로 직접 실행했다.

시나리오 A(`A-crashloop.yaml`) 배포 → 파드가 CrashLoopBackOff 진입, `kube_pod_container_status_waiting_reason{namespace="rca-test", reason="CrashLoopBackOff"}=1`까지 Prometheus로 확인. 그런데 10분 넘게 기다려도 RCA Agent 로그에 `POST /webhook`이 없었다(로그는 kubelet probe의 `GET /healthz`만).

**원인: Grafana에 알림 규칙이 0개 로드돼 있었다.** `/api/v1/provisioning/alert-rules` → `[]`. Grafana 컨테이너 로그에 `errorMessageID=alerting.alert-rule.invalidRelativeTime`, `error="Invalid alert rule query A: invalid relative time range [From: 0s, To: 0s]"`, `POST /api/admin/provisioning/alerting/reload status=500`. `monitoring/alerting/rules/*.yaml`의 `data[]`에 `relativeTimeRange`가 없어서 Grafana가 프로비저닝 reload 배치 전체를 거부 — contact point(`discord.yaml`)와 notification policy만 로드되고 규칙 3종은 전부 누락. sidecar(`grafana-sc-alerts` 컨테이너, 이름에 s 있음)는 파일을 `/etc/grafana/provisioning/alerting/`에 정상적으로 쓰고 있었고, 데이터소스 uid(`prometheus`/`loki`)도 정상. **저장소 배포 이후 알림이 한 번도 동작한 적 없다.**

**수정:** `monitoring/alerting/rules/` 5개 파일 모두 `refId: A`와 `refId: C`에 `relativeTimeRange: {from: 600, to: 0}` 추가. `kubectl kustomize monitoring/alerting/`로 렌더링에 8개 들어가는 것 확인(배포 대상 pod-health 4 + pvc 2 + log 2). **아직 커밋 안 함.** `kubectl apply`로 라이브 검증은 auto-mode classifier가 차단(git 앞서는 클러스터 변경) — 병합 후 검증해야 한다.

시나리오 A 워크로드와 `rca-test` 네임스페이스는 정리 완료.

**다음 세션이 이어받을 것:** (1) `monitoring/alerting/rules/*.yaml` `relativeTimeRange` 수정 커밋 → PR → `develop` 병합 → ArgoCD `alerting` sync → 포트포워드 후 `curl -u admin:<pw> localhost:3000/api/v1/provisioning/alert-rules`로 규칙 로드 확인 + Grafana 로그 reload 500 사라짐 확인. admin 비번은 `kubectl -n monitoring get secret grafana-admin-credentials -o jsonpath='{.data.admin-password}' | base64 -d`. (2) 그 다음 `test/rca-scenarios/phase2/`의 A→B→C→D를 하나씩 실행하며 Discord에 원본 알림 + RCA 후속 메시지 확인. 상세 절차는 `test/rca-scenarios/phase2/README.md`. 미커밋 변경: `.harness/*` 4개 + `monitoring/alerting/rules/*` 5개.

## 2026-08-28 — RCA Agent Phase 1 스모크 테스트 (CLIAR-159)

사용자가 "모니터링 배포 완료, 장애 시나리오로 RCA Agent 테스트하고 싶다"고 요청. 가장 안전한 방법으로 좁혀, 실제 장애 워크로드 없이 합성 Grafana webhook 페이로드를 `rca-agent`의 `/webhook`에 직접 POST하는 Phase 1 스모크 테스트를 만들었다. 산출물: `test/rca-scenarios/` (`payloads/crashloop-firing.json`, `payloads/resolved.json`, `send-webhook.sh`, `README.md`) — ArgoCD/CI 대상 아님(수동).

**로컬 kubectl 접근 세팅에 시간이 걸렸다.** 사용자가 그동안 CloudShell에서만 클러스터를 만졌음. IAM 사용자 `kosa12`에 `kosa-edu-mfa-pol`(MFA 없으면 전부 deny) 정책이 걸려 있고 기존 MFA는 U2F 패스키뿐이라 CLI `get-session-token`을 못 썼다. 사용자가 콘솔에서 TOTP 인증앱 MFA(`arn:.../mfa/otp-cli`)를 추가 → `aws sts get-session-token`으로 12h 임시 자격증명 발급 → `--profile mfa`에 저장 → `aws eks update-kubeconfig --profile mfa`로 해결. (세션 만료 시 `get-session-token` + `aws configure set ... --profile mfa` 3줄 재실행)

**첫 테스트에서 실제 버그 발견.** webhook→`analyze()`→Strands→Bedrock `ConverseStream`까지 도달(IRSA·권한 정상)한 뒤 `ValidationException: Invocation of model ID anthropic.claude-sonnet-5 with on-demand throughput isn't supported. Retry ... with an inference profile`. Sonnet 5는 베어 모델 ID on-demand 불가. `aws bedrock list-inference-profiles --region ap-northeast-2` → Sonnet 5용은 `global.anthropic.claude-sonnet-5` 하나뿐(`apac.` 없음). `configmap.yaml`의 `BEDROCK_MODEL_ID`를 그걸로 바꾸고, IAM Role `dpgy-infra-rca-agent` 정책을 `inference-profile/global.anthropic.claude-sonnet-5` + `arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-5`로 확장(사용자가 콘솔에서). 경위는 `DECISIONS.md` 2026-08-28 항목.

**커밋 2개(`feat` 테스트 시나리오, `fix` 모델 ID)를 CLIAR-159 브랜치에 만들고 사용자가 PR #4로 develop 병합.** CI가 이미지 재빌드 + `kustomization.yaml` 태그 갱신(`f36c680`) → ArgoCD `rca-agent` Synced/Healthy, 새 파드가 `global.anthropic.claude-sonnet-5`로 기동. 재테스트 → **Discord에 `RCA: 파드 CrashLoopBackOff` 임베드 정상 도착, 파이프라인 전 구간 확인.** `rca-test` 네임스페이스가 실재하지 않아 도구 쿼리는 빈 결과지만 Agent가 스모크 테스트임을 스스로 인지하고 합리적 보고서 작성.

부수 확인: (1) `resolved` 페이로드의 500은 Windows PowerShell `Invoke-RestMethod -InFile`이 한글을 UTF-8로 안 보낸 탓 — `curl.exe`로는 정상. README에 반영. (2) `analyze()` 예외가 `/webhook` 500으로만 나오고 Discord 통지가 없음 — RCA 실패 가시성 부재, `PLAN.md`에 후속 항목으로.

**다음 세션이 이어받을 것:** `.harness/PLAN.md`의 "RCA Agent 테스트 — Phase 2"(실제 장애 주입 E2E, 별도 컨펌 필요) + "RCA 실패 가시성" 후속 항목. `test/rca-scenarios/send-webhook.sh`는 CRLF로 커밋됨(Windows) — Linux에서 실행 시 주의, 필요하면 `.gitattributes` 검토.

## 2026-08-28 — kube-prometheus-stack / loki Progressing 진단 세션

사용자가 "kube-prometheus-stack과 loki 두 애플리케이션만 processing 상태"라고 요청. 코드 변경 없이 클러스터 진단부터 시작했다(에이전트 쪽에 kubeconfig·유효한 AWS 자격증명이 없어, 명령은 사용자가 실행하고 출력을 붙여주는 방식으로 진행).

**클러스터 특정에 시간이 걸렸다.** 사용자의 kubectl 컨텍스트가 처음엔 다른 클러스터, 다음엔 `dpyb-prod`를 가리켜 `argocd`/`monitoring` 네임스페이스가 없었다. `argocd-cluster`라는 별칭 컨텍스트가 실제로는 `dpyb-prod`를 가리키고 있었던 것도 혼선 요인. 관측 스택은 `dpyb-dev`에 있다.

**Loki — 두 단계 문제였다.**
1. STS `loki`의 `volumeClaimTemplates.storageClassName`이 `gp2`로 굳어 있어 ArgoCD sync가 `Forbidden: updates to statefulset spec ...`으로 5회 재시도 후 실패. 이미 `DECISIONS.md`(2026-08-27 정정 항목)에 예고돼 있던 불변 필드 문제다. `kubectl delete statefulset loki` + `kubectl delete pvc storage-loki-0`(Pending이라 데이터 없음) 후 ArgoCD sync로 재생성 → `auto-ebs-sc`로 20Gi `Bound` 성공.
   - sync 트리거 시 주의: hard refresh 어노테이션은 비교만 다시 할 뿐 sync를 실행하지 않는다. `argocd` CLI는 서버 주소 미설정으로 못 썼고, `kubectl -n argocd patch application loki --type merge -p '{"operation":{...}}'`로 sync를 직접 넣어 해결했다.
2. PVC가 붙자 그동안 가려져 있던 config 오류가 드러남 — `compactor.delete-request-store should be configured when retention is enabled`. `monitoring/loki/values.yaml`에 `compactor.delete_request_store: s3` 추가로 수정하고 `helm template`로 렌더링 검증 완료. **아직 커밋/푸시 안 됨 — 병합 전까지 `loki-0`는 CrashLoopBackOff.**

**Prometheus — 오퍼레이터가 CRD보다 먼저 떠서 컨트롤러를 등록하지 못한 상태였다.** 자세한 내용은 `DECISIONS.md` 2026-08-28 항목. ArgoCD sync가 27시간째 `Running`으로 매달려 새 sync를 받지 못하던 교착까지 겹쳐 있었다. 매달린 operation 제거 + `rollout restart deployment/kube-prometheus-stack-operator`로 해소 → Prometheus `RECONCILED: True`/`AVAILABLE: True`, STS가 `auto-ebs-sc`로 생성, Application `Synced`/`Healthy`.

진단 과정에서 유용했던 명령: `kubectl -n argocd get application <name> -o jsonpath='{.status.operationState.phase}{.status.operationState.message}'`(교착 확인), 오퍼레이터 로그를 `grep -v "Endpoints is deprecated"`로 걸러 기동 로그 확인(3분 주기 경고에 밀려 `--tail=100`으로는 안 보인다).

**다음 세션이 이어받을 것:** `monitoring/loki/values.yaml` 수정 커밋·푸시·병합(작업 트리에만 있음, 티켓 브랜치 미생성 — 사용자에게 티켓 번호 확인 필요) → ArgoCD `loki` Sync → `loki-0` Running 확인 → 그다음 IRSA(`dpgy-infra-loki` IAM Role) 실제 존재 여부 확인. `.harness/PLAN.md`의 "dev 클러스터 배포 검증" 섹션 참고. 재발 방지 항목 2건은 `BACKLOG.md`에 있다.

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
