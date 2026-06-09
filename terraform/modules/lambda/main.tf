variable "lambda_role_arn" { type = string }
variable "bedrock_model_id" {
  type = string
  default = "anthropic.claude-3-sonnet-20240229-v1:0"
}

data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/../../../src/ai-agent"
  output_path = "${path.module}/lambda_function.zip"
}

resource "aws_lambda_function" "ai_agent" {
  filename      = data.archive_file.lambda_zip.output_path
  function_name = "ai-self-healing-agent"
  role          = var.lambda_role_arn
  handler       = "main.lambda_handler"
  runtime       = "python3.11"
  timeout       = 60

  environment {
    variables = {
      BEDROCK_MODEL_ID = var.bedrock_model_id
      AGENT_AWS_REGION = "eu-north-1"
    }
  }
}

resource "aws_lambda_function_url" "ai_agent_url" {
  function_name      = aws_lambda_function.ai_agent.function_name
  authorization_type = "NONE" # Open for Alertmanager webhook
  cors {
    allow_credentials = true
    allow_origins     = ["*"]
  }
}

output "function_url" {
  value = aws_lambda_function_url.ai_agent_url.function_url
}
