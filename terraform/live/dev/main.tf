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

output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "rds_endpoint" {
  value = module.rds.db_endpoint
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
