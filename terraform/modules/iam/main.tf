variable "cluster_name" { type = string }
variable "region" { type = string }

resource "aws_iam_role" "eso_role" {
  name = "external-secrets-operator-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRoleWithWebIdentity"
        Effect = "Allow"
        Principal = {
          Federated = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${data.aws_eks_cluster.cluster.cluster_name}.eks.${var.region}.amazonaws.com/ex" # Simplified
        }
      }
    ]
  })
}
