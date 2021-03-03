# Linux Integration Services Automation (LISA)

[![CI Workflow](https://github.com/microsoft/lisa/workflows/CI%20Workflow/badge.svg?branch=main)](https://github.com/microsoft/lisa/actions?query=workflow%3A%22CI+Workflow+for+LISAv3%22+event%3Apush+branch%3Amain)
[![GitHub license](https://img.shields.io/github/license/microsoft/lisa)](https://github.com/microsoft/lisa/blob/main/LICENSE)

**Linux Integration Services Automation (LISA)** is designed to be an end-to-end solution to validate Linux kernels and distributions quality on virtualization platforms of Microsoft and others. It can be used on more tests, or support other cloud platforms as well.

* **End-to-end**: LISA defines several set of test suites to validate Linux kernels and distributions in Microsoft Azure, and Hyper-V. The test suites can help find integration issues easily.
* **Ease-to-use**: The complexity and diversity of testing or Linux distributions is wrapped in different components of LISA. When running LISA, it doesn't need to know much on details.
* **Extensibility**: LISA is extendable in many components to support various scenarios, including virtualization platforms, commands, Linux distributions, community test suites, etc. LISA supports to validate Microsoft virtualization platforms natively, but also is able to extend to support other cloud or on-premises platforms.

## Why LISA

There are a lot of tools, which focus on Linux kernels or distributions quality. They are very important to guarantee quality of kernels and distributions. The integration validation on virtualization platforms is a little different with classic Linux testing. It needs to cover different types of resources with manageable cost. It needs to create/delete resources with a good plan automatically.

LISA focuses on validating the integration of Linux kernels/distributions and virtualization platforms. It needs more interactive with virtualization platforms to run tests for different purposes, like test different capacity, hardware, and so on.

## Documents

* [Key concepts](docs/concepts.md)
* [Install LISA](docs/install.md)
* [Run tests with LISA](docs/run.md)
* [Command line reference](docs/command_line.md)
* [Runbook reference](docs/runbook.md)
* [Microsoft test suites](https://github.com/microsoft/lisa/blob/master/Documents/LISAv2-TestCase-Statistics.md)
* [How to write tests](docs/write_case.md)
* [How to extend and customize LISA](docs/extension.md)
* [How to run previous version LISA (aka LISAv2)](docs/run_legacy.md)

## Contribute

You are very welcome to contribute. Please follow [the contribution document](docs/contributing.md) for details.

## History and road map

The previous LISA called LISAv2, which is in [master branch](https://github.com/microsoft/lisa/tree/master). The previous LISA can be used standalone or called from current LISA. Refer to [how to run LISAv2 test cases](docs/run_legacy.md) for details.

LISA is in active developing, and a lot of exciting features are implementing. We're listening your feedback.

## License

The entire codebase is under [MIT license](LICENSE).
