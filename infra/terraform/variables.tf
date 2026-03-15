variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (local, staging, production)"
  type        = string
  default     = "local"
}

variable "project_name" {
  description = "Project name prefix for all resources"
  type        = string
  default     = "cloud-ref"
}
