# Feature Specification: LocalStack Quality Monitor CLI

**Feature Branch**: `001-lsqm-cli`
**Created**: 2026-01-10
**Status**: Draft
**Input**: Build a CLI tool called `lsqm` that runs weekly via GitHub Actions to discover AWS infrastructure patterns, generate Python test applications using Claude API, validate them against LocalStack, and generate compatibility reports with regression detection.

## Clarifications

### Session 2026-01-10

- Q: What structured telemetry should the pipeline emit during execution? → A: Structured JSON logs with stage timing and error context
- Q: How long should historical run data be retained in the artifact repository? → A: Keep last 52 runs (1 year of weekly data)
- Q: Should architectures be filtered by complexity before validation? → A: Skip architectures using services not in LocalStack's supported list

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Weekly Automated Pipeline Execution (Priority: P1)

As an Engineering Manager, I want the system to automatically run every week to discover new AWS patterns, validate them against LocalStack, and push results to a repository so that I have continuous visibility into LocalStack compatibility without manual intervention.

**Why this priority**: This is the core value proposition - unattended automated monitoring that feeds into engineering prioritization. Without this, the entire system has no purpose.

**Independent Test**: Can be fully tested by running `lsqm run` command end-to-end and verifying artifacts are produced and pushed to the repository.

**Acceptance Scenarios**:

1. **Given** a scheduled GitHub Actions workflow, **When** Sunday 00:00 UTC arrives, **Then** the pipeline executes all stages (sync, mine, generate, validate, report, push, notify) automatically
2. **Given** a running pipeline, **When** one architecture validation fails, **Then** the pipeline continues processing remaining architectures and records partial results
3. **Given** a completed pipeline run, **When** results are generated, **Then** all artifacts are pushed to the configured artifact repository
4. **Given** any regressions detected, **When** the pipeline completes, **Then** GitHub issues are created and Slack notification is sent

---

### User Story 2 - Architecture Discovery and Incremental Growth (Priority: P2)

As an Engineering Manager, I want the system to continuously discover NEW AWS infrastructure patterns from public sources so that our test corpus grows over time and catches edge cases that static tests miss.

**Why this priority**: Continuous discovery is essential for expanding coverage. The system must find new patterns each week to remain valuable.

**Independent Test**: Can be tested by running `lsqm mine` and verifying new architectures are discovered, deduplicated by content hash, and not re-downloading existing ones.

**Acceptance Scenarios**:

1. **Given** an empty architecture index, **When** `lsqm mine` runs for the first time, **Then** at least 50 unique architectures are discovered
2. **Given** an existing architecture index, **When** `lsqm mine` runs, **Then** only NEW architectures not already in the index are processed
3. **Given** the same architecture appears in multiple sources, **When** content hash is computed, **Then** duplicates are detected and skipped
4. **Given** CloudFormation or Serverless templates, **When** discovered, **Then** they are normalized to Terraform format
5. **Given** a discovered architecture, **When** processed, **Then** metadata is extracted including AWS services used, resource count, and source URL

---

### User Story 3 - Test Application Generation via AI (Priority: P3)

As an Engineering Manager, I want Python test applications to be automatically generated for each architecture using AI so that I can validate LocalStack compatibility without manual test writing.

**Why this priority**: AI-generated tests enable scaling validation to hundreds of architectures. Manual test writing would be prohibitive.

**Independent Test**: Can be tested by running `lsqm generate` on architectures without apps and verifying valid Python files are produced.

**Acceptance Scenarios**:

1. **Given** an architecture without a test app, **When** `lsqm generate` runs, **Then** conftest.py, app.py, test_app.py, and requirements.txt are generated
2. **Given** generated Python code, **When** validated, **Then** syntax is verified before saving
3. **Given** an architecture with an existing test app, **When** `lsqm generate` runs, **Then** the existing app is skipped
4. **Given** a token budget (default 500,000), **When** exceeded, **Then** generation stops and reports budget exhaustion
5. **Given** generated test code, **When** executed, **Then** boto3 is configured to use LocalStack endpoint from environment

---

### User Story 4 - LocalStack Validation Execution (Priority: P4)

As an Engineering Manager, I want each architecture validated against LocalStack in isolation so that results reflect true compatibility without cross-test interference.

**Why this priority**: Isolated validation ensures reliable, reproducible results that can be trusted for engineering decisions.

**Independent Test**: Can be tested by running `lsqm validate` and verifying each architecture runs in its own container with proper cleanup.

**Acceptance Scenarios**:

1. **Given** an architecture with a test app, **When** `lsqm validate` runs, **Then** a fresh LocalStack container starts on a unique port
2. **Given** a running LocalStack container, **When** validation begins, **Then** health check at `/_localstack/health` passes first
3. **Given** Terraform configuration, **When** applied, **Then** tflocal init and tflocal apply execute with auto-approve
4. **Given** pytest tests, **When** executed, **Then** 60-second timeout is enforced per test
5. **Given** validation completion, **When** cleanup runs, **Then** tflocal destroy executes, container stops, and temp directory is removed
6. **Given** multiple validations, **When** parallel execution enabled, **Then** up to 4 concurrent validations run without interference
7. **Given** a validation result, **When** recorded, **Then** status is one of: PASSED, PARTIAL, FAILED, TIMEOUT, or ERROR

---

### User Story 5 - Compatibility Reporting and Dashboard (Priority: P5)

As an Engineering Manager, I want an HTML dashboard showing compatibility status, trends, and regression alerts so that I can quickly assess LocalStack health and prioritize fixes.

**Why this priority**: Actionable reporting enables data-driven engineering decisions. Without visualization, raw data has limited value.

**Independent Test**: Can be tested by running `lsqm report` and opening the generated HTML file in a browser.

**Acceptance Scenarios**:

1. **Given** validation results, **When** `lsqm report` runs, **Then** summary shows total, passed, partial, failed, and timeout counts
2. **Given** detected regressions, **When** report generates, **Then** red banner alert appears prominently
3. **Given** historical run data, **When** report generates, **Then** trend charts show last 12 runs
4. **Given** service-level data, **When** displayed, **Then** compatibility matrix shows pass rates and trends per AWS service
5. **Given** failed validations, **When** expanded, **Then** detailed logs are visible
6. **Given** the generated report, **When** loaded in browser, **Then** renders in under 2 seconds

---

### User Story 6 - Regression Detection and Alerting (Priority: P6)

As an Engineering Manager, I want immediate notification when a previously-passing architecture starts failing so that I can respond quickly to LocalStack regressions.

**Why this priority**: Regression detection is the primary mechanism for catching LocalStack breaking changes early.

**Independent Test**: Can be tested by running `lsqm compare` between two runs and verifying correct identification of regressions and fixes.

**Acceptance Scenarios**:

1. **Given** two run results, **When** `lsqm compare` executes, **Then** regressions (was passing, now failing) are identified
2. **Given** two run results, **When** `lsqm compare` executes, **Then** fixes (was failing, now passing) are identified
3. **Given** regressions detected, **When** comparison completes, **Then** exit code is 1 for CI integration
4. **Given** regressions detected, **When** push stage runs, **Then** GitHub issues are created in the configured repository
5. **Given** a Slack webhook configured, **When** regressions exist, **Then** notification includes regression alert and link to report

---

### User Story 7 - Manual Pipeline Control (Priority: P7)

As a Developer, I want to run individual pipeline stages manually so that I can debug issues, test changes, and run partial pipelines.

**Why this priority**: Developer experience for debugging and local development. Not critical for automated operation but essential for maintenance.

**Independent Test**: Can be tested by running each subcommand individually and verifying it completes its stage independently.

**Acceptance Scenarios**:

1. **Given** CLI installed, **When** `lsqm sync` runs, **Then** artifact repository is cloned/pulled and index loaded
2. **Given** local cache, **When** `lsqm status` runs, **Then** statistics about architectures, apps, and runs are displayed
3. **Given** stale containers, **When** `lsqm clean` runs, **Then** local cache is cleared and containers removed
4. **Given** `--dry-run` flag, **When** any command runs, **Then** actions are displayed without execution
5. **Given** `--verbose` flag, **When** any command runs, **Then** detailed logging is output
6. **Given** `--parallel N` flag, **When** validation runs, **Then** concurrency level is set to N

---

### Edge Cases

- What happens when the artifact repository is empty on first run? System initializes all index files and directories.
- What happens when GitHub API rate limits are hit during mining? System retries with exponential backoff, then continues with remaining sources.
- What happens when LocalStack container fails to start? Validation is marked as ERROR with container logs captured.
- What happens when Terraform apply hangs indefinitely? Timeout is enforced (default 300s) and validation marked as TIMEOUT.
- What happens when Claude API returns malformed code? Syntax validation fails, app is not saved, architecture is skipped for this run.
- What happens when multiple pipeline runs overlap? Each run uses unique run_id; parallel runs operate on separate artifacts.
- What happens when network connectivity is lost mid-validation? Error is captured, partial results saved, pipeline continues.

## Requirements *(mandatory)*

### Functional Requirements

**CLI Interface**

- **FR-001**: System MUST provide a command-line interface named `lsqm` with subcommands: sync, mine, generate, validate, report, push, notify, run, compare, status, clean
- **FR-002**: System MUST support global flags: `--config PATH`, `--verbose/-v`, `--dry-run`, `--parallel N`, `--localstack-version VERSION`
- **FR-003**: System MUST execute full pipeline when `lsqm run` is invoked

**Sync Stage**

- **FR-004**: System MUST clone or pull the configured artifact repository before any other operation
- **FR-005**: System MUST load `architectures/index.json` into local cache
- **FR-006**: System MUST load latest run results for comparison baseline

**Mine Stage**

- **FR-007**: System MUST discover architectures from Terraform Registry (VPC, Lambda, S3, DynamoDB, SQS, SNS, API Gateway, Step Functions modules)
- **FR-008**: System MUST discover architectures from GitHub organizations: aws-quickstart, aws-solutions, aws-samples
- **FR-009**: System MUST discover architectures from serverless/examples repository
- **FR-010**: System MUST discover architectures from aws-samples/aws-cdk-examples
- **FR-011**: System MUST skip architectures already present in index.json by source URL
- **FR-012**: System MUST normalize CloudFormation templates to Terraform format
- **FR-013**: System MUST normalize Serverless Framework templates to Terraform format
- **FR-014**: System MUST compute content hash for deduplication
- **FR-015**: System MUST extract metadata: AWS services, resource count, source URL
- **FR-068**: System MUST maintain a list of LocalStack-supported AWS services
- **FR-069**: System MUST skip architectures that use AWS services not in LocalStack's supported list
- **FR-070**: System MUST record skipped architectures with reason (unsupported services) in metadata

**Generate Stage**

- **FR-016**: System MUST check if `apps/{hash}/` exists and skip if current
- **FR-017**: System MUST call Claude API with Terraform content to generate test code
- **FR-018**: System MUST generate: conftest.py, app.py, test_app.py, requirements.txt
- **FR-019**: System MUST configure boto3 for LocalStack endpoint from environment
- **FR-020**: System MUST validate Python syntax before saving generated code
- **FR-021**: System MUST track token usage against configured budget (default 500,000)
- **FR-022**: System MUST stop generation when token budget is exhausted

**Validate Stage**

- **FR-023**: System MUST create temporary directory with Terraform and app files
- **FR-024**: System MUST start LocalStack container on unique port per validation
- **FR-025**: System MUST wait for health check at `/_localstack/health` before proceeding
- **FR-026**: System MUST run tflocal init and tflocal apply with auto-approve
- **FR-027**: System MUST run pytest with 60-second timeout per test
- **FR-028**: System MUST capture terraform output, pytest output, and container logs
- **FR-029**: System MUST cleanup: tflocal destroy, stop container, remove temp directory
- **FR-030**: System MUST record status as: PASSED, PARTIAL, FAILED, TIMEOUT, or ERROR
- **FR-031**: System MUST support parallel execution with configurable concurrency (default 4)

**Report Stage**

- **FR-032**: System MUST generate HTML dashboard with summary statistics
- **FR-033**: System MUST display regression alerts with red banner when detected
- **FR-034**: System MUST show service compatibility matrix with pass rates and trends
- **FR-035**: System MUST display historical trend charts for last 12 runs
- **FR-036**: System MUST provide sortable architecture results table
- **FR-037**: System MUST provide expandable failure details with logs
- **FR-038**: System MUST generate single self-contained HTML file

**Push Stage**

- **FR-039**: System MUST update `architectures/index.json` with new architectures
- **FR-040**: System MUST add new architecture and app directories
- **FR-041**: System MUST create `runs/{run_id}/` with all results
- **FR-042**: System MUST update `reports/latest/` with current report
- **FR-043**: System MUST update `trends/*.json` files
- **FR-044**: System MUST commit with descriptive summary message
- **FR-045**: System MUST create GitHub issues for regressions in configured repository
- **FR-066**: System MUST retain only the last 52 runs in the artifact repository (1 year of weekly data)
- **FR-067**: System MUST delete runs older than the retention limit during push stage

**Notify Stage**

- **FR-046**: System MUST send Slack webhook with results summary
- **FR-047**: System MUST include pass rate with delta from last run
- **FR-048**: System MUST include new architectures count
- **FR-049**: System MUST include regression alert if any detected
- **FR-050**: System MUST include link to report

**Compare Stage**

- **FR-051**: System MUST detect regressions (was passing, now failing)
- **FR-052**: System MUST detect fixes (was failing, now passing)
- **FR-053**: System MUST exit with code 1 if regressions detected

**Observability**

- **FR-063**: System MUST emit structured JSON logs for all pipeline stages
- **FR-064**: System MUST include stage timing (start, end, duration) in log output
- **FR-065**: System MUST include error context (error type, message, stack trace reference) in failure logs

**Configuration**

- **FR-054**: System MUST read ANTHROPIC_API_KEY from environment
- **FR-055**: System MUST read GITHUB_TOKEN from environment
- **FR-056**: System MUST read ARTIFACT_REPO from environment
- **FR-057**: System MUST support optional ANTHROPIC_TOKEN_BUDGET (default 500,000)
- **FR-058**: System MUST support optional LOCALSTACK_VERSION (default latest)
- **FR-059**: System MUST support optional LSQM_PARALLEL (default 4)
- **FR-060**: System MUST support optional LSQM_TIMEOUT (default 300)
- **FR-061**: System MUST support optional SLACK_WEBHOOK_URL
- **FR-062**: System MUST support optional ISSUE_REPO (default localstack/localstack)

### Key Entities

- **Architecture**: A discovered AWS infrastructure pattern with content hash, source URL, Terraform files, metadata (services used, resource count), and discovery timestamp
- **TestApp**: Generated Python test code for an architecture including conftest.py, app.py, test_app.py, requirements.txt, and generation metadata
- **Run**: A single pipeline execution with unique ID, timestamp, configuration snapshot, LocalStack version, and collection of validation results
- **ValidationResult**: Outcome of validating one architecture including status, duration, terraform output, pytest output, container logs, and any errors
- **Regression**: A change in status from passing to failing between two runs, referencing the architecture and both run IDs
- **ServiceTrend**: Aggregated compatibility statistics per AWS service over time

## Assumptions

- Terraform and tflocal are available in the execution environment
- Docker is available and the user has permission to start containers
- Network access to GitHub, Terraform Registry, and Claude API is available
- GitHub Actions provides sufficient compute for parallel validation (4 concurrent by default)
- LocalStack container images are available from Docker Hub
- Standard OAuth2/token-based authentication is used for GitHub operations

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: System discovers at least 50 unique architectures on the first run
- **SC-002**: System adds at least 10 new architectures per weekly run on average
- **SC-003**: AI generates working test applications for more than 80% of architectures
- **SC-004**: Full pipeline completes in under 3 hours
- **SC-005**: Zero false positive regressions (every reported regression is a genuine compatibility change)
- **SC-006**: Dashboard loads in browser in under 2 seconds
- **SC-007**: 100% of detected regressions result in trackable GitHub issues
- **SC-008**: Single architecture failure never halts the entire pipeline
- **SC-009**: All artifacts from each run are preserved in the repository for audit trail
- **SC-010**: Slack notification is sent within 5 minutes of pipeline completion when configured
