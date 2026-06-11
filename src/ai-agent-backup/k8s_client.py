import os
import boto3
import base64
from kubernetes import client, config

class K8sObserver:
    def __init__(self):
        self.cluster_endpoint = os.environ.get("EKS_CLUSTER_ENDPOINT")
        if not self.cluster_endpoint:
            raise Exception("EKS_CLUSTER_ENDPOINT environment variable is not set")

        # Generate EKS token using boto3
        token = self._get_eks_token()

        configuration = client.Configuration()
        configuration.host = self.cluster_endpoint
        configuration.verify_ssl = True
        configuration.api_key = {"authorization": f"Bearer {token}"}

        client.Configuration.set_default(configuration)

        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

    def _get_eks_token(self):
        """Generates an EKS authentication token."""
        # This is a simplified version of the 'aws eks get-token' logic
        # In a real production environment, you'd use a more robust implementation
        # or a library like 'eks-token'. For this agent, we use the identity of the Lambda.
        import subprocess
        try:
            # Use the aws cli if available in the Lambda layer, otherwise we'd need
            # to implement the signed request manually.
            # Since we are deploying a custom zip, we can include the aws-cli or
            # better, use the boto3 generated token.

            # For the sake of this implementation, we use a shell call to 'aws eks get-token'
            # as it is the most reliable way to get the token.
            # NOTE: This requires the 'aws' cli to be present in the Lambda environment
            # (which is true for AWS provided runtimes).
            cmd = f"aws eks get-token --cluster-name {os.environ.get('CLUSTER_NAME', 'ai-selfhealing-cluster-dev')} --output text"
            token = subprocess.check_output(cmd, shell=True).decode('utf-8').strip()
            return token
        except Exception as e:
            print(f"Error getting EKS token: {str(e)}")
            # Fallback: try to use a dummy token or raise exception
            raise Exception(f"Could not generate EKS token: {str(e)}")

    def get_pod_context(self, namespace, pod_name):
        """Collects logs, events and status for a specific pod."""
        context = {}
        try:
            # 1. Pod Status
            pod = self.core_v1.read_namespaced_pod(name=pod_name, namespace=namespace)
            context['status'] = pod.status.phase
            context['restart_count'] = sum([c.restart_count for c in pod.status.container_statuses] if pod.status.container_statuses else 0)

            # 2. Pod Logs (last 100 lines)
            logs = self.core_v1.read_namespaced_pod_log(name=pod_name, namespace=namespace, tail=100)
            context['logs'] = logs

            # 3. Relevant Events
            events = self.core_v1.list_namespaced_event(namespace=namespace)
            relevant_events = [e.message for e in events.items if pod_name in (e.involved_object.name or "")]
            context['events'] = relevant_events[-10:] # Last 10 events

        except Exception as e:
            context['error'] = str(e)

        return context

    def get_deployment_context(self, namespace, deployment_name):
        """Collects deployment details."""
        try:
            deploy = self.apps_v1.read_namespaced_deployment(name=deployment_name, namespace=namespace)
            return {
                'replicas': deploy.spec.replicas,
                'ready_replicas': deploy.status.ready_replicas,
                'updated_replicas': deploy.status.updated_replicas
            }
        except Exception as e:
            return {'error': str(e)}
