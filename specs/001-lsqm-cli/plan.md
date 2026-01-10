# Implementation Plan: LocalStack Quality Monitor CLI

**Branch**: `001-lsqm-cli` | **Date**: 2026-01-10 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-lsqm-cli/spec.md`

## Summary

Build a CLI tool (`lsqm`) that automatically discovers AWS infrastructure patterns from public sources, generates Python test applications using Claude API, validates them against LocalStack containers, and produces compatibility reports with regression detection. The tool runs weekly via GitHub Actions and pushes all artifacts to a dedicated repository.

## Technical Context

**Language/Version**: Python 3.11+ (mandated by constitution)
**Primary Dependencies**: Click (CLI), Docker SDK for Python (containers), Jinja2 (HTML reports), anthropic (Claude API), boto3 (AWS SDK), aiohttp (async HTTP)
**Storage**: JSON files in Git repository (architectures/index.json, runs/, trends/)
**Testing**: pytest with pytest-asyncio for async tests
**Target Platform**: Linux (GitHub Actions runners), macOS (local development)
**Project Type**: Single project (CLI tool)
**Performance Goals**: Full pipeline completes in <3 hours; dashboard loads in <2 seconds
**Constraints**: 4 concurrent validations default; 500K token budget; 300s timeout per validation
**Scale/Scope**: 50+ architectures first run; 10+ new per week; 52 runs retained

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Status |
|-----------|-------------|--------|
| I. Continuous Discovery | New architectures discovered incrementally; no re-downloading known patterns | [x] Pass - FR-011 skips known URLs; FR-014 deduplicates by hash |
| II. Regression Detection | Comparison against previous runs; alerts on regressions | [x] Pass - FR-051/052 detect regressions; FR-045 creates issues |
| III. AWS API Fidelity | Real boto3 calls; official AWS provider; no LocalStack workarounds | [x] Pass - FR-019 configures boto3; FR-026 uses tflocal with AWS provider |
| IV. Reproducibility | Content-hash deduplication; deterministic ordering; pinned versions | [x] Pass - FR-014 content hash; FR-058 pins LocalStack version |
| V. Isolation | Fresh container per validation; no shared state | [x] Pass - FR-024 unique port per container; FR-029 cleanup |
| VI. Graceful Degradation | Single failure cannot halt pipeline; partial results recorded | [x] Pass - Acceptance scenario 2 in US1; FR-030 records all statuses |
| VII. Budget Awareness | Token budgets enforced; caching used; skip unchanged | [x] Pass - FR-021/022 budget tracking; FR-016 skips existing apps |
| VIII. Operational Excellence | Unattended runs; Slack notifications; self-cleaning; clear logs | [x] Pass - FR-046-050 notifications; FR-063-065 structured logs |

## Project Structure

### Documentation (this feature)

```text
specs/001-lsqm-cli/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (CLI interface spec)
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
src/
├── lsqm/
│   ├── __init__.py
│   ├── cli.py              # Click CLI entry point
│   ├── commands/           # Subcommand implementations
│   │   ├── __init__.py
│   │   ├── sync.py
│   │   ├── mine.py
│   │   ├── generate.py
│   │   ├── validate.py
│   │   ├── report.py
│   │   ├── push.py
│   │   ├── notify.py
│   │   ├── compare.py
│   │   ├── status.py
│   │   ├── clean.py
│   │   └── run.py
│   ├── models/             # Data structures
│   │   ├── __init__.py
│   │   ├── architecture.py
│   │   ├── test_app.py
│   │   ├── run.py
│   │   ├── validation_result.py
│   │   └── regression.py
│   ├── services/           # Business logic
│   │   ├── __init__.py
│   │   ├── discovery/      # Mining sources
│   │   │   ├── __init__.py
│   │   │   ├── terraform_registry.py
│   │   │   ├── github_orgs.py
│   │   │   ├── serverless.py
│   │   │   └── cdk_examples.py
│   │   ├── normalizer.py   # CloudFormation/Serverless → Terraform
│   │   ├── generator.py    # Claude API test generation
│   │   ├── validator.py    # LocalStack container management
│   │   ├── reporter.py     # HTML dashboard generation
│   │   ├── notifier.py     # Slack webhook
│   │   └── git_ops.py      # GitHub operations
│   ├── templates/          # Jinja2 templates
│   │   └── report.html.j2
│   └── utils/
│       ├── __init__.py
│       ├── logging.py      # Structured JSON logging
│       ├── hashing.py      # Content hash computation
│       └── config.py       # Environment/config loading

tests/
├── conftest.py
├── unit/
│   ├── test_models.py
│   ├── test_hashing.py
│   └── test_normalizer.py
├── integration/
│   ├── test_discovery.py
│   ├── test_generator.py
│   └── test_validator.py
└── contract/
    └── test_cli_interface.py

.github/
└── workflows/
    └── weekly-run.yml      # Sunday 00:00 UTC schedule
```

**Structure Decision**: Single project layout with modular command structure. Each pipeline stage is a separate subcommand module under `commands/`. Discovery sources are isolated in `services/discovery/` for extensibility.

## Complexity Tracking

No constitution violations requiring justification.
