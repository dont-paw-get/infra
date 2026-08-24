#!/usr/bin/env bash
# 최초 부트스트랩 전용. ArgoCD가 이후의 모든 동기화(Helm 설치/업그레이드, Secret 생성 등)를 자동으로 담당한다.
# 사전 조건: 클러스터에 ArgoCD가 이미 설치되어 있어야 한다 (이 저장소 범위 밖 — docs/adr/0003-argocd-gitops.md).
set -euo pipefail

kubectl apply -f monitoring/namespace.yaml

# monitoring/argocd/*.yaml의 Application CR을 최초 1회 등록한다.
# 이후 변경은 Git 커밋 → ArgoCD 자동 동기화(automated: selfHeal + prune)로 반영되며 이 스크립트를 다시 실행할 필요가 없다.
kubectl apply -f monitoring/argocd/
