# AWS deployment starter

This directory contains a parameterized ECS/Fargate deployment layer for CiteLadder.
It is intentionally separate from the local Docker Compose stack.

The deployment uses:

- one ECR backend image for the API, migration task, and all backend workers;
- one ECR Next.js frontend image;
- ECS/Fargate services with private task networking;
- PostgreSQL supplied through an existing RDS instance;
- Secrets Manager ARNs supplied through a local ignored configuration file;
- ECS Service Connect so the frontend rewrites `"/api/*"` to `http://api:8000`;
- an existing ALB target group for the frontend.

The script does not create a VPC, RDS instance, security groups, ALB, certificates,
CloudFront, WAF, or secret values. Those resources need reviewed IaC and an approved
AWS environment. This keeps an accidental run from creating an incomplete public
production stack.

## Important scope

The repository's AWS runbook identifies ECS/Fargate as the target architecture, but
also states that production prerequisites are still open. These files are suitable as
a reviewed staging deployment layer after the prerequisites below exist. They are not
a claim that production is ready.

For production, complete the runbook requirements for CloudFront/WAF, HTTPS-only ALB
origin access, private networking/NAT or VPC endpoints, RDS Multi-AZ/backups/TLS,
secret rotation, image signing/scanning, migrations, rollback, and recovery drills.

## Prerequisites

Install and configure:

- AWS CLI v2 with an approved deployment role;
- Docker Desktop;
- PowerShell 7 (`pwsh`);
- an existing AWS VPC in the target region;
- at least two private ECS subnets in different Availability Zones;
- an ECS security group with no inbound rules and egress to RDS, AWS endpoints,
  and the required external providers through the approved network path;
- an RDS PostgreSQL 16 instance in isolated subnets, with its security group allowing
  TCP 5432 from the ECS security group;
- an ECS task execution role that can pull the two ECR repositories, write CloudWatch
  logs, and read only the configured Secrets Manager ARNs;
- a regional KMS key for encrypting the ECS CloudWatch log groups;
- an ECS Service Connect private DNS namespace;
- an ALB frontend target group forwarding to port 3000 and health-checking `/`;
- a database URL secret using the backend's async driver, for example:
  `postgresql+asyncpg://citeladder_app:<password>@<rds-host>:5432/citeladder`.

Set `DB_SSL_MODE=require` in the backend environment. The application passes this to
asyncpg and refuses production startup when it is not `require`.

The RDS security group must be configured outside this directory. Do not put its
password in `config.json`, task definitions, Docker build arguments, or Git.

## Prepare local configuration

From the repository root:

```powershell
Copy-Item infra/aws/config.example.json infra/aws/config.json
Copy-Item infra/aws/secret-arns.example.json infra/aws/secret-arns.json
```

Edit the copied files with real account-specific IDs and secret ARNs. Both files are
ignored by Git. They contain identifiers only; the secret values stay in Secrets Manager.

Required secret values:

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `ENCRYPTION_KEY`
- `REFERRAL_HASH_SALT`
- `ORDER_HASH_SALT`

Add optional provider, integration, or billing secret ARNs only when those features
are configured in the target environment. The deployment injects the same backend
secret set into the API, migration task, and workers. The frontend receives no backend
secrets.

The frontend origin must be the public app origin, not the API origin:

```json
{
  "frontendUrl": "https://staging.example.com",
  "frontendOrigins": "https://staging.example.com",
  "backendOrigin": "http://api:8000"
}
```

`backendOrigin` is used at frontend build time for the server-only Next.js rewrite.
The browser still calls relative `/api/*` URLs.

## Validate without changing AWS

The script performs configuration validation and prints the plan by default:

```powershell
pwsh -File infra/aws/deploy-ecs.ps1 -ConfigPath infra/aws/config.json -SecretArnsPath infra/aws/secret-arns.json
```

No ECR, ECS, CloudWatch, or other AWS resources are changed without `-Apply`.

## Build and deploy

After reviewing the dry-run output:

```powershell
pwsh -File infra/aws/deploy-ecs.ps1 -ConfigPath infra/aws/config.json -SecretArnsPath infra/aws/secret-arns.json -Apply
```

The deployment performs these actions:

1. verifies the AWS account and region;
2. creates the two ECR repositories if absent and enables scan-on-push;
3. builds and pushes one immutable-tagged backend image from
   `infra/docker/Dockerfile`;
4. builds and pushes one immutable-tagged frontend image from
   `infra/aws/frontend.Dockerfile`;
5. creates/updates CloudWatch log groups;
6. registers ECS task definitions for the frontend, API, migration, and workers;
7. runs exactly one migration task and stops if it fails;
8. creates or updates the API, frontend, and worker services;
9. enables the ECS deployment circuit breaker and waits for service stability.

The backend image is reused with different commands:

| ECS service | Container command |
|---|---|
| API | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Migration | `alembic upgrade head` |
| Audit worker | `python -m app.workers.audit_worker` |
| Site Health | `python -m app.workers.site_health_worker` |
| Brand discovery | `python -m app.workers.brand_discovery_worker` |
| Content | `python -m app.workers.content_worker` |
| Analytics | `python -m app.workers.analytics_worker` |
| Integration | `python -m app.workers.integration_worker` |
| Integration dispatcher | `python -m app.workers.integration_dispatcher` |

The integration dispatcher remains at exactly one desired task. The other desired
counts are configurable in `config.json`.

## Useful AWS checks

```powershell
$config = Get-Content infra/aws/config.json -Raw | ConvertFrom-Json
aws ecs describe-services -Cluster $config.clusterName -Services citeladder-$($config.environment)-api,citeladder-$($config.environment)-frontend -Region $config.awsRegion -Query 'services[].[serviceName,status,desiredCount,runningCount]' -Output table
aws logs tail /ecs/citeladder/$($config.environment)/api --follow --region $config.awsRegion
```

Inspect a worker by replacing `api` with its service name.

## Updating the application

Use a new Git revision tag for every deployment. Do not deploy `latest`; the script
uses an immutable tag by default.

```powershell
pwsh -File infra/aws/deploy-ecs.ps1 -ConfigPath infra/aws/config.json -SecretArnsPath infra/aws/secret-arns.json -ImageTag <new-git-revision> -Apply
```

The script runs migrations before updating services. Review the migration and rollback
procedure for every schema change. The current repository migration policy still
requires an explicit decision before production schema evolution.

## Files

- `frontend.Dockerfile` — Next.js standalone production image;
- `deploy-ecs.ps1` — validated, opt-in ECS deployment script;
- `config.example.json` — non-secret AWS/network/service configuration;
- `secret-arns.example.json` — secret names mapped to Secrets Manager ARNs;
- `.gitignore` — prevents local account-specific files and generated output from
  being committed.
