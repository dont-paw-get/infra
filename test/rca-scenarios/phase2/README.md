# RCA Agent Phase 2 — 실제 장애 주입 E2E

`rca-test` 네임스페이스에 의도적 장애 워크로드를 배포해 **배포된 알림 규칙 3종**을 실제로 발화시키고,
Discord에 `원본 알림` + `RCA 후속 메시지` 두 개가 오는지, RCA가 실제 메트릭/로그를 근거로 작성되는지 확인한다.

Phase 1(합성 webhook)과 달리 실제로 클러스터에 리소스를 만들고 실제 알림을 쏜다.

## ⚠️ 시작 전

1. **팀에 공지** — 이 테스트는 Discord 알림 채널에 실제 알림 6~8건을 발생시킨다.
2. **전제 조건 확인**
   ```
   kubectl -n monitoring get pod loki-0          # 시나리오 C는 Running 2/2 필요
   kubectl get pvc -A                            # 시나리오 D 전에 이미 85% 넘는 PVC 없는지
   ```
   `loki-0`가 죽어 있으면 C는 건너뛴다.
3. **비용** — RCA 분석 1회당 Bedrock 호출 ≈ 수십 센트. A~D + OOMKill 부수 발화까지 전체 대략 $1~2.
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
| D | `D-pvc-usage.yaml` | PVC 사용률 초과 | ~15-20분 |

> `HTTP 5xx 에러율 초과` / `p99 레이턴시 초과` 알림은 여기에 없다 — 두 규칙은 서비스 저장소의
> Micrometer 계측(`http_server_requests_seconds_*`)과 `ServiceMonitor`가 있어야 발화하고,
> 그때 Agent가 `search_traces`/`get_trace`로 trace를 근거에 넣는지 확인하는 시나리오를 별도로 추가한다.
> 현재는 `monitoring/alerting/kustomization.yaml`에서 배포 제외 상태 — `.harness/PLAN.md` 참고.

각 시나리오:

```
kubectl apply -f test/rca-scenarios/phase2/<파일>

# 발화 확인 (둘 중 하나)
#  - Grafana UI → Alerting → Alert rules / Active
#  - kubectl -n monitoring get pods -n rca-test   등으로 워크로드 상태 관찰

# Discord 확인:
#  1) 원본 알림 임베드 도착
#  2) "RCA: <알림명>" 임베드 도착 — 내용이 실제 재시작 카운트 / 에러 로그 / PVC 추세를 인용하는지
#     C(로그 ERROR 급증): 에러 로그에 trace_id가 있으면 Agent가 get_trace를 호출해
#     span exception을 근거에 넣는지도 확인 (로그가 trace_id를 담을 때만)

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

네임스페이스를 지우면 Deployment/Job/PVC가 모두 삭제되고, `auto-ebs-sc`의 reclaimPolicy가 `Delete`라
시나리오 D의 EBS 볼륨도 함께 정리된다. 삭제 후 Grafana Alerting에서 관련 알림이 `Normal`로 돌아오는지 확인.

## 알림이 안 뜰 때

- **A/B** — kube-state-metrics 메트릭 지연. `kube_pod_container_status_waiting_reason` / `_last_terminated_reason`를
  Grafana Explore(Prometheus)에서 직접 조회. `for` 시간(A는 2m)만큼 조건이 유지돼야 발화.
- **C** — `loki-0` 상태, 그리고 `{namespace="rca-test"} | json | level="ERROR"`가 Loki에서 실제로 조회되는지 확인.
  Alloy가 `app` 라벨을 채우는지(`{app="rca-test-logspike"}`)도 점검.
- **D** — `dd`가 `No space left`로 죽었으면 파일의 `count`를 850 → 800으로 낮춘다.
  `kubelet_volume_stats_used_bytes{namespace="rca-test"}`가 실제로 올라오는지 확인(마운트 유지 필요).
