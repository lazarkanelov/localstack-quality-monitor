# Research: LocalStack Quality Monitor CLI

**Date**: 2026-01-10
**Branch**: 001-lsqm-cli

## Overview

This document consolidates research findings for key technical decisions required to implement the LSQM CLI tool.

---

## 1. Terraform Registry API

### Decision
Use the public Terraform Registry API v1 to discover and download AWS modules.

### Rationale
- No authentication required for public registry
- Well-documented REST API with search and filter capabilities
- Direct access to module source via `X-Terraform-Get` header
- Supports filtering by provider (aws) and verification status

### Key Implementation Details

**Base URL**: `https://registry.terraform.io/v1/modules/`

**Endpoints**:
| Endpoint | Purpose |
|----------|---------|
| `GET /v1/modules/search?q=<query>&provider=aws` | Search AWS modules |
| `GET /v1/modules/:namespace/:name/aws/versions` | List module versions |
| `GET /v1/modules/:namespace/:name/aws/:version/download` | Get download URL |

**Download Pattern**:
1. Call download endpoint
2. Read `X-Terraform-Get` header from response
3. Download tarball from that URL
4. Extract to architecture directory

**Rate Limiting**:
- No explicit limits documented
- HTTP 429 returned when exceeded
- Implement exponential backoff with max 3 retries

### Alternatives Considered
- **GitHub API only**: Would miss Terraform Registry-specific modules
- **Scraping registry.terraform.io**: Fragile, may break with UI changes

---

## 2. CloudFormation to Terraform Conversion

### Decision
Use `cf2tf` Python library for initial conversion with manual fallback for edge cases.

### Rationale
- Most mature Python-based converter
- Installable via pip: `pip install cf2tf`
- Handles ~70% of resources automatically
- Well-maintained with active GitHub repository

### Key Implementation Details

**Usage**:
```python
import subprocess

def convert_cf_to_tf(cf_template_path: str, output_dir: str) -> tuple[bool, str]:
    result = subprocess.run(
        ['cf2tf', cf_template_path, '-o', output_dir],
        capture_output=True,
        text=True
    )
    return result.returncode == 0, result.stderr
```

**Known Limitations**:
| Issue | Handling Strategy |
|-------|-------------------|
| CF Map types | Mark architecture for manual review |
| Custom Resources | Skip architecture (not testable) |
| Intrinsic Functions (Ref, GetAtt) | cf2tf handles most; validate output |
| Complex Conditions | May require manual adjustment |

**Post-Conversion Validation**:
1. Run `terraform validate` on output
2. Check for conversion warnings in cf2tf output
3. Mark architecture as "needs_review" if validation fails

### Alternatives Considered
- **AI-powered conversion (Bedrock)**: Higher accuracy but adds API dependency
- **Terraformer**: Generates from live infra, not templates
- **Manual parsing**: Not maintainable at scale

---

## 3. Serverless Framework to Terraform Conversion

### Decision
Parse serverless.yml and generate Terraform using templates for common patterns.

### Rationale
- No mature converter exists for Serverless → Terraform
- Serverless Framework has predictable structure
- Most patterns map to Lambda + API Gateway + IAM

### Key Implementation Details

**Serverless to Terraform Mappings**:
| Serverless | Terraform Resource |
|------------|-------------------|
| `functions.{name}` | `aws_lambda_function` |
| `functions.{name}.events.http` | `aws_api_gateway_*` |
| `functions.{name}.events.sqs` | `aws_lambda_event_source_mapping` |
| `functions.{name}.events.s3` | `aws_s3_bucket_notification` |
| `functions.{name}.events.schedule` | `aws_cloudwatch_event_rule` + `aws_cloudwatch_event_target` |

**Implementation Approach**:
1. Parse serverless.yml with PyYAML
2. Extract function definitions and event triggers
3. Generate Terraform HCL using Jinja2 templates
4. Include IAM role/policy for Lambda execution

**Scope Limitation**:
Focus on common patterns only. Mark complex configurations (step functions plugins, custom authorizers) as "partial_conversion".

### Alternatives Considered
- **Lift plugin**: Converts to CloudFormation first, then use cf2tf (two-step, more error-prone)
- **Skip Serverless entirely**: Would miss valuable test patterns

---

## 4. LocalStack Supported Services

### Decision
Hybrid approach: static list for mining stage, runtime health check for validation stage.

### Rationale
- Health endpoint provides authoritative runtime data
- Static list enables pre-filtering before test generation
- Reduces wasted Claude API calls on unsupported architectures

### Key Implementation Details

**Runtime Check (Validation Stage)**:
```python
def get_available_services(endpoint: str) -> set[str]:
    response = requests.get(f"{endpoint}/_localstack/health")
    health = response.json()
    return set(health.get('services', {}).keys())
```

**Static List (Mining Stage)**:
Maintain in `src/lsqm/services/localstack_services.py`:
```python
LOCALSTACK_COMMUNITY_SERVICES = {
    'acm', 'apigateway', 'cloudformation', 'cloudwatch', 'config',
    'dynamodb', 'dynamodbstreams', 'ec2', 'ecr', 'ecs', 'events',
    'firehose', 'iam', 'kinesis', 'kms', 'lambda', 'logs', 'opensearch',
    'rds', 'redshift', 'resource-groups', 'resourcegroupstaggingapi',
    'route53', 's3', 's3control', 'secretsmanager', 'ses', 'sns',
    'sqs', 'ssm', 'stepfunctions', 'sts', 'transcribe'
}
```

**Update Cadence**:
- Check LocalStack releases monthly
- Update list when major versions add services
- Track in `services_last_updated` metadata field

**Service Detection in Terraform**:
Parse `.tf` files for `resource` blocks and extract service from resource type:
- `aws_lambda_function` → `lambda`
- `aws_s3_bucket` → `s3`
- `aws_dynamodb_table` → `dynamodb`

### Alternatives Considered
- **Always query health endpoint**: Requires running container during mining
- **Scrape documentation**: Fragile and may lag behind releases

---

## 5. GitHub API for Repository Mining

### Decision
Use GitHub REST API with PyGithub library for discovering architectures from AWS organizations.

### Rationale
- Well-documented API with Python SDK
- Supports search queries and directory listing
- Rate limits manageable with token authentication

### Key Implementation Details

**Target Organizations**:
- `aws-quickstart`: Production-ready reference architectures
- `aws-solutions`: AWS Solutions Library implementations
- `aws-samples`: Example code and tutorials

**Search Strategy**:
1. List repositories in each organization
2. Filter by topics: `terraform`, `cloudformation`, `serverless`
3. Search file patterns: `*.tf`, `template.yaml`, `serverless.yml`
4. Extract from subdirectories with infrastructure code

**Rate Limiting**:
- Authenticated: 5,000 requests/hour
- Use GITHUB_TOKEN from environment
- Implement request pooling and caching

**Code**:
```python
from github import Github

def discover_from_org(org_name: str, token: str) -> list[dict]:
    g = Github(token)
    org = g.get_organization(org_name)
    architectures = []

    for repo in org.get_repos():
        # Check for Terraform files
        try:
            contents = repo.get_contents("")
            # ... traverse and collect
        except Exception:
            continue

    return architectures
```

### Alternatives Considered
- **Clone all repos locally**: Storage-heavy, slow
- **GraphQL API**: More complex, no significant benefit for this use case

---

## 6. Content Hashing Strategy

### Decision
Use SHA-256 hash of normalized Terraform content for deduplication.

### Rationale
- Consistent across platforms
- Collision-resistant
- Fast enough for large file sets

### Key Implementation Details

**Normalization Before Hashing**:
1. Sort `.tf` files alphabetically
2. Remove comments and blank lines
3. Normalize whitespace
4. Concatenate in sorted order
5. Hash resulting string

**Implementation**:
```python
import hashlib

def compute_architecture_hash(tf_files: dict[str, str]) -> str:
    normalized = []
    for filename in sorted(tf_files.keys()):
        content = normalize_terraform(tf_files[filename])
        normalized.append(f"# {filename}\n{content}")

    combined = "\n".join(normalized)
    return hashlib.sha256(combined.encode()).hexdigest()[:16]
```

**Hash Length**: 16 characters (64 bits) - sufficient for ~10K architectures with negligible collision probability.

### Alternatives Considered
- **MD5**: Faster but deprecated for new projects
- **Full SHA-256**: 64 chars is unnecessarily long for identifiers

---

## 7. Claude API Integration for Test Generation

### Decision
Use Anthropic Python SDK with structured prompts and response validation.

### Rationale
- Official SDK with async support
- Token counting built-in
- Structured output via response prefilling

### Key Implementation Details

**Prompt Structure**:
```
You are generating Python test code for AWS infrastructure.

Given this Terraform configuration:
{terraform_content}

Generate these files:
1. conftest.py - pytest fixtures with boto3 clients configured for LocalStack
2. app.py - Application code that exercises the infrastructure
3. test_app.py - pytest tests that validate the infrastructure works
4. requirements.txt - Python dependencies

Requirements:
- Use boto3 for all AWS interactions
- Configure endpoint_url from LOCALSTACK_ENDPOINT environment variable
- Include setup/teardown in conftest.py
- Tests should verify resources exist and are functional
```

**Token Budget Tracking**:
```python
class TokenBudget:
    def __init__(self, limit: int = 500_000):
        self.limit = limit
        self.used = 0

    def can_generate(self, estimated_tokens: int) -> bool:
        return self.used + estimated_tokens <= self.limit

    def record_usage(self, input_tokens: int, output_tokens: int):
        self.used += input_tokens + output_tokens
```

**Syntax Validation**:
```python
import ast

def validate_python_syntax(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False
```

### Alternatives Considered
- **OpenAI API**: Less accurate for code generation in benchmarks
- **Local LLM**: Insufficient quality for complex code generation

---

## Summary of Dependencies

| Dependency | Version | Purpose |
|------------|---------|---------|
| click | ^8.1 | CLI framework |
| docker | ^7.0 | Container management |
| jinja2 | ^3.1 | HTML report templating |
| anthropic | ^0.40 | Claude API client |
| boto3 | ^1.35 | AWS SDK for test code |
| aiohttp | ^3.9 | Async HTTP for API calls |
| pygithub | ^2.3 | GitHub API client |
| pyyaml | ^6.0 | YAML parsing (serverless.yml) |
| cf2tf | ^0.7 | CloudFormation conversion |
| pytest | ^8.0 | Testing framework |
| pytest-asyncio | ^0.24 | Async test support |
