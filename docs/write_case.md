# How to write test cases

- [Understand LISA](#understand-lisa)
- [Document excellence](#document-excellence)
  - [Description in metadata](#description-in-metadata)
  - [Code comments](#code-comments)
  - [Commit messages](#commit-messages)
  - [Logging](#logging)
  - [Error message](#error-message)
  - [Assertion](#assertion)
- [Troubleshooting excellence](#troubleshooting-excellence)
- [Test code excellence](#test-code-excellence)
  - [Compositions of test](#compositions-of-test)
  - [Metadata](#metadata)
    - [Test suite metadata](#test-suite-metadata)
    - [Test case metadata](#test-case-metadata)
  - [Test case body](#test-case-body)
  - [Setup and cleanup](#setup-and-cleanup)
- [Use components in code](#use-components-in-code)
  - [Environment and node](#environment-and-node)
  - [Tool](#tool)
  - [Scripts](#scripts)
  - [Features](#features)
- [Best practices](#best-practices)
  - [Debug in ready environment](#debug-in-ready-environment)
  - [Written by non-native English speakers](#written-by-non-native-english-speakers)

Before writing a test case, we strongly recommend that you read the entire document. In addition to how to write test cases, we also believe that the engineering excellence is equally important. After the test case is completed, it will be run thousands of times, and many people will read and troubleshoot it. A good test case can save your and others' time.

## Understand LISA

It depends on your contribution to LISA, you may need to learn more about LISA. Learn more from the topics below.

- [Concepts](concepts.md) includes design considerations, how components work together. It's important for everyone who wants to write code in LISA.
- [Development](development.md) includes how to setup environment, code guidelines, and related topics.
- [Extensions](extension.md) includes how to develop extensions for LISA. In some cases, you may need to implement or improve extensions for new test cases.

## Document excellence

The documentation is the opportunity to make things clear and easy to maintain. A good document does not mean longer is better. Each kind of documentation has it's own purpose. Good technical documentation should be *useful and accurate*.

The following introduces the principle of each type of document in LISA.

### Description in metadata

The description is used to generate test specifications. Therefore, it should include the purpose and procedures of the test.

- Test suite metadata. A test suite is a set of test cases with similar test purposes or shared steps. Therefore, the metadata should explain why the test cases are bundled together.
- Test case metadata. Each test case has its test purpose, and steps. Since metadata is used to generate specifications, the main steps of the test logic need to be recorded. If it is a regression test case, the bug should be quoted. Including the impact of failure is also good.

### Code comments

How to write good code comments is a hot topic, and many best practices are also valuable. Here are some highlights.

- Do not repeat the code logic. Code comments are always in the same place as the code, which is different from metadata. Do not repeat `if/else` statement like "if ... else ...", do not repeat the content that already exists in the log string and exception message, do not repeat what can be clearly seen from the variable name.
- Record business logic. Code logic is more detailed than business logic. Some complex code logic may not be intuitive for understanding business logic. Code comments can help summarize complex code logic.
- Record trick things. We cannot avoid writing tricky code. For example, magic numbers, special handling of the Linux version, or other content.
- Provide regular expression examples. LISA uses many regular expressions to parse command output. It is simple and useful, but it may not match. When you need to create or update a regular expression, it needs to check the sample for regression. These examples also help to understand what the expression does.

### Commit messages

The commit message is used to explain why this change was made. The code comments describe the current state. The commit message describes the reason for the change. If you think the content is also suitable for writing in the code, please write it as a code comment.

### Logging

The log has two purposes, 1) display progress, and 2) troubleshoot.

To show progress, the log should be simple and logical. To troubleshoot, it requires more detailed information. These two goals sound contradictory, but they can be achieved through different INFO and DEBUG levels. LISA always enables the DEBUG level in the file, while the INFO level is the default setting on the console.

In LISA, when writing log lines in the code, consider what the test runner needs to know, not what the developer needs to know. If the developer needs to know something, it should be done in code comments.

- **DEBUG** level log should provide the *correct level* detail. The only way to write at the "correct level" is to use it from the beginning.

  When writing code, please continue to use and improve the log. If you need to debug step by step, it means you need to improve the log. If you don’t understand the meaning of the log and others may not, please optimize it. If you find duplicate information, please merge it.

- **INFO** level log should be *like a story*, to illustrate what happened.

  Even if the whole process goes smoothly, this is what you want to know every time. It should be friendly so that new users can understand what is going on. It should be as little as possible. It should tell the user to wait before performing a long operation.

- **WARNING** level logs should be avoided.

  The warning message indicates that it is important, but there is no need to stop. But in most cases, you will find that it is either not as important as the information level, or it is so important to stop running.

  At the time of writing, there are 3 warning messages in LISA. After review, I converted them all into information or error level. There is only one left, and it is up to the user to suppress errors.

- **ERROR** level log should be reviewed carefully.

  Error level logs can help identify potential problems. If there are too many error level logs, it will hide the actual problem. When it goes smoothly, there should be no error level logs. According to experience, 95% of successful runs should not contain any error level logs.

some tips,

- By reading the log, you should be able to understand the progress without having to look at the code. And logs describe business logic, not code logic. A bad example, "4 items found: [a , b , c]", should be "found 4 channels, unique names: [a, b, c]".
- Make each log line unique in the code. If you must check where the log is printed in the code. We can quickly find the code by searching. A bad example, `log.info("received stop signal")`, should be `log.info("received stop signal in lisa_runner")`.
- Do not repeat similar lines in succession. It is worth adding logic and variables to reduce redundant logs.
- Reduce log lines. If two lines of logs always appear together, merge them into one line. The impact of log lines on readability is much greater than the length of the log.
- Associate related logs through shared context. In the case of concurrency, this is very important. A bad example, "cmd: echo hello world", "cmd: hello world" can be "cmd[666]: echo hello world", "cmd[666]: hello world".

### Error message

There are two kinds of error messages in LISA. The first is an error message, and it does not fail. It will be printed as stderr and will be more obvious when the test case fails. The second is a one-line message in the failed test case. This section applies to two of them, but the second one is more important because we want it to be the only information that helps understand the failed test case.

In LISA, failed, skipped, and some passed test cases have a message. It specifies the reason the test case failed or skipped. Through this message, the user can understand what will happen and can act. Therefore, this message should be as helpful as possible.

The error message should include what happened and how to resolve it. It may not be easy to provide all the information for the first time, but guesswork is also helpful. At the same time, the original error message is also useful, please don't hide it.

For examples,

- "The subscription ID [aaa] could not be found, please make sure it exists and is accessible by the current account". A bad example, "The subscription ID [aaa] could not be found". This bad example illustrates what happened, but there is no suggestion.
- "The vm size [aaa] could not be found on the location [bbb]. This may be because the virtual machine size is not available in this location". A bad example, "The vm size [aaa] could not be found on the location [bbb]". It explains what happened, but it does not provide a guess at the root cause.

### Assertion

Assertions are heavily used in test code. Assertions are a simple pattern of "if some checks fail, raise an exception".

The assertion library includes commonly used patterns and detailed error messages. LISA uses `assertpy` as a standard assertion library, which provides Pythonic and test-friendly assertions.

When writing the assertion,

- Put the actual value in `assert_that` to keep the style consistent, and you can compare it with multiple expected values continuously.
- Assertions should be as comprehensive as possible, but do not repeat existing checks. For example, `assert_that(str1).is_equal_to('hello')` is enough, no need like `assert_that(str1).is_instance_of(str).is_equal_to('hello')`.
- Add a description to explain the business logic. If a malfunction occurs, these instructions will be displayed. For example, `assert_that(str1).described_as('echo back result is unexpected').is_equal_to('hello')` is better than `assert_that(str1).is_equal_to('hello')`.
- Try to use native assertions instead of manipulating the data yourself. `assert_that(vmbuses).is_length(6)` is better than `assert_that(len(vmbuses)).is_equal_to(6)`. It is simpler and the error message is clearer.
- Don't forget to use powerful collection assertions. They can compare ordered list by `contains` (actual value is superset), `is_subset_of` (actual value is subset), and others.

Learn more from [examples](../examples/testsuites) and [assertpy document](https://github.com/assertpy/assertpy#readme).

## Troubleshooting excellence

Test failure is a common phenomenon. Therefore, perform troubleshooting frequently. There are some useful ways to troubleshoot failures. In the list below, the higher items are better than the lower items because of its lower cost of analysis.

1. Single line message. A one-line message is sent with the test result status. If this message clearly describes the root cause, no other digging is necessary. You can even perform some automated actions to match messages and act.
2. Test case log. LISA provides a complete log for each run, which includes the output of all test cases, all threads, and all nodes. This file can be regarded as the default log, which is easy to search.
3. Other log files. Some original logs may be divided into test cases. After finding out the cause, it is easier to find out. But it needs to download and browse the test result files.
4. Reproduce in the environment. It is costly but contains most of the original information. But sometimes, the problem cannot be reproduced.

In LISA, test cases fail due to exceptions, and exception messages are treated as single-line messages. When writing test cases, it's time to adjust the exception message. Therefore, after completing the test case, many errors will be explained well.

## Test code excellence

Your code is an example of others, and they will follow your approach. Therefore, both good and bad practices will be amplified.

In LISA, test code should be organized according to business logic. This means that the code should perform the purpose of the test like a test specification. The underlying logic should be implemented elsewhere, such as tools, functions, or private methods in test suites.

Be careful when using `sleep`! The only way to use sleep is in polling mode. This means that you must wait for something with regular inspections. In the inspection cycle, you can wait for a reasonable period. Don't wait for 10 seconds of sleep. This causes two problems, 1) if it is too short, the case may fail; 2) if it is long enough, it will slow down the running speed.

Please keep in mind that your code may be copied by others.

### Compositions of test

The LISA test is composed of metadata, setting/cleaning up, and test body.

### Metadata

Metadata is used to provide documentation and the settings of test suites and test cases.

#### Test suite metadata

- **area** classifies test suites by belonging. When it needs to have a special validation on some area, it can be used to filter test cases. The values can be provisioning, cpu, memory, storage, network, etc.
- **category** categorizes test cases by test type. It includes functional, performance, pressure, and community. Performance and stress test cases take longer to run, which is not included in regular operations. Community test cases are wrappers that help provide results comparable to the community.
- **description** should introduce this test suite, including purpose, coverage, and any other content, which is helpful to understand this test suite.
- **name** is optional. The default name is the class name and can be replaced with the name field. The name is part of the test name. Just like the name space in a programming language.
- **requirement** defines the default requirements for this test suite and can be rewritten at the test case level. Learn more from [concepts](concepts.md).

See [examples](../examples/testsuites) for details.

```python
@TestSuiteMetadata(
    area="provisioning",
    category="functional",
    description="""
    This test suite uses to verify if an environment can be provisioned correct or not.

    - The basic smoke test can run on all images to determinate if a image can boot and
    reboot.
    - Other provisioning tests verify if an environment can be provisioned with special
    hardware configurations.
    """,
)
class Provisioning(TestSuite):
    ...
```

#### Test case metadata

- **priority** priority depends on the impact of the test case and is used to determine how often to run the case. Learn more from [concepts](concepts.md).
- **description** explains the purpose and procedures of the test. It is used to generate test specification documents.
- **requirement** define the requirements in this case. If no requirement is specified, the test suite or global default requirements will be used.

See [examples](../examples/testsuites) for details.

```python
@TestCaseMetadata(
    description="""
    This case verifies whether a node is operating normally.

    Steps,
    1. Connect to TCP port 22. If it's not connectable, failed and check whether
        there is kernel panic.
    2. Connect to SSH port 22, and reboot the node. If there is an error and kernel
        panic, fail the case. If it's not connectable, also fail the case.
    3. If there is another error, but not kernel panic or tcp connection, pass with
        warning.
    4. Otherwise, fully passed.
    """,
    priority=0,
    requirement=simple_requirement(
        environment_status=EnvironmentStatus.Deployed,
        supported_features=[SerialConsole],
    ),
)
def smoke_test(self, case_name: str) -> None:
    ...
```

### Test case body

Learn more from [test code excellence](#test-code-excellence) and learn how to use below LISA components to speed up development. The [examples](../examples/testsuites) and [Microsoft tests](../microsoft/tests) are good examples.

The method signature can use environment, node and other arguments like the following.

```python
def hello(self, case_name: str, node: Node, environment: Environment) -> None:
    ...
```

### Setup and cleanup

There are four methods: 1) before_suite, after_suite and 2) before_case, after_case. They will be called in the corresponding steps. When writing test cases, they are used to share common logic or variables.

The kwargs supports variables similar to those in test methods.

```python
def before_suite(self, **kwargs: Any) -> None:
    ...

def after_suite(self, **kwargs: Any) -> None:
    ...

def before_case(self, **kwargs: Any) -> None:
    ...

def after_case(self, **kwargs: Any) -> None:
    ...
```

## Use components in code

LISA wraps the shared logic in the following components. When implementing test cases, you may need a new component, and you are welcome to contribute to it. Make sure to read [concepts](concepts.md) to understand the following components. This section focuses on how to use them in the test code.

### Environment and node

The environment and node variables are obtained from the method arguments `def hello(self, node: Node, environment: Environment)`. If there are multiple nodes in the environment, you can get them from `environment.nodes`. The node can run any command, but it is recommended to implement the logic in the tool and obtain the tool through `node.tools[ToolName]`.

### Tool

When calling `node.tools[ToolName]`, LISA will check if the tool is installed. If it is not, LISA will install it. After that, an instance of the tool will be returned.  The instance is available until the node is recycled. Therefore, when `node.tools[ToolName]` is called again, it will not perform the installation again.

### Scripts

The script is like the tool and needs to be uploaded to the node before use. Before using the script, you need to define the following script builder.

```python
self._echo_script = CustomScriptBuilder(
    Path(__file__).parent.joinpath("scripts"), ["echo.sh"]
)
```

Once defined, it can be used like `script: CustomScript = node.tools[self._echo_script]`.

Please note that it is recommended that you use the tools in LISA instead of writing scripts. Bash scripts are not as flexible as Python, so we prefer to write logic in Python.

### Features

This feature needs to be declared in the test requirements of the test suite or test case, as shown below. This means that the test case requires this feature, and if the feature is not available in the environment, this test case will be skipped.

```python
@TestCaseMetadata(
    requirement=simple_requirement(
        supported_features=[SerialConsole],
    ),
)
```

After the declaration, the usage is like the tool, but it is obtained from `node.features[SerialConsole]`.

## Best practices

### Debug in ready environment

When debugging test cases or tools, it can be done in local computer, in the ready environment, or in the deployed Azure environment. This can save a lot of deployment time.

### Written by non-native English speakers

Today, there are some great tools to help you create high-quality English documents. If writing in English is challenging, please try the following steps.

1. Write in your language first.
2. Use machine translation such as [Microsoft Translator](https://www.bing.com/translator/) and [Google translate](https://translate.google.com/) to convert to English.
3. Convert the English version back to your language. If it doesn't make sense now, it means the sentence is too complicated. Make it simpler, and then start from step 1 again.
4. Once satisfied, please use [Microsoft Editor](https://www.microsoft.com/en-us/microsoft-365/microsoft-editor) to fix the grammar and conventions.
5. Learning from the above tools, your writing will continue to improve.
