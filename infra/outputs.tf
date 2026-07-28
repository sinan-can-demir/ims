output "alb_dns_name" {
  description = "Public URL of the API (HTTP only, no domain yet)."
  value       = aws_lb.main.dns_name
}

output "ecr_repository_url" {
  description = "Push images here (CD does this automatically)."
  value       = aws_ecr_repository.api.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  value = aws_ecs_service.api.name
}

output "ecs_migrate_task_definition_family" {
  description = "Task definition family for the one-off migration task, run via `aws ecs run-task` in ci.yml's deploy job before each service update."
  value       = aws_ecs_task_definition.migrate.family
}

output "github_actions_role_arn" {
  description = "Register this as the AWS_DEPLOY_ROLE_ARN GitHub repo variable: gh variable set AWS_DEPLOY_ROLE_ARN --body <this value>"
  value       = aws_iam_role.github_deploy.arn
}

output "rds_endpoint" {
  value     = aws_db_instance.main.endpoint
  sensitive = true
}

output "data_lake_bucket_name" {
  description = "Point DATA_LAKE_ROOT/WAREHOUSE_ROOT/FEATURE_STORE_PATH/MODELS_DIR at s3://<this>/<subpath>."
  value       = aws_s3_bucket.data_lake.id
}
