import asyncio
import logging

from fastapi import BackgroundTasks, FastAPI, Request

from analyzer import analyze
from notifier import send_rca_report

logger = logging.getLogger("rca-agent")

app = FastAPI()


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def _analyze_and_report(alert: dict) -> None:
    """Bedrock 호출(수십 초)과 Discord 전송을 수행한다. 모두 블로킹 I/O라 워커 스레드에서 실행된다."""
    alert_name = alert.get("labels", {}).get("alertname", "unknown")
    try:
        summary = analyze(alert)
    except Exception:
        # 분석이 실패해도 Discord에 실패 사실을 남긴다 — 원본 알림과 RCA는 별개 경로라
        # 여기서 조용히 죽으면 RCA가 돌았는지조차 알 수 없다 (docs/adr/0002 미결정 항목).
        logger.exception("RCA 분석 실패: %s", alert_name)
        summary = (
            "RCA 분석에 실패했습니다. Agent 로그(`kubectl -n monitoring logs -l app=rca-agent`)를 확인하세요."
        )
    try:
        send_rca_report(alert_name, summary)
    except Exception:
        logger.exception("Discord 전송 실패: %s", alert_name)


async def _run_analysis(alert: dict) -> None:
    # 이벤트 루프에서 직접 분석을 돌리면 /healthz 가 응답하지 못해 liveness probe 가 파드를 죽인다.
    await asyncio.to_thread(_analyze_and_report, alert)


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    """Grafana Alerting webhook 수신부. 분석은 백그라운드로 넘기고 즉시 응답한다 —
    Grafana의 webhook 전송에는 짧은 타임아웃이 있어 분석을 기다리면 전송이 실패로 처리된다."""
    body = await request.json()
    alerts = body.get("alerts", [])
    queued = 0
    for alert in alerts:
        if alert.get("status") != "firing":
            continue
        background_tasks.add_task(_run_analysis, alert)
        queued += 1
    return {"received": len(alerts), "queued": queued}
