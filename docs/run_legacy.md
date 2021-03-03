# How to run Legacy LISAv2 tests

[LISAv2](https://github.com/microsoft/lisa) brings incredible value to Linux quality on Microsoft virtualization platforms. To keep and increase the value of LISA, we decide to have more innovation and continue invest on LISA. So we start the current version of LISA.

During the transition time, we keep to validate Linux distributions. We cannot and don't want to stop to wait the exciting current LISA. The two versions will be co-existing for a while, under current LISA experience.

With this document, you will know how to run LISAv2 tests for validation in the current LISA.

The current LISA can clone any repo of LISAv2 to run, and parse LISAv2 log to generate test results with new format.

## Preparation

LISAv2 should run in the latest Windows 10 client 64 bits, or Windows Server 2019 editions.

Follow [LISAv2 document](https://github.com/microsoft/lisa/blob/master/README.md) to understand prerequisites, and prepare secret files.

Note, you don't need to run git clone, the current LISA will clone LISAv2 when running.

## Limitations

1. Test in parallel of LISAv2 doesn't support with the current LISA together. The current LISA will implement test matrix to replace current test in parallel in LISAv2. But there is no plan to compatible with LISAv2.
2. The LISAv2 results has low chance to be missed. There is rare race condition on accessing conflict of LISAv2 test log. If it happens on key logs which relates to test result parsing, it may cause the status of results are not shown correctly.

## road map

We're migrating LISAv2 test cases to current LISA by test case priority. We will keep t0 to tx runbooks update to date. When test cases migrated, they will be included in current LISA, and remove from LISAv2. It will be transparent to you.
