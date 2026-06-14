variable "cluster_name" {
  description = "EKS cluster name for the AI agent to connect to"
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnets" {
  type = list(string)
}

variable "public_subnets" {
  type = list(string)
}

variable "eks_cluster_endpoint" {
  type = string
}

variable "eks_cluster_ca" {
  type    = string
  default = ""
}

variable "bedrock_model_id" {
  type    = string
  default = "zai.glm-5"
}

variable "agent_region" {
  type    = string
  default = "eu-north-1"
}

variable "task_execution_role_arn" {
  type = string
}

variable "task_role_arn" {
  type = string
}

variable "eks_cluster_security_group_id" {
  description = "EKS cluster security group ID — needed to allow ECS tasks to reach the K8s API"
  type        = string
  default     = ""
}

###############################################################################
# ECR Repository
###############################################################################
resource "aws_ecr_repository" "ai_agent" {
  name                 = "ai-selfhealing-agent"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

###############################################################################
# CloudWatch Log Group
###############################################################################
resource "aws_cloudwatch_log_group" "ai_agent" {
  name              = "/ecs/ai-self-healing-agent"
  retention_in_days = 14

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

###############################################################################
# ECS Cluster
###############################################################################
resource "aws_ecs_cluster" "ai_agent" {
  name = "ai-selfhealing-agent-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

###############################################################################
# Security Groups
###############################################################################
resource "aws_security_group" "alb_sg" {
  name        = "ai-agent-alb-sg"
  description = "Allow HTTP traffic to ALB"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
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
    Name        = "ai-agent-alb-sg"
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

resource "aws_security_group" "ecs_sg" {
  name        = "ai-agent-ecs-sg"
  description = "Allow traffic from ALB to ECS tasks"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb_sg.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "ai-agent-ecs-sg"
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

###############################################################################
# Application Load Balancer (Internal)
###############################################################################
resource "aws_lb" "ai_agent" {
  name               = "ai-agent-alb"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb_sg.id]
  subnets            = var.private_subnets

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

resource "aws_lb_target_group" "ai_agent" {
  name        = "ai-agent-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    enabled             = true
    healthy_threshold   = 2
    interval            = 30
    matcher             = "200"
    path                = "/health"
    port                = "traffic-port"
    unhealthy_threshold = 3
    timeout             = 15
  }

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

resource "aws_lb_listener" "ai_agent" {
  load_balancer_arn = aws_lb.ai_agent.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ai_agent.arn
  }
}

###############################################################################
# ECS Task Definition
###############################################################################
resource "aws_ecs_task_definition" "ai_agent" {
  family                   = "ai-self-healing-agent"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = var.task_execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name  = "ai-agent"
      image = "${aws_ecr_repository.ai_agent.repository_url}:latest"

      portMappings = [
        {
          containerPort = 8000
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "BEDROCK_MODEL_ID", value = "zai.glm-5" },
        { name = "AGENT_AWS_REGION", value = var.agent_region },
        { name = "EKS_CLUSTER_ENDPOINT", value = var.eks_cluster_endpoint },
        { name = "EKS_CLUSTER_CA", value = var.eks_cluster_ca },
        { name = "CLUSTER_NAME", value = var.cluster_name },
        { name = "CONFIDENCE_THRESHOLD", value = "0.8" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.ai_agent.name
          "awslogs-region"        = var.agent_region
          "awslogs-stream-prefix" = "ai-agent"
        }
      }

      essential = true
    }
  ])

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

###############################################################################
# ECS Service
###############################################################################
resource "aws_ecs_service" "ai_agent" {
  name            = "ai-self-healing-agent"
  cluster         = aws_ecs_cluster.ai_agent.id
  task_definition = aws_ecs_task_definition.ai_agent.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  health_check_grace_period_seconds = 60

  network_configuration {
    subnets          = var.private_subnets
    security_groups  = [aws_security_group.ecs_sg.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ai_agent.arn
    container_name   = "ai-agent"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.ai_agent]

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

###############################################################################
# Allow ECS tasks to reach EKS API server (private endpoint)
###############################################################################
resource "aws_security_group_rule" "ecs_to_eks_api" {
  count = var.eks_cluster_security_group_id != "" ? 1 : 0

  type                     = "ingress"
  from_port                = 443
  to_port                  = 443
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.ecs_sg.id
  security_group_id        = var.eks_cluster_security_group_id

  description = "Allow ECS AI Agent to reach EKS API server"
}

###############################################################################
# Route53 Private Hosted Zone (stable internal DNS)
###############################################################################
resource "aws_route53_zone" "internal" {
  name = "ai-selfhealing.internal"

  vpc {
    vpc_id = var.vpc_id
  }

  tags = {
    Environment = "dev"
    Project     = "ai-selfhealing"
  }
}

resource "aws_route53_record" "ai_agent" {
  zone_id = aws_route53_zone.internal.zone_id
  name    = "ai-agent.ai-selfhealing.internal"
  type    = "A"

  alias {
    name                   = aws_lb.ai_agent.dns_name
    zone_id                = aws_lb.ai_agent.zone_id
    evaluate_target_health = true
  }
}

###############################################################################
# Outputs
###############################################################################
output "alb_dns_name" {
  description = "Internal ALB DNS for Alertmanager webhook"
  value       = aws_lb.ai_agent.dns_name
}

output "webhook_url" {
  description = "Stable internal webhook URL for Alertmanager"
  value       = "http://ai-agent.ai-selfhealing.internal/webhook"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.ai_agent.repository_url
}
