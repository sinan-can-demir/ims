# ---------------------------------------------------------------------------
# ECS task execution role — used by the ECS agent itself to pull the image,
# write logs, and fetch secrets. NOT the same as the task role below.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name               = "${local.name_prefix}-ecs-task-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution_managed" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# The managed policy above covers ECR pull + CloudWatch Logs, but NOT Secrets
# Manager — that has to be granted explicitly and scoped to just these two
# secrets.
data "aws_iam_policy_document" "ecs_task_execution_secrets" {
  statement {
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.database_url.arn,
      aws_secretsmanager_secret.jwt_secret.arn,
    ]
  }
}

resource "aws_iam_role_policy" "ecs_task_execution_secrets" {
  name   = "${local.name_prefix}-ecs-task-execution-secrets"
  role   = aws_iam_role.ecs_task_execution.id
  policy = data.aws_iam_policy_document.ecs_task_execution_secrets.json
}

# ---------------------------------------------------------------------------
# ECS task role — used by application code inside the container for any AWS
# SDK calls it makes itself. Empty for this API-only slice; this is the
# attach point for S3 access when the data pipeline migrates to S3.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "ecs_task" {
  name               = "${local.name_prefix}-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

# ---------------------------------------------------------------------------
# GitHub Actions OIDC — lets CI assume an AWS role without any long-lived
# access keys stored as GitHub secrets.
#
# NOTE: aws_iam_openid_connect_provider for token.actions.githubusercontent.com
# is a singleton per AWS account. Run
#   aws iam list-open-id-connect-providers
# before the first `terraform apply` — if one already exists (e.g. from
# unrelated prior work in this account), `terraform import` it instead of
# letting this resource try to create a duplicate.
# ---------------------------------------------------------------------------

# thumbprint_list is the SHA1 fingerprint of GitHub's OIDC root CA (ISRG
# Root X1, since GitHub migrated to Let's Encrypt — the older DigiCert
# thumbprint some tutorials still show is stale). AWS doesn't actually use
# this for cert validation on well-known providers like GitHub's, but the
# API still requires a syntactically valid one. If GitHub ever rotates CAs
# again and this needs regenerating:
#   openssl s_client -connect token.actions.githubusercontent.com:443 \
#     -showcerts </dev/null 2>/dev/null | openssl x509 -noout -fingerprint -sha1
# (take the ROOT cert's fingerprint, last one in the chain / self-signed)
resource "aws_iam_openid_connect_provider" "github" {
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = ["cabd2a79a1076a31f21d253635cb039d4329a5e8"]
}

data "aws_iam_policy_document" "github_deploy_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Scoped to the main branch only — PRs and forks cannot assume this role.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/main"]
    }
  }
}

resource "aws_iam_role" "github_deploy" {
  name               = "${local.name_prefix}-github-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_deploy_assume.json
}

data "aws_iam_policy_document" "github_deploy_permissions" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # this action does not support resource-level scoping
  }

  statement {
    sid = "EcrPush"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:PutImage",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:BatchGetImage",
    ]
    resources = [aws_ecr_repository.api.arn]
  }

  statement {
    sid = "EcsDeploy"
    actions = [
      "ecs:UpdateService",
      "ecs:DescribeServices",
      "ecs:DescribeTaskDefinition",
      "ecs:DescribeTasks",
    ]
    resources = [
      aws_ecs_cluster.main.arn,
      aws_ecs_service.api.id,
    ]
  }

  statement {
    sid       = "EcsRegisterTaskDefinition"
    actions   = ["ecs:RegisterTaskDefinition"] # does not support resource-level scoping
    resources = ["*"]
  }

  statement {
    sid       = "PassEcsRoles"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.ecs_task_execution.arn, aws_iam_role.ecs_task.arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "github_deploy_permissions" {
  name   = "${local.name_prefix}-github-deploy-permissions"
  role   = aws_iam_role.github_deploy.id
  policy = data.aws_iam_policy_document.github_deploy_permissions.json
}
