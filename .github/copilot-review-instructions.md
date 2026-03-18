# LISA Code Review Instructions

These rules govern every automated PR review on the LISA repository. Follow them strictly.

---

## 1. Mandatory Output — Test Suggestion Block

**Every review MUST end with this block.** Never omit it.

```
**Key Test Cases:**
verify_reboot_in_platform|verify_stop_start_in_platform|smoke_test

**Impacted LISA Features:**
NetworkInterface, StartStop

**Tested Azure Marketplace Images:**
- canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest
- redhat rhel 9_5 latest
```

### Rules for the test suggestion block

- **Test method names**: Use exact method names only. Never include class names or file paths. Separate multiple methods with `|`.
  - ✅ Correct: `verify_reboot_in_platform`
  - ❌ Incorrect: `core.provisioning` or `TestProvisioning.verify_reboot_in_platform`
- **Feature classes**: Use exact class names as they appear in the codebase (e.g. `NetworkInterface`, `StartStop`, `Gpu`, `Nvme`, `Resize`, `SerialConsole`, `Hibernate`). List only features directly impacted by the PR. Consider both primary and secondary impacts of the changes.
- **Marketplace images**: Select the minimal set needed to validate the change while maximizing coverage across affected scenarios. Use exact strings from the image list in Section 7. Choose images based on:
  - Which distros are affected by the change
  - Both Gen1 and Gen2 if generation-sensitive
  - Both x64 and ARM64 if architecture-sensitive
  - Distribution-specific changes require images for those specific distributions
- **Test selection strategy**:
  - If the change targets specific functionality, choose tests that directly exercise that functionality.
  - If the change is broad or foundational, select representative tests that cover the most likely impact areas.
- **Unit tests** are automatically run — only list integration/end-to-end tests.

---

## 2. PR Hygiene Checks

Flag these as issues in your review:

- **Empty or missing PR description**: Comment: _"Please add a description explaining what this PR does and why."_
- **No linked issue or bug context**: If the change fixes a bug or addresses an issue and none is referenced, comment: _"Consider linking the related issue for traceability."_
- **Overly large PR**: If the PR touches more than 10 files across unrelated areas, suggest splitting.

---

## 3. Code Quality Rules

Check every changed file against these rules:

### Constants and magic numbers
- Hardcoded numeric values that control test behavior (loop counts, timeouts, thresholds) **must** have an inline comment explaining the chosen value. Flag any uncommented magic number change.

### Test coverage reduction
- If the PR **reduces** iteration counts, removes test cases, lowers retry limits, or narrows test scope, flag it: _"This change reduces test coverage. Please provide data or justification for why the reduced value is sufficient."_

### Exception handling
- Catch specific exceptions, not bare `except:` or `except Exception`.
- Exception messages must be descriptive and include relevant context (e.g. iteration count, resource name).

### Assertions
- Use `assert_that()` from the LISA assertion library, not bare `assert` statements.
- Every test must have at least one meaningful assertion.

### Cleanup and cost
- Tests that create Azure resources must clean them up.
- Flag any test that sets `keep_environment: yes` without clear justification.

### Logging
- Use `node.log` or `log` objects, not `print()`.
- Log meaningful state transitions (before/after actions).

---

## 4. LISA Conventions

### Test structure (AAA pattern)
- **Arrange**: Set up preconditions, get tools/features.
- **Act**: Perform the operation under test.
- **Assert**: Verify the expected outcome.
- Flag tests that don't follow this pattern.

### Metadata decorators
- Every test method must have `@TestCaseMetadata` with `description`, `priority`, and `requirement`.
- Flag missing or incomplete metadata.

### Tools and features
- Use existing LISA tools from `lisa/tools/` — don't shell out with `node.execute()` when a tool exists.
- Use LISA features from `lisa/features/` for platform capabilities.

---

## 5. Security Checks

Flag these immediately:

- Hardcoded credentials, tokens, or secrets.
- Command injection risks (unsanitized user input passed to `node.execute()` or shell commands).
- Internal infrastructure details (subscription IDs, tenant IDs, internal hostnames, ADO bug IDs).

---

## 6. Severity Guide

Use these severity levels in your review:

| Severity | When to use | Action |
|----------|-------------|--------|
| **Critical** | Security issue, data loss risk, breaks existing tests | Request Changes |
| **Major** | Coverage reduction without justification, missing cleanup, wrong logic | Request Changes |
| **Minor** | Missing comments on magic numbers, inconsistent naming | Comment |
| **Nit** | Style preferences, minor formatting | Comment |

- **Request Changes** if any Critical or Major issue exists.
- **Approve** only if no Critical or Major issues remain.

---

## 7. Azure Marketplace Images

Use these exact strings when recommending test images:

### Ubuntu
- `canonical 0001-com-ubuntu-server-jammy 22_04-lts latest`
- `canonical 0001-com-ubuntu-server-jammy 22_04-lts-arm64 latest`
- `canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest`
- `canonical ubuntu-24_04-lts server latest`
- `canonical ubuntu-24_04-lts server-arm64 latest`
- `canonical ubuntu-24_04-lts server-gen1 latest`

### Debian
- `debian debian-11 11 latest`
- `debian debian-11 11-gen2 latest`
- `debian debian-12 12 latest`
- `debian debian-12 12-arm64 latest`
- `debian debian-12 12-gen2 latest`

### Azure Linux
- `microsoftcblmariner azure-linux-3 azure-linux-3 latest`
- `microsoftcblmariner azure-linux-3 azure-linux-3-arm64 latest`
- `microsoftcblmariner azure-linux-3 azure-linux-3-gen2 latest`

### Oracle Linux
- `oracle oracle-linux ol810-arm64-lvm-gen2 latest`
- `oracle oracle-linux ol810-lvm latest`
- `oracle oracle-linux ol810-lvm-gen2 latest`
- `oracle oracle-linux ol94-arm64-lvm-gen2 latest`
- `oracle oracle-linux ol94-lvm latest`
- `oracle oracle-linux ol94-lvm-gen2 latest`

### Red Hat Enterprise Linux
- `redhat rhel 8_10 latest`
- `redhat rhel 810-gen2 latest`
- `redhat rhel 9_5 latest`
- `redhat rhel 95_gen2 latest`
- `redhat rhel-arm64 9_5-arm64 latest`

### SUSE Linux Enterprise Server
- `suse sles-12-sp5 gen1 latest`
- `suse sles-12-sp5 gen2 latest`
- `suse sles-15-sp6 gen1 latest`
- `suse sles-15-sp6 gen2 latest`
- `suse sles-15-sp6-arm64 gen2 latest`

---

## 8. Best Practices Summary

1. **Be Specific**: Use exact method names, feature classes, and image strings.
2. **Be Minimal**: Select only what's necessary to validate the changes.
3. **Be Practical**: Format suggestions for easy copy-paste usage.
4. **Be Comprehensive**: Consider all three areas (tests, features, images) for complete coverage.
5. **Be Cost-Conscious**: Remember that each image selection has cost implications.
