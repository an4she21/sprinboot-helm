variable "cluster_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnets" {
  type = list(string)
}

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
      instance_types = ["t3.medium"]
      min_size     = 1
      max_size     = 3
      desired_capacity = 2
    }
  }

  # Enable cluster endpoint access
  cluster_endpoint_public_access = true

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

output "cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "cluster_name" {
  value = module.eks.cluster_name
}
