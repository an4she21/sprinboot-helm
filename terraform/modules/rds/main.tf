variable "db_name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnets" {
  type = list(string)
}

resource "aws_security_group" "rds_sg" {
  name        = "ai-selfhealing-rds-sg"
  description = "Allow MySQL traffic from VPC"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 3306
    to_port     = 3306
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"] # Allow VPC traffic
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

resource "aws_db_subnet_group" "main" {
  name       = "ai-selfhealing-db-subnet-group"
  subnet_ids = var.private_subnets

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

resource "aws_db_instance" "this" {
  identifier           = "ai-selfhealing-db"
  engine               = "mariadb"
  engine_version       = "10.6"
  instance_class       = "db.t3.micro"
  allocated_storage    = 20
  max_allocated_storage = 100
  db_name              = var.db_name
  username             = "admin"
  password             = aws_secretsmanager_secret_version.rds_password_val.secret_string

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds_sg.id]

  skip_final_snapshot    = true
  storage_encrypted      = true

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

resource "aws_secretsmanager_secret" "rds_password" {
  name        = "ai-selfhealing-rds-password"
  description = "RDS root password for ai-selfhealing"

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

resource "aws_secretsmanager_secret_version" "rds_password_val" {
  secret_id     = aws_secretsmanager_secret.rds_password.id
  secret_string = "StrongPassword123!"
}

resource "aws_ssm_parameter" "rds_endpoint" {
  name  = "/ai-selfhealing/dev/rds_endpoint"
  type  = "String"
  value = aws_db_instance.this.endpoint

  tags = {
    Environment = "dev"
    Project       = "ai-selfhealing"
  }
}

resource "aws_ssm_parameter" "rds_db_name" {
  name  = "/ai-selfhealing/dev/db_name"
  type  = "String"
  value = var.db_name

  tags = {
    Environment = "dev"
    Project       = "ai-selfhealing"
  }
}

output "db_endpoint" {
  value = aws_db_instance.this.endpoint
}
