# Migration runner image for DriftShield.
#
# Builds a container that applies the DriftShield Alembic migration chain
# against a PostgreSQL database. The same image runs locally with
# DATABASE_URL or as an AWS Lambda function with DB_SECRET_ARN pointing at
# a Secrets Manager secret in the {username, password, host, port, dbname}
# shape produced by AWS managed credentials.

FROM public.ecr.aws/lambda/python:3.12

WORKDIR /var/task

# Copy the package source and the Alembic configuration. The image installs
# driftshield itself from the local source so the migration scripts can
# import db.models for autogeneration consistency.
COPY pyproject.toml ./
COPY src/ ./src/
COPY alembic.ini ./

# Install the package and the runtime dependencies the handler needs.
# boto3 is a hard dependency of the runner image so secret resolution does
# not silently rely on the Lambda runtime copy.
RUN pip install --no-cache-dir . 'boto3>=1.34.0'

# The handler module lives next to the Alembic config.
COPY migrations/lambda_handler.py ./lambda_handler.py

CMD ["lambda_handler.handler"]
