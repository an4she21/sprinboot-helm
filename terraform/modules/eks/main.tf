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
      instance_types = ["t3.small"]
      min_size     = 1
      max_size     = 5
      desired_capacity = 1
    }
  }

  # Enable cluster endpoint access
  cluster_endpoint_public_access = true

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

# AI Agent Access Entry
resource "aws_eks_access_entry" "ai_agent" {
  cluster_name      = module.eks.cluster_name
  principal_arn     = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/ai-self-healing-agent-role"
  type              = "STANDARD"
}

resource "aws_eks_access_policy_association" "ai_agent_admin" {
  cluster_name  = module.eks.cluster_name
  principal_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/ai-self-healing-agent-role"
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "cluster_name" {
  value = module.eks.cluster_name
}
