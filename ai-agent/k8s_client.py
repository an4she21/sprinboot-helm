"""
Kubernetes client with auto-refreshing EKS STS token.

Uses AWS STS GetCallerIdentity signed URL to generate short-lived
authentication tokens for EKS. Token is automatically refreshed
before expiry to keep long-running agents connected.
"""

from __future__ import annotations

import base64
import logging
import tempfile
import threading
import time
from typing import Any, Optional

import boto3
from botocore.signers import RequestSigner
from kubernetes import client as k8s_client
from kubernetes.client.exceptions import ApiException
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# STS pre-signed URLs are valid for 15 minutes max.
# We refresh a bit earlier to avoid edge-case expiries.
TOKEN_DURATION_SECONDS = 900  # 15 min max
TOKEN_REFRESH_MARGIN_SECONDS = 120  # refresh 2 min before expiry


class K8sObserver:
    """Thread-safe EKS Kubernetes client with auto-refreshing auth token."""

    def __init__(self) -> None:
        self.cluster_name: str = _env("CLUSTER_NAME", "ai-selfhealing-cluster-dev")
        self.region: str = _env("AGENT_AWS_REGION", "eu-north-1")

        # Discover cluster endpoint + CA if not provided via env
        self.cluster_endpoint: str = _env("EKS_CLUSTER_ENDPOINT", "")
        self.cluster_ca: str = _env("EKS_CLUSTER_CA", "")

        if not self.cluster_endpoint:
            self._discover_cluster()

        # Token state (guarded by lock)
        self._token: str = ""
        self._token_fetched_at: float = 0.0
        self._token_lock = threading.Lock()

        # Bootstrap configuration
        self._init_k8s_config()

        # API clients
        self.core_v1 = k8s_client.CoreV1Api()
        self.apps_v1 = k8s_client.AppsV1Api()

        logger.info(
            "Connected to EKS cluster",
            extra={"cluster": self.cluster_name, "endpoint": self.cluster_endpoint},
        )

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    def _ensure_valid_token(self) -> None:
        """Refresh the STS token if it is near expiry.

        Called before every K8s API operation — cheap when token is fresh
        (just a lock + timestamp check), auto-refreshes when needed.
        """
        now = time.monotonic()
        with self._token_lock:
            age = now - self._token_fetched_at
            if self._token and age < (TOKEN_DURATION_SECONDS - TOKEN_REFRESH_MARGIN_SECONDS):
                return  # still fresh
            logger.info("Refreshing EKS STS token (age=%.0fs)", age)
            self._token = self._get_eks_token()
            self._token_fetched_at = now
            # Update the default configuration with the new token
            k8s_client.Configuration.get_default_copy().api_key["authorization"] = (
                f"Bearer {self._token}"
            )
            # Also update the global default so all API clients pick it up
            config = k8s_client.Configuration()
            config.host = self.cluster_endpoint
            config.api_key = {"authorization": f"Bearer {self._token}"}
            config.timeout = 30  # 30s timeout for all K8s API calls
            if self._ssl_ca_file:
                config.ssl_ca_cert = self._ssl_ca_file
                config.verify_ssl = True
            else:
                config.verify_ssl = False
            k8s_client.Configuration.set_default(config)
            # Re-create API clients so they use the refreshed config
            self.core_v1 = k8s_client.CoreV1Api()
            self.apps_v1 = k8s_client.AppsV1Api()

    def _get_eks_token(self) -> str:
        """Generate a k8s-aws-v1 token using STS GetCallerIdentity."""
        session = boto3.Session()
        sts = session.client("sts", region_name=self.region)
        service_id = sts.meta.service_model.service_id

        signer = RequestSigner(
            service_id,
            self.region,
            "sts",
            "v4",
            session.get_credentials(),
            session.events,
        )

        params = {
            "method": "GET",
            "url": (
                f"https://sts.{self.region}.amazonaws.com/"
                f"?Action=GetCallerIdentity&Version=2011-06-15"
            ),
            "body": {},
            "headers": {"x-k8s-aws-id": self.cluster_name},
            "context": {},
        }

        signed_url = signer.generate_presigned_url(
            params,
            region_name=self.region,
            expires_in=TOKEN_DURATION_SECONDS,
            operation_name="",
        )

        token = (
            "k8s-aws-v1."
            + base64.urlsafe_b64encode(signed_url.encode("utf-8"))
            .rstrip(b"=")
            .decode("utf-8")
        )
        return token

    # ------------------------------------------------------------------
    # Cluster discovery & config bootstrap
    # ------------------------------------------------------------------

    def _discover_cluster(self) -> None:
        eks = boto3.client("eks", region_name=self.region)
        cluster = eks.describe_cluster(name=self.cluster_name)["cluster"]
        self.cluster_endpoint = cluster["endpoint"]
        self.cluster_ca = cluster["certificateAuthority"]["data"]
        logger.info("Discovered EKS cluster endpoint: %s", self.cluster_endpoint)

    _ssl_ca_file: Optional[str] = None

    def _init_k8s_config(self) -> None:
        """Build initial kubernetes-client Configuration object."""
        self._token = self._get_eks_token()
        self._token_fetched_at = time.monotonic()

        config = k8s_client.Configuration()
        config.host = self.cluster_endpoint
        config.api_key = {"authorization": f"Bearer {self._token}"}
        config.timeout = 30  # 30s timeout for all K8s API calls

        if self.cluster_ca:
            ca_file = tempfile.NamedTemporaryFile(
                delete=False, suffix=".crt", prefix="eks-ca-"
            )
            ca_file.write(base64.b64decode(self.cluster_ca))
            ca_file.close()
            config.ssl_ca_cert = ca_file.name
            config.verify_ssl = True
            self._ssl_ca_file = ca_file.name
        else:
            config.verify_ssl = False

        k8s_client.Configuration.set_default(config)

    # ------------------------------------------------------------------
    # Observability methods (all auto-refresh token first)
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type((ApiException, ConnectionError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def get_pod_context(self, namespace: str, pod_name: str) -> dict[str, Any]:
        """Gather pod status, recent logs, and relevant events."""
        self._ensure_valid_token()
        context: dict[str, Any] = {}

        try:
            pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            context["status"] = pod.status.phase
            context["restart_count"] = sum(
                c.restart_count for c in (pod.status.container_statuses or [])
            )
            context["containers"] = [
                {
                    "name": c.name,
                    "image": c.image,
                    "ready": c.ready,
                    "restart_count": c.restart_count,
                    "state": _container_state_dict(c.state),
                    "last_termination_reason": (
                        c.last_state.terminated.reason if c.last_state and c.last_state.terminated else None
                    ),
                }
                for c in (pod.status.container_statuses or [])
            ]
        except ApiException as exc:
            if exc.status == 404:
                context["error"] = f"Pod {pod_name} not found in {namespace}"
            else:
                context["error"] = f"K8s API error: {exc}"
            return context

        # Recent logs (last 100 lines)
        try:
            logs = self.core_v1.read_namespaced_pod_log(
                name=pod_name, namespace=namespace, tail_lines=100
            )
            context["logs"] = logs
        except Exception:
            context["logs"] = "Unable to fetch logs"

        # Events related to this pod
        try:
            events = self.core_v1.list_namespaced_event(namespace=namespace)
            relevant = [
                {"message": e.message, "reason": e.reason, "count": e.count}
                for e in events.items
                if e.involved_object and e.involved_object.name == pod_name
            ]
            context["events"] = relevant[-10:]
        except Exception:
            context["events"] = []

        return context

    @retry(
        retry=retry_if_exception_type((ApiException, ConnectionError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def get_deployment_context(
        self, namespace: str, deployment_name: str
    ) -> dict[str, Any]:
        """Gather deployment replica status."""
        self._ensure_valid_token()
        try:
            deploy = self.apps_v1.read_namespaced_deployment(
                name=deployment_name, namespace=namespace
            )
            return {
                "replicas": deploy.spec.replicas,
                "ready_replicas": deploy.status.ready_replicas or 0,
                "updated_replicas": deploy.status.updated_replicas or 0,
                "unavailable_replicas": deploy.status.unavailable_replicas or 0,
            }
        except ApiException as exc:
            if exc.status == 404:
                return {"error": f"Deployment {deployment_name} not found"}
            return {"error": f"K8s API error: {exc}"}

    @retry(
        retry=retry_if_exception_type((ApiException, ConnectionError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def get_namespace_events(self, namespace: str, limit: int = 20) -> list[dict]:
        """Fetch recent events in a namespace (useful for INVESTIGATE action)."""
        self._ensure_valid_token()
        try:
            events = self.core_v1.list_namespaced_event(namespace=namespace)
            return [
                {
                    "message": e.message,
                    "reason": e.reason,
                    "count": e.count,
                    "involved_object": (
                        f"{e.involved_object.kind}/{e.involved_object.name}"
                        if e.involved_object
                        else "unknown"
                    ),
                    "last_timestamp": str(e.last_timestamp or e.event_time),
                    "type": e.type,
                }
                for e in (events.items or [])[-limit:]
            ]
        except Exception as exc:
            logger.warning("Failed to fetch namespace events: %s", exc)
            return []

    @retry(
        retry=retry_if_exception_type((ApiException, ConnectionError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def get_nodes_context(self) -> list[dict[str, Any]]:
        """Gather node-level info for deeper cluster diagnostics."""
        self._ensure_valid_token()
        try:
            nodes = self.core_v1.list_node()
            result = []
            for n in (nodes.items or []):
                conditions = {
                    c.type: c.status
                    for c in (n.status.conditions or [])
                }
                result.append({
                    "name": n.metadata.name,
                    "ready": conditions.get("Ready", "Unknown"),
                    "memory_pressure": conditions.get("MemoryPressure", "Unknown"),
                    "disk_pressure": conditions.get("DiskPressure", "Unknown"),
                    "pid_pressure": conditions.get("PIDPressure", "Unknown"),
                    "network_unavailable": conditions.get("NetworkUnavailable", "Unknown"),
                })
            return result
        except Exception as exc:
            logger.warning("Failed to fetch node info: %s", exc)
            return [{"error": str(exc)}]

    # ------------------------------------------------------------------
    # Remediation actions (also auto-refresh token)
    # ------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type((ApiException, ConnectionError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def restart_deployment(self, namespace: str, deployment_name: str) -> str:
        """Rolling restart: patch deployment with restartedAt annotation."""
        self._ensure_valid_token()
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
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
        self.apps_v1.patch_namespaced_deployment(
            name=deployment_name, namespace=namespace, body=body
        )
        msg = f"Restarted deployment {deployment_name} in {namespace}"
        logger.info(msg)
        return msg

    @retry(
        retry=retry_if_exception_type((ApiException, ConnectionError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def scale_deployment(
        self, namespace: str, deployment_name: str, max_replicas: int = 5
    ) -> str:
        """Scale up by 1 replica, capped at max_replicas to prevent runaway."""
        self._ensure_valid_token()
        deploy = self.apps_v1.read_namespaced_deployment(
            name=deployment_name, namespace=namespace
        )
        current = deploy.spec.replicas or 1
        if current >= max_replicas:
            msg = (
                f"Scale-up blocked: deployment {deployment_name} already at "
                f"max replicas ({max_replicas})"
            )
            logger.warning(msg)
            return msg

        new_count = current + 1
        body = {"spec": {"replicas": new_count}}
        self.apps_v1.patch_namespaced_deployment(
            name=deployment_name, namespace=namespace, body=body
        )
        msg = f"Scaled deployment {deployment_name} from {current} to {new_count} replicas"
        logger.info(msg)
        return msg

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def check_connection(self) -> bool:
        """Quick liveness check: can we reach the K8s API? (5s timeout)"""
        try:
            self._ensure_valid_token()
            # Use a short timeout so we don't block health checks
            old_timeout = k8s_client.Configuration.get_default_copy().timeout
            config = k8s_client.Configuration.get_default_copy()
            config.timeout = 5
            k8s_client.Configuration.set_default(config)
            self.core_v1 = k8s_client.CoreV1Api()
            self.core_v1.list_namespace(limit=1)
            # Restore original timeout
            config.timeout = old_timeout or 30
            k8s_client.Configuration.set_default(config)
            self.core_v1 = k8s_client.CoreV1Api()
            return True
        except Exception as exc:
            logger.warning("EKS connection check failed: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(key: str, default: str = "") -> str:
    import os
    return os.environ.get(key, default)


def _container_state_dict(state: Any) -> Optional[dict]:
    """Convert a kubernetes container state object to a simple dict."""
    if state is None:
        return None
    if state.waiting:
        return {"waiting": {"reason": state.waiting.reason, "message": state.waiting.message}}
    if state.running:
        return {"running": {"started_at": str(state.running.started_at)}}
    if state.terminated:
        return {
            "terminated": {
                "reason": state.terminated.reason,
                "exit_code": state.terminated.exit_code,
            }
        }
    return None
