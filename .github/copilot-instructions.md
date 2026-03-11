# LISA Testing Guidelines for Pull Requests

This document provides comprehensive guidelines for generating test suggestions for pull requests (PRs) in the LISA project. These guidelines ensure thorough validation while maintaining cost efficiency and testing relevance.

## Overview

When reviewing or creating PRs, follow these three key areas of testing guidance:

1. **Test Case Selection** - Identify the essential test methods
2. **Feature Impact Analysis** - Determine affected LISA features
3. **Image Selection** - Choose appropriate Azure marketplace images

## Copilot Instructions for Code Reviews

**MANDATORY REQUIREMENT:** Every code review must include a test suggestion using the Quick Reference Template provided below. This is required for all pull request reviews to ensure consistent test coverage guidance.

When reviewing any pull request, you must:

1. **Always generate and present the test suggestion block** as part of your review
2. **Use the exact Quick Reference Template format** (found at the bottom of this document) for copy-paste convenience
3. **Include all three required components:**
   - Essential integration/end-to-end test method names (using exact method names separated by `|`)
   - Directly impacted LISA feature class names (using exact class names as they appear in codebase)
   - Minimal set of Azure Marketplace images required for validation (using exact image strings from the provided list)

This ensures every code review provides actionable, standardized test guidance that reviewers and contributors can immediately use for validation.

## Test Case Selection Guidelines

### Unit Tests
- Unit tests are automatically included and should **not** be listed in test suggestions
- Focus only on integration and end-to-end test recommendations

### Key Test Cases
- **Identify Essential Tests Only**: Select the minimal set of test cases that validate your specific changes
- **Use Method Names**: Always specify the exact test method names, never include class names or file paths
  - ✅ Correct: `verify_reboot_in_platform`
  - ❌ Incorrect: `core.provisioning` or `TestProvisioning.verify_reboot_in_platform`
- **Multiple Test Format**: When suggesting multiple tests, separate method names with a pipe (`|`) for easy copy-paste usage
  - Example: `verify_reboot_in_platform|verify_stop_start_in_platform|verify_resize_operation`

### Test Selection Strategy
- If your change targets specific functionality, choose tests that directly exercise that functionality
- If your change is broad or foundational, select representative tests that cover the most likely impact areas

## LISA Features Impact Analysis

### What are LISA Features?
LISA Features are platform-specific capability classes that represent testable functionality. They serve as requirements for test cases and help identify testing scope.

### Common LISA Features
Examples include (but are not limited to):
- `Gpu` - Graphics processing capabilities
- `Nvme` - NVMe storage functionality
- `StartStop` - VM start/stop operations
- `Resize` - VM resizing capabilities
- `NetworkInterface` - Network interface management
- `SerialConsole` - Serial console access
- `Hibernate` - VM hibernation features

### Feature Selection Guidelines
- List only features **directly impacted** by your changes
- Use the exact feature class names as they appear in the codebase
- Consider both primary and secondary impacts of your changes

## Azure Marketplace Image Selection

### Selection Principles
- **Minimize Cost**: Select only the essential images needed to validate your changes
- **Maximize Coverage**: Ensure selected images cover the key scenarios affected by your PR
- **Use Exact Strings**: Always provide the complete image string exactly as listed below for direct copy-paste usage

### When to Select Images
- **OS-Specific Changes**: Choose images representing the affected operating systems
- **Architecture Changes**: Include both x64 and ARM64 variants if relevant
- **Generation Changes**: Consider both Gen1 and Gen2 images if applicable
- **Distribution Changes**: Select specific Linux distributions if your change is distribution-sensitive

### Available Azure Marketplace Images

Copy the exact string for the images you need:

#### Ubuntu Images
- `canonical 0001-com-ubuntu-server-jammy 22_04-lts latest`
- `canonical 0001-com-ubuntu-server-jammy 22_04-lts-arm64 latest`
- `canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest`
- `canonical ubuntu-24_04-lts server latest`
- `canonical ubuntu-24_04-lts server-arm64 latest`
- `canonical ubuntu-24_04-lts server-gen1 latest`

#### Debian Images
- `debian debian-11 11 latest`
- `debian debian-11 11-gen2 latest`
- `debian debian-12 12 latest`
- `debian debian-12 12-arm64 latest`
- `debian debian-12 12-gen2 latest`

#### Azure Linux Images
- `microsoftcblmariner azure-linux-3 azure-linux-3 latest`
- `microsoftcblmariner azure-linux-3 azure-linux-3-arm64 latest`
- `microsoftcblmariner azure-linux-3 azure-linux-3-gen2 latest`

#### Oracle Linux Images
- `oracle oracle-linux ol810-arm64-lvm-gen2 latest`
- `oracle oracle-linux ol810-lvm latest`
- `oracle oracle-linux ol810-lvm-gen2 latest`
- `oracle oracle-linux ol94-arm64-lvm-gen2 latest`
- `oracle oracle-linux ol94-lvm latest`
- `oracle oracle-linux ol94-lvm-gen2 latest`

#### Red Hat Enterprise Linux Images
- `redhat rhel 8_10 latest`
- `redhat rhel 810-gen2 latest`
- `redhat rhel 9_5 latest`
- `redhat rhel 95_gen2 latest`
- `redhat rhel-arm64 9_5-arm64 latest`

#### SUSE Linux Enterprise Server Images
- `suse sles-12-sp5 gen1 latest`
- `suse sles-12-sp5 gen2 latest`
- `suse sles-15-sp6 gen1 latest`
- `suse sles-15-sp6 gen2 latest`
- `suse sles-15-sp6-arm64 gen2 latest`

## Best Practices Summary

1. **Be Specific**: Use exact method names, feature classes, and image strings
2. **Be Minimal**: Select only what's necessary to validate your changes
3. **Be Practical**: Format suggestions for easy copy-paste usage
4. **Be Comprehensive**: Consider all three areas (tests, features, images) for complete coverage
5. **Be Cost-Conscious**: Remember that each image selection has cost implications

## Quick Reference Template

When providing test suggestions, use this format:

```
**Key Test Cases:**
verify_reboot_in_platform|verify_stop_start_in_platform|smoke_test

**Impacted LISA Features:**
FeatureName1, FeatureName2, FeatureName3

**Tested Azure Marketplace Images:**
- exact image string 1
- exact image string 2
- exact image string 3
```
