# ADR-0001: 관측(Observability) 스택 선정

## 상태

승인됨 (2026-08-23)

## 배경

Organization은 여러 서비스로 구성된 MSA(Book Service, Python RAG Service 등)이며 Kubernetes에 배포된다. 클러스터 전체를 대상으로 메트릭 수집, 로그 수집, Discord를 통한 이상 알림 발송이 필요하다. 이 관측 스택은 특정 서비스가 아닌 클러스터 공유 인프라이며, 각 서비스 저장소는 계측 지점(메트릭 엔드포인트, 구조화 로깅)만 책임진다 — database-per-service와 같은 결의 "관측 책임 분리" 원칙을 따른다.

## 검토한 대안

| 스택 | 비고 |
|---|---|
| A. Prometheus + Grafana + Loki (`kube-prometheus-stack`) | 사실상 K8s 관측 표준. 최대 커뮤니티/생태계 |
| B. VictoriaMetrics + VictoriaLogs/Loki | Prometheus API 호환, 리소스 효율 우수 |
| C. Elastic/OpenSearch (EFK) | 로그 검색은 강하나 메트릭 결합이 어색하고 오버스펙 |
| D. SigNoz (OTel + ClickHouse) | 로그/메트릭/트레이스 통합 뷰가 강점이나 상대적으로 신생 |
| E. Grafana Cloud (매니지드) | 위 스택 중 어느 것이든 매니지드로 운용 가능한 별도 축 |

## 결정

1. **스택: A (Prometheus + Grafana + Loki, `kube-prometheus-stack` Helm 차트)**를 채택한다.
   - PromQL/Grafana 생태계가 업계 표준이라 레퍼런스·트러블슈팅 자료가 가장 풍부하고, CRD(`ServiceMonitor`/`PodMonitor`) 기반 설정이 표준화되어 있다.
   - 리소스/카디널리티 문제가 실제로 발생하면 Prometheus API 호환인 VictoriaMetrics로 전환 가능하도록 PromQL 표준을 유지한다 (탈출 경로 확보).
2. **호스팅: 자체 호스팅**. `kube-prometheus-stack` + Loki + Alloy를 클러스터 안에 직접 설치한다.
   - 데이터가 클러스터 밖으로 나가지 않고 비용을 예측 가능한 범위(클러스터 리소스)로 통제할 수 있다.
   - Grafana Cloud 등 매니지드 전환은 추후 운영 부담이 커질 때 재검토 가능한 옵션으로 남겨둔다.
3. **알림 경로: Alertmanager 대신 Grafana Alerting**을 사용한다. Discord contact point를 네이티브로 지원해 별도 릴레이(`alertmanager-discord` 등) 없이 구성 요소를 줄인다. `kube-prometheus-stack`의 Alertmanager는 비활성화한다.
4. **`ServiceMonitor`/`PodMonitor` CR의 소유권은 각 서비스 저장소**(`backend-book` 등)에 둔다. 이 인프라 저장소는 수집·저장·시각화·알림 파이프라인만 소유하고, "무엇을 스크레이핑할지"는 해당 서비스의 배포 매니페스트가 책임진다 — database-per-service와 동일한 관측 책임 분리 원칙.

## 결과

- 이 저장소는 `monitoring/` 하위에 kube-prometheus-stack, Loki, Alloy의 Helm values와 Grafana Alerting(연락처/정책/규칙) 설정만 갖는다.
- 각 서비스 저장소는 `/actuator/prometheus`(Micrometer) 또는 동등한 엔드포인트를 노출하고, 자신의 배포 매니페스트에 `ServiceMonitor` CR을 포함해야 한다.
- Discord 웹훅 URL 등 시크릿은 저장소에 커밋하지 않는다 (`secrets/README.md` 참고).

## 미결정 (추후 논의 필요)

- ~~Prometheus/Loki 데이터 보존 기간과 PVC 스토리지 용량~~ → 해소 (Prometheus 15d/20Gi 유지, Loki는 S3 전환 후 14d — `docs/adr/0004-loki-s3-storage.md`)
- Grafana 외부 노출 방식(Ingress)과 인증 방식
- ~~시크릿 관리 방식 최종 확정~~ → `docs/adr/0003-argocd-gitops.md`에서 해소 (External Secrets Operator + AWS Secrets Manager)
- 알림 규칙(threshold) 초기값 튜닝 — 트래픽 규모 파악 전이므로 러프한 기본값으로 시작
- ~~GitOps 도구(ArgoCD/Flux) 도입 여부~~ → `docs/adr/0003-argocd-gitops.md`에서 해소 (ArgoCD)
