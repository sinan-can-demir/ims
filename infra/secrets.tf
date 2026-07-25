# DATABASE_URL is fully derived from the RDS instance + generated password —
# no manual value needed, Terraform's dependency graph wires it automatically.
resource "aws_secretsmanager_secret" "database_url" {
  name = "${local.name_prefix}/database-url"

  tags = {
    Name = "${local.name_prefix}-database-url"
  }
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id     = aws_secretsmanager_secret.database_url.id
  secret_string = "postgresql://${var.db_username}:${random_password.db.result}@${aws_db_instance.main.endpoint}/${var.db_name}"
}

# JWT_SECRET is supplied by the operator (same value the app uses to
# sign/verify tokens), not generated — matches today's local .env pattern.
resource "aws_secretsmanager_secret" "jwt_secret" {
  name = "${local.name_prefix}/jwt-secret"

  tags = {
    Name = "${local.name_prefix}-jwt-secret"
  }
}

resource "aws_secretsmanager_secret_version" "jwt_secret" {
  secret_id     = aws_secretsmanager_secret.jwt_secret.id
  secret_string = var.jwt_secret
}
