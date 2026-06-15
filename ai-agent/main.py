"""
AI Self-Healing Agent — production FastAPI service.

Receives Alertmanager webhooks, analyses alerts via NVIDIA NIM (GLM 5.1),
and executes remediation actions on the EKS cluster.

Key features:
  • NVIDIA NIM API for AI decisions (GLM 5.1)
  • Auto-refreshing EKS STS tokens (no stale connections)
  • Cooldown / deduplication (prevents flip-flop remediation loops)
  • Retry with exponential backoff
  • Input validation via Pydantic models
  • Structured JSON logging for CloudWatch
  • Health + readiness endpoints with real connectivity checks
  • Web dashboard + remediation history for observability
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import boto3
import httpx
import uvicorn
from cachetools import TTLCache
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from k8s_client import K8sObserver
from models import (
    ActionId,
    AIDecision,
    AlertDetail,
    AlertmanagerPayload,
    HealthResponse,
    ReadinessResponse,
    RemediationResult,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NIM_API_KEY = os.environ.get("NIM_API_KEY", "")
NIM_BASE_URL = os.environ.get("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")
NIM_MODEL = os.environ.get("NIM_MODEL", "z-ai/glm-5.1")
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.8"))
AGENT_AWS_REGION = os.environ.get("AGENT_AWS_REGION", "eu-north-1")
SCALE_MAX_REPLICAS = int(os.environ.get("SCALE_MAX_REPLICAS", "5"))
COOLDOWN_SECONDS = int(os.environ.get("COOLDOWN_SECONDS", "300"))  # 5 min
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
HISTORY_MAX = int(os.environ.get("HISTORY_MAX", "100"))

# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------

class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry)


handler = logging.StreamHandler()
handler.setFormatter(JSONFormatter())
logging.basicConfig(level=LOG_LEVEL, handlers=[handler])
logger = logging.getLogger("ai-agent")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

observer: Optional[K8sObserver] = None
start_time = time.monotonic()

# Cooldown cache: key -> timestamp of last action
# TTL = COOLDOWN_SECONDS so entries auto-expire
cooldown_cache: TTLCache = TTLCache(maxsize=1024, ttl=COOLDOWN_SECONDS)

# Simple counters for health endpoint
stats = {"alerts_processed": 0, "actions_taken": 0, "actions_skipped": 0}

# Remediation history (capped ring buffer)
remediation_history: deque = deque(maxlen=HISTORY_MAX)


def get_observer() -> K8sObserver:
    """Lazy-initialise K8sObserver (thread-safe via GIL in CPython)."""
    global observer
    if observer is None:
        observer = K8sObserver()
    return observer


# ---------------------------------------------------------------------------
# NVIDIA NIM AI brain
# ---------------------------------------------------------------------------

AI_PROMPT_TEMPLATE = """You are a Kubernetes SRE Expert. Analyze the following cluster state snapshot and determine the best remediation action.

ALERT CONTEXT:
- Alert Name: {alertname}
- Severity: {severity}
- Status: {alert_status}

CLUSTER SNAPSHOT:
{snapshot_json}

SUPPORTED ACTIONS (choose exactly one):
- RESTART_POD: Rolling restart of the deployment. Use for CrashLoopBackOff, app deadlock, or stuck pods.
- SCALE_UP: Add 1 replica (max {max_replicas}). Use for OOMKilled, CPU exhaustion, or under-capacity.
- INVESTIGATE: Gather deeper diagnostics (no action taken). Use when data is inconclusive or you need more information.
- MANUAL: Escalate to human SRE. Use for network partitions, image pull errors, config errors, or low confidence.

GUIDELINES:
1. If confidence < 0.7, always choose MANUAL.
2. If the pod was OOMKilled recently and resources allow, choose SCALE_UP.
3. If the pod is crash-looping with a clear app error, choose RESTART_POD.
4. If you are unsure about root cause, choose INVESTIGATE.
5. Never choose SCALE_UP if the deployment is already at max replicas.

Return ONLY a JSON response with this exact structure:
{{
  "analysis": "Your detailed reasoning (2-4 sentences)",
  "action_id": "RESTART_POD | SCALE_UP | INVESTIGATE | MANUAL",
  "confidence": 0.0
}}"""


def _is_nim_retryable(exc: BaseException) -> bool:
    """Return True for NIM API exceptions worth retrying."""
    exc_name = type(exc).__name__
    return exc_name in (
        "ConnectError",
        "ReadTimeout",
        "ConnectTimeout",
        "HTTPStatusError",
        "ConnectionError",
    )


@retry(
    retry=retry_if_exception(_is_nim_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
def invoke_brain(snapshot: dict, alert: AlertDetail) -> AIDecision:
    """Call NVIDIA NIM API (GLM 5.1) to analyse the alert and decide an action.

    Uses the OpenAI-compatible chat completions endpoint.
    """
    if not NIM_API_KEY:
        raise RuntimeError("NIM_API_KEY is not set")

    prompt = AI_PROMPT_TEMPLATE.format(
        alertname=alert.alertname,
        severity=alert.severity,
        alert_status=alert.status.value,
        snapshot_json=json.dumps(snapshot, indent=2, default=str),
        max_replicas=SCALE_MAX_REPLICAS,
    )

    url = f"{NIM_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {NIM_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": NIM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "max_tokens": 600,
        "temperature": 0.3,
    }

    with httpx.Client(timeout=60) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()

    result = response.json()
    raw_text = result["choices"][0]["message"]["content"]

    # Parse the JSON from the model response
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.split("\n", 1)[1] if "\n" in raw_text else raw_text[3:]
        if raw_text.endswith("```"):
            raw_text = raw_text[:-3]
        raw_text = raw_text.strip()

    decision_data = json.loads(raw_text)
    logger.info(
        "NIM API response received (model=%s)", NIM_MODEL,
        extra={"correlation_id": alert.resource_key},
    )
    return AIDecision(**decision_data)


def invoke_brain_safe(snapshot: dict, alert: AlertDetail) -> AIDecision:
    """Call NIM API with retry + fallback to MANUAL on total failure."""
    try:
        return invoke_brain(snapshot, alert)
    except Exception as exc:
        logger.error(
            "NIM API call failed after retries, falling back to MANUAL",
            extra={"correlation_id": alert.resource_key, "exception": str(exc)},
        )
        return AIDecision(
            analysis=f"AI call failed: {exc}. Escalating to human.",
            action_id=ActionId.MANUAL,
            confidence=0.0,
        )


# ---------------------------------------------------------------------------
# Remediation actions
# ---------------------------------------------------------------------------

def execute_action(action_id: ActionId, alert: AlertDetail) -> str:
    """Execute the remediation action on the EKS cluster."""
    obs = get_observer()
    ns = alert.namespace
    deploy = alert.deployment

    if action_id == ActionId.RESTART_POD:
        return obs.restart_deployment(namespace=ns, deployment_name=deploy)

    elif action_id == ActionId.SCALE_UP:
        return obs.scale_deployment(
            namespace=ns, deployment_name=deploy, max_replicas=SCALE_MAX_REPLICAS
        )

    elif action_id == ActionId.INVESTIGATE:
        # No action — just log the deep context we already gathered
        events = obs.get_namespace_events(namespace=ns)
        logger.info(
            "INVESTIGATE: No automated action. Namespace events: %s",
            json.dumps(events[:5], default=str),
            extra={"correlation_id": alert.resource_key},
        )
        return f"Investigated {deploy} in {ns} - no automated action taken, events logged"

    # MANUAL — no action
    return "Manual intervention required - no automated action taken."


# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AI Self-Healing Agent</title>
<style>
  :root {
    --bg: #0f172a; --card: #1e293b; --border: #334155;
    --green: #22c55e; --red: #ef4444; --yellow: #eab308;
    --blue: #3b82f6; --purple: #a855f7; --cyan: #06b6d4;
    --text: #f1f5f9; --text2: #94a3b8;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); font-family:'Segoe UI',system-ui,sans-serif; padding:24px; }
  .header { display:flex; align-items:center; gap:16px; margin-bottom:28px; }
  .header h1 { font-size:28px; font-weight:700; }
  .header .badge { font-size:12px; padding:4px 12px; border-radius:99px; font-weight:600; }
  .badge-green { background:#22c55e22; color:var(--green); border:1px solid #22c55e44; }
  .badge-yellow { background:#eab30822; color:var(--yellow); border:1px solid #eab30844; }
  .badge-red { background:#ef444422; color:var(--red); border:1px solid #ef444444; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); gap:16px; margin-bottom:28px; }
  .stat-card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; }
  .stat-card .label { font-size:13px; color:var(--text2); margin-bottom:6px; text-transform:uppercase; letter-spacing:0.5px; }
  .stat-card .value { font-size:32px; font-weight:700; }
  .stat-card .value.green { color:var(--green); }
  .stat-card .value.blue { color:var(--blue); }
  .stat-card .value.yellow { color:var(--yellow); }
  .stat-card .value.purple { color:var(--purple); }
  .section-title { font-size:20px; font-weight:600; margin-bottom:16px; display:flex; align-items:center; gap:10px; }
  .section-title .dot { width:8px; height:8px; border-radius:50%; display:inline-block; }
  .timeline { background:var(--card); border:1px solid var(--border); border-radius:12px; overflow:hidden; }
  .timeline-header { display:grid; grid-template-columns:180px 120px 120px 100px 1fr 120px; padding:12px 16px; font-size:12px; color:var(--text2); text-transform:uppercase; letter-spacing:0.5px; border-bottom:1px solid var(--border); font-weight:600; }
  .timeline-row { display:grid; grid-template-columns:180px 120px 120px 100px 1fr 120px; padding:14px 16px; border-bottom:1px solid #1e293b55; font-size:14px; align-items:center; }
  .timeline-row:hover { background:#ffffff05; }
  .action-badge { font-size:11px; padding:3px 10px; border-radius:6px; font-weight:600; display:inline-block; }
  .action-RESTART_POD { background:#3b82f622; color:var(--blue); border:1px solid #3b82f644; }
  .action-SCALE_UP { background:#a855f722; color:var(--purple); border:1px solid #a855f744; }
  .action-INVESTIGATE { background:#06b6d422; color:var(--cyan); border:1px solid #06b6d444; }
  .action-MANUAL { background:#eab30822; color:var(--yellow); border:1px solid #eab30844; }
  .action-SKIP { background:#64748b22; color:var(--text2); border:1px solid #64748b44; }
  .conf-bar { height:6px; border-radius:3px; background:#334155; overflow:hidden; width:100px; }
  .conf-bar-fill { height:100%; border-radius:3px; transition:width 0.3s; }
  .conf-high { background:var(--green); }
  .conf-mid { background:var(--yellow); }
  .conf-low { background:var(--red); }
  .empty-state { text-align:center; padding:48px; color:var(--text2); }
  .refresh-info { font-size:12px; color:var(--text2); margin-left:auto; }
  a { color:var(--blue); text-decoration:none; }
  a:hover { text-decoration:underline; }
  .footer { margin-top:32px; font-size:13px; color:var(--text2); text-align:center; }
</style>
</head>
<body>

<div class="header">
  <h1>&#129302; AI Self-Healing Agent</h1>
  <span class="badge badge-green" id="status-badge">&#9679; Online</span>
  <span class="refresh-info">Auto-refresh: 5s</span>
</div>

<div class="grid" id="stats-grid">
  <div class="stat-card"><div class="label">Alerts Processed</div><div class="value green" id="v-processed">—</div></div>
  <div class="stat-card"><div class="label">Actions Taken</div><div class="value blue" id="v-taken">—</div></div>
  <div class="stat-card"><div class="label">Actions Skipped</div><div class="value yellow" id="v-skipped">—</div></div>
  <div class="stat-card"><div class="label">Uptime</div><div class="value purple" id="v-uptime">—</div></div>
  <div class="stat-card"><div class="label">EKS Connection</div><div class="value green" id="v-eks">—</div></div>
  <div class="stat-card"><div class="label">AI Model</div><div class="value" id="v-model" style="font-size:16px;">—</div></div>
</div>

<div class="section-title">
  <span class="dot" style="background:var(--blue);"></span>
  Remediation History
  <span class="refresh-info"><a href="/history">JSON</a> &middot; <a href="/stats">Stats API</a></span>
</div>

<div class="timeline" id="timeline">
  <div class="timeline-header">
    <div>Time</div><div>Alert</div><div>Deployment</div><div>Action</div><div>AI Analysis</div><div>Confidence</div>
  </div>
  <div id="timeline-rows">
    <div class="empty-state">No remediation events yet — waiting for alerts...</div>
  </div>
</div>

<div class="footer">
  AI Self-Healing Agent v3.0 &middot; NVIDIA NIM (GLM 5.1) &middot; ECS Fargate + EKS
</div>

<script>
const fmt = s => {
  if (!s) return '—';
  const d = new Date(s);
  return d.toLocaleTimeString('en-GB', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
};
const fmtUptime = s => {
  if (s < 60) return s + 's';
  if (s < 3600) return Math.floor(s/60) + 'm ' + (s%60) + 's';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h + 'h ' + m + 'm';
};

async function refresh() {
  try {
    const [statsRes, historyRes, healthRes, readyRes] = await Promise.all([
      fetch('/stats'), fetch('/history'), fetch('/health'), fetch('/ready')
    ]);
    const st = await statsRes.json();
    const hi = await historyRes.json();
    const he = await healthRes.json();
    const re = await readyRes.json();

    document.getElementById('v-processed').textContent = st.alerts_processed;
    document.getElementById('v-taken').textContent = st.actions_taken;
    document.getElementById('v-skipped').textContent = st.actions_skipped;
    document.getElementById('v-uptime').textContent = fmtUptime(st.uptime_seconds);
    document.getElementById('v-eks').textContent = re.eks_connected ? 'Connected' : 'Disconnected';
    document.getElementById('v-eks').style.color = re.eks_connected ? 'var(--green)' : 'var(--red)';
    document.getElementById('v-model').textContent = 'GLM 5.1';

    const badge = document.getElementById('status-badge');
    badge.textContent = re.ready ? '● Online' : '● Degraded';
    badge.className = 'badge ' + (re.ready ? 'badge-green' : 'badge-yellow');

    const rows = document.getElementById('timeline-rows');
    if (!hi.length) {
      rows.innerHTML = '<div class="empty-state">No remediation events yet — waiting for alerts...</div>';
    } else {
      rows.innerHTML = hi.slice().reverse().map(e => {
        const confClass = e.confidence >= 0.8 ? 'conf-high' : e.confidence >= 0.5 ? 'conf-mid' : 'conf-low';
        const pct = Math.round(e.confidence * 100);
        return `<div class="timeline-row">
          <div style="color:var(--text2);font-size:13px;">${fmt(e.timestamp)}</div>
          <div style="font-weight:600;">${e.alertname}</div>
          <div><span style="color:var(--text2);">${e.namespace}/</span>${e.deployment}</div>
          <div><span class="action-badge action-${e.action}">${e.action}</span></div>
          <div style="font-size:13px;color:var(--text2);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:400px;" title="${(e.analysis||'').replace(/"/g,'"')}">${e.analysis || e.result || '—'}</div>
          <div style="display:flex;align-items:center;gap:8px;">
            <div class="conf-bar"><div class="conf-bar-fill ${confClass}" style="width:${pct}%;"></div></div>
            <span style="font-size:13px;">${pct}%</span>
          </div>
        </div>`;
      }).join('');
    }
  } catch(err) {
    console.error('Dashboard refresh failed:', err);
  }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise K8s observer and start periodic EKS health check."""
    import asyncio

    logger.info("AI Self-Healing Agent starting up (model=%s)...", NIM_MODEL)
    try:
        get_observer()
        logger.info("K8s observer initialised successfully")
    except Exception as exc:
        logger.warning("K8s observer init failed (will retry on first webhook): %s", exc)

    async def periodic_eks_check():
        """Background task: test EKS connectivity every 60s and log result."""
        await asyncio.sleep(15)  # wait for first token refresh
        while True:
            try:
                connected = get_observer().check_connection()
                if connected:
                    logger.info("Periodic EKS check: CONNECTED")
                else:
                    logger.warning("Periodic EKS check: FAILED - cannot reach EKS API")
            except Exception as exc:
                logger.warning("Periodic EKS check exception: %s", exc)
            await asyncio.sleep(60)

    task = asyncio.create_task(periodic_eks_check())
    yield
    task.cancel()
    logger.info("AI Self-Healing Agent shutting down")


app = FastAPI(
    title="AI Self-Healing Agent",
    version="3.0.0",
    description="Receives Alertmanager webhooks, analyses via NVIDIA NIM, and remediates EKS issues",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
def health():
    """Liveness: lightweight - always returns 200 quickly.

    ALB uses this endpoint with a 5-second timeout, so we must
    respond instantly. Deep connectivity checks are on /ready instead.
    """
    return HealthResponse(
        status="healthy",
        nim="ok",
        eks="ok" if observer is not None else "initialising",
        uptime_seconds=round(time.monotonic() - start_time, 1),
    )


@app.get("/ready", response_model=ReadinessResponse)
def readiness():
    """Readiness: returns 200 only when EKS connection is established."""
    try:
        connected = get_observer().check_connection()
    except Exception:
        connected = False

    return ReadinessResponse(
        ready=connected,
        eks_connected=connected,
        reason=None if connected else "Cannot connect to EKS cluster",
    )


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    """Beautiful web dashboard showing agent status and remediation history."""
    return DASHBOARD_HTML


@app.get("/history")
def get_history():
    """Return recent remediation events as JSON."""
    return list(remediation_history)


@app.post("/webhook")
async def alertmanager_webhook(request: Request):
    """Main webhook: receive Alertmanager payload, analyse, remediate."""
    correlation_id = str(uuid.uuid4())[:8]
    logger.info(
        "Webhook received", extra={"correlation_id": correlation_id}
    )

    # Parse and validate payload
    try:
        raw = await request.json()
        payload = AlertmanagerPayload(**raw)
    except Exception as exc:
        logger.error("Invalid webhook payload: %s", exc, extra={"correlation_id": correlation_id})
        return JSONResponse(
            status_code=400,
            content={"status": "error", "message": f"Invalid payload: {exc}"},
        )

    if not payload.alerts:
        return {"status": "ok", "message": "No alerts in payload"}

    obs = get_observer()
    results: list[dict] = []
    now = time.time()

    for alert in payload.alerts:
        cid = f"{correlation_id}-{alert.pod}"
        logger.info(
            "Processing alert: %s pod=%s ns=%s deploy=%s severity=%s",
            alert.alertname, alert.pod, alert.namespace, alert.deployment, alert.severity,
            extra={"correlation_id": cid},
        )

        # ---- Cooldown check ----
        key = alert.resource_key
        if key in cooldown_cache:
            last_action_time = cooldown_cache[key]
            remaining = int(COOLDOWN_SECONDS - (now - last_action_time))
            logger.warning(
                "Cooldown active for %s - skipping (%ds remaining)",
                key, remaining,
                extra={"correlation_id": cid},
            )
            stats["actions_skipped"] += 1
            result_entry = RemediationResult(
                pod=alert.pod,
                namespace=alert.namespace,
                deployment=alert.deployment,
                alertname=alert.alertname,
                action="SKIP",
                confidence=0.0,
                result=f"Cooldown: {remaining}s remaining",
                skipped=True,
                skip_reason="cooldown",
                correlation_id=cid,
            )
            results.append(result_entry.model_dump())
            remediation_history.append(result_entry.model_dump())
            continue

        # ---- Gather context ----
        snapshot: dict = {"alert": {
            "name": alert.alertname,
            "status": alert.status.value,
            "severity": alert.severity,
            "annotations": alert.annotations,
        }}

        if alert.pod != "unknown":
            snapshot["pod"] = obs.get_pod_context(alert.namespace, alert.pod)

        if alert.deployment != "unknown":
            snapshot["deployment"] = obs.get_deployment_context(alert.namespace, alert.deployment)

        # ---- AI decision ----
        decision = invoke_brain_safe(snapshot, alert)
        logger.info(
            "AI Decision: action=%s confidence=%.2f analysis=%s",
            decision.action_id.value, decision.confidence, decision.analysis[:100],
            extra={"correlation_id": cid},
        )

        # ---- Execute or skip ----
        if decision.confidence >= CONFIDENCE_THRESHOLD and decision.action_id != ActionId.MANUAL:
            try:
                action_result = execute_action(decision.action_id, alert)
                cooldown_cache[key] = now  # mark cooldown
                stats["actions_taken"] += 1
            except Exception as exc:
                action_result = f"Action failed: {exc}"
                logger.error(
                    "Action execution failed: %s", exc,
                    extra={"correlation_id": cid},
                )
        else:
            action_result = "Human intervention needed (low confidence or MANUAL)"
            stats["actions_skipped"] += 1

        stats["alerts_processed"] += 1
        result_entry = RemediationResult(
            pod=alert.pod,
            namespace=alert.namespace,
            deployment=alert.deployment,
            alertname=alert.alertname,
            action=decision.action_id.value,
            confidence=decision.confidence,
            result=action_result,
            analysis=decision.analysis,
            correlation_id=cid,
        )
        results.append(result_entry.model_dump())
        remediation_history.append(result_entry.model_dump())

    return {"status": "processed", "details": results, "stats": stats}


@app.get("/stats")
def get_stats():
    """Expose alert processing counters."""
    return {
        "alerts_processed": stats["alerts_processed"],
        "actions_taken": stats["actions_taken"],
        "actions_skipped": stats["actions_skipped"],
        "cooldown_size": len(cooldown_cache),
        "uptime_seconds": round(time.monotonic() - start_time, 1),
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level=LOG_LEVEL.lower(),
        access_log=True,
    )
