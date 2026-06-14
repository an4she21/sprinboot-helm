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

# VPC Endpoint for EKS API (PrivateLink)
# Allows ECS tasks in private subnets to reach EKS without NAT
resource "aws_vpc_endpoint" "eks" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.eu-north-1.eks"
  vpc_endpoint_type = "Interface"

  subnet_ids          = module.vpc.private_subnets
  private_dns_enabled = true

  security_group_ids = [aws_security_group.eks_vpc_endpoint.id]

  tags = {
    Name        = "eks-vpc-endpoint"
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

resource "aws_security_group" "eks_vpc_endpoint" {
  name        = "eks-vpc-endpoint-sg"
  description = "Allow HTTPS from VPC to EKS VPC endpoint"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description = "HTTPS from VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "eks-vpc-endpoint-sg"
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

# VPC Endpoint for STS (needed by ECS tasks to get EKS auth tokens)
resource "aws_vpc_endpoint" "sts" {
  vpc_id            = module.vpc.vpc_id
  service_name      = "com.amazonaws.eu-north-1.sts"
  vpc_endpoint_type = "Interface"

  subnet_ids          = module.vpc.private_subnets
  private_dns_enabled = true

  security_group_ids = [aws_security_group.eks_vpc_endpoint.id]

  tags = {
    Name        = "sts-vpc-endpoint"
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
