# Cloud Reference Architecture

Production-grade cloud system template built on constrained home hardware.
Local stack → one-command AWS deployment.

## Stack

| Layer | Local | AWS |
|---|---|---|
| Relational DB | PostgreSQL (Docker) | RDS PostgreSQL |
| Document DB | MongoDB (Docker) | DocumentDB |
| Cache | Redis (Docker) | ElastiCache |
| Message Queue | RabbitMQ (Docker) | SQS |
| Event Streaming | Apache Kafka (Docker) | MSK / Kinesis |
| File Storage | LocalStack S3 | S3 |
| Auth | Keycloak + LocalStack Cognito | Cognito |
| Orchestration | K3s | EKS / ECS |
| IaC | Terraform + tflocal | Terraform |
| CI/CD | GitHub Actions | GitHub Actions + ECR |
| Monitoring | Prometheus + Grafana | CloudWatch + Grafana |

## Phases

| # | Phase |
|---|---|
| 1 | Docker + LocalStack + Terraform |
| 2 | PostgreSQL + EF Core |
| 3 | MongoDB |
| 4 | Redis (cache + pub/sub) |
| 5 | Auth (Keycloak + Cognito) |
| 6 | React frontend |
| 7 | File storage (S3) |
| 8 | Message queuing (RabbitMQ + SQS) |
| 9 | Event streaming (Kafka) |
| 10 | Container orchestration (K3s) |
| 11 | Monitoring (Prometheus + Grafana) |
| 12 | CI/CD pipeline |
| 13 | Load, stress & security testing |

See `/runbooks` for per-phase documentation generated during build.

## AWS Deployment

One-time manual setup (~1 hour), then:
```bash
terraform apply       # creates full environment
terraform destroy     # removes everything, billing stops
```

## Local → AWS Switch
```bash
# Local (LocalStack on DISCWORLD)
AWSSDK_ENDPOINT_URL=http://DISCWORLD:4566

# AWS (real endpoints)
# unset AWSSDK_ENDPOINT_URL
```

Same Docker image. Same code. Same Terraform HCL. Only the variable changes.
