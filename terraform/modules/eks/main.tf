variable "cluster_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnets" {
  type = list(string)
}

data "aws_caller_identity" "current" {}

module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.30"

  vpc_id     = var.vpc_id
  subnet_ids = var.private_subnets

  # Managed Node Groups
  eks_managed_node_groups = {
    general = {
      instance_types   = ["t3.small"]
      min_size         = 1
      max_size         = 5
      desired_capacity = 1
      create_iam_role  = false
      iam_role_arn     = "arn:aws:iam::181728646118:role/general-eks-node-group-20260607221902321300000002"
    }
  }

  cluster_addons = {
    aws-ebs-csi-driver = {
      most_recent_compatible_version = true
      service_account_role_arn     = aws_iam_role.ebs_csi_driver.arn
    }
  }

  # Enable cluster endpoint access
  cluster_endpoint_public_access = true

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

# AI Agent Access Entry (ECS Fargate Task Role)
resource "aws_eks_access_entry" "ai_agent" {
  cluster_name  = module.eks.cluster_name
  principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/ai-self-healing-agent-role"
  type          = "STANDARD"
}

resource "aws_eks_access_policy_association" "ai_agent_admin" {
  cluster_name  = module.eks.cluster_name
  principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/ai-self-healing-agent-role"
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }
}

# EBS CSI Driver IAM Role
resource "aws_iam_role" "ebs_csi_driver" {
  name = "${var.cluster_name}-ebs-csi-driver"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/${replace(module.eks.cluster_oidc_issuer_url, "https://", "")}"
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "${replace(module.eks.cluster_oidc_issuer_url, "https://", "")}:sub" = "system:serviceaccount:kube-system:ebs-csi-controller-sa"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ebs_csi_driver_policy" {
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"
  role       = aws_iam_role.ebs_csi_driver.name
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "cluster_certificate_authority_data" {
  value = module.eks.cluster_certificate_authority_data
}
