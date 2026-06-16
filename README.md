<p align="center">
  <img src="https://img.shields.io/badge/AWS-EKS-orange?logo=amazon-aws&logoColor=white" />
  <img src="https://img.shields.io/badge/AWS-ECS_Fargate-blue?logo=amazon-aws&logoColor=white" />
  <img src="https://img.shields.io/badge/AI-NVIDIA_NIM-76B900?logo=nvidia&logoColor=white" />
  <img src="https://img.shields.io/badge/IaC-Terraform-7B42BC?logo=terraform&logoColor=white" />
  <img src="https://img.shields.io/badge/GitOps-ArgoCD-FE5960?logo=argo&logoColor=white" />
  <img src="https://img.shields.io/badge/Monitoring-Prometheus%20%2B%20Grafana-E6522C?logo=prometheus&logoColor=white" />
  <img src="https://img.shields.io/badge/Container-Docker-2496ED?logo=docker&logoColor=white" />
</p>

<h1 align="center">AI Self-Healing Kubernetes Platform</h1>

<p align="center">
  <strong>Fully automated incident detection, AI-powered analysis, and remediation on AWS EKS</strong><br>
  Zero human intervention — Prometheus alerts trigger NVIDIA NIM GLM 5.1 to diagnose and auto-fix production issues.
</p>

---

## Architecture

```
                         ┌─────────────────────────────────────────────────┐
                         │              AWS Account (eu-north-1)           │
                         │                                                 │
  ┌──────────────┐       │  ┌──────────────────────────────────────────┐   │
  │   GitHub     │──────┼──│  ArgoCD (GitOps)                         │   │
  │   Repo       │ push │  │  Auto-syncs Helm charts to EKS cluster   │   │
  └──────────────┘       │  └──────────────────────────────────────────┘   │
                         │                                                 │
  ┌──────────────┐       │  ┌──────────────────────────────────────────┐   │
  │   Terraform  │──────┼──│  EKS Cluster (v1.30)                     │   │
  │   IaC        │ apply│  │  ┌─────────┐ ┌──────────┐ ┌───────────┐  │   │
  └──────────────┘       │  │  │Backend  │ │Frontend  │ │Monitoring │  │   │
                         │  │  │(Spring) │ │(React)  │ │(Prom+Graf)│  │   │
                         │  │  └─────────┘ └──────────┘ └───────────┘  │   │
                         │  └──────────────────┬───────────────────────┘   │
                         │                     │ metrics                     │
                         │                     ▼                            │
                         │  ┌──────────────────────────────────────────┐   │
                         │  │  Prometheus + Alertmanager               │   │
                         │  │  Scrapes kube-state-metrics + AI Agent  │   │
                         │  │  Fires alerts: CrashLoop, OOMKilled...  │   │
                         │  └──────────────────┬───────────────────────┘   │
                         │                     │ webhook                     │
                         │                     ▼                            │
                         │  ┌──────────────────────────────────────────┐   │
                         │  │  ECS Fargate — AI Self-Healing Agent    │   │
                         │  │  ┌────────────┐ ┌─────────────────────┐  │   │
                         │  │  │ FastAPI    │ │ NVIDIA NIM          │  │   │
                         │  │  │ /webhook   │→│ GLM 5.1 (LLM)     │  │   │
                         │  │  │ /metrics   │ │ AI Decision Engine  │  │   │
                         │  │  │ /dashboard │←│ RESTART/SCALE/INV  │  │   │
                         │  │  └────────────┘ └─────────────────────┘  │   │
                         │  │         │                                │   │
                         │  │    ┌────┴────┐                           │   │
                         │  │    ▼         ▼                           │   │
                         │  │  EKS API   AWS SNS                       │   │
                         │  │  Remediate  Email Reports               │   │
                         │  └──────────────────────────────────────────┘   │
                         │                                                 │
                         │  ┌──────────────────────────────────────────┐   │
                         │  │  Route53 Private Zone                    │   │
                         │  │  ai-selfhealing.internal                  │   │
                         │  │  ai-agent.ai-selfhealing.internal → ALB  │   │
                         │  └──────────────────────────────────────────┘   │
                         └─────────────────────────────────────────────────┘
```

## The Self-Healing Loop

This is the core value of the project — **zero-touch incident remediation**:

```
  Pod Crashes          Prometheus         Alertmanager         AI Agent            NIM GLM 5.1         Auto-Fix
  ───────────▶ Detect ──────────▶ Alert ──────────▶ Analyze ──────────▶ Decide ──────────▶ Execute
  (CrashLoop,   (kube-state-    (routes by       (enriches with     (LLM reasoning     (kubectl rollout
   OOM, etc.)    metrics +        severity)        EKS snapshot)      + confidence        restart / scale)
                 alert rules)                                                          score)
                                                                              │
                                                                              ▼
                                                                        SNS Email Report
                                                                        (detailed remediation
                                                                         summary to inbox)
```

1. **Detect** — Prometheus scrapes `kube-state-metrics` every 30s and fires alerts (PodCrashLooping, PodOOMKilled, PodNotReady, DeploymentReplicasMismatch)
2. **Route** — Alertmanager groups alerts by severity and sends to the AI Agent webhook
3. **Analyze** — AI Agent gathers a full cluster snapshot (pod status, events, deployment context) and sends to NVIDIA NIM GLM 5.1
4. **Decide** — The LLM returns a structured JSON: `{action_id: RESTART_POD|SCALE_UP|INVESTIGATE|MANUAL, confidence: 0.0-1.0, analysis: "..."}`
5. **Execute** — If confidence >= 0.8 and action != MANUAL, the agent executes remediation via the EKS Kubernetes API
6. **Report** — A detailed email is sent via AWS SNS with the full diagnosis, AI reasoning, and action taken

### Safety Mechanisms

| Mechanism | Purpose |
|---|---|
| Confidence threshold (0.8) | AI won't act unless it's 80%+ sure the action is correct |
| Cooldown cache (300s TTL) | Prevents flip-flop remediation loops on the same alert |
| MANUAL fallback | Low-confidence or ambiguous cases are escalated to humans |
| INVESTIGATE mode | AI logs pod events without taking action when unsure |

---

## Tech Stack

| Category | Technology | Purpose |
|---|---|---|
| **Kubernetes** | AWS EKS v1.30 | Container orchestration |
| **AI/ML** | NVIDIA NIM API — GLM 5.1 | LLM-powered decision engine |
| **Serverless Compute** | AWS ECS Fargate | AI Agent hosting (no node management) |
| **Infrastructure** | Terraform | Full IaC — VPC, EKS, ECS, IAM, Route53, SNS |
| **GitOps** | ArgoCD | Automated Helm chart sync from GitHub to EKS |
| **Monitoring** | Prometheus + Grafana + Alertmanager | Metrics, dashboards, alert routing |
| **Networking** | AWS ALB + Route53 Private Zone | Internal DNS + external dashboard access |
| **Notifications** | AWS SNS | Email reports after every remediation |
| **Security** | EKS Access Entries + IAM Roles | Fine-grained ECS→EKS API access |
| **Secrets** | AWS SSM Parameter Store + External Secrets | API keys and credentials management |
| **CI/CD** | GitHub Actions | Docker build → ECR push on every commit |
| **Language** | Python (FastAPI) | AI Agent REST API |
| **Backend** | Java Spring Boot | Sample microservice for demo |

---

## Project Structure

```
.
├── ai-agent/                          # AI Self-Healing Agent (FastAPI)
│   ├── main.py                        # Core logic: webhook, NIM API, remediation, metrics, SNS
│   ├── models.py                      # Pydantic models (AlertDetail, AIDecision, etc.)
│   ├── k8s_client.py                  # EKS Kubernetes API client with STS token refresh
│   ├── Dockerfile                     # Multi-stage Docker build
│   └── requirements.txt               # Python dependencies
│
├── helm/                              # Helm charts (managed by ArgoCD)
│   ├── ai-selfhealing-app/            # Spring Boot + React deployment
│   └── monitoring/
│       ├── prometheus/                # Prometheus + Alertmanager + kube-state-metrics
│       │   ├── Chart.yaml
│       │   └── values.yaml            # Scrape configs, alert rules, webhook config
│       └── grafana/                    # Grafana with pre-provisioned AI Agent dashboard
│           ├── Chart.yaml
│           └── values.yaml            # Datasource, dashboard JSON (9 panels)
│
├── terraform/                         # Full infrastructure as code
│   └── modules/
│       ├── vpc/                       # VPC, subnets, NAT gateway, IGW
│       ├── eks/                       # EKS cluster, node groups, EBS CSI, access entries
│       ├── ecs/                       # ECS Fargate, ALB, Route53, SNS, ECR
│       └── iam/                       # IAM roles + policies for AI agent
│
├── .github/
│   └── workflows/
│       └── ci.yml                     # CI: Docker build → Trivy scan → ECR push
│
└── argocd/                            # ArgoCD Application manifests
```

---

## AI Agent Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/webhook` | POST | Receives Alertmanager payloads |
| `/health` | GET | Liveness probe (ALB health check) |
| `/ready` | GET | Readiness probe (checks EKS connection) |
| `/metrics` | GET | Prometheus-compatible metrics (15+ gauges/counters) |
| `/dashboard` | GET | Real-time web dashboard (auto-refresh) |
| `/history` | GET | Last 100 remediation actions (JSON) |
| `/stats` | GET | Alert processing counters |

### Prometheus Metrics

```
ai_agent_alerts_processed_total        # Total alerts from Alertmanager
ai_agent_actions_taken_total           # Remediation actions executed
ai_agent_actions_skipped_total          # Actions skipped (cooldown/low confidence)
ai_agent_eks_connected                  # EKS connection status (1=connected)
ai_agent_uptime_seconds                # Agent uptime
ai_agent_nim_api_calls_total           # NVIDIA NIM API calls
ai_agent_nim_api_failures_total        # NIM API failures
ai_agent_nim_api_latency_avg_seconds   # Average NIM response latency
ai_agent_eks_restarts_total            # RESTART_POD actions
ai_agent_eks_scale_ups_total           # SCALE_UP actions
ai_agent_eks_investigates_total        # INVESTIGATE actions
ai_agent_manual_escalations_total      # MANUAL escalations
ai_agent_cooldown_skips_total          # Cooldown prevention skips
ai_agent_cooldown_cache_size           # Active cooldown entries
ai_agent_last_confidence_score         # Last LLM confidence (0-1)
```

---

## Grafana Dashboard

Pre-provisioned via Helm values — 9 panels auto-loaded on first deploy:

| Panel | Type | Metric |
|---|---|---|
| EKS Connection | Stat (green/red) | `ai_agent_eks_connected` |
| Uptime | Stat | `ai_agent_uptime_seconds` |
| NIM API Latency | Gauge (0-10s) | `ai_agent_nim_api_latency_avg_seconds` |
| Confidence Score | Gauge (0-100%) | `ai_agent_last_confidence_score` |
| Alerts Over Time | Time series | Processed / Taken / Skipped |
| Action Breakdown | Pie chart | RESTART / SCALE / INVESTIGATE / MANUAL |
| NIM API Calls vs Failures | Time series | Calls / Failures |
| Cooldown Cache | Time series | Active cooldowns |
| Remediation by Type | Bar chart | All action types |

---

## Infrastructure

All infrastructure is defined in Terraform and managed as code:

| Resource | Module | Details |
|---|---|---|
| VPC | `vpc/` | 2 AZs, public + private subnets, NAT gateway |
| EKS Cluster | `eks/` | v1.30, t3.small managed node group (1-5 auto-scaling) |
| EBS CSI Driver | `eks/` | GP3 volumes via IAM role + OIDC trust |
| ECS Fargate | `ecs/` | AI Agent service (0.5 vCPU, 1GB RAM) |
| Application LB | `ecs/` | Internet-facing, health check on /health |
| Route53 | `ecs/` | Private zone `ai-selfhealing.internal` |
| SNS Topic | `ecs/` | `ai-selfhealing-reports` for email notifications |
| ECR | `ecs/` | `ai-selfhealing-agent` repository |
| IAM Roles | `iam/` | Task role (EKS + SSM + SNS), Execution role (ECR + SSM) |
| EKS Access Entry | `eks/` | ECS task role → EKS cluster admin |

---

## Quick Start

### Prerequisites

- AWS CLI configured with appropriate credentials
- Terraform >= 1.5
- kubectl + helm
- Docker
- GitHub account (for ArgoCD GitOps)

### Deploy Infrastructure

```bash
# 1. Deploy VPC + EKS + ECS + IAM
cd terraform/live/dev
terraform init
terraform apply -auto-approve

# 2. Update kubeconfig
aws eks update-kubeconfig --name ai-selfhealing-cluster-dev --region eu-north-1

# 3. Install ArgoCD
kubectl apply -k argocd/

# 4. SNS email subscription
aws sns subscribe \
  --topic-arn arn:aws:sns:eu-north-1:<ACCOUNT_ID>:ai-selfhealing-reports \
  --protocol email \
  --notification-endpoint your-email@example.com \
  --region eu-north-1

# 5. Store NIM API key in SSM
aws ssm put-parameter \
  --name /ai-selfhealing/dev/nim-api-key \
  --value "nvapi-xxxx" \
  --type SecureString \
  --region eu-north-1
```

### Verify

```bash
# Check AI Agent health
curl http://<ALB-DNS>/health

# Test self-healing loop
curl -X POST http://<ALB-DNS>/webhook \
  -H "Content-Type: application/json" \
  -d '{"alerts":[{"status":"firing","labels":{"alertname":"PodCrashLooping","severity":"critical","namespace":"default","pod":"test-pod"},"annotations":{"summary":"Pod test-pod is crash looping"}}]}'
```

---

## Key Design Decisions

| Decision | Why |
|---|---|
| ECS Fargate for AI Agent (not EKS pod) | Isolates AI agent from cluster failures — if EKS goes down, agent can still remediate |
| NVIDIA NIM API (not self-hosted LLM) | Zero GPU cost, instant availability, no model deployment complexity |
| Confidence threshold (0.8) | Prevents AI from taking risky actions on ambiguous situations |
| Cooldown cache (300s) | Prevents remediation loops — same alert won't trigger repeated restarts |
| Route53 Private Zone | Stable internal DNS — pods can always reach the AI agent, even if ALB IP changes |
| Terraform + ArgoCD split | Infrastructure (VPC/EKS/ECS) in Terraform, app deployments in ArgoCD — clean separation |

---

## Skills Demonstrated

> Relevant for DevOps / Cloud / Platform / SRE roles

- **AWS**: EKS, ECS Fargate, VPC, IAM, ALB, Route53, SNS, ECR, SSM, CloudWatch, STS, OIDC
- **Kubernetes**: Cluster management, RBAC via access entries, Helm charts, deployments, HPA
- **Terraform**: Modular IaC, remote state, data sources, OIDC IAM trust
- **GitOps**: ArgoCD automated sync, self-healing drift correction
- **Monitoring**: Prometheus, Alertmanager, Grafana, kube-state-metrics, alert routing
- **AI/ML Integration**: LLM API (NVIDIA NIM), structured output, prompt engineering
- **Python**: FastAPI, Pydantic, httpx, boto3, Kubernetes client, tenacity retry
- **CI/CD**: GitHub Actions, Docker multi-stage builds, Trivy security scanning, ECR
- **Security**: IAM least privilege, OIDC federation, SSM SecureString, EKS access entries
- **SRE Practices**: Alert-driven remediation, confidence scoring, cooldown/dedup, email reporting

---

## License

MIT
