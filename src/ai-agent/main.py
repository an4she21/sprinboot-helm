import os
import json
import logging
from fastapi import FastAPI, Request
from pydantic import BaseModel
import boto3
from k8s_client import K8sObserver

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="AI Self-Healing Agent", version="2.0.0")

BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.8"))
AGENT_AWS_REGION = os.environ.get("AGENT_AWS_REGION", "eu-north-1")

bedrock_runtime = boto3.client("bedrock-runtime", region_name=AGENT_AWS_REGION)
observer = None


def get_observer():
    global observer
    if observer is None:
        observer = K8sObserver()
    return observer


def invoke_brain(context_snapshot: dict) -> dict:
    prompt = f"""You are a Kubernetes SRE Expert. Analyze the following cluster state snapshot and determine the best remediation action.

SNAPSHOT:
{json.dumps(context_snapshot, indent=2)}

SUPPORTED ACTIONS:
- RESTART_POD: Use if the pod is in CrashLoopBackOff or Deadlock.
- SCALE_UP: Use if the pod is OOMKilled or CPU exhausted.
- MANUAL: Use if the issue is a network partition, image error, or low confidence.

Return ONLY a JSON response with this structure:
{{
  "analysis": "Your detailed reasoning",
  "action_id": "RESTART_POD | SCALE_UP | MANUAL",
  "confidence": 0.0 to 1.0
}}"""

    response = bedrock_runtime.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
        }),
    )

    result = json.loads(response["body"].read())
    return json.loads(result["content"][0]["text"])


def execute_action(action_id: str, namespace: str, pod_name: str, deployment_name: str) -> str:
    obs = get_observer()
    if action_id == "RESTART_POD":
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": now,
                        }
                    }
                }
            }
        }
        obs.apps_v1.patch_namespaced_deployment(name=deployment_name, namespace=namespace, body=body)
        return f"Restarted deployment {deployment_name}"

    elif action_id == "SCALE_UP":
        deploy = obs.apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        current_replicas = deploy.spec.replicas or 1
        body = {"spec": {"replicas": current_replicas + 1}}
        obs.apps_v1.patch_namespaced_deployment(name=deployment_name, namespace=namespace, body=body)
        return f"Scaled up deployment {deployment_name} to {current_replicas + 1}"

    return "Manual intervention required - no automated action taken."


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/webhook")
async def alertmanager_webhook(request: Request):
    """Receives Alertmanager webhook payload and processes alerts."""
    try:
        payload = await request.json()
        alerts = payload.get("alerts", [])
        if not alerts:
            return {"status": "ok", "message": "No alerts in payload"}

        obs = get_observer()
        results = []

        for alert in alerts:
            labels = alert.get("labels", {})
            namespace = labels.get("namespace", "default")
            pod_name = labels.get("pod", "unknown")
            deployment_name = labels.get("deployment", pod_name.rsplit("-", 2)[0] if pod_name != "unknown" else "unknown")

            logger.info(f"Processing alert for pod={pod_name} namespace={namespace} deployment={deployment_name}")

            snapshot = obs.get_pod_context(namespace, pod_name)
            snapshot["deployment"] = obs.get_deployment_context(namespace, deployment_name)
            snapshot["alert"] = {
                "name": alert.get("labels", {}).get("alertname", "unknown"),
                "status": alert.get("status", "unknown"),
                "annotations": alert.get("annotations", {}),
            }

            decision = invoke_brain(snapshot)
            logger.info(f"AI Decision: action={decision['action_id']} confidence={decision['confidence']}")

            if decision["confidence"] >= CONFIDENCE_THRESHOLD and decision["action_id"] != "MANUAL":
                action_result = execute_action(decision["action_id"], namespace, pod_name, deployment_name)
                results.append({"pod": pod_name, "action": decision["action_id"], "result": action_result})
            else:
                results.append({"pod": pod_name, "action": "MANUAL", "result": "Human intervention needed", "analysis": decision["analysis"]})

        return {"status": "processed", "details": results}

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return {"status": "error", "message": str(e)}
