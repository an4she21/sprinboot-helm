variable "vpc_name" {
  description = "Name of the VPC"
  type        = string
}

variable "cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = var.vpc_name
  cidr = var.cidr

  # Public subnets for Load Balancers and Jump hosts
  public_subnets  = ["10.0.1.0/24", "10.0.2.0/24", "10.0.3.0/24"]
  # Private subnets for Worker Nodes and DB
  private_subnets = ["10.0.11.0/24", "10.0.12.0/24", "10.0.13.0/24"]
  azs             = ["eu-north-1a", "eu-north-1b", "eu-north-1c"]

  enable_nat_gateway = true

  single_nat_gateway = true # For cost saving in dev

  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

output "vpc_id" {
  value = module.vpc.vpc_id
}

output "private_subnets" {
  value = module.vpc.private_subnets
}

output "public_subnets" {
  value = module.vpc.public_subnets
}
