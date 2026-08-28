# BACKLOG

지금 하지 않지만 나중에 할 것(오픈 이슈·기술부채·아이디어). 실제로 작업을 시작하면 `.harness/PLAN.md`로 옮긴다.

현재 미해결 오픈 이슈는 모두 `.harness/PLAN.md`에 체크리스트로 정리되어 있다 (사용자 요청). 이후 당장 계획에 넣지 않을 아이디어나 기술부채가 생기면 이 파일에 쌓는다.

- **prometheus-operator vs CRD 기동 경쟁 조건 재발 방지** — kube-prometheus-stack Application 하나가 CRD와 오퍼레이터 Deployment를 같은 sync에 적용해서, 오퍼레이터가 CRD보다 먼저 뜨면 컨트롤러를 등록하지 못한 채 영원히 idle 상태가 된다(2026-08-28 실제 발생, `.harness/DECISIONS.md` 참고). 지금은 수동 재시작으로 풀었지만, CRD를 별도 Application(낮은 sync-wave)으로 분리하거나 오퍼레이터에 CRD 존재를 기다리는 initContainer를 두는 식의 구조적 해법이 필요하다. 클러스터 재구축이나 차트 메이저 업그레이드 때 다시 밟을 수 있는 함정
- **`argocd/argocd-applicationset-controller` CrashLoopBackOff** — 2026-08-29 알림 규칙이 처음 로드되자마자 감지됨(430회 재시작, 2d+). ArgoCD 자체는 이 저장소 범위 밖(클러스터에 이미 설치됨, ADR-0003)이지만 `파드 CrashLoopBackOff` 알림이 계속 이 파드로 발화하므로, 원인 파악(로그/이벤트)하거나 담당자에게 전달 필요. 방치 시 Discord 알림 + RCA가 4h마다 반복됨
- **StorageClass 변경 시 StatefulSet 수동 삭제 절차 문서화** — `volumeClaimTemplates`가 불변이라 git만 고쳐서는 절대 반영되지 않는다(Loki에서 2회 발생). 스토리지 관련 values를 바꿀 때 따라야 할 절차를 `README.md`나 runbook으로 남길지 검토
