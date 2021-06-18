# Understand test results

- [Overview](#overview)
- [Intermediate results](#intermediate-results)
- [Final results](#final-results)

## Overview

It's essential to understand the results after running tests. LISA has seven
kinds of test results in total: three of which are intermediate results, and
four of which are final results, as explained in sections below. 

Each test case can and will be moved from one result to another but can never
have two or more results at the same time. The result of each test case will be
shown when the test case is finished and in the end of the test run.

## Intermediate results

An intermediate result of a test shows information of an unfinished test.

- **QUEUED**

  QUEUED tests are tests that are created, and planned to run (not started yet).
  They suggest that there are some tests waiting to be performed.

- **ASSIGNED**

  ASSIGNED tests are tests that are assigned to an environment, they will start
  to run once the environment is deployed. They suggest some environmental
  setting up is going on. ASSIGNED tests will move to FAILED if the environment
  fails to deploy. They will also move to QUEUED if the environment does not fit
  the tests requirement.

- **RUNNING**

  RUNNING tests are tests that are in test procedure. Note some tests take hours
  to run.

## Final results

When a test completes, it will have one of the following final results. This is
the test result you want to focus on.

- **FAILED**

  FAILED tests are tests that failed in running. The reason why will be given as
  `LISA exceptions` or `Assertion failure`. You can use them to analyze test
  results.

- **PASSED**

  PASSED tests are tests that are passed or at least partially passed, with a
  special `PASSException` that warns there are minor errors in the run but they
  do not affect the test result.

- **SKIPPED**

  SKIPPPED tests are tests that did not start and would no longer run. It is
  often due to failure to meet some requirements in the environment involved
  with the test.

- **ATTEMPTED**

  ATTEMPTED tests are a special category of failed tests because of known
  issues, which are not likely to be fixed soon.
