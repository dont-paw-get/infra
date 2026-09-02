#!/usr/bin/env bash
# MFA 임시 자격증명(12h)을 발급받아 `dpgy-mfa` 프로파일에 바로 주입하고
# kubeconfig(dpyb-dev)가 그 프로파일을 쓰도록 갱신한다.
# 장기 키는 `dpgy-infra` 프로파일(IAM user/kosa12)에서 읽는다.
# 자격증명 값은 터미널에 출력하지 않는다. OTP 6자리만 입력받는다.
#
#   사용법: bash scripts/aws-mfa-login.sh
#           OTP_CODE=123456 bash scripts/aws-mfa-login.sh   # 비대화식

set -euo pipefail

MFA_SERIAL="arn:aws:iam::594532711953:mfa/otp-cli"
SRC_PROFILE="dpgy-infra"   # 장기 IAM 사용자 키(kosa12) — get-session-token 호출용
PROFILE="dpgy-mfa"         # 발급된 12h 임시 자격증명을 넣을 프로파일
REGION="ap-northeast-2"
CLUSTER="dpyb-dev"

CODE="${OTP_CODE:-}"
if [[ -z "$CODE" ]]; then
  read -rsp "MFA 6자리 코드: " CODE
  echo
fi

# 자격증명을 탭 구분 한 줄로만 받는다(화면 출력 없음).
read -r AK SK ST EXP < <(aws sts get-session-token \
  --profile "$SRC_PROFILE" \
  --serial-number "$MFA_SERIAL" \
  --token-code "$CODE" \
  --duration-seconds 43200 \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken,Expiration]' \
  --output text)

if [[ -z "${AK:-}" || -z "${SK:-}" || -z "${ST:-}" ]]; then
  echo "실패: 자격증명을 받지 못했습니다 (OTP 코드 확인)" >&2
  exit 1
fi

aws configure set aws_access_key_id     "$AK" --profile "$PROFILE"
aws configure set aws_secret_access_key "$SK" --profile "$PROFILE"
aws configure set aws_session_token     "$ST" --profile "$PROFILE"
aws configure set region                "$REGION" --profile "$PROFILE"

unset AK SK ST

aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" --profile "$PROFILE" >/dev/null

echo "OK: mfa 프로파일 + kubeconfig 갱신 완료 (만료: $EXP)"
aws sts get-caller-identity --profile "$PROFILE" --query Arn --output text
