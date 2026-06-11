import json
import boto3
import os
from k8s_client import K8sObserver

# Configuration
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0")
SENSITIVITY_THRESHOLD = 0.8

bedrock_runtime = boto3.client('bedrock-runtime', region_name=os.environ.get("AGENT_AWS_REGION", "eu-north-1"))
observer = K8sObserver()

def invoke_brain(context_snapshot):
    """Uses Bedrock LLM to analyze the snapshot and decide on an action."""
    prompt = f"""
    You are a Kubernetes SRE Expert. Analyze the following cluster state snapshot and determine the best remediation action.

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
    }}
    """

    response = bedrock_runtime.invoke_model(
        modelId=BEDROCK_MODEL_ID,
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}]
        })
    )

    result = json.loads(response.get('body').read())
    return json.loads(result['content'][0]['text'])

def execute_action(action_id, namespace, pod_name, deployment_name):
    """Applies the decided fix to the cluster."""
    if action_id == "RESTART_POD":
        # Rollout restart: patch deployment with a timestamp
        import datetime
        now = datetime.datetime.now().isoformat()
        body = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "kubectl.kubernetes.io/restartedAt": now
                        }
                    }
                }
            }
        }
        observer.apps_v1.patch_namespaced_deployment(name=deployment_name, namespace=namespace, body=body)
        return f"Restarted deployment {deployment_name}"

    elif action_id == "SCALE_UP":
        # Simple increment of replicas
        deploy = observer.apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
        current_replicas = deploy.spec.replicas
        body = {"spec": {"replicas": current_replicas + 1}}
        observer.apps_v1.patch_namespaced_deployment(name=deployment_name, namespace=namespace, body=body)
        return f"Scaled up deployment {deployment_name} to {current_replicas + 1}"

    return "Manual intervention required - no automated action taken."

def lambda_handler(event, context):
    """Main entry point for the AI Self-Healing Agent."""
    try:
        # 1. Parse Alertmanager Payload
        # Note: Alertmanager sends a list of alerts
        alerts = event.get('alerts', [])
        if not alerts:
            return {"statusCode": 200, "body": "No alerts found in payload"}

        results = []
        for alert in alerts:
            namespace = alert['labels'].get('namespace', 'default')
            pod_name = alert['labels'].get('pod', 'unknown')
            deployment_name = alert['labels'].get('deployment', 'unknown')

            # 2. Observe
            print(f"Analyzing alert for pod {pod_name} in {namespace}...")
            snapshot = observer.get_pod_context(namespace, pod_name)
            snapshot['deployment'] = observer.get_deployment_context(namespace, deployment_name)

            # 3. Decide
            decision = invoke_brain(snapshot)
            print(f"AI Decision: {decision['action_id']} (Confidence: {decision['confidence']})")

            # 4. Act
            if decision['confidence'] >= SENSITIVITY_THRESHOLD and decision['action_id'] != "MANUAL":
                action_result = execute_action(decision['action_id'], namespace, pod_name, deployment_name)
                results.append({"pod": pod_name, "action": decision['action_id'], "result": action_result})
            else:
                results.append({"pod": pod_name, "action": "MANUAL", "result": "Human intervention needed"})

        return {
            "statusCode": 200,
            "body": json.dumps({
                "status": "processed",
                "details": results
            })
        }

    except Exception as e:
        print(f"Error in self-healing loop: {str(e)}")
        return {"statusCode": 500, "body": str(e)}
