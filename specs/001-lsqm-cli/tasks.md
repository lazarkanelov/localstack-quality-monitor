# Tasks: LocalStack Quality Monitor CLI

**Input**: Design documents from `/specs/001-lsqm-cli/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Tests are NOT explicitly requested in the feature specification. Test tasks are omitted.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/lsqm/`, `tests/` at repository root
- Per plan.md structure with commands/, models/, services/, utils/ subdirectories

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Create project directory structure per plan.md in src/lsqm/
- [x] T002 Initialize Python project with pyproject.toml including Click, Docker SDK, Jinja2, anthropic, boto3, aiohttp, PyGithub dependencies
- [x] T003 [P] Create src/lsqm/__init__.py with version info
- [x] T004 [P] Create tests/conftest.py with shared pytest fixtures
- [x] T005 [P] Configure ruff for linting in pyproject.toml
- [x] T006 [P] Create .github/workflows/weekly-run.yml with Sunday 00:00 UTC schedule

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Models (Shared Entities)

- [x] T007 [P] Create Architecture model with hash, source_url, services, resource_count fields in src/lsqm/models/architecture.py
- [x] T008 [P] Create TestApp model with arch_hash, generated_at, files, token_usage fields in src/lsqm/models/test_app.py
- [x] T009 [P] Create Run model with run_id, started_at, config, summary fields in src/lsqm/models/run.py
- [x] T010 [P] Create ValidationResult model with status enum (PASSED/PARTIAL/FAILED/TIMEOUT/ERROR) in src/lsqm/models/validation_result.py
- [x] T011 [P] Create Regression model with arch_hash, from_run_id, to_run_id, status change in src/lsqm/models/regression.py
- [x] T012 [P] Create ServiceTrend model with service_name, pass_rate, history in src/lsqm/models/service_trend.py
- [x] T013 Create models __init__.py exporting all models in src/lsqm/models/__init__.py

### Utilities (Shared Infrastructure)

- [x] T014 [P] Implement structured JSON logging with stage timing in src/lsqm/utils/logging.py
- [x] T015 [P] Implement content hash computation (SHA-256, 16 chars) in src/lsqm/utils/hashing.py
- [x] T016 [P] Implement config loading from environment and YAML file in src/lsqm/utils/config.py
- [x] T017 Create utils __init__.py exporting utilities in src/lsqm/utils/__init__.py

### CLI Framework

- [x] T018 Create Click CLI entry point with global options (--config, --verbose, --dry-run, --parallel, --localstack-version) in src/lsqm/cli.py
- [x] T019 Create commands __init__.py with command group registration in src/lsqm/commands/__init__.py
- [x] T020 Add console_scripts entry point 'lsqm' in pyproject.toml

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Weekly Automated Pipeline Execution (Priority: P1) 🎯 MVP

**Goal**: Execute full pipeline automatically: sync → mine → generate → validate → report → push → notify

**Independent Test**: Run `lsqm run` end-to-end and verify artifacts are produced and pushed

### Implementation for User Story 1

- [x] T021 [US1] Implement run command orchestrating all stages in src/lsqm/commands/run.py
- [x] T022 [US1] Add graceful degradation: continue on single architecture failure in src/lsqm/commands/run.py
- [x] T023 [US1] Add stage timing and structured logging to run command in src/lsqm/commands/run.py
- [x] T024 [US1] Implement exit codes per CLI contract (0=success, 1=regressions, 2=partial, 3=config, 4=fatal) in src/lsqm/commands/run.py
- [x] T025 [US1] Update weekly-run.yml to install lsqm and execute `lsqm run` in .github/workflows/weekly-run.yml

**Checkpoint**: `lsqm run` executes all stages; single failures don't halt pipeline

---

## Phase 4: User Story 2 - Architecture Discovery and Incremental Growth (Priority: P2)

**Goal**: Discover NEW architectures from public sources, deduplicate, normalize to Terraform

**Independent Test**: Run `lsqm mine` and verify new architectures discovered, existing ones skipped

### Discovery Services

- [x] T026 [P] [US2] Create base discovery interface in src/lsqm/services/discovery/__init__.py
- [x] T027 [P] [US2] Implement Terraform Registry discovery with module search API in src/lsqm/services/discovery/terraform_registry.py
- [x] T028 [P] [US2] Implement GitHub organization discovery (aws-quickstart, aws-solutions, aws-samples) in src/lsqm/services/discovery/github_orgs.py
- [x] T029 [P] [US2] Implement Serverless Framework examples discovery in src/lsqm/services/discovery/serverless.py
- [x] T030 [P] [US2] Implement AWS CDK examples discovery in src/lsqm/services/discovery/cdk_examples.py

### Normalization

- [x] T031 [US2] Implement CloudFormation to Terraform conversion using cf2tf in src/lsqm/services/normalizer.py
- [x] T032 [US2] Implement Serverless Framework to Terraform conversion in src/lsqm/services/normalizer.py
- [x] T033 [US2] Add LocalStack supported services list for filtering in src/lsqm/services/localstack_services.py
- [x] T034 [US2] Implement service extraction from Terraform resource types in src/lsqm/services/normalizer.py

### Mine Command

- [x] T035 [US2] Implement mine command with --source and --limit options in src/lsqm/commands/mine.py
- [x] T036 [US2] Add content hash deduplication to skip existing architectures in src/lsqm/commands/mine.py
- [x] T037 [US2] Add metadata extraction (services, resource_count, source_url) in src/lsqm/commands/mine.py
- [x] T038 [US2] Add skip logic for unsupported LocalStack services with skip_reason in src/lsqm/commands/mine.py

**Checkpoint**: `lsqm mine` discovers 50+ architectures, skips duplicates and unsupported

---

## Phase 5: User Story 3 - Test Application Generation via AI (Priority: P3)

**Goal**: Generate Python test applications using Claude API with budget tracking

**Independent Test**: Run `lsqm generate` on architectures without apps and verify valid Python files produced

### Generator Service

- [x] T039 [US3] Implement Claude API client with structured prompt in src/lsqm/services/generator.py
- [x] T040 [US3] Add Python syntax validation using ast.parse() in src/lsqm/services/generator.py
- [x] T041 [US3] Implement token budget tracking and enforcement in src/lsqm/services/generator.py
- [x] T042 [US3] Add generated file structure (conftest.py, app.py, test_app.py, requirements.txt) in src/lsqm/services/generator.py

### Generate Command

- [x] T043 [US3] Implement generate command with --budget, --arch, --force options in src/lsqm/commands/generate.py
- [x] T044 [US3] Add skip logic for existing apps (check apps/{hash}/ exists) in src/lsqm/commands/generate.py
- [x] T045 [US3] Add generation metadata (generated_at.json) writing in src/lsqm/commands/generate.py
- [x] T046 [US3] Handle budget exhaustion gracefully with progress reporting in src/lsqm/commands/generate.py

**Checkpoint**: `lsqm generate` creates valid Python test apps, respects budget

---

## Phase 6: User Story 4 - LocalStack Validation Execution (Priority: P4)

**Goal**: Validate architectures against LocalStack in isolated containers with parallel execution

**Independent Test**: Run `lsqm validate` and verify each architecture runs in own container with cleanup

### Validator Service

- [x] T047 [US4] Implement Docker container management using Docker SDK in src/lsqm/services/validator.py
- [x] T048 [US4] Add unique port allocation per container in src/lsqm/services/validator.py
- [x] T049 [US4] Implement health check polling at /_localstack/health in src/lsqm/services/validator.py
- [x] T050 [US4] Add tflocal init and apply execution with auto-approve in src/lsqm/services/validator.py
- [x] T051 [US4] Add pytest execution with 60-second timeout per test in src/lsqm/services/validator.py
- [x] T052 [US4] Implement cleanup: tflocal destroy, container stop, temp dir removal in src/lsqm/services/validator.py
- [x] T053 [US4] Add container logs capture on failure in src/lsqm/services/validator.py

### Parallel Execution

- [x] T054 [US4] Implement asyncio-based parallel validation with semaphore for concurrency control in src/lsqm/services/validator.py
- [x] T055 [US4] Add timeout handling (default 300s) with cleanup on timeout in src/lsqm/services/validator.py

### Validate Command

- [x] T056 [US4] Implement validate command with --arch, --timeout, --keep-containers options in src/lsqm/commands/validate.py
- [x] T057 [US4] Add progress reporting with status per architecture in src/lsqm/commands/validate.py
- [x] T058 [US4] Save ValidationResult JSON to runs/{run_id}/results/{arch_hash}.json in src/lsqm/commands/validate.py

**Checkpoint**: `lsqm validate` runs isolated containers, captures results, cleans up

---

## Phase 7: User Story 5 - Compatibility Reporting and Dashboard (Priority: P5)

**Goal**: Generate HTML dashboard with summary, trends, regression alerts, expandable logs

**Independent Test**: Run `lsqm report` and open generated HTML in browser

### Reporter Service

- [x] T059 [P] [US5] Create Jinja2 HTML template with Tailwind CSS and Chart.js in src/lsqm/templates/report.html.j2
- [x] T060 [US5] Implement summary statistics aggregation (total, passed, partial, failed, timeout) in src/lsqm/services/reporter.py
- [x] T061 [US5] Implement regression alert banner rendering in src/lsqm/services/reporter.py
- [x] T062 [US5] Implement service compatibility matrix with pass rates in src/lsqm/services/reporter.py
- [x] T063 [US5] Implement historical trend charts (last 12 runs) using Chart.js in src/lsqm/services/reporter.py
- [x] T064 [US5] Implement sortable architecture results table in src/lsqm/services/reporter.py
- [x] T065 [US5] Implement expandable failure details with logs in src/lsqm/services/reporter.py
- [x] T066 [US5] Generate single self-contained HTML file with inline CSS/JS in src/lsqm/services/reporter.py

### Report Command

- [x] T067 [US5] Implement report command with --output and --run options in src/lsqm/commands/report.py
- [x] T068 [US5] Add report generation summary output in src/lsqm/commands/report.py

**Checkpoint**: `lsqm report` generates dashboard loading in <2s with all visualizations

---

## Phase 8: User Story 6 - Regression Detection and Alerting (Priority: P6)

**Goal**: Detect regressions, create GitHub issues, send Slack notifications

**Independent Test**: Run `lsqm compare` between runs and verify correct regression/fix identification

### Comparison Service

- [x] T069 [US6] Implement run comparison logic (was passing → now failing = regression) in src/lsqm/services/comparator.py
- [x] T070 [US6] Implement fix detection (was failing → now passing) in src/lsqm/services/comparator.py

### GitHub Integration

- [x] T071 [US6] Implement GitHub issue creation for regressions using PyGithub in src/lsqm/services/git_ops.py
- [x] T072 [US6] Add issue template with architecture details, services affected, logs in src/lsqm/services/git_ops.py

### Slack Integration

- [x] T073 [US6] Implement Slack webhook notification in src/lsqm/services/notifier.py
- [x] T074 [US6] Add message formatting with pass rate, delta, regression alert, report link in src/lsqm/services/notifier.py

### Commands

- [x] T075 [US6] Implement compare command with --current, --format options in src/lsqm/commands/compare.py
- [x] T076 [US6] Add exit code 1 when regressions detected in src/lsqm/commands/compare.py
- [x] T077 [US6] Implement notify command with --run, --webhook options in src/lsqm/commands/notify.py

**Checkpoint**: `lsqm compare` detects regressions; issues created; Slack notified

---

## Phase 9: User Story 7 - Manual Pipeline Control (Priority: P7)

**Goal**: Individual stage commands for debugging and local development

**Independent Test**: Run each subcommand individually and verify independent operation

### Sync Command

- [x] T078 [US7] Implement sync command with --force option in src/lsqm/commands/sync.py
- [x] T079 [US7] Add git clone/pull for artifact repository in src/lsqm/services/git_ops.py
- [x] T080 [US7] Load architectures/index.json into local cache in src/lsqm/commands/sync.py

### Push Command

- [x] T081 [US7] Implement push command with --skip-issues, --message options in src/lsqm/commands/push.py
- [x] T082 [US7] Add architecture index update in src/lsqm/services/git_ops.py
- [x] T083 [US7] Add run results commit with summary message in src/lsqm/services/git_ops.py
- [x] T084 [US7] Implement 52-run retention (delete older runs during push) in src/lsqm/services/git_ops.py
- [x] T085 [US7] Update trends/*.json files during push in src/lsqm/services/git_ops.py

### Utility Commands

- [x] T086 [P] [US7] Implement status command with --format option in src/lsqm/commands/status.py
- [x] T087 [P] [US7] Implement clean command with --containers, --cache, --all options in src/lsqm/commands/clean.py
- [x] T088 [US7] Add stale container detection and removal using Docker SDK in src/lsqm/commands/clean.py

### Global Flags

- [x] T089 [US7] Implement --dry-run mode showing actions without execution in src/lsqm/cli.py
- [x] T090 [US7] Implement --verbose mode with detailed structured logging in src/lsqm/cli.py

**Checkpoint**: All commands work independently; dry-run and verbose modes functional

---

## Phase 10: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T091 [P] Add error handling with exponential backoff for GitHub API rate limits in src/lsqm/services/discovery/github_orgs.py
- [x] T092 [P] Add error handling for Claude API failures in src/lsqm/services/generator.py
- [x] T093 [P] Add graceful container cleanup on SIGTERM/SIGINT in src/lsqm/services/validator.py
- [x] T094 Validate quickstart.md instructions work end-to-end
- [x] T095 [P] Add type hints to all public functions
- [x] T096 Run ruff lint and fix all issues

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-9)**: All depend on Foundational phase completion
  - US1 (run) depends on all other commands being implemented or stubbed
  - US2 (mine) is independent after foundational
  - US3 (generate) depends on US2 (needs architectures to generate apps for)
  - US4 (validate) depends on US3 (needs apps to validate)
  - US5 (report) depends on US4 (needs validation results to report)
  - US6 (compare/notify) depends on US4 (needs run results to compare)
  - US7 (manual control) is independent after foundational
- **Polish (Phase 10)**: Depends on all user stories being complete

### User Story Dependencies

```
US2 (mine) ──────────────────────────────────────────────────┐
     │                                                       │
     ▼                                                       │
US3 (generate) ──────────────────────────────────────────────┤
     │                                                       │
     ▼                                                       │
US4 (validate) ──────────────────────────────────────────────┤
     │                                                       │
     ├──────────────┬───────────────┐                        │
     ▼              ▼               ▼                        ▼
US5 (report)   US6 (compare)   US7 (sync/push/etc.)     US1 (run)
```

### Within Each User Story

- Models before services
- Services before commands
- Core implementation before options/flags
- Story complete before moving to next priority

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel (T003, T004, T005, T006)
- All Foundational model tasks marked [P] can run in parallel (T007-T012)
- All Foundational utility tasks marked [P] can run in parallel (T014-T016)
- US2 discovery sources can run in parallel (T027-T030)
- US7 utility commands can run in parallel (T086, T087)
- Polish tasks marked [P] can run in parallel (T091-T093, T095)

---

## Parallel Example: Phase 2 Foundational

```bash
# Launch all model tasks in parallel:
Task: "Create Architecture model in src/lsqm/models/architecture.py"
Task: "Create TestApp model in src/lsqm/models/test_app.py"
Task: "Create Run model in src/lsqm/models/run.py"
Task: "Create ValidationResult model in src/lsqm/models/validation_result.py"
Task: "Create Regression model in src/lsqm/models/regression.py"
Task: "Create ServiceTrend model in src/lsqm/models/service_trend.py"

# Launch all utility tasks in parallel:
Task: "Implement structured JSON logging in src/lsqm/utils/logging.py"
Task: "Implement content hash computation in src/lsqm/utils/hashing.py"
Task: "Implement config loading in src/lsqm/utils/config.py"
```

---

## Parallel Example: US2 Discovery Sources

```bash
# Launch all discovery implementations in parallel:
Task: "Implement Terraform Registry discovery in src/lsqm/services/discovery/terraform_registry.py"
Task: "Implement GitHub organization discovery in src/lsqm/services/discovery/github_orgs.py"
Task: "Implement Serverless Framework examples discovery in src/lsqm/services/discovery/serverless.py"
Task: "Implement AWS CDK examples discovery in src/lsqm/services/discovery/cdk_examples.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 via US2-US4)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 4: User Story 2 (mine) - Architecture discovery
4. Complete Phase 5: User Story 3 (generate) - Test generation
5. Complete Phase 6: User Story 4 (validate) - Validation execution
6. Complete Phase 3: User Story 1 (run) - Orchestrate all stages
7. **STOP and VALIDATE**: Test `lsqm run` end-to-end
8. Deploy to GitHub Actions for first automated run

### Incremental Delivery

1. Setup + Foundational → Core infrastructure ready
2. Add US2 (mine) → Can discover architectures → Demo
3. Add US3 (generate) → Can generate test apps → Demo
4. Add US4 (validate) → Can run validations → Demo
5. Add US1 (run) → Full pipeline works → **MVP Complete!**
6. Add US5 (report) → Dashboard available → Demo
7. Add US6 (compare/notify) → Alerts enabled → Demo
8. Add US7 (manual control) → Developer experience → Full Release

### MVP Scope

The MVP consists of:
- Phase 1: Setup (6 tasks)
- Phase 2: Foundational (14 tasks)
- Phase 4: US2 - mine (13 tasks)
- Phase 5: US3 - generate (8 tasks)
- Phase 6: US4 - validate (12 tasks)
- Phase 3: US1 - run (5 tasks)

**MVP Total: 58 tasks**

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Test tasks omitted (not requested in specification)
