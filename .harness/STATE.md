# STATE

지금까지 끝난 것의 단계 단위 요약. 세션별 서술은 `HANDOFF.md`에 남긴다.

- [x] 관측 스택 결정: Prometheus + Grafana + Loki(`kube-prometheus-stack`), 자체 호스팅, Grafana Alerting(Discord), `ServiceMonitor`는 서비스 저장소 소유 — `docs/adr/0001-observability-stack.md`
- [x] `monitoring/` 스캐폴딩: kube-prometheus-stack / Loki / Alloy Helm values, Discord contact point·알림 정책·알림 규칙 5종(5xx 에러율, p99 레이턴시, CrashLoopBackOff/OOMKilled, PVC 사용률, 로그 ERROR 급증)
- [x] 시크릿 관리 임시 방식 확립: 루트 `.env`(값 비움, gitignore됨) → `scripts/install.sh`가 source해서 Secret 생성/갱신
- [x] `scripts/install.sh` 작성: `.env` 검증 → 네임스페이스/Secret 생성 → alerting ConfigMap 생성 → Helm 3종 설치
- [x] `CLAUDE.md` 크로스 툴 하네스 워크플로 문서 작성 (backend-book 오염 내용 제거, infra 저장소 기준으로 재작성)
- [x] `.harness/` 스캐폴딩 (이 문서 포함 6종)
- [x] 이상탐지/RCA Agent 도입 결정: Strands SDK + Amazon Bedrock, Grafana Alerting webhook 트리거 기반, read-only 분석/보고 전용, `monitoring` 네임스페이스에 소스 포함 배포, Bedrock 인증은 IRSA — `docs/adr/0002-anomaly-rca-agent.md`
