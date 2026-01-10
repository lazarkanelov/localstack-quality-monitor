"""Test application generator using Claude API."""

import ast
import json
import logging
import time
from pathlib import Path

from anthropic import Anthropic, APIConnectionError, APIError, RateLimitError

from lsqm import __version__

# Retry configuration for Claude API
MAX_RETRIES = 3
INITIAL_BACKOFF = 5  # seconds


# Prompt template for realistic application generation
GENERATION_PROMPT = """You are generating a realistic Python application that uses AWS infrastructure, designed to run against LocalStack for validation.

Given this Terraform configuration:
```hcl
{terraform_content}
```

The architecture uses these AWS services: {services}

## Your Task

Generate a **realistic application** that demonstrates actual business logic using this infrastructure - NOT just basic CRUD tests. The application should simulate how a real user would deploy and use this architecture.

### Examples of Realistic Applications:

**If the architecture has Lambda + S3 + DynamoDB:**
- Create a data processing pipeline: Lambda triggered by S3 upload, processes the data, stores results in DynamoDB
- Include functions that upload sample data, trigger processing, and verify results

**If the architecture has API Gateway + Lambda + RDS/DynamoDB:**
- Create a REST API backend: endpoints for CRUD operations on business entities
- Include functions that test the full request/response cycle

**If the architecture has SQS + Lambda + SNS:**
- Create an event-driven workflow: messages published to SQS, processed by Lambda, notifications sent via SNS
- Include functions that send messages and verify processing

**If the architecture has S3 + CloudFront/S3 static hosting:**
- Create a static site deployment test: upload assets, verify accessibility
- Include functions that test content serving

## Required Files

Generate these files:

### 1. conftest.py
```python
# Pytest fixtures with boto3 clients for LocalStack
# - Use endpoint_url from LOCALSTACK_ENDPOINT env var (default: http://localhost:4566)
# - Create fixtures for each AWS service
# - Include any test data setup/teardown
```

### 2. app.py
```python
# Realistic application logic that uses the AWS infrastructure
# - Implement actual business workflows, not just wrapper functions
# - Simulate real-world usage patterns
# - Include proper error handling
# Examples based on services:
# - S3: upload/download files, process data streams
# - Lambda: invoke functions with real payloads, handle responses
# - DynamoDB: implement data models, queries, transactions
# - SQS: send messages, process queues
# - API Gateway: make HTTP requests through the gateway
```

### 3. test_app.py
```python
# Integration tests that validate the ENTIRE workflow
# - Test resource provisioning (resources exist after terraform apply)
# - Test the realistic application workflows end-to-end
# - Include data flow verification
# - At least 5-8 meaningful test cases covering:
#   1. Resource existence checks
#   2. Data upload/creation
#   3. Processing/transformation
#   4. Result verification
#   5. Error handling scenarios
#   6. Edge cases
```

### 4. requirements.txt
```
# All required Python packages
boto3
pytest
pytest-asyncio  # if async code is used
# Add any other packages needed
```

## Technical Requirements

1. **LocalStack Configuration:**
   - All boto3 clients must use: `endpoint_url=os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")`
   - Use `region_name="us-east-1"` for all clients
   - Use `aws_access_key_id="test"` and `aws_secret_access_key="test"` for LocalStack

2. **Resource Names:**
   - Extract resource names from the Terraform configuration
   - Use the EXACT names defined in Terraform (bucket names, table names, function names, etc.)

3. **Realistic Data:**
   - Use realistic sample data appropriate for the use case
   - Include proper data types and structures

4. **Code Quality:**
   - Use type hints
   - Include docstrings
   - Implement proper error handling
   - Use logging for debugging

5. **Standard AWS APIs Only:**
   - Do NOT use LocalStack-specific APIs or workarounds
   - Code should work identically against real AWS

## Output Format

Output ONLY a JSON object in this exact format (no markdown code blocks, no other text):
{{
  "conftest.py": "...",
  "app.py": "...",
  "test_app.py": "...",
  "requirements.txt": "..."
}}"""


def generate_test_apps(
    architectures: list[tuple[str, dict]],
    api_key: str,
    budget: int,
    artifacts_dir: Path,
    logger: logging.Logger | None = None,
) -> dict:
    """Generate test applications for architectures using Claude API.

    Args:
        architectures: List of (hash, arch_data) tuples
        api_key: Anthropic API key
        budget: Token budget
        artifacts_dir: Path to artifacts directory
        logger: Logger instance

    Returns:
        Dictionary with generation results
    """
    client = Anthropic(api_key=api_key)

    results = []
    tokens_used = 0
    generated_count = 0

    for arch_hash, arch_data in architectures:
        if tokens_used >= budget:
            break

        name = arch_data.get("name", arch_hash[:8])

        try:
            result = _generate_single_app(
                client=client,
                arch_hash=arch_hash,
                arch_data=arch_data,
                artifacts_dir=artifacts_dir,
                logger=logger,
            )

            tokens = result.get("tokens", 0)
            tokens_used += tokens

            if result.get("success"):
                generated_count += 1

            results.append({
                "hash": arch_hash,
                "name": name,
                "success": result.get("success", False),
                "tokens": tokens,
                "error": result.get("error"),
            })

        except Exception as e:
            if logger:
                logger.error(f"Generation failed for {arch_hash}: {e}")
            results.append({
                "hash": arch_hash,
                "name": name,
                "success": False,
                "tokens": 0,
                "error": str(e),
            })

    remaining = len(architectures) - len(results)

    return {
        "generated_count": generated_count,
        "tokens_used": tokens_used,
        "remaining": remaining,
        "results": results,
    }


def _generate_single_app(
    client: Anthropic,
    arch_hash: str,
    arch_data: dict,
    artifacts_dir: Path,
    logger: logging.Logger | None = None,
) -> dict:
    """Generate test app for a single architecture."""
    # Load Terraform content
    arch_dir = artifacts_dir / "architectures" / arch_hash
    tf_content = ""

    if arch_dir.exists():
        for tf_file in arch_dir.glob("*.tf"):
            with open(tf_file) as f:
                tf_content += f"\n# {tf_file.name}\n{f.read()}"
    else:
        # Use embedded terraform_files if available
        tf_files = arch_data.get("terraform_files", {})
        for name, content in tf_files.items():
            tf_content += f"\n# {name}\n{content}"

    if not tf_content:
        return {"success": False, "error": "No Terraform content found", "tokens": 0}

    services = arch_data.get("services", [])

    # Generate prompt
    prompt = GENERATION_PROMPT.format(
        terraform_content=tf_content[:15000],  # Limit content size
        services=", ".join(services),
    )

    # Retry loop for API calls
    retries = 0

    while retries < MAX_RETRIES:
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=16000,  # Increased for realistic application generation
                messages=[{"role": "user", "content": prompt}],
            )
            break  # Success

        except RateLimitError:
            retries += 1
            backoff = INITIAL_BACKOFF * (2 ** (retries - 1))
            if logger:
                logger.warning(f"Claude API rate limited, waiting {backoff}s (retry {retries}/{MAX_RETRIES})")
            if retries < MAX_RETRIES:
                time.sleep(backoff)
            else:
                return {"success": False, "error": f"Rate limit exceeded after {MAX_RETRIES} retries", "tokens": 0}

        except APIConnectionError as e:
            retries += 1
            backoff = INITIAL_BACKOFF * (2 ** (retries - 1))
            if logger:
                logger.warning(f"Claude API connection error, waiting {backoff}s (retry {retries}/{MAX_RETRIES})")
            if retries < MAX_RETRIES:
                time.sleep(backoff)
            else:
                return {"success": False, "error": f"Connection failed after {MAX_RETRIES} retries: {e}", "tokens": 0}

        except APIError as e:
            # Non-retryable API errors (e.g., invalid request, authentication)
            if logger:
                logger.error(f"Claude API error: {e}")
            return {"success": False, "error": f"API error: {e}", "tokens": 0}

    # Extract tokens used
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    total_tokens = input_tokens + output_tokens

    # Parse response
    content = response.content[0].text

    # Extract JSON from response
    files = _extract_files_from_response(content)
    if not files:
        return {
            "success": False,
            "error": "Failed to parse response",
            "tokens": total_tokens,
        }

    # Validate Python syntax
    for filename, code in files.items():
        if filename.endswith(".py"):
            valid, error = _validate_python_syntax(code)
            if not valid:
                return {
                    "success": False,
                    "error": f"Syntax error in {filename}: {error}",
                    "tokens": total_tokens,
                }

    # Save files using centralized function
    from datetime import datetime

    from lsqm.services.git_ops import mark_architecture_has_app, save_generated_app

    metadata = {
        "arch_hash": arch_hash,
        "arch_name": arch_data.get("name", ""),
        "services": arch_data.get("services", []),
        "generated_at": datetime.utcnow().isoformat(),
        "generator_version": __version__,
        "model_used": "claude-sonnet-4-20250514",
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "files_generated": list(files.keys()),
    }

    save_generated_app(
        arch_hash=arch_hash,
        files=files,
        metadata=metadata,
        artifacts_dir=artifacts_dir,
        logger=logger,
    )

    # Mark the architecture as having an app in the index
    mark_architecture_has_app(arch_hash, artifacts_dir, logger=logger)

    return {"success": True, "tokens": total_tokens}


def _extract_files_from_response(content: str) -> dict[str, str]:
    """Extract files dictionary from Claude response."""
    try:
        # Try to find JSON block
        start = content.find("{")
        end = content.rfind("}") + 1

        if start == -1 or end == 0:
            return {}

        json_str = content[start:end]
        files = json.loads(json_str)

        # Validate expected files
        required = {"conftest.py", "app.py", "test_app.py", "requirements.txt"}
        if not required.issubset(files.keys()):
            return {}

        return files

    except json.JSONDecodeError:
        return {}


def _validate_python_syntax(code: str) -> tuple[bool, str | None]:
    """Validate Python code syntax using ast.parse."""
    try:
        ast.parse(code)
        return True, None
    except SyntaxError as e:
        return False, f"Line {e.lineno}: {e.msg}"
