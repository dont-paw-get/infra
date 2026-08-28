#!/usr/bin/env bash
# RCA Agent 합성 webhook 스모크 테스트.
#
# 사전: 별도 터미널에서 rca-agent Service로 port-forward 를 열어둔다.
#   kubectl -n monitoring port-forward svc/rca-agent 8080:8080
#
# 사용:
#   ./send-webhook.sh resolved            # firing 필터가 skip 하는지 확인 (Bedrock 호출 없음)
#   ./send-webhook.sh crashloop-firing    # 전 구간 (analyze -> Bedrock -> Discord) 확인
#
# TARGET 환경변수로 엔드포인트를 바꿀 수 있다 (기본 http://localhost:8080).
set -euo pipefail

NAME="${1:?사용법: ./send-webhook.sh <payloads/ 안의 파일 이름, 확장자 제외>}"
TARGET="${TARGET:-http://localhost:8080}"
PAYLOAD="$(cd "$(dirname "$0")" && pwd)/payloads/${NAME}.json"

if [ ! -f "$PAYLOAD" ]; then
  echo "페이로드 없음: $PAYLOAD" >&2
  echo "사용 가능:" >&2
  ls -1 "$(dirname "$PAYLOAD")" | sed 's/\.json$//' | sed 's/^/  /' >&2
  exit 1
fi

echo "POST ${TARGET}/webhook  <-  payloads/${NAME}.json"
# analyze() 가 Bedrock 왕복을 동기로 도는 동안 응답이 지연되므로 넉넉히 잡는다.
curl -sS -X POST "${TARGET}/webhook" \
  -H 'Content-Type: application/json' \
  --max-time 300 \
  --data @"$PAYLOAD"
echo
