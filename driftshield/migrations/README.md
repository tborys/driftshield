# Migration runner

A container image that applies the DriftShield Alembic migration chain
against a PostgreSQL database. Runs locally for development and as an AWS
Lambda function for managed deployments.

The image is intentionally small and single-purpose. It does not start the
DriftShield API server. It does one thing: `alembic upgrade head`.

## Configuration

Set exactly one of the following environment variables.

`DATABASE_URL`
  A SQLAlchemy-compatible PostgreSQL URL. Used as-is.

`DB_SECRET_ARN`
  An AWS Secrets Manager ARN. The secret value must be JSON containing
  `username`, `password`, `host`, `port`, and `dbname` (`database` is
  accepted as an alias for `dbname`). The runner builds the URL itself.

If neither is set, the runner exits with an error. If both are set, the
runner exits with an error. There are no defaults.

The runner never logs the resolved URL or the password.

## Build

From the package root, with `Dockerfile` at `migrations/Dockerfile`:

```bash
docker build -f migrations/Dockerfile -t driftshield-migrations:dev .
```

## Run locally

Bring up a throwaway PostgreSQL and run the migration image against it:

```bash
docker network create migrations-net

docker run --rm -d --name pg --network migrations-net \
  -e POSTGRES_PASSWORD=devpass \
  -e POSTGRES_DB=driftshield \
  postgres:16

docker run --rm --network migrations-net \
  -e DATABASE_URL=postgresql+psycopg2://postgres:devpass@pg:5432/driftshield \
  --entrypoint python \
  driftshield-migrations:dev \
  -c "from lambda_handler import handler; import json; print(json.dumps(handler({}, None), indent=2))"
```

Expected output is a JSON object describing the starting and resulting
head revisions.

Tear down:

```bash
docker stop pg
docker network rm migrations-net
```

## Deploy as a container Lambda

The image is compatible with the AWS Lambda container runtime. The default
`CMD` is `lambda_handler.handler`. The function role must allow
`secretsmanager:GetSecretValue` on the target secret if `DB_SECRET_ARN`
is used. The function must have network reachability to the database.

The Lambda invocation event is ignored. Invoke with an empty payload:

```bash
aws lambda invoke \
  --function-name <your-migration-function> \
  --payload '{}' \
  /tmp/migration-output.json

cat /tmp/migration-output.json
```

A successful response looks like:

```json
{
  "status": "ok",
  "starting_revision": "8f1a2b3c4d5e",
  "head_revision": "ce8b08023f17",
  "target_head": "ce8b08023f17"
}
```

A failed migration raises, so the Lambda invocation is marked as failed
and CloudWatch contains a redacted error message.

## What this image does not do

- It does not seed sample data.
- It does not start the API server.
- It does not run integration tests.
- It does not generate new revisions. Authoring revisions stays a developer
  workflow with a local checkout.
