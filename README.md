# Linux Integration Services Automation (LISA)

[![CI
Workflow](https://github.com/microsoft/lisa/workflows/CI%20Workflow/badge.svg?branch=main)](https://github.com/microsoft/lisa/actions?query=workflow%3A%22CI+Workflow+for+LISAv3%22+event%3Apush+branch%3Amain)
[![GitHub
license](https://img.shields.io/github/license/microsoft/lisa)](https://github.com/microsoft/lisa/blob/main/LICENSE)

**Linux Integration Services Automation (LISA)** is a Linux quality validation system,
which consists of two parts：

* A test framework to drive test execution.
* A set of test suites to verify Linux kernel/distribution quality.

`LISA` was originally designed and implemented for Microsoft Azure and 
Windows HyperV platforms; now it can be used to validate Linux quality on 
any platforms if the proper orchestrator module implemented.

## Why LISA

* **Scalable**：Benefit from the appropriate abstractions, `LISA` can be used 
to test the quality of numerous Linux distributions without duplication of code 
implementation.

* **Customizable**: The test suites created on top of `LISA` can be customized 
to support different quality validation needs. 

* **Support multiple platforms**: `LISA` is created with modular design, to 
support various of Linux platforms including Microsoft Azure, Windows HyperV, 
Linux bare metal, and other cloud based platforms. 

* **End-to-end**: `LISA` supports platform specific orchestrator to create and 
delete test environment automatically; it also provides flexibility to preserve 
environment for troubleshooting if test failed.

## Documents

* [Install LISA](docs/install.md)
* [Run tests](docs/run.md)
* [Microsoft tests](docs/microsoft_tests.md)
* [Write test cases in LISA](docs/write_case.md)
* [Command line reference](docs/command_line.md)
* [Runbook reference](docs/runbook.md)
* [Extend and customize LISA](docs/extension.md)
* [Run previous version LISA (aka LISAv2)](docs/run_legacy.md)

## Contribute

You are very welcome to contribute. Please follow [the contribution
document](docs/contributing.md) for details.

## History and road map

The previous LISA called LISAv2, which is in [master
branch](https://github.com/microsoft/lisa/tree/master). The previous LISA can be
used standalone or called from the current LISA. Learn more from [how to run
LISAv2 test cases](docs/run_legacy.md).

LISA is in active developing, and a lot of exciting features are implementing.
We're listening your [feedback](https://github.com/microsoft/lisa/issues/new).

## License

The entire codebase is under [MIT license](LICENSE).
