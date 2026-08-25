import httpx

import config


def send_rca_report(alert_name: str, summary: str) -> None:
    payload = {
        "embeds": [
            {
                "title": f"RCA: {alert_name}",
                "description": summary[:4096],
            }
        ]
    }
    httpx.post(config.DISCORD_WEBHOOK_URL, json=payload, timeout=10)
