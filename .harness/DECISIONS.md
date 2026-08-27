# DECISIONS

`docs/adr/`에 없는 소규모/운영 결정의 역사 (append-only, 최신이 위). 아키텍처 수준 결정(스택 선정, 호스팅 방식 등)은 여기가 아니라 `docs/adr/`에 기록한다.

## 2026-08-27 — Loki/Prometheus PVC StorageClass는 `gp2`로 유지

Loki(`loki-0`)와 Prometheus 파드가 PVC Pending으로 멈춰있던 원인은 클러스터(EKS Auto Mode)에 default StorageClass가 없어서였다. 조사 결과 이 클러스터는 `storageConfig.blockStorage.enabled: true`로 Auto Mode 블록스토리지 기능 자체는 켜져 있었지만, AWS 문서상 Auto Mode는 `auto-ebs-sc` StorageClass 리소스를 자동으로 만들어주지 않고 사용자가 직접 생성해야 한다 — 그래서 존재하지 않았다. 대안으로 `auto-ebs-sc`(gp3, CSI 드라이버 `ebs.csi.eks.amazonaws.com`)를 새로 만들어 전환하는 안을 검토했으나, 사용자가 이미 존재하는 레거시 `gp2`(in-tree `kubernetes.io/aws-ebs`) StorageClass를 그대로 쓰기로 결정 — 이미 동작하고 dev 클러스터 규모에 충분하며 추가 리소스 생성이 필요 없음.

**영향받은 파일:** `monitoring/loki/values.yaml`(`singleBinary.persistence.storageClass: gp2`), `monitoring/kube-prometheus-stack/values.yaml`(`storageClassName: gp2`).

## 2026-08-23 — 시크릿을 `.env` + `scripts/install.sh` 자동 생성으로 통합

기존에는 `secrets/README.md`에만 수동 `kubectl create secret` 절차가 있었고 `scripts/install.sh`는 이미 Secret이 존재한다고 가정했다. 사용자가 값 채울 자리(.env)를 원해 루트에 `.env`(값 비움, gitignore됨)를 만들고, `scripts/install.sh`가 이를 source해 `grafana-admin-credentials`/`discord-webhook` Secret을 직접 생성·갱신하도록 변경했다.

**이유:** 수동 2단계(Secret 먼저 생성 → install.sh 실행)보다 `.env` 채우고 스크립트 한 번 실행으로 끝나는 편이 더 명확하고 재실행에도 안전(`--dry-run=client | kubectl apply`)하다.

**영향받은 파일:** `.env`(신규), `scripts/install.sh`, `secrets/README.md`.
