# BACKLOG

지금 하지 않지만 나중에 할 것(오픈 이슈·기술부채·아이디어). 실제로 작업을 시작하면 `.harness/PLAN.md`로 옮긴다.

현재 미해결 오픈 이슈는 모두 `.harness/PLAN.md`에 체크리스트로 정리되어 있다 (사용자 요청). 이후 당장 계획에 넣지 않을 아이디어나 기술부채가 생기면 이 파일에 쌓는다.

- **prometheus-operator vs CRD 기동 경쟁 조건 재발 방지** — kube-prometheus-stack Application 하나가 CRD와 오퍼레이터 Deployment를 같은 sync에 적용해서, 오퍼레이터가 CRD보다 먼저 뜨면 컨트롤러를 등록하지 못한 채 영원히 idle 상태가 된다(2026-08-28 실제 발생, `.harness/DECISIONS.md` 참고). 지금은 수동 재시작으로 풀었지만, CRD를 별도 Application(낮은 sync-wave)으로 분리하거나 오퍼레이터에 CRD 존재를 기다리는 initContainer를 두는 식의 구조적 해법이 필요하다. 클러스터 재구축이나 차트 메이저 업그레이드 때 다시 밟을 수 있는 함정
- ~~**`argocd/argocd-applicationset-controller` CrashLoopBackOff**~~ → 2026-08-29 해결(`applicationsets.argoproj.io` CRD 누락, `.harness/DECISIONS.md` 참고). ArgoCD 설치 자체를 client-side apply로 했을 때 큰 CRD가 annotation 한도로 누락될 수 있다는 사례 — ArgoCD 재설치·업그레이드 시 `--server-side`를 쓰는지 확인할 것
- **StorageClass 변경 시 StatefulSet 수동 삭제 절차 문서화** — `volumeClaimTemplates`가 불변이라 git만 고쳐서는 절대 반영되지 않는다(Loki에서 2회 발생). 스토리지 관련 values를 바꿀 때 따라야 할 절차를 `README.md`나 runbook으로 남길지 검토
- **prod 트레이스 endpoint 전달** — `backend-book` 등 서비스 저장소의 prod overlay는 `OTEL_EXPORTER_OTLP_ENDPOINT`를 관례 기본값(`http://opentelemetry-collector.observability.svc.cluster.local:4318`)으로 두고 있다. prod 클러스터에 Collector가 배포되면(prod overlay 설계, ADR-0007 미결정) 실제 서비스 DNS를 각 서비스 저장소에 전달해야 한다. 이 저장소는 dev tracing 스택만 소유
- **Tempo 밸러스트 → `GOMEMLIMIT` 전환** — `monitoring/tempo/values.yaml`의 `memBallastSizeMbs: 128`은 Go 1.19+ `GOMEMLIMIT`로 대체하는 것이 최신 권장이다. 메모리 상향(CLIAR-254, 512Mi→1Gi)으로 당장 급하지 않아 보류. prod topology(ADR-0007 미결정)와 함께 다룬다
