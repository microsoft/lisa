---
applyTo: "**"
excludeAgent: "coding-agent"
---

# LISA Code Review Instructions

YOU MUST FOLLOW EVERY RULE BELOW. These are not suggestions.

## CRITICAL REQUIREMENT — Test Suggestion Block

EVERY review you produce MUST end with a test validation block in EXACTLY this format. Do not skip it. Do not rephrase it. Do not place it inside a summary section. Place it as the LAST thing in your review output.

**Key Test Cases:**
<method_names separated by | — use exact method names, no class prefixes>

**Impacted LISA Features:**
<feature class names — e.g. NetworkInterface, StartStop, Gpu, Nvme, Resize, Hibernate>

**Tested Azure Marketplace Images:**
<exact image strings from Section 7 below, one per line with - prefix>

Example:

**Key Test Cases:**
verify_reboot_in_platform|verify_stop_start_in_platform|smoke_test

**Impacted LISA Features:**
NetworkInterface, StartStop

**Tested Azure Marketplace Images:**
- canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest
- redhat rhel 9_5 latest

Rules:
- Test method names: exact names only, no class prefix, separated by `|`.
- Feature classes: exact class names from `lisa/features/`.
- Images: use exact strings from Section 7. Choose by affected distro, Gen1/Gen2 if generation-sensitive, x64/ARM64 if architecture-sensitive.
- Only list integration tests. Unit tests run automatically.

---

## Severity Levels — Use These Exact Labels

| Level | When | Action |
|-------|------|--------|
| Critical | Security issue, data loss, breaks existing tests | Request Changes |
| Major | Coverage reduction without justification, missing cleanup, wrong logic | Request Changes |
| Minor | Missing comments on magic numbers, inconsistent naming | Comment |
| Nit | Style preference, formatting | Comment |

Do NOT use "High", "Medium", "Low". Use "Critical", "Major", "Minor", "Nit" only.

Request Changes if any Critical or Major issue exists. Approve only if none remain.

---

## PR Hygiene

- Empty PR description → comment: "Please add a description explaining what this PR does and why."
- No linked issue for a bug fix → comment: "Consider linking the related issue for traceability."
- PR touches >10 unrelated files → suggest splitting.

---

## Code Quality

- Magic numbers controlling test behavior (loop counts, timeouts, thresholds) MUST have inline comments. Flag any uncommented magic number.
- If the PR reduces iteration counts, removes tests, lowers retries, or narrows scope → flag: "This change reduces test coverage. Please provide justification."
- Catch specific exceptions, not bare `except:` or `except Exception`.
- Exception messages must include **what happened** AND **how to resolve/investigate**. Bad: `"VM size not found"`. Good: `"VM size [X] not found in location [Y]. Verify the size is available in this region."`.
- Use `assert_that()` from assertpy, not bare `assert`.
- Tests creating Azure resources must clean them up.
- Flag `keep_environment: yes` without justification.
- Use `node.log` or `log`, not `print()`.
- **No `time.sleep()`**. Use bounded waits: `check_till_timeout()`, `retry_without_exceptions()`, or the `retry` decorator. Bare `sleep()` causes flaky or slow tests.
- **Type hints mandatory** on all test method parameters and return types. At minimum `node: Node` and `-> None`. Flag missing type hints.
- **Prefer f-strings** over `%` formatting or `.format()`.
- **Path handling**: Use `node.get_pure_path()` for cross-OS path compatibility. Flag hardcoded `/` or `\\` path separators in node commands.

---

## Assertions

- Put the **actual value** in `assert_that(actual)`, not the expected value.
- Add `.described_as("business context")` to every assertion that isn't self-explanatory. The description should explain **why** this check matters, not repeat the code.
- Prefer **native matchers** over manual manipulation: `assert_that(items).is_length(6)` not `assert_that(len(items)).is_equal_to(6)`.
- Use **collection assertions**: `.contains()`, `.is_subset_of()`, `.does_not_contain()` instead of manual loops.
- Do not repeat already-checked conditions. One precise assertion is better than redundant chains.

---

## LISA Conventions

### Test Structure
- **One test class per file.** Class name PascalCase, describes the feature (not a scenario). Inherits `TestSuite`.
- **Method naming**: Prefix with `verify_` or `test_`. Name describes the scenario being validated.
- **File location**: `lisa/microsoft/testsuites/<feature_area>/<test_name>.py`. Filename in snake_case.
- Tests follow **AAA pattern**: Arrange → Act → Assert. Keep sections clearly separated.

### Metadata
- Every test class has `@TestSuiteMetadata` with `area`, `category`, `description`. Flag if any field is missing.
- Every test method has `@TestCaseMetadata` with `description`, `priority`, `requirement`. Flag if any field is missing.
- `requirement` should use `simple_requirement(supported_os=..., unsupported_os=..., supported_features=..., supported_platform_type=...)`. Flag custom selection logic that duplicates what `simple_requirement` already provides.

### Tools, Features, and Extensions
- Use LISA tools from `lisa/tools/` instead of raw `node.execute()` when a tool exists.
- Use LISA features from `lisa/features/` for platform capabilities.
- Features used via `node.features[X]` must be declared in the test's `requirement=simple_requirement(supported_features=[X])`. Flag undeclared feature usage.
- Prefer Python tool implementations over bash scripts. Flag new `.sh` scripts when a Tool class would be more appropriate.

### Skip vs Fail
- **`SkippedException`** for unmet preconditions (wrong OS, missing hardware, feature unavailable). This is NOT a failure.
- **Assertion failure** or **`LisaException`** for actual test logic failures. Do not use `SkippedException` to hide real failures.

### Cleanup and Node State
- Use `after_case()` for guaranteed cleanup. Use `try/finally` for inline cleanup.
- Call `node.mark_dirty()` if the test modifies: kernel parameters, drivers loaded/unloaded, network config, or requires reboot. Flag tests that appear to modify system state without `mark_dirty()`.
- **Cost awareness**: VMs cost money. Flag tests that deploy extra resources without cleanup, or that use `use_new_environment=True` without justification.

---

## Logging

- **INFO**: High-level progress milestones, reads like a story. Even a passing run should make sense from INFO alone.
- **DEBUG**: Command output, parsed values, intermediate state. Used for troubleshooting.
- **WARNING**: Avoid unless truly needed. Most warnings should be INFO or ERROR.
- **ERROR**: Only for real problems. A passing test run should have zero ERROR lines. Flag excessive ERROR logging in normal paths.
- Each log line should be **unique and searchable** in the codebase. Include context like node name, iteration count, or resource ID. Bad: `"received signal"`. Good: `"received stop signal in lisa_runner"`.
- Logging is **not a substitute for assertions**. If a condition matters, assert it; don't just log it.

---

## Naming Conventions

- Follow PEP 8: `snake_case` for functions/variables, `CamelCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Avoid `import as` renaming unless there is a genuine name conflict. Use the module as namespace instead (e.g., `schema.Node`).
- Flag inconsistent naming that deviates from surrounding code.

---

## Security

Flag immediately:
- Hardcoded credentials, tokens, or secrets.
- Command injection risks (unsanitized input to `node.execute()` or shell).
- Internal infrastructure details (subscription IDs, tenant IDs, internal hostnames, ADO bug IDs).

---

## Section 7 — Azure Marketplace Images

Use ONLY these exact strings when recommending images:

Ubuntu:
- `canonical 0001-com-ubuntu-server-jammy 22_04-lts latest`
- `canonical 0001-com-ubuntu-server-jammy 22_04-lts-arm64 latest`
- `canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest`
- `canonical ubuntu-24_04-lts server latest`
- `canonical ubuntu-24_04-lts server-arm64 latest`
- `canonical ubuntu-24_04-lts server-gen1 latest`

Debian:
- `debian debian-11 11 latest`
- `debian debian-11 11-gen2 latest`
- `debian debian-12 12 latest`
- `debian debian-12 12-arm64 latest`
- `debian debian-12 12-gen2 latest`

Azure Linux:
- `microsoftcblmariner azure-linux-3 azure-linux-3 latest`
- `microsoftcblmariner azure-linux-3 azure-linux-3-arm64 latest`
- `microsoftcblmariner azure-linux-3 azure-linux-3-gen2 latest`

Oracle Linux:
- `oracle oracle-linux ol810-arm64-lvm-gen2 latest`
- `oracle oracle-linux ol810-lvm latest`
- `oracle oracle-linux ol810-lvm-gen2 latest`
- `oracle oracle-linux ol94-arm64-lvm-gen2 latest`
- `oracle oracle-linux ol94-lvm latest`
- `oracle oracle-linux ol94-lvm-gen2 latest`

Red Hat Enterprise Linux:
- `redhat rhel 8_10 latest`
- `redhat rhel 810-gen2 latest`
- `redhat rhel 9_5 latest`
- `redhat rhel 95_gen2 latest`
- `redhat rhel-arm64 9_5-arm64 latest`

SUSE Linux Enterprise Server:
- `suse sles-12-sp5 gen1 latest`
- `suse sles-12-sp5 gen2 latest`
- `suse sles-15-sp6 gen1 latest`
- `suse sles-15-sp6 gen2 latest`
- `suse sles-15-sp6-arm64 gen2 latest`

---

## REMINDER — DO NOT FORGET

Your review MUST end with the test suggestion block. Go back and check. If your output does not end with **Key Test Cases:**, **Impacted LISA Features:**, and **Tested Azure Marketplace Images:**, your review is incomplete. Add it now.
