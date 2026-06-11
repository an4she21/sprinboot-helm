import os
import base64
import logging
from kubernetes import client
import boto3
from botocore.signers import RequestSigner

logger = logging.getLogger(__name__)

STS_TOKEN_EXPIRES_IN = 60


class K8sObserver:
    def __init__(self):
        self.cluster_name = os.environ.get("CLUSTER_NAME", "ai-selfhealing-cluster-dev")
        self.cluster_endpoint = os.environ.get("EKS_CLUSTER_ENDPOINT")
        self.cluster_ca = os.environ.get("EKS_CLUSTER_CA", "")
        self.region = os.environ.get("AGENT_AWS_REGION", "eu-north-1")

        if not self.cluster_endpoint:
            self.cluster_endpoint, self.cluster_ca = self._discover_cluster()

        token = self._get_eks_token()

        configuration = client.Configuration()
        configuration.host = self.cluster_endpoint
        configuration.api_key = {"authorization": f"Bearer {token}"}

        if self.cluster_ca:
            import tempfile
            ca_file = tempfile.NamedTemporaryFile(delete=False, suffix=".crt")
            ca_file.write(base64.b64decode(self.cluster_ca))
            ca_file.close()
            configuration.ssl_ca_cert = ca_file.name
            configuration.verify_ssl = True
        else:
            configuration.verify_ssl = False

        client.Configuration.set_default(configuration)
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
        logger.info(f"Connected to EKS cluster: {self.cluster_name}")

    def _discover_cluster(self):
        eks = boto3.client("eks", region_name=self.region)
        cluster = eks.describe_cluster(name=self.cluster_name)["cluster"]
        return cluster["endpoint"], cluster["certificateAuthority"]["data"]

    def _get_eks_token(self) -> str:
        session = boto3.Session()
        sts_client = session.client("sts", region_name=self.region)
        service_id = sts_client.meta.service_model.service_id

        signer = RequestSigner(service_id, self.region, "sts", "v4", session.get_credentials(), session.events)

        params = {
            "method": "GET",
            "url": f"https://sts.{self.region}.amazonaws.com/?Action=GetCallerIdentity&Version=2011-06-15",
            "body": {},
            "headers": {"x-k8s-aws-id": self.cluster_name},
            "context": {},
        }

        signed_url = signer.generate_presigned_url(
            params, region_name=self.region, expires_in=STS_TOKEN_EXPIRES_IN, operation_name=""
        )

        token = "k8s-aws-v1." + base64.urlsafe_b64encode(signed_url.encode("utf-8")).rstrip(b"=").decode("utf-8")
        return token

    def get_pod_context(self, namespace: str, pod_name: str) -> dict:
        context = {}
        try:
            pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            context["status"] = pod.status.phase
            context["restart_count"] = sum(
                c.restart_count for c in (pod.status.container_statuses or [])
            )

            try:
                logs = self.core_v1.read_namespaced_pod_log(
                    name=pod_name, namespace=namespace, tail_lines=100
                )
                context["logs"] = logs
            except Exception:
                context["logs"] = "Unable to fetch logs"

            events = self.core_v1.list_namespaced_event(namespace=namespace)
            relevant_events = [
                e.message for e in events.items
                if e.involved_object.name and pod_name in e.involved_object.name
            ]
            context["events"] = relevant_events[-10:]

        except Exception as e:
            context["error"] = str(e)

        return context

    def get_deployment_context(self, namespace: str, deployment_name: str) -> dict:
        try:
            deploy = self.apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
            return {
                "replicas": deploy.spec.replicas,
                "ready_replicas": deploy.status.ready_replicas,
                "updated_replicas": deploy.status.updated_replicas,
            }
        except Exception as e:
            return {"error": str(e)}
