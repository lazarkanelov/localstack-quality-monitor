# CLI Interface Contract: lsqm

**Date**: 2026-01-10
**Version**: 1.0.0

## Overview

This document defines the command-line interface contract for the `lsqm` tool.

---

## Global Options

All subcommands inherit these options:

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--config` | | PATH | `~/.lsqm/config.yaml` | Configuration file path |
| `--verbose` | `-v` | FLAG | false | Enable verbose output |
| `--dry-run` | | FLAG | false | Show actions without executing |
| `--parallel` | `-p` | INT | 4 | Concurrency level |
| `--localstack-version` | | STRING | "latest" | LocalStack image version |

---

## Commands

### lsqm run

Execute the full pipeline.

**Usage**: `lsqm run [OPTIONS]`

**Options**: Global options only

**Exit Codes**:
| Code | Meaning |
|------|---------|
| 0 | Success, no regressions |
| 1 | Success, regressions detected |
| 2 | Partial success, some stages failed |
| 3 | Configuration error |
| 4 | Fatal error |

**Output** (JSON when `--verbose`):
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "stages": {
    "sync": {"status": "success", "duration": 5.2},
    "mine": {"status": "success", "new_architectures": 12, "duration": 120.5},
    "generate": {"status": "success", "apps_generated": 10, "tokens_used": 45000, "duration": 300.0},
    "validate": {"status": "success", "passed": 120, "failed": 5, "duration": 3600.0},
    "report": {"status": "success", "path": "reports/latest/index.html", "duration": 2.1},
    "push": {"status": "success", "commits": 1, "duration": 15.3},
    "notify": {"status": "success", "duration": 0.5}
  },
  "summary": {
    "total_architectures": 150,
    "passed": 120,
    "regressions": 2
  }
}
```

---

### lsqm sync

Pull existing artifacts from GitHub repository.

**Usage**: `lsqm sync [OPTIONS]`

**Options**:
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--force` | FLAG | false | Force fresh clone |

**Exit Codes**:
| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Repository not configured |
| 2 | Clone/pull failed |

**Output**:
```
Syncing artifact repository...
Repository: localstack/quality-monitor-artifacts
Architectures loaded: 138
Latest run: 2026-01-03T00:00:00Z (run_550e8400)
Sync complete.
```

---

### lsqm mine

Discover new infrastructure templates.

**Usage**: `lsqm mine [OPTIONS]`

**Options**:
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--source` | STRING[] | all | Sources to mine (terraform_registry, github, serverless, cdk) |
| `--limit` | INT | 0 | Max architectures to discover (0=unlimited) |

**Exit Codes**:
| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | No new architectures found |
| 2 | All sources failed |

**Output**:
```
Mining new architectures...
  Terraform Registry: 5 new
  GitHub (aws-quickstart): 3 new
  GitHub (aws-solutions): 2 new
  GitHub (aws-samples): 1 new
  Serverless Examples: 1 new
  CDK Examples: 0 new
Total: 12 new architectures discovered
Skipped: 3 (unsupported services)
```

---

### lsqm generate

Generate Python test applications using Claude API.

**Usage**: `lsqm generate [OPTIONS]`

**Options**:
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--budget` | INT | 500000 | Token budget |
| `--arch` | STRING | | Generate for specific architecture hash |
| `--force` | FLAG | false | Regenerate existing apps |

**Exit Codes**:
| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Budget exhausted |
| 2 | API error |

**Output**:
```
Generating test applications...
  [1/12] a1b2c3d4... terraform-aws-vpc: Generated (2500 tokens)
  [2/12] b2c3d4e5... terraform-aws-lambda: Generated (3200 tokens)
  ...
  [10/12] j0k1l2m3... Budget exhausted
Generated: 10 apps
Tokens used: 485000 / 500000
Remaining: 2 architectures
```

---

### lsqm validate

Run validations against LocalStack.

**Usage**: `lsqm validate [OPTIONS]`

**Options**:
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--arch` | STRING | | Validate specific architecture |
| `--timeout` | INT | 300 | Timeout per validation (seconds) |
| `--keep-containers` | FLAG | false | Don't cleanup containers |

**Exit Codes**:
| Code | Meaning |
|------|---------|
| 0 | All passed |
| 1 | Some failed |
| 2 | All failed |

**Output**:
```
Validating architectures (parallel: 4)...
  [1/150] a1b2c3d4 terraform-aws-vpc: PASSED (45s)
  [2/150] b2c3d4e5 terraform-aws-lambda: FAILED (60s)
    └─ 2/5 tests failed
  [3/150] c3d4e5f6 terraform-aws-s3: TIMEOUT (300s)
  ...

Summary:
  Passed: 120
  Partial: 10
  Failed: 15
  Timeout: 3
  Error: 2
```

---

### lsqm report

Generate HTML compatibility dashboard.

**Usage**: `lsqm report [OPTIONS]`

**Options**:
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--output` | PATH | reports/latest | Output directory |
| `--run` | STRING | latest | Run ID to report on |

**Exit Codes**:
| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | No data available |

**Output**:
```
Generating compatibility report...
Run: 550e8400-e29b-41d4-a716-446655440000
Date: 2026-01-10T03:00:00Z

Report generated: reports/latest/index.html
  - Summary: 150 architectures, 80% pass rate
  - Regressions: 2 detected
  - Services: 35 tracked
```

---

### lsqm push

Push artifacts to GitHub repository.

**Usage**: `lsqm push [OPTIONS]`

**Options**:
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--skip-issues` | FLAG | false | Don't create GitHub issues |
| `--message` | STRING | auto | Custom commit message |

**Exit Codes**:
| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Nothing to push |
| 2 | Push failed |

**Output**:
```
Pushing artifacts...
  New architectures: 12
  Updated apps: 10
  New run: 550e8400
  Report: reports/latest/

Commit: 3a4b5c6 "Run 2026-01-10: 150 archs, 80% pass, 2 regressions"

Creating GitHub issues for regressions...
  Issue #12345: terraform-aws-vpc regression
  Issue #12346: terraform-aws-lambda regression

Push complete.
```

---

### lsqm notify

Send Slack notification.

**Usage**: `lsqm notify [OPTIONS]`

**Options**:
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--run` | STRING | latest | Run ID to notify about |
| `--webhook` | STRING | env | Override webhook URL |

**Exit Codes**:
| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Webhook not configured |
| 2 | Send failed |

**Output**:
```
Sending Slack notification...
  Channel: #localstack-quality
  Run: 550e8400
  Pass rate: 80% (+2% from last run)
  Regressions: 2

Notification sent.
```

---

### lsqm compare

Compare two runs and detect regressions.

**Usage**: `lsqm compare [OPTIONS] [RUN_ID]`

**Arguments**:
| Argument | Type | Default | Description |
|----------|------|---------|-------------|
| RUN_ID | STRING | previous | Run to compare current against |

**Options**:
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--current` | STRING | latest | Current run ID |
| `--format` | STRING | text | Output format (text, json) |

**Exit Codes**:
| Code | Meaning |
|------|---------|
| 0 | No regressions |
| 1 | Regressions detected |

**Output**:
```
Comparing runs...
  Current: 550e8400 (2026-01-10)
  Previous: 440d7300 (2026-01-03)

Regressions (2):
  - a1b2c3d4 terraform-aws-vpc: PASSED → FAILED
  - b2c3d4e5 terraform-aws-lambda: PASSED → TIMEOUT

Fixes (3):
  - c3d4e5f6 terraform-aws-s3: FAILED → PASSED
  - d4e5f6g7 terraform-aws-sqs: TIMEOUT → PASSED
  - e5f6g7h8 terraform-aws-sns: PARTIAL → PASSED

Summary: 2 regressions, 3 fixes
```

---

### lsqm status

Show current statistics.

**Usage**: `lsqm status [OPTIONS]`

**Options**:
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--format` | STRING | text | Output format (text, json) |

**Exit Codes**:
| Code | Meaning |
|------|---------|
| 0 | Success |

**Output**:
```
LocalStack Quality Monitor Status
=================================

Architectures:
  Total: 150
  With apps: 145
  Pending generation: 5

Runs:
  Total: 15
  Latest: 2026-01-10 (550e8400)
  Pass rate: 80%

Services tracked: 35
  Highest: dynamodb (95%)
  Lowest: stepfunctions (62%)

Token usage this month: 1,250,000 / 2,000,000
```

---

### lsqm clean

Remove local cache and stale containers.

**Usage**: `lsqm clean [OPTIONS]`

**Options**:
| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--containers` | FLAG | true | Remove stale LocalStack containers |
| `--cache` | FLAG | true | Remove local cache |
| `--all` | FLAG | false | Remove everything including repo clone |

**Exit Codes**:
| Code | Meaning |
|------|---------|
| 0 | Success |

**Output**:
```
Cleaning up...
  Removed 3 stale containers
  Cleared cache: 150MB freed

Clean complete.
```

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| ANTHROPIC_API_KEY | Yes | | Claude API key |
| GITHUB_TOKEN | Yes | | GitHub personal access token |
| ARTIFACT_REPO | Yes | | Artifact repository (owner/repo) |
| ANTHROPIC_TOKEN_BUDGET | No | 500000 | Monthly token budget |
| LOCALSTACK_VERSION | No | latest | Default LocalStack version |
| LSQM_PARALLEL | No | 4 | Default concurrency |
| LSQM_TIMEOUT | No | 300 | Default timeout (seconds) |
| SLACK_WEBHOOK_URL | No | | Slack webhook for notifications |
| ISSUE_REPO | No | localstack/localstack | Repo for regression issues |

---

## Configuration File

**Location**: `~/.lsqm/config.yaml` or `--config` path

```yaml
# LSQM Configuration

# API Keys (override env vars)
anthropic_api_key: ${ANTHROPIC_API_KEY}
github_token: ${GITHUB_TOKEN}

# Repositories
artifact_repo: localstack/quality-monitor-artifacts
issue_repo: localstack/localstack

# Execution
parallel: 4
timeout: 300
token_budget: 500000
localstack_version: latest

# Sources
sources:
  terraform_registry: true
  github_orgs:
    - aws-quickstart
    - aws-solutions
    - aws-samples
  serverless: true
  cdk: true

# Notifications
slack_webhook_url: ${SLACK_WEBHOOK_URL}

# Logging
log_level: INFO
log_format: json
```
