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

module "vpc" {
  source  = "../../modules/vpc"
  vpc_name = "ai-selfhealing-vpc-dev"
}

module "eks" {
  source       = "../../modules/eks"
  cluster_name = "ai-selfhealing-cluster-dev"
  vpc_id       = module.vpc.vpc_id
  private_subnets = module.vpc.private_subnets
}

module "rds" {
  source         = "../../modules/rds"
  db_name        = "voiture_db"
  vpc_id         = module.vpc.vpc_id
  private_subnets = module.vpc.private_subnets
}

module "iam" {
  source       = "../../modules/iam"
  cluster_name = module.eks.cluster_name
  region       = "eu-north-1"
}

module "lambda_ai" {
  source          = "../../modules/lambda"
  lambda_role_arn = module.iam.ai_agent_role_arn
}

output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "rds_endpoint" {
  value = module.rds.db_endpoint
}

output "lambda_ai_url" {
  value = module.lambda_ai.function_url
}

resource "aws_ecr_repository" "backend" {
  name                 = "ai-selfhealing-backend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "ai-selfhealing-frontend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

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
  role       = "general-eks-node-group-20260607221902321300000002" # Using the role from the logs
  policy_arn = aws_iam_policy.ssm_read_policy.arn
}
