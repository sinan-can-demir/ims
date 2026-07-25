# AWS Infrastructure (Enterprise Deployment)

Terraform for the IMS API on ECS Fargate — sub-phase 1 of the AWS deployment
(ROADMAP.md Epoch 7 Phase 5). Deploys the API + RDS Postgres behind an ALB.
**Not included yet**: the data pipeline (S3), the Streamlit dashboard, a
custom domain/HTTPS. See the root `ROADMAP.md` for what's planned next.

This is the **enterprise path** — for teams already running on AWS who want
a `terraform apply`-and-go deployment. If you just want to run IMS somewhere
cheaply and simply (a VPS, no cloud account), see
[`docs/deployment/self-hosted.md`](../docs/deployment/self-hosted.md) instead
— same Docker image, ~$5-20/month instead of ~$75-85/month, fully
open-source tooling end to end.

**Estimated cost: ~$75-85/month**, mostly the NAT Gateway (~$35) and ALB
(~$18) — the cost of using private subnets rather than the cheapest possible
design. Review `terraform plan` before every `apply`; this creates real,
billed AWS resources.

## Prerequisites

- Terraform >= 1.9
- AWS CLI v2, configured with credentials that can create VPCs, RDS, ECS,
  IAM roles, Secrets Manager secrets, and an OIDC provider
- An AWS account you're comfortable being billed on

## One-time setup

### 1. Bootstrap the Terraform state backend

This bucket/table can't be created by the Terraform config that then uses
them as its own backend — create them once via the CLI:

```bash
aws s3api create-bucket --bucket ims-terraform-state --region us-east-1
aws s3api put-bucket-versioning --bucket ims-terraform-state \
  --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket ims-terraform-state \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws dynamodb create-table --table-name ims-terraform-locks \
  --attribute-definitions AttributeName=LockID,AttributeType=S \
  --key-schema AttributeName=LockID,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST
```

If you use a bucket/table name or region other than the defaults in
`versions.tf`, update that file to match.

### 2. Check for an existing GitHub OIDC provider

`aws_iam_openid_connect_provider` for `token.actions.githubusercontent.com`
is a singleton per AWS account:

```bash
aws iam list-open-id-connect-providers
```

If one already exists (e.g. from unrelated prior work in this account),
`terraform import aws_iam_openid_connect_provider.github <arn>` instead of
letting `apply` try to create a duplicate (it will error).

### 3. Configure variables

```bash
cp terraform.tfvars.example terraform.tfvars
# edit terraform.tfvars: set jwt_secret (openssl rand -hex 32)
```

`terraform.tfvars` is gitignored — never commit a real API key.

### 4. First apply (two-step, because ECR starts empty)

The ECS task definition needs a real image to reference, but on a from-scratch
account there's no image yet — chicken and egg. Bootstrap it:

```bash
terraform init
terraform apply -target=aws_ecr_repository.api

# build and push one image tagged "initial" (matches variables.tf's
# api_image_tag default) so the first full apply has something to reference
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin <account-id>.dkr.ecr.us-east-1.amazonaws.com
docker build -f ../docker/Dockerfile -t <ecr-repo-url>:initial ..
docker push <ecr-repo-url>:initial

terraform apply
```

(`terraform output ecr_repository_url` after the first `-target` apply gives
you the exact repo URL.)

RDS provisioning takes ~5-10 minutes — expected.

### 5. Wire up CD

```bash
gh variable set AWS_DEPLOY_ROLE_ARN --body "$(terraform output -raw github_actions_role_arn)"
```

After this, every push to `main` builds, pushes, and deploys automatically
via `.github/workflows/ci.yml`'s `deploy` job — no more manual `terraform
apply` for routine code changes. Re-run `terraform apply` only when you
change the *infrastructure* itself (this `infra/` directory).

## Verify

```bash
curl http://$(terraform output -raw alb_dns_name)/health

# No self-service registration — create an account first:
#   docker exec <api-task-container> python scripts/create_user.py --email you@example.com --display-name "Your Name"
TOKEN=$(curl -s -X POST http://$(terraform output -raw alb_dns_name)/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"<your password>"}' | jq -r .access_token)
curl -H "Authorization: Bearer $TOKEN" http://$(terraform output -raw alb_dns_name)/api/products
```

## Notes / known limitations of this slice

- HTTP only — no domain/ACM cert yet, so no HTTPS. Don't send anything
  sensitive to the ALB URL over the open internet until that's added.
- Migrations run as a dedicated one-off task (`aws_ecs_task_definition.migrate`,
  run via `aws ecs run-task` in `ci.yml`'s deploy job) before each deploy
  updates the `api` service — safe to raise `desired_count` above 1.
- RDS is single-AZ, no deletion protection, no final snapshot on destroy —
  fine for this project's current stage, not production-grade durability.
