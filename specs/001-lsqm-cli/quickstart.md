# Quickstart: LocalStack Quality Monitor CLI

**Date**: 2026-01-10
**Branch**: 001-lsqm-cli

## Prerequisites

- Python 3.11+
- Docker (running)
- Terraform CLI
- tflocal (LocalStack Terraform wrapper)
- GitHub account with personal access token
- Anthropic API key

## Installation

```bash
# Clone the repository
git clone https://github.com/localstack/localstack-quality-monitor.git
cd localstack-quality-monitor

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -e .

# Verify installation
lsqm --version
```

## Configuration

### Environment Variables

```bash
# Required
export ANTHROPIC_API_KEY="sk-ant-..."
export GITHUB_TOKEN="ghp_..."
export ARTIFACT_REPO="your-org/quality-monitor-artifacts"

# Optional
export SLACK_WEBHOOK_URL="https://hooks.slack.com/..."
export LOCALSTACK_VERSION="3.0.0"
export LSQM_PARALLEL=4
export LSQM_TIMEOUT=300
```

### Create Artifact Repository

1. Create a new GitHub repository for artifacts
2. Initialize with a README
3. Set as `ARTIFACT_REPO`

## First Run

### Step 1: Sync (Initialize)

```bash
lsqm sync
```

Expected output:
```
Syncing artifact repository...
Repository: your-org/quality-monitor-artifacts
Initialized empty index.
Sync complete.
```

### Step 2: Mine Architectures

```bash
lsqm mine --limit 10
```

Expected output:
```
Mining new architectures...
  Terraform Registry: 5 new
  GitHub (aws-quickstart): 3 new
  GitHub (aws-samples): 2 new
Total: 10 new architectures discovered
```

### Step 3: Generate Test Apps

```bash
lsqm generate --budget 50000
```

Expected output:
```
Generating test applications...
  [1/10] a1b2c3d4... terraform-aws-vpc: Generated (2500 tokens)
  [2/10] b2c3d4e5... terraform-aws-lambda: Generated (3200 tokens)
  ...
Generated: 10 apps
Tokens used: 28000 / 50000
```

### Step 4: Validate

```bash
lsqm --parallel 2 validate
```

Expected output:
```
Validating architectures (parallel: 2)...
  [1/10] a1b2c3d4 terraform-aws-vpc: PASSED (45s)
  [2/10] b2c3d4e5 terraform-aws-lambda: PASSED (60s)
  ...

Summary:
  Passed: 8
  Partial: 1
  Failed: 1
```

### Step 5: Generate Report

```bash
lsqm report
```

Expected output:
```
Generating compatibility report...
Report generated: reports/latest/index.html
  - Summary: 10 architectures, 80% pass rate
```

Open `reports/latest/index.html` in a browser to view the dashboard.

### Step 6: Push Results

```bash
lsqm push
```

Expected output:
```
Pushing artifacts...
  New architectures: 10
  Updated apps: 10
  New run: 550e8400
Commit: 3a4b5c6 "Run 2026-01-10: 10 archs, 80% pass"
Push complete.
```

## Full Pipeline

Run all stages with a single command:

```bash
lsqm run
```

This executes: sync → mine → generate → validate → report → push → notify

## Dry Run Mode

Preview what would happen without making changes:

```bash
lsqm run --dry-run
```

## Verbose Mode

Get detailed logging:

```bash
lsqm run -v
```

## Validate Single Architecture

Test a specific architecture:

```bash
lsqm validate --arch a1b2c3d4
```

## Check Status

View current statistics:

```bash
lsqm status
```

## Cleanup

Remove local cache and stale containers:

```bash
lsqm clean
```

## GitHub Actions Setup

Add to `.github/workflows/weekly-run.yml`:

```yaml
name: Weekly Quality Monitor

on:
  schedule:
    - cron: '0 0 * * 0'  # Sunday at 00:00 UTC
  workflow_dispatch:  # Manual trigger

jobs:
  monitor:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Set up Terraform
        uses: hashicorp/setup-terraform@v3

      - name: Install tflocal
        run: pip install terraform-local

      - name: Install LSQM
        run: pip install -e .

      - name: Run Pipeline
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          ARTIFACT_REPO: ${{ github.repository_owner }}/quality-monitor-artifacts
          SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}
        run: lsqm run

      - name: Check for Regressions
        run: |
          if lsqm compare; then
            echo "No regressions detected"
          else
            echo "Regressions detected!"
            exit 1
          fi
```

## Troubleshooting

### Docker Not Running

```
Error: Cannot connect to Docker daemon
```

Solution: Start Docker Desktop or `sudo systemctl start docker`

### API Key Invalid

```
Error: Invalid API key
```

Solution: Verify `ANTHROPIC_API_KEY` is set correctly

### Rate Limited

```
Error: GitHub API rate limit exceeded
```

Solution: Wait 1 hour or use a different token

### Container Timeout

```
Validation timeout after 300s
```

Solution: Increase timeout with `--timeout 600` or check architecture complexity

### Stale Containers

```
Error: Port 4566 already in use
```

Solution: Run `lsqm clean --containers`

## Next Steps

1. Set up weekly GitHub Actions workflow
2. Configure Slack notifications
3. Review first report and identify patterns
4. Iterate on test generation prompts if needed
