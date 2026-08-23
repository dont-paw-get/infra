#!/usr/bin/env bash
# 관측 스택(kube-prometheus-stack + Loki + Alloy) 설치/업그레이드.
# 사전 조건: 저장소 루트 .env(secrets/README.md 참고)에 값이 채워져 있어야 한다.
set -euo pipefail

NAMESPACE=monitoring

if [ ! -f .env ]; then
  echo "저장소 루트에 .env가 없습니다. secrets/README.md를 참고해 값을 채워주세요." >&2
  exit 1
fi
set -a
source .env
set +a

for var in GRAFANA_ADMIN_USER GRAFANA_ADMIN_PASSWORD DISCORD_WEBHOOK_URL; do
  if [ -z "${!var:-}" ]; then
    echo ".env의 $var 값이 비어 있습니다." >&2
    exit 1
  fi
done

helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

kubectl apply -f monitoring/namespace.yaml

# .env 값으로 Secret을 생성/갱신한다 (이미 있으면 덮어씀 — 재실행 안전).
kubectl -n "$NAMESPACE" create secret generic grafana-admin-credentials \
  --from-literal=admin-user="$GRAFANA_ADMIN_USER" \
  --from-literal=admin-password="$GRAFANA_ADMIN_PASSWORD" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl -n "$NAMESPACE" create secret generic discord-webhook \
  --from-literal=url="$DISCORD_WEBHOOK_URL" \
  --dry-run=client -o yaml | kubectl apply -f -

# monitoring/alerting/ 하위 provisioning YAML을 grafana_alert=1 라벨의 ConfigMap으로 만든다.
# kube-prometheus-stack의 grafana sidecar.alerts가 이 라벨을 감시해 자동으로 반영한다.
for dir in contact-points policies rules; do
  for file in monitoring/alerting/"$dir"/*.yaml; do
    name="grafana-alerting-$(basename "$file" .yaml)"
    envsubst < "$file" \
      | kubectl create configmap "$name" \
          --from-file="$(basename "$file")=/dev/stdin" \
          --namespace "$NAMESPACE" \
          --dry-run=client -o yaml \
      | kubectl label --local -f - grafana_alert=1 -o yaml \
      | kubectl apply -f -
  done
done

helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace "$NAMESPACE" \
  -f monitoring/kube-prometheus-stack/values.yaml

helm upgrade --install loki grafana/loki \
  --namespace "$NAMESPACE" \
  -f monitoring/loki/values.yaml

helm upgrade --install alloy grafana/alloy \
  --namespace "$NAMESPACE" \
  -f monitoring/alloy/values.yaml
