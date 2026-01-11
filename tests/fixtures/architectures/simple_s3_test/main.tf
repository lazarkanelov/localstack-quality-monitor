# Simple S3 bucket - tflocal handles LocalStack endpoints automatically
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_s3_bucket" "test_bucket" {
  bucket = "lsqm-test-bucket-simple"
}

output "bucket_name" {
  value = aws_s3_bucket.test_bucket.id
}
