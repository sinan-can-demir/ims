variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name used as a prefix for resource names and tags."
  type        = string
  default     = "ims"
}

variable "environment" {
  description = "Deployment environment name, used in tags."
  type        = string
  default     = "prod"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_cidrs" {
  description = "CIDR blocks for the two public subnets (ALB, NAT gateway)."
  type        = list(string)
  default     = ["10.0.0.0/24", "10.0.1.0/24"]
}

variable "private_subnet_cidrs" {
  description = "CIDR blocks for the two private subnets (ECS tasks, RDS)."
  type        = list(string)
  default     = ["10.0.10.0/24", "10.0.11.0/24"]
}

variable "container_port" {
  description = "Port the API container listens on."
  type        = number
  default     = 8000
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_allocated_storage" {
  description = "RDS allocated storage in GB."
  type        = number
  default     = 20
}

variable "db_name" {
  description = "Postgres database name."
  type        = string
  default     = "ims"
}

variable "db_username" {
  description = "Postgres master username."
  type        = string
  default     = "ims_admin"
}

variable "db_multi_az" {
  description = "Enable Multi-AZ for the RDS instance. Roughly doubles RDS cost — override to false for a cheaper single-AZ dev/test deployment."
  type        = bool
  default     = true
}

variable "db_backup_retention_period" {
  description = "Days to retain automated RDS backups. 0 disables automated backups entirely."
  type        = number
  default     = 7
}

variable "db_deletion_protection" {
  description = "Enable RDS deletion protection. Must be overridden to false (and re-applied) before `terraform destroy` can remove the instance."
  type        = bool
  default     = true
}

variable "ecs_task_cpu" {
  description = "Fargate task vCPU units (256 = 0.25 vCPU, the cheapest tier)."
  type        = number
  default     = 256
}

variable "ecs_task_memory" {
  description = "Fargate task memory in MB (must pair validly with ecs_task_cpu)."
  type        = number
  default     = 512
}

variable "ecs_desired_count" {
  description = "Number of API tasks to run. Migrations run as a dedicated one-off task in CI (see aws_ecs_task_definition.migrate, ci.yml's deploy job) before each service update, not inline in the api container's startup command — safe to raise above 1."
  type        = number
  default     = 1
}

variable "gunicorn_workers" {
  description = "Number of Gunicorn worker processes per task, each a full Python process with the app's dependencies loaded (pandas/prophet/duckdb are not small). Kept conservative by default because the default ecs_task_cpu/ecs_task_memory (256/512) is the cheapest Fargate tier — raise this only alongside ecs_task_cpu/ecs_task_memory, not independently, or workers will OOM."
  type        = number
  default     = 2
}

variable "jwt_secret" {
  description = "Secret key used to sign/verify the JWTs issued by POST /api/auth/login (HS256). Generate with `openssl rand -hex 32`. Supply via terraform.tfvars (gitignored) or TF_VAR_jwt_secret — never commit a real value."
  type        = string
  sensitive   = true
}

variable "cors_origins" {
  description = "Comma-separated list of allowed CORS origins for the API."
  type        = string
  default     = "http://localhost:8501"
}

variable "github_repository" {
  description = "GitHub repo allowed to assume the CD deploy role, as \"owner/repo\"."
  type        = string
  default     = "sinan-can-demir/ims"
}

variable "data_lake_bucket_name" {
  description = "Name for the data lake S3 bucket (DATA_LAKE_ROOT/WAREHOUSE_ROOT/FEATURE_STORE_PATH/MODELS_DIR). S3 bucket names are globally unique across all AWS accounts, so the default (\"<project>-<environment>-data-lake\") may collide — override if it does. null uses the default."
  type        = string
  default     = null
}

variable "data_lake_bucket_versioning" {
  description = "Enable S3 versioning on the data lake bucket, mirroring the durability story documented for the self-hosted MinIO path (docs/deployment/self-hosted.md). Leave enabled unless you have your own durability mechanism."
  type        = bool
  default     = true
}

# On the very first `terraform apply`, the ECR repo is empty — there is no
# image at this tag yet. Push one manually with this tag before the first
# full apply (see README.md's bootstrap steps). Every deploy after that is
# handled by CI, which registers a fresh task definition revision pointing
# at the new image tag directly (Terraform ignores task_definition changes
# on aws_ecs_service after the first apply — see ecs.tf).
variable "api_image_tag" {
  description = "Image tag for the initial task definition."
  type        = string
  default     = "initial"
}
