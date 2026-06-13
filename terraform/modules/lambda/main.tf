# DEPRECATED: Lambda has been replaced by ECS Fargate.
# This module is intentionally empty.
# The AI agent now runs as an ECS Fargate service.
# See: terraform/modules/ecs/main.tf
#
# To destroy the old Lambda resources manually:
#   terraform destroy -target=module.lambda_ai
# Then remove this module block from live/dev/main.tf
