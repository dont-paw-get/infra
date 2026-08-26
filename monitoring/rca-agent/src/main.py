from fastapi import FastAPI, Request

from analyzer import analyze
from notifier import send_rca_report

app = FastAPI()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request):
    body = await request.json()
    for alert in body.get("alerts", []):
        if alert.get("status") != "firing":
            continue
        alert_name = alert.get("labels", {}).get("alertname", "unknown")
        summary = analyze(alert)
        send_rca_report(alert_name, summary)
    return {"received": len(body.get("alerts", []))}
