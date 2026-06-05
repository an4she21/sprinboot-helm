variable "db_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnets" {
  type = list(string)
}

module "db_subnet" {
  source  = "terraform-aws-modules/subnet/aws"
  version = "~> 5.0"

  name = "db-subnet"
  vpc_id = var.vpc_id
  cidr = "10.0.20.0/24" # Note: In a real scenario, a DB subnet group needs multiple subnets in different AZs
}

module "rds" {
  source  = "terraform-aws-modules/rds/aws"
  version = "~> 6.0"

  identifier = "ai-selfhealing-db"

  engine               = "mariadb"
  engine_version       = "10.6"
  instance_class       = "db.t3.micro"
  allocated_storage    = 20
  max_allocated_storage = 100

  db_name  = var.db_name
  username = "admin"
  password = "StrongPassword123!" # Use a secret manager in production

  subnet_ids = [module.db_subnet.id] # Simplified for demo, normally a subnet group

  vpc_security_group_rules = {
    ingress_mysql = {
      type                     = "ingress"
      from_port                = 3306
      to_port                  = 3306
      protocol                 = "tcp"
      cidr_blocks              = ["10.0.0.0/16"] # Allow VPC traffic
      description              = "Allow MySQL from VPC"
    }
  }

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

output "db_endpoint" {
  value = module.rds.db_cluster_endpoint # or db_instance_endpoint depending on module version
}
