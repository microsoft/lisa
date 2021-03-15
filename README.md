# Linux Integration Services Automation (LISA)

[![CI Workflow](https://github.com/microsoft/lisa/workflows/CI%20Workflow/badge.svg?branch=main)](https://github.com/microsoft/lisa/actions?query=workflow%3A%22CI+Workflow+for+LISAv3%22+event%3Apush+branch%3Amain)
[![GitHub license](https://img.shields.io/github/license/microsoft/lisa)](https://github.com/microsoft/lisa/blob/main/LICENSE)

**Linux Integration Services Automation (LISA)** is designed to be an end-to-end solution for verifying Linux kernels and distributions quality on Microsoft virtualization technologies. It can be used on other quality validation, and virtualization technologies as well.

* **End-to-end**: LISA defines several sets of test suites to validate Linux kernels and distributions in Microsoft Azure, Hyper-V, etc. The test suites can help find integration issues easily.
* **Ease-to-use**: The complexity and diversity of Linux kernels/distributions are wrapped in different components of LISA. When running LISA, it doesn't need to know details. Developers can focus on validation logic, when creating new tests.
* **Extensibility**: LISA is extendable in many components to support various scenarios, including virtualization platforms, commands, Linux distributions, community test suites, etc. LISA supports to validate Microsoft virtualization platforms natively, but also can be extended to other cloud or on-premises platforms.

## Why LISA

There are a lot of classic tools and tests, which focus on the quality of Linux kernels or distributions. They are important to ensure the quality of kernels and distributions. The integration validation on virtualization platforms is a little different with classic Linux testing. It covers diverse types of resources with manageable cost. So that, it needs to plan resources creation and deletion automatically.

LISA focuses on validating the integration of Linux kernels/distributions and virtualization platforms. It needs more interactive with virtualization platforms to run tests for different purposes, like test different capabilities, hardware, and so on.

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

You are very welcome to contribute. Please follow [the contribution document](docs/contributing.md) for details.

## History and road map

The previous LISA called LISAv2, which is in [master branch](https://github.com/microsoft/lisa/tree/master). The previous LISA can be used standalone or called from the current LISA. Learn more from [how to run LISAv2 test cases](docs/run_legacy.md).

LISA is in active developing, and a lot of exciting features are implementing. We're listening your [feedback](https://github.com/microsoft/lisa/issues/new).

## License

The entire codebase is under [MIT license](LICENSE).
