# ADR-0002: 이상탐지/근본원인분석(RCA) Agent 도입

## 상태

승인됨 (2026-08-23)

## 배경

`docs/adr/0001-observability-stack.md`로 구축한 Prometheus + Grafana + Loki 스택은 임계값 기반 알림(5종 규칙)을 Discord로 발송한다. 알림이 발생한 뒤 "왜 발생했는지"를 파악하는 과정은 여전히 수동이다. 이 부담을 줄이기 위해, 알림 발생 시 관련 메트릭/로그를 자동으로 조사해 원인 분석 결과를 사람이 읽을 수 있는 형태로 Discord에 보고하는 Agent를 도입한다.

## 검토한 대안

| 항목 | 대안 | 비고 |
|---|---|---|
| Agent 프레임워크 | Strands SDK(AWS) | Bedrock 네이티브 통합, AWS 종속 |
| | LangGraph 등 클라우드 중립 프레임워크 | 프로바이더 자유도 높으나 이번 결정에서는 Bedrock 사용이 이미 확정되어 이점이 상쇄됨 |
| 입력 경로(트리거) | A. Prometheus/Loki 직접 폴링 | 임계값 미만의 이상도 탐지 가능하나, 기존 알림 규칙과 탐지 로직이 이원화되고 폴링마다 Bedrock 호출 비용 발생 |
| | B. Grafana Alerting 발화를 webhook으로 트리거 | 기존 5종 알림 규칙을 탐지 계층으로 재사용, 이벤트 발생 시에만 Bedrock 호출 — 채택 |
| Discord 출력 배치 | 원본 알림과 RCA를 한 메시지로 병합 | Agent 장애 시 원본 알림 자체가 유실됨 |
| | 같은 채널에 원본 알림 + RCA 후속 메시지 (두 메시지) | 원본 알림 경로(`discord-webhook`)가 Agent와 독립적으로 유지되어 Agent 장애 시에도 기본 알림은 보존 — 채택 |
| | 별도 채널로 분리 | 채널 관리 부담 증가, 이번엔 불필요하다고 판단 |
| 조치 권한 | 분석/보고만 (read-only) | 채택 — blast radius 최소화 |
| | 제한된 자동 조치(재시작 등) 허용 | RBAC 설계·승인 절차 등 부가 안전장치 필요, 이번 범위에서 제외 |
| 소스 코드 위치 | 이 저장소(`dpgy-infra`)에 포함 | 채택 — Agent를 서비스가 아닌 공유 관측 인프라로 취급 |
| | 별도 저장소로 분리 | 관측 인프라와 애플리케이션 코드가 나뉘어 배포 파이프라인이 이원화됨 |

## 결정

1. **프레임워크: Strands SDK + Amazon Bedrock**을 사용한다.
   - `docs/adr/0001-observability-stack.md`의 "자체 호스팅/매니지드 서비스 미사용" 원칙은 관측 파이프라인(수집·저장·시각화·알림)의 호스팅 방식에 대한 결정이며, Agent의 LLM 백엔드 선택에는 적용되지 않는다. 이 Agent는 Bedrock(매니지드 LLM)을 명시적으로 사용한다.
2. **입력 경로: Grafana Alerting 트리거(webhook) 기반**. 기존 알림 규칙(`monitoring/alerting/rules/`)이 이상탐지를 담당하고, 규칙 발화 시 Grafana가 webhook으로 Agent에 이벤트를 전달한다. Agent는 자체적으로 Prometheus/Loki를 주기 폴링하지 않는다. Agent는 발화 시점을 기준으로 PromQL/LogQL을 추가 조회해 원인분석만 수행한다.
3. **출력: 같은 Discord 채널에 원본 알림 + RCA 후속 메시지**. 기존 `discord-webhook` contact point는 그대로 유지하고, 같은 알림 규칙이 Agent에도 동시에 webhook을 보내도록 구성한다(구현 방식은 기존 contact point에 webhook 통합을 추가하는 것으로 시작). Agent 장애 시에도 원본 임계값 알림은 유지되도록 두 경로를 독립적으로 둔다.
4. **권한: read-only 분석/보고 전용**. Pod 재시작, 스케일 조정 등 클러스터에 대한 쓰기 권한을 갖지 않는다.
5. **호스팅 위치: `monitoring` 네임스페이스** (이 저장소 범위). Agent를 서비스가 아닌 클러스터 공유 관측 인프라로 취급하며, `docs/adr/0001-observability-stack.md`의 "서비스 저장소와의 경계" 원칙(계측 지점은 서비스 저장소 책임)과 별개로 이 Agent 자체는 인프라 저장소가 소유한다.
6. **소스 코드 위치: 이 저장소에 포함**. Strands SDK 애플리케이션 소스, Dockerfile, 배포 매니페스트를 모두 `dpgy-infra`에 둔다.
7. **Bedrock 인증: IRSA**. 클러스터는 EKS이며, Agent의 ServiceAccount에 IAM Role을 연결해 Bedrock 호출 권한을 부여한다. AWS 액세스 키를 시크릿으로 관리하지 않는다.
8. **Prometheus/Loki 접근**: 기존 Alloy와 동일하게 클러스터 내부 서비스 DNS(예: `loki-gateway.monitoring.svc.cluster.local`)로 접근하며 별도 인증을 두지 않는다 (네임스페이스 내부 통신 전제).

## 결과

- `monitoring/rca-agent/`에 Agent 소스(FastAPI webhook 서버 + Strands SDK Agent + Discord 알림), Dockerfile, K8s manifest(Kustomize)가 추가되었다. `monitoring/argocd/rca-agent.yaml`로 배포된다.
- Grafana Alerting의 webhook 통합은 기존 `discord-webhook` contact point에 `rca-agent-webhook-receiver`를 추가하는 방식으로 구성했다(`monitoring/alerting/contact-points/discord.yaml`).
- IRSA `ServiceAccount`(`rca-agent-irsa`) + IAM Role(`dpgy-infra-rca-agent`) 생성 완료(2026-08-25, AWS Console). 신뢰 정책은 `sub: system:serviceaccount:monitoring:rca-agent-irsa`로 좁혔고, 권한은 `bedrock:InvokeModel(WithResponseStream)`을 `foundation-model/anthropic.claude-sonnet-5`로 스코프했다.
- Bedrock 모델은 **anthropic.claude-sonnet-5**로 확정(`monitoring/rca-agent/k8s/configmap.yaml`의 `BEDROCK_MODEL_ID`). Bedrock 콘솔의 모델 액세스(Model access) 승인은 별도 확인 필요.
- Agent는 클러스터 쓰기 권한이 없으므로, 자동 조치가 필요한 경우는 이번 범위에서 제외되며 향후 별도 ADR로 재검토한다.

## 미결정 (추후 논의 필요)

- Agent 장애/타임아웃 시 재시도·알림 정책 (RCA 실패를 어떻게 가시화할지)
- 향후 제한된 자동 조치 권한 부여 여부 — 이번 ADR은 명시적으로 배제, 필요해지면 별도 ADR
