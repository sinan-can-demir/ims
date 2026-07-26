resource "aws_db_subnet_group" "main" {
  name       = "${local.name_prefix}-db-subnet-group"
  subnet_ids = aws_subnet.private[*].id

  tags = {
    Name = "${local.name_prefix}-db-subnet-group"
  }
}

resource "random_password" "db" {
  length  = 32
  special = false # avoid characters that need URL-encoding in DATABASE_URL
}

# Hardened defaults (issue #20): Multi-AZ, deletion protection, and a final
# snapshot on destroy are all on by default — override the corresponding
# variables (db_multi_az, db_deletion_protection) for a cheaper single-AZ
# dev/test deployment. Two operational tradeoffs worth knowing before you
# `terraform apply`, documented further in infra/README.md:
#   - deletion_protection = true blocks `terraform destroy` outright until
#     you override the variable to false and re-apply first.
#   - skip_final_snapshot = false means every destroy leaves a manual RDS
#     snapshot named final_snapshot_identifier behind — delete it yourself
#     via the AWS console/CLI if you don't need it, and rename/remove it
#     before a second destroy of the same identifier or the create-time
#     snapshot-name collision will fail the apply.
resource "aws_db_instance" "main" {
  identifier     = "${local.name_prefix}-db"
  engine         = "postgres"
  engine_version = "15"

  instance_class    = var.db_instance_class
  allocated_storage = var.db_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.db_name
  username = var.db_username
  password = random_password.db.result
  port     = 5432

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  multi_az                  = var.db_multi_az
  backup_retention_period   = var.db_backup_retention_period
  deletion_protection       = var.db_deletion_protection
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.name_prefix}-db-final-snapshot"

  tags = {
    Name = "${local.name_prefix}-db"
  }
}
