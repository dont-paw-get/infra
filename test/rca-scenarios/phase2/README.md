# RCA Agent Phase 2 — 실제 장애 주입 E2E

`rca-test` 네임스페이스에 의도적 장애 워크로드를 배포해 **배포된 알림 규칙**을 실제로 발화시키고,
Discord에 `원본 알림` + `RCA 후속 메시지` 두 개가 오는지, RCA가 실제 메트릭/로그/trace를 근거로
작성되는지 확인한다.

Phase 1(합성 webhook)과 달리 실제로 클러스터에 리소스를 만들고 실제 알림을 쏜다.

## ⚠️ 시작 전

1. **팀에 공지** — 이 테스트는 Discord 알림 채널에 실제 알림 8~12건을 발생시킨다.
2. **전제 조건 확인**
   ```
   kubectl -n monitoring get pod loki-0          # 시나리오 C는 Running 2/2 필요
   kubectl get pvc -A                            # 시나리오 D 전에 이미 80% 넘는 PVC 없는지
   kubectl -n monitoring get pod -l app.kubernetes.io/name=tempo   # E·F는 Tempo Running 필요
   ```
   `loki-0`가 죽어 있으면 C는 건너뛴다. Tempo/OTel Collector가 없으면 E·F는 메트릭 발화는 되지만
   trace 근거 확인은 불가하다.
3. **비용** — RCA 분석 1회당 Bedrock 호출 ≈ 수십 센트. A~F + 부수 발화까지 전체 대략 $2~3.
4. **가장 큰 리스크는 정리 누락** — firing 상태가 유지되면 `repeat_interval: 4h`마다 RCA가 다시 돈다.
   각 시나리오는 확인 즉시 `kubectl delete` 하고, 마지막에 네임스페이스를 통째로 지운다.

## 실행

```
# 최초 1회
kubectl apply -f test/rca-scenarios/phase2/namespace.yaml
```

시나리오별로 **하나씩** 진행 (동시에 여러 개 띄우면 알림·RCA가 섞여 판독이 어렵다):

| # | 파일 | 발화 알림 | apply 후 대기 |
|---|------|-----------|---------------|
| A | `A-crashloop.yaml` | 파드 CrashLoopBackOff | ~2-3분 |
| B | `B-oomkill.yaml` | 파드 OOMKilled (+ CrashLoopBackOff 부수) | ~1-2분 |
| C | `C-log-error-spike.yaml` | 로그 ERROR 급증 | ~5-6분 |
| D | `D-pvc-usage.yaml` | PVC 사용률 초과(warning) + 위험(critical) | critical ~10-13분 / warning ~15-20분 |
| E | `E-http-5xx.yaml` | HTTP 5xx 에러율 초과 (+ 로그 ERROR 급증 부수) | ~7-10분 |
| F | `F-p99-latency.yaml` | p99 레이턴시 초과 | ~7-10분 |

> **E·F는 자체 계측 목 서비스를 띄운다.** 순수 stdlib 파이썬으로 만든 목 HTTP 서비스가 500 응답(E) /
> ~1.5초 지연(F)을 내면서 Micrometer 호환 `http_server_requests_seconds_*`를 `/actuator/prometheus`로
> 노출하고, 요청마다 OTLP span + `trace_id` JSON 로그를 남긴다. 부하 생성 컨테이너가 최소 트래픽
> 게이트(`>= 0.5 req/s`)를 넘긴다. 스크레이핑을 위해 **테스트 전용 `ServiceMonitor`**를 함께 배포한다 —
> 관측 스택 정책상 `ServiceMonitor`는 서비스 저장소 소유지만 이 CR은 ArgoCD/CI 대상이 아닌
> 수동 apply·삭제 리소스다(2026-09-06 컨펌, `docs/adr/0001-observability-stack.md`).

각 시나리오:

```
kubectl apply -f test/rca-scenarios/phase2/<파일>

# 발화 확인 (둘 중 하나)
#  - Grafana UI → Alerting → Alert rules / Active
#  - kubectl -n monitoring get pods -n rca-test   등으로 워크로드 상태 관찰

# 발화 확인 (E·F 추가):
#  - Grafana Explore(Prometheus)에서
#      sum(rate(http_server_requests_seconds_count{application="rca-test-5xx"}[5m]))  가 0.5 이상인지
#  - Status > Targets 에 serviceMonitor/rca-test/rca-test-5xx(또는 -slow) 타겟이 UP 인지

# Discord 확인:
#  1) 원본 알림 임베드 도착
#  2) "RCA: <알림명>" 임베드 도착 — 내용이 실제 재시작 카운트 / 에러 로그 / PVC 추세를 인용하는지
#     C(로그 ERROR 급증): 에러 로그에 trace_id가 있으면 Agent가 get_trace를 호출해
#     span exception을 근거에 넣는지도 확인 (로그가 trace_id를 담을 때만)
#     E(5xx): Agent가 search_traces '{ status = error }' → get_trace 로 SimulatedServerError
#     exception span 을 근거에 인용하는지 확인
#     F(p99): Agent가 search_traces '{ duration > 1s }' → get_trace 로 느린 span 을 인용하는지 확인

# 확인 끝나면 즉시
kubectl delete -f test/rca-scenarios/phase2/<파일>
```

RCA Agent 로그를 같이 보려면:
```
kubectl -n monitoring logs -l app=rca-agent --tail=150 -f
```

## 정리 (필수)

```
kubectl delete ns rca-test
```

네임스페이스를 지우면 Deployment/Job/PVC/ServiceMonitor가 모두 삭제되고, `auto-ebs-sc`의
reclaimPolicy가 `Delete`라 시나리오 D의 EBS 볼륨도 함께 정리된다. 삭제 후 Grafana Alerting에서
관련 알림이 `Normal`로 돌아오는지 확인. E·F의 `ServiceMonitor`도 사라지므로 Prometheus 타겟에서 빠진다.

## 알림이 안 뜰 때

- **A/B** — kube-state-metrics 메트릭 지연. `kube_pod_container_status_waiting_reason` / `_last_terminated_reason`를
  Grafana Explore(Prometheus)에서 직접 조회. `for` 시간(A는 2m)만큼 조건이 유지돼야 발화.
- **C** — `loki-0` 상태, 그리고 `{namespace="rca-test"} | json | level="ERROR"`가 Loki에서 실제로 조회되는지 확인.
  Alloy가 `app` 라벨을 채우는지(`{app="rca-test-logspike"}`)도 점검.
- **D** — `dd`가 `No space left`로 죽었으면 파일의 `count`를 850 → 800으로 낮춘다.
  `kubelet_volume_stats_used_bytes{namespace="rca-test"}`가 실제로 올라오는지 확인(마운트 유지 필요).
- **E/F** — ① `kubectl -n rca-test get servicemonitor` 존재 확인 → Prometheus `Status > Targets`에
  `rca-test/rca-test-5xx`(또는 `-slow`) 타겟이 뜨는지(스크레이핑까지 최대 1~2분). ② `python:3.12-slim`
  이미지 pull 실패 시 `kubectl -n rca-test describe pod`로 확인. ③ 게이트 미달이면 `load` 컨테이너
  로그와 병렬 루프 수(E 4개 / F 8개)를 늘린다. ④ p99가 안 오르면 `application` 라벨이 규칙 제외
  목록(`backend-librarian|backend-discovery`)과 안 겹치는지 확인. ⑤ trace가 없으면 Tempo/OTel
  Collector 상태와 목 서비스 로그의 `otlp export failed` 여부 확인.
