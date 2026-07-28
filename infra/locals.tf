locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  # S3 bucket names are globally unique across all AWS accounts, so the
  # plain name_prefix default risks colliding with someone else's bucket —
  # var.data_lake_bucket_name lets that be overridden per deployment.
  data_lake_bucket_name = coalesce(var.data_lake_bucket_name, "${local.name_prefix}-data-lake")
}
