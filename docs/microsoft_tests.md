# Microsoft tests

- [Microsoft tests](#microsoft-tests)
  - [How to run Microsoft tests](#how-to-run-microsoft-tests)
    - [Quick start](#quick-start)
    - [Advanced](#advanced)
  - [Test priority](#test-priority)
  - [Test tier](#test-tier)
  - [Test cases specification](#test-cases-specification)

The test suite in LISA is called Microsoft tests, which are provided by Microsoft Linux System Group. This document introduces how Microsoft tests were defined, categorized, and how to have the appropriate coverage.

## How to run Microsoft tests

### Quick start

Microsoft tests are organized under the folder `microsoft/runbook`. The root folder contains runbooks for azure, ready, and local. Learn more from [how to run LISA tests](run.md) to run different tiers on an image or existing environment.

### Advanced

If you want to verify on specified conditions, like to select some VM size in azure, or select test cases by names, learn more from [runbook reference](runbook.md).

## Test priority

The priority of each test case is determined by the impact if it's failed. The smaller number means the higher priority. For example, if a high-priority test case fails, it means the operating system cannot start. If a lower-priority test case fails, it may mean that a function does not work.

Note that when multiple test cases fail, we should first check the failure of high-priority test cases to speed up the analysis.

- **P0**. The system fails/hangs on start/restart using default settings.
- **P1**. The system fails/hangs on start/restart using popular configurations, for example, add firewall rules, install some popular packages. There is data loss with popular configurations. The system cannot be connected via network with default settings. The system performance drops significantly, like SRIOV doesn't work as expected; only one CPU core works on multiple core machine; an important feature doesn't work with default settings; or the system can be used with limited functionality.
- **P2**. The system fails/hangs on start/restart using unpopular configurations. Data loss with unpopular configurations. The system cannot be connected with popular configurations. The system performance drops obviously. An important feature doesn't work with popular configurations.
- **P3**. A feature doesn't work with unpopular configurations with low impact.
- **P4**. The system has obvious but not serious problems on long-haul, stress or performance test scenarios.

Please Note that the above examples do not cover all situations and are for reference. For example, in a cloud environment, one host version may cause problems of some Linux virtual machines. The impact is affected by the percentage the problematic version also.

## Test tier

Ideally, all tests should be run to maximize the coverage. But the time and resource are limited, and the risks need to be minimized based on the limitations. In LISA, Microsoft tests are organized into several tiers to have the appropriate coverage using limited resource.

Test tiers can be T0, T1, T2, T3, T4. It maps to priorities of test cases. For example, T0 means all P0 test cases are selected in a test run. T2 means all P0, P1, P2 test cases are selected in a test run.

- **T0** completes in 5 minutes with single VM in average. 100% automation, and no need for manual analysis of results.
- **T1** completes in 2 hours with 2 VMs in each environment, and two environments are parallel. 100% automation, and no need for manual analysis of results.
- **T2** completes in 8 hours with two environments are parallel. 100% automation.
- **T3** completes in 16 hours with two environments are parallel. 100% automation.
- **T4** has no cost limit, and the coverage is maximized. 100% automation.

## Test cases specification

TODO: add spec of LISA test cases.

Learn more on not migrated [legacy LISAv2 tests](https://github.com/microsoft/lisa/blob/master/Documents/LISAv2-TestCase-Statistics.md).
