import os
from kubernetes import client, config

class K8sObserver:
    def __init__(self):
        # In Lambda, we use a token or the IAM role provided by IRSA
        # For local testing, this would use load_kube_config()
        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()

        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()

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
            relevant_events = [e.message for e in events.items if pod_name in e.involved_object.name]
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
