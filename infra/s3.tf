# Data lake bucket for the pipeline's 4 storage roots (DATA_LAKE_ROOT,
# WAREHOUSE_ROOT, FEATURE_STORE_PATH, MODELS_DIR — see app/core/storage.py).
# Mirrors the durability story already documented for the self-hosted MinIO
# path (docs/deployment/self-hosted.md): versioning on, no lifecycle
# deletion, back the underlying data up out-of-band.
#
# Hardened by default, matching this repo's RDS convention (infra/rds.tf):
# versioning + SSE + all public access blocked. Bucket name/versioning are
# both overridable — see variables.tf.

resource "aws_s3_bucket" "data_lake" {
  bucket = local.data_lake_bucket_name

  tags = {
    Name = local.data_lake_bucket_name
  }
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  versioning_configuration {
    status = var.data_lake_bucket_versioning ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
