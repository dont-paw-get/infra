# 시크릿 관리 정책

이 저장소에는 실제 시크릿 값(Discord 웹훅 URL, Grafana admin 비밀번호 등)을 커밋하지 않는다 — `backend-book`과 동일한 원칙.

## 현재 방식 (임시)

저장소 루트의 `.env`(gitignore됨)에 값을 채운다.

```bash
# .env
GRAFANA_ADMIN_USER=admin
GRAFANA_ADMIN_PASSWORD=<직접-생성한-강력한-비밀번호>
DISCORD_WEBHOOK_URL=<discord-webhook-url>
```

`scripts/install.sh`가 이 `.env`를 읽어 `monitoring` 네임스페이스 생성, `grafana-admin-credentials`/`discord-webhook` Secret 생성(재실행 시 갱신)까지 자동으로 처리한다. 수동으로 하고 싶다면:

```bash
set -a; source .env; set +a

kubectl create namespace monitoring

kubectl -n monitoring create secret generic grafana-admin-credentials \
  --from-literal=admin-user="$GRAFANA_ADMIN_USER" \
  --from-literal=admin-password="$GRAFANA_ADMIN_PASSWORD"

kubectl -n monitoring create secret generic discord-webhook \
  --from-literal=url="$DISCORD_WEBHOOK_URL"
```

`monitoring/alerting/contact-points/discord.yaml`의 `${DISCORD_WEBHOOK_URL}`은 위 Secret 값이 아니라 `.env`의 값을 `scripts/install.sh`가 `envsubst`로 직접 치환해 Grafana alerting provisioning ConfigMap에 주입하는 자리표시자다.

## 미결정 항목

시크릿 관리 관련 미결정 항목은 `.harness/PLAN.md`의 "시크릿 관리" 섹션에서 관리한다 (중복 기록 방지).
