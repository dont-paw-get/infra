import os


BEDROCK_REGION = os.environ.get("BEDROCK_REGION", "ap-northeast-2")
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-5")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://prometheus-operated.monitoring.svc.cluster.local:9090")
LOKI_URL = os.environ.get("LOKI_URL", "http://loki-gateway.monitoring.svc.cluster.local")
TEMPO_URL = os.environ.get("TEMPO_URL", "http://tempo.monitoring.svc.cluster.local:3200")
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
