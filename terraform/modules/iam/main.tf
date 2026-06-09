variable "cluster_name" { type = string }
variable "region" { type = string }

data "aws_caller_identity" "current" {}
data "aws_eks_cluster" "cluster" {
  name = var.cluster_name
}

resource "aws_iam_role" "eso_role" {
  name = "external-secrets-operator-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRoleWithWebIdentity"
        Effect = "Allow"
        Principal = {
          Federated = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${data.aws_eks_cluster.cluster.name}.eks.${var.region}.amazonaws.com/ex" # Simplified
        }
      }
    ]
  })
}

resource "aws_iam_role" "ai_agent_role" {
  name = "ai-self-healing-agent-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

# ... (previous content)
resource "aws_iam_role_policy" "ai_agent_policy" {
  name = "ai-agent-policy"
  role = aws_iam_role.ai_agent_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "bedrock:InvokeModel",
          "eks:DescribeCluster"
        ]
        Effect   = "Allow"
        Resource = "*"
      },
      {
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

output "ai_agent_role_arn" {
  value = aws_iam_role.ai_agent_role.arn
}
