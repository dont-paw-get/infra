# ADR-0007: dev 분산 트레이싱 스택 추가

## 상태

승인됨 (2026-09-01)

## 배경

`backend-book`과 `backend-auth`에 OpenTelemetry trace 계측이 이미 구현되어 있다. dev 환경에서 이를 실제로 수집, 저장, 조회하려면 trace backend가 필요하다. 기존 관측 스택은 Prometheus/Grafana/Loki/Alloy 기반으로 metrics/logs를 안정적으로 처리하고 있으므로, 이 구조를 교체하지 않고 tracing 계층만 추가한다.

## 결정

1. **OpenTelemetry Collector를 trace 수집 진입점으로 둔다.**
   - 애플리케이션은 OTLP HTTP/protobuf `:4318`로 Collector에 전송한다.
   - Collector는 Kubernetes 내부 `ClusterIP` Service로만 노출하고 Ingress/LoadBalancer를 만들지 않는다.
   - Collector pipeline은 traces만 활성화한다. 로그는 기존 `Application stdout -> Alloy -> Loki` 경로를 유지하고 OpenTelemetry Logs pipeline을 만들지 않는다.
2. **Grafana Tempo single binary를 dev trace backend로 둔다.**
   - dev는 작은 단일 바이너리 + PVC(`auto-ebs-sc`) 로컬 저장으로 시작한다.
   - Tempo distributed cluster나 Kafka/object storage 기반 구성을 dev에 도입하지 않는다.
   - prod 확장 시에는 S3/object storage backend와 더 긴 retention을 별도 ADR로 검토한다.
3. **Grafana에서 Loki와 Tempo를 상호 연결한다.**
   - Tempo datasource uid는 `tempo`로 고정한다.
   - Loki datasource에는 JSON 로그의 `trace_id`를 추출하는 derived field를 추가한다.
   - `trace_id`는 high cardinality 값이므로 Loki label로 승격하지 않는다.
4. **probe trace는 애플리케이션 SDK에서 생성 자체를 막는 것을 우선한다.**
   - Collector에는 `/health`, `/ready`, `/readiness`, `/live`, `/liveness` 같은 명확한 probe path만 보완 필터로 둔다.
   - 정상 사용자 endpoint가 지워질 수 있는 넓은 조건은 사용하지 않는다.

## 결과

- `monitoring/tempo/values.yaml`, `monitoring/otel-collector/values.yaml`이 추가된다.
- ArgoCD Application은 기존 멀티소스 Helm 패턴으로 `monitoring/argocd/tempo.yaml`, `monitoring/argocd/otel-collector.yaml`에 추가된다.
- 서비스 저장소는 다음 endpoint를 dev overlay에 설정한다:
  - `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector.monitoring.svc.cluster.local:4318`
- Grafana Explore에서 Tempo trace 조회와 Loki trace_id 기반 trace 링크 이동이 가능해진다.
- RCA Agent가 이 Tempo 백엔드를 `search_traces`/`get_trace` tool로 직접 조회한다 (2026-09-02, CLIAR-238) — `docs/adr/0008-rca-agent-tempo-source.md` 참고.

## 미결정

- prod tracing storage(S3 bucket, IRSA role, retention, topology)는 추후 prod overlay 설계 시 결정한다.
- Tempo metrics generator 및 service graph/span metrics 활성화는 실제 trace volume과 대시보드 요구가 생긴 뒤 재검토한다.
