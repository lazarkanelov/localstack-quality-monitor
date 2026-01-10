# Data Model: LocalStack Quality Monitor CLI

**Date**: 2026-01-10
**Branch**: 001-lsqm-cli

## Overview

This document defines the data structures used by LSQM. All data is stored as JSON files in the artifact repository.

---

## Entity Relationship Diagram

```
┌─────────────────┐     1:N     ┌─────────────────┐
│   Architecture  │─────────────│     TestApp     │
│                 │             │                 │
│ - hash (PK)     │             │ - arch_hash(FK) │
│ - source_url    │             │ - generated_at  │
│ - services[]    │             │ - files{}       │
│ - resource_count│             │ - token_usage   │
└─────────────────┘             └─────────────────┘
        │
        │ N:M
        ▼
┌─────────────────┐
│ ValidationResult│
│                 │
│ - run_id (FK)   │◄────────────┐
│ - arch_hash(FK) │             │
│ - status        │             │
│ - duration      │             │
└─────────────────┘             │
        │                       │
        │                       │ 1:N
        ▼                       │
┌─────────────────┐     ┌───────────────┐
│   Regression    │     │      Run      │
│                 │     │               │
│ - arch_hash     │     │ - run_id (PK) │
│ - from_run_id   │     │ - timestamp   │
│ - to_run_id     │     │ - config      │
│ - from_status   │     │ - ls_version  │
│ - to_status     │     │ - summary     │
└─────────────────┘     └───────────────┘
                              │
                              │ aggregates
                              ▼
                        ┌─────────────────┐
                        │  ServiceTrend   │
                        │                 │
                        │ - service_name  │
                        │ - run_history[] │
                        │ - pass_rate     │
                        └─────────────────┘
```

---

## Entity Definitions

### Architecture

Represents a discovered AWS infrastructure pattern.

**Storage**: `architectures/{hash}/metadata.json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| hash | string | Yes | Content-based SHA-256 hash (16 chars) |
| source_url | string | Yes | Original URL where discovered |
| source_type | enum | Yes | "terraform_registry" \| "github" \| "serverless" \| "cdk" |
| discovered_at | datetime | Yes | ISO 8601 timestamp |
| services | string[] | Yes | AWS services used (e.g., ["lambda", "s3", "dynamodb"]) |
| resource_count | integer | Yes | Number of Terraform resources |
| name | string | No | Human-readable name from source |
| description | string | No | Description from source |
| version | string | No | Version tag if applicable |
| skipped | boolean | No | True if skipped due to unsupported services |
| skip_reason | string | No | Reason for skipping |

**Example**:
```json
{
  "hash": "a1b2c3d4e5f67890",
  "source_url": "https://registry.terraform.io/modules/terraform-aws-modules/vpc/aws/5.1.0",
  "source_type": "terraform_registry",
  "discovered_at": "2026-01-10T00:00:00Z",
  "services": ["ec2", "vpc"],
  "resource_count": 23,
  "name": "terraform-aws-vpc",
  "description": "Terraform module for creating AWS VPC resources",
  "version": "5.1.0",
  "skipped": false
}
```

**Validation Rules**:
- `hash` must be exactly 16 hexadecimal characters
- `source_url` must be valid URL
- `services` must contain at least one service
- `resource_count` must be positive integer

**State Transitions**:
- `discovered` → `skipped` (if uses unsupported services)
- `discovered` → `ready` (has Terraform files, awaits test generation)
- `ready` → `has_app` (test app generated)

---

### TestApp

Generated Python test application for an architecture.

**Storage**: `apps/{arch_hash}/`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| arch_hash | string | Yes | Reference to Architecture.hash |
| generated_at | datetime | Yes | ISO 8601 timestamp |
| generator_version | string | Yes | LSQM version that generated |
| model_used | string | Yes | Claude model identifier |
| input_tokens | integer | Yes | Tokens used for prompt |
| output_tokens | integer | Yes | Tokens used for response |
| files | object | Yes | Map of filename → content |

**Files Structure**:
```
apps/{arch_hash}/
├── generated_at.json    # Metadata above
├── conftest.py          # pytest fixtures
├── app.py               # Application code
├── test_app.py          # pytest tests
└── requirements.txt     # Python dependencies
```

**Example (generated_at.json)**:
```json
{
  "arch_hash": "a1b2c3d4e5f67890",
  "generated_at": "2026-01-10T01:30:00Z",
  "generator_version": "1.0.0",
  "model_used": "claude-sonnet-4-20250514",
  "input_tokens": 2500,
  "output_tokens": 4200
}
```

**Validation Rules**:
- All four Python files must exist
- Each file must pass Python syntax validation
- `requirements.txt` must include `boto3` and `pytest`

---

### Run

A single pipeline execution.

**Storage**: `runs/{run_id}/`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| run_id | string | Yes | UUID v4 identifier |
| started_at | datetime | Yes | Pipeline start time |
| completed_at | datetime | No | Pipeline end time |
| localstack_version | string | Yes | Pinned LocalStack version |
| lsqm_version | string | Yes | LSQM version |
| config | object | Yes | Runtime configuration snapshot |
| summary | object | Yes | Aggregate results |

**Config Object**:
```json
{
  "parallel": 4,
  "timeout": 300,
  "token_budget": 500000,
  "dry_run": false
}
```

**Summary Object**:
```json
{
  "total": 150,
  "passed": 120,
  "partial": 10,
  "failed": 15,
  "timeout": 3,
  "error": 2,
  "new_architectures": 12,
  "tokens_used": 125000,
  "duration_seconds": 7200
}
```

**Files Structure**:
```
runs/{run_id}/
├── config.json           # Full config snapshot
├── summary.json          # Aggregate results
├── localstack_version.txt
└── results/
    ├── {arch_hash_1}.json
    ├── {arch_hash_2}.json
    └── ...
```

**Validation Rules**:
- `run_id` must be valid UUID v4
- `summary.total` = sum of all status counts
- `completed_at` must be after `started_at`

---

### ValidationResult

Outcome of validating one architecture in a run.

**Storage**: `runs/{run_id}/results/{arch_hash}.json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| arch_hash | string | Yes | Reference to Architecture.hash |
| run_id | string | Yes | Reference to Run.run_id |
| status | enum | Yes | "PASSED" \| "PARTIAL" \| "FAILED" \| "TIMEOUT" \| "ERROR" |
| started_at | datetime | Yes | Validation start time |
| completed_at | datetime | Yes | Validation end time |
| duration_seconds | float | Yes | Total validation time |
| terraform_apply | object | No | Terraform apply output |
| pytest_results | object | No | pytest execution results |
| container_logs | string | No | LocalStack container logs |
| error_message | string | No | Error details if status is ERROR |

**Status Definitions**:
| Status | Definition |
|--------|------------|
| PASSED | All pytest tests pass |
| PARTIAL | Some tests pass, some fail |
| FAILED | All tests fail or terraform apply fails |
| TIMEOUT | Exceeded timeout (300s default) |
| ERROR | Infrastructure error (container, network, etc.) |

**Terraform Apply Object**:
```json
{
  "success": true,
  "resources_created": 5,
  "outputs": {"vpc_id": "vpc-12345", "subnet_ids": ["subnet-a", "subnet-b"]},
  "logs": "..."
}
```

**Pytest Results Object**:
```json
{
  "total": 5,
  "passed": 4,
  "failed": 1,
  "skipped": 0,
  "output": "..."
}
```

**Validation Rules**:
- `duration_seconds` must be positive
- If `status` is ERROR, `error_message` is required
- If `status` is PASSED/PARTIAL/FAILED, `pytest_results` is required

---

### Regression

Records a compatibility regression between runs.

**Storage**: `trends/regressions.json` (array)

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| arch_hash | string | Yes | Affected architecture |
| architecture_name | string | No | Human-readable name |
| from_run_id | string | Yes | Previous run (was passing) |
| to_run_id | string | Yes | Current run (now failing) |
| from_status | enum | Yes | Previous status (PASSED/PARTIAL) |
| to_status | enum | Yes | Current status (FAILED/TIMEOUT/ERROR) |
| detected_at | datetime | Yes | When regression was detected |
| services_affected | string[] | Yes | AWS services in architecture |
| github_issue_url | string | No | Created issue URL |

**Example**:
```json
{
  "arch_hash": "a1b2c3d4e5f67890",
  "architecture_name": "terraform-aws-vpc",
  "from_run_id": "550e8400-e29b-41d4-a716-446655440000",
  "to_run_id": "550e8400-e29b-41d4-a716-446655440001",
  "from_status": "PASSED",
  "to_status": "FAILED",
  "detected_at": "2026-01-10T03:00:00Z",
  "services_affected": ["ec2", "vpc"],
  "github_issue_url": "https://github.com/localstack/localstack/issues/12345"
}
```

**Validation Rules**:
- `from_status` must be PASSED or PARTIAL
- `to_status` must be FAILED, TIMEOUT, or ERROR
- Both run_ids must exist

---

### ServiceTrend

Aggregated compatibility statistics per AWS service.

**Storage**: `trends/services.json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| service_name | string | Yes | AWS service identifier |
| current_pass_rate | float | Yes | Pass rate in latest run (0.0-1.0) |
| previous_pass_rate | float | No | Pass rate in previous run |
| trend | enum | Yes | "improving" \| "stable" \| "declining" |
| architecture_count | integer | Yes | Number of architectures using service |
| history | object[] | Yes | Last 12 runs data |

**History Entry**:
```json
{
  "run_id": "...",
  "run_date": "2026-01-10",
  "total": 25,
  "passed": 20,
  "pass_rate": 0.8
}
```

**Example**:
```json
{
  "service_name": "lambda",
  "current_pass_rate": 0.85,
  "previous_pass_rate": 0.82,
  "trend": "improving",
  "architecture_count": 45,
  "history": [
    {"run_id": "...", "run_date": "2026-01-10", "total": 45, "passed": 38, "pass_rate": 0.85},
    {"run_id": "...", "run_date": "2026-01-03", "total": 42, "passed": 34, "pass_rate": 0.82}
  ]
}
```

**Trend Calculation**:
- `improving`: current_pass_rate > previous_pass_rate + 0.02
- `declining`: current_pass_rate < previous_pass_rate - 0.02
- `stable`: otherwise

---

## Index Files

### architectures/index.json

Master index of all discovered architectures.

```json
{
  "version": 1,
  "last_updated": "2026-01-10T03:00:00Z",
  "count": 150,
  "architectures": {
    "a1b2c3d4e5f67890": {
      "source_url": "...",
      "source_type": "terraform_registry",
      "discovered_at": "2026-01-10T00:00:00Z",
      "has_app": true,
      "last_validated": "2026-01-10T02:00:00Z",
      "last_status": "PASSED"
    }
  }
}
```

### trends/architectures.json

Architecture-level trend data.

```json
{
  "version": 1,
  "last_updated": "2026-01-10T03:00:00Z",
  "architectures": {
    "a1b2c3d4e5f67890": {
      "name": "terraform-aws-vpc",
      "current_status": "PASSED",
      "streak": 5,
      "history": [
        {"run_id": "...", "status": "PASSED"},
        {"run_id": "...", "status": "PASSED"}
      ]
    }
  }
}
```

---

## Data Retention

Per clarification (FR-066, FR-067):
- Retain last 52 runs (1 year of weekly data)
- Older runs deleted during push stage
- Architecture and app data retained indefinitely (deduplication prevents growth)
- Trend history limited to 12 data points per service/architecture
