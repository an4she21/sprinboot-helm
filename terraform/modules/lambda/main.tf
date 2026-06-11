# DEPRECATED: Lambda has been replaced by ECS Fargate.
# This file is kept for reference during migration.
# To destroy the old Lambda: terraform destroy -target=module.lambda
#
# The AI agent now runs as an ECS Fargate service.
# See: terraform/modules/ecs/main.tf

variable "lambda_role_arn" {
  type    = string
  default = ""
}

variable "bedrock_model_id" {
  type    = string
  default = "anthropic.claude-3-sonnet-20240229-v1:0"
}
