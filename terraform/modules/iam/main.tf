# IAM Module — AI Agent & ECS Roles
#
# NOTE: We no longer use data.aws_eks_cluster here.
# The OIDC provider URL is passed as a variable from the EKS module output
# to avoid a circular dependency (IAM needs cluster info, cluster needs IAM).

variable "cluster_name" { type = string }
variable "region" { type = string }

# --- NEW: OIDC info passed from EKS module instead of data source ---
variable "oidc_provider_arn" {
  description = "ARN of the EKS OIDC provider (from module.eks.oidc_provider_arn)"
  type        = string
  default     = ""
}

variable "oidc_provider_url" {
  description = "URL of the EKS OIDC issuer (from module.eks.cluster_oidc_issuer_url)"
  type        = string
  default     = ""
}

data "aws_caller_identity" "current" {}

###############################################################################
# External Secrets Operator Role
###############################################################################
resource "aws_iam_role" "eso_role" {
  name = "external-secrets-operator-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRoleWithWebIdentity"
        Effect = "Allow"
        Principal = {
          Federated = var.oidc_provider_arn
        }
        Condition = {
          StringEquals = {
            "${replace(var.oidc_provider_url, "https://", "")}:sub" = "system:serviceaccount:external-secrets:external-secrets"
          }
        }
      }
    ]
  })
}

###############################################################################
# ECS Task Execution Role (pulls images, writes logs)
###############################################################################
resource "aws_iam_role" "ecs_task_execution_role" {
  name = "ai-agent-ecs-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_policy" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
  role       = aws_iam_role.ecs_task_execution_role.name
}

###############################################################################
# ECS Task Role (what the container can do at runtime)
###############################################################################
resource "aws_iam_role" "ai_agent_role" {
  name = "ai-self-healing-agent-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "ai_agent_policy" {
  name = "ai-agent-policy"
  role = aws_iam_role.ai_agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockInvoke"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:Converse"
        ]
        Effect   = "Allow"
        Resource = "arn:aws:bedrock:${var.region}::foundation-model/*"
      },
      {
        Sid    = "EKSAccess"
        Action = [
          "eks:DescribeCluster",
          "eks:ListClusters"
        ]
        Effect   = "Allow"
        Resource = "arn:aws:eks:${var.region}:${data.aws_caller_identity.current.account_id}:cluster/${var.cluster_name}"
      },
      {
        Sid    = "STSGetToken"
        Action = [
          "sts:GetCallerIdentity"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
      {
        Sid    = "CloudWatchLogs"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Effect   = "Allow"
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

###############################################################################
# Outputs
###############################################################################
output "ai_agent_role_arn" {
  value = aws_iam_role.ai_agent_role.arn
}

output "ecs_task_execution_role_arn" {
  value = aws_iam_role.ecs_task_execution_role.arn
}
