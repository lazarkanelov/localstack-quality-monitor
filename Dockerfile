# LocalStack Quality Monitor Docker Image
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install Terraform
ARG TERRAFORM_VERSION=1.6.0
RUN curl -fsSL https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip -o terraform.zip \
    && unzip terraform.zip \
    && mv terraform /usr/local/bin/ \
    && rm terraform.zip

# Install tflocal
RUN pip install --no-cache-dir terraform-local

# Set working directory
WORKDIR /app

# Copy package files
COPY pyproject.toml setup.py README.md ./
COPY src/ ./src/

# Install LSQM
RUN pip install --no-cache-dir -e .

# Create cache directory
RUN mkdir -p /root/.lsqm/cache

# Set environment variables
ENV LOCALSTACK_ENDPOINT=http://localstack:4566
ENV PYTHONUNBUFFERED=1

# Default command
ENTRYPOINT ["lsqm"]
CMD ["--help"]
