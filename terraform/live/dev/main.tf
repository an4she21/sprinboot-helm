terraform {
  backend "s3" {
    bucket         = "ai-selfhealing-terraform-state-unique-id" # Use the name from global/main.tf
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "terraform-state-locks"
    encrypt        = true
  }
}

provider "aws" {
  region = "eu-north-1"
}

# NOTE: kubernetes provider removed from Terraform.
# K8s resources (StorageClass, etc.) are managed by ArgoCD instead.
# This avoids auth issues during terraform apply.

# ── Module 1: VPC ──────────────────────────────────────────────────────────
module "vpc" {
  source   = "../../modules/vpc"
  vpc_name = "ai-selfhealing-vpc-dev"
}

# ── Module 2: EKS cluster ─────────────────────────────────────────────────
module "eks" {
  source          = "../../modules/eks"
  cluster_name    = "ai-selfhealing-cluster-dev"
  vpc_id          = module.vpc.vpc_id
  private_subnets = module.vpc.private_subnets
}

# ── Module 3: RDS (MariaDB) ───────────────────────────────────────────────
module "rds" {
  source          = "../../modules/rds"
  db_name         = "voiture_db"
  vpc_id          = module.vpc.vpc_id
  private_subnets = module.vpc.private_subnets
}

# ── Module 4: IAM roles (ECS agent, ESO) ─────────────────────────────────
# NOTE: OIDC info is now passed from EKS module outputs instead of using
# data.aws_eks_cluster (which caused circular dependency errors).
module "iam" {
  source             = "../../modules/iam"
  cluster_name       = module.eks.cluster_name
  region             = "eu-north-1"
  oidc_provider_arn  = module.eks.oidc_provider_arn
  oidc_provider_url  = module.eks.cluster_oidc_issuer_url
}

# ── Module 5: ECS Fargate AI Agent ────────────────────────────────────────
module "ecs_ai_agent" {
  source                       = "../../modules/ecs"
  cluster_name                 = module.eks.cluster_name
  vpc_id                       = module.vpc.vpc_id
  private_subnets              = module.vpc.private_subnets
  public_subnets               = module.vpc.public_subnets
  eks_cluster_endpoint         = module.eks.cluster_endpoint
  eks_cluster_ca               = module.eks.cluster_certificate_authority_data
  task_execution_role_arn      = module.iam.ecs_task_execution_role_arn
  task_role_arn                = module.iam.ai_agent_role_arn
  eks_cluster_security_group_id = module.eks.cluster_security_group_id
}

# ── ECR Repositories (with force_delete for clean terraform destroy) ──────
resource "aws_ecr_repository" "backend" {
  name                 = "ai-selfhealing-backend"
  image_tag_mutability = "MUTABLE"
  force_delete         = true  # Allows terraform destroy even with images

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "ai-selfhealing-frontend"
  image_tag_mutability = "MUTABLE"
  force_delete         = true  # Allows terraform destroy even with images

  image_scanning_configuration {
    scan_on_push = true
  }
}

# ── SSM read policy for EKS nodes ─────────────────────────────────────────
resource "aws_iam_policy" "ssm_read_policy" {
  name        = "ai-selfhealing-ssm-read-policy"
  description = "Allow EKS nodes to read specific SSM parameters"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Effect   = "Allow"
        Resource = "arn:aws:ssm:eu-north-1:181728646118:parameter/ai-selfhealing/*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "node_ssm_attach" {
  role       = "general-eks-node-group-20260607221902321300000002"
  policy_arn = aws_iam_policy.ssm_read_policy.arn
}

# ── GP3 Storage Class — managed via ArgoCD (kubernetes/argocd/storage-gp3.yaml) ─
# Removed from Terraform to avoid kubernetes provider auth issues during cluster creation.
# ArgoCD will apply this manifest once the cluster is ready.

# ── Outputs ────────────────────────────────────────────────────────────────
output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "rds_endpoint" {
  value = module.rds.db_endpoint
}

output "ai_agent_webhook_url" {
  value = module.ecs_ai_agent.webhook_url
}

output "ai_agent_ecr_url" {
  value = module.ecs_ai_agent.ecr_repository_url
}
