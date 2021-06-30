# How to write test suites/cases

- [Preparation](#preparation)
- [Test composition](#test-composition)
  - [Metadata](#metadata)
    - [Metadata in test case](#metadata-in-test-case)
    - [Metadata in test suite](#metadata-in-test-suite)
  - [Test case body](#test-case-body)
  - [Setup and clean-up](#setup-and-clean-up)
- [Extensions in code](#extensions-in-code)
  - [Environment and node](#environment-and-node)
  - [Tool](#tool)
  - [Scripts](#scripts)
  - [Features](#features)
- [Best practices](#best-practices)
  - [Debug in ready environment](#debug-in-ready-environment)

## Preparation

Before getting down to do some exciting coding, we recommend that you read the
following documents to understand LISA development better. In addition to how to
write test cases, we believe that the engineering excellence is equally
important. A test case will be run thousands of times, and many people will read
and troubleshoot it. Therefore, a good test case can save your and others' time.

- [Concepts](concepts.md) includes design considerations, how components work
  together. It's important to everyone who wants to write code in LISA.
- [Coding guidelines](guidelines.md) includes guidelines to follow, such as
  naming, code, comment conventions, etc.
- [Development setup](setup.md) includes how to setup environment, code checks.
- [Extensions](extension.md) includes how to develop extensions for LISA. In
  some cases, you may need to implement or improve extensions for new test
  cases.

## Test composition

The LISA test is composed of metadata, test body and setup/clean-up.

### Metadata

Metadata provides the documentation and the settings of test cases and test
suites, records the main test logic, and is used to generate specifications.

#### Metadata in test case

Each test case should have its own test purpose and steps. If it is a regression
test case, meaning it touches issues around the fixed bug, the related bug
should be presented. It is also helpful to include impact of failure in
metadata.

- **description** explains the purpose and procedures of the test. It is used to
  generate test specification documents.
- **priority** priority depends on the impact of the test case and is used to
  determine how often to run the case. Learn more from [concepts](concepts.md).
- **requirement** defines the requirements in this case. If no requirement is
  specified, the test suite or global default requirements will be used.

```python
@TestCaseMetadata(
    description="""
    This case verifies whether a node is operating normally.

    Steps,
    1. Connect to TCP port 22. If it's not connectable, failed and check whether
        there is kernel panic.
    2. Connect to SSH port 22, and reboot the node. If there is an error and kernel
        panic, fail the case. If it's not connectable, also fail the case.
    3. If there is another error, but not kernel panic or TCP connection, pass with
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

#### Metadata in test suite

A test suite is a set of test cases with similar test purposes or shared steps.

- **area** classifies test suites by their task field. When it needs to have a
  special validation on some area, it can be used to filter test cases. It can
  be provisioning, CPU, memory, storage, network, etc.
- **category** categorizes test cases by test type. It includes functional,
  performance, pressure, and community. Performance and stress test cases take
  longer to run, which is not included in regular operations. Community test
  cases are wrappers that help provide results comparable to the community.
- **description** should introduce this test suite, including purpose, coverage,
  why these test cases are bundled together and any other content, which helps
  understand this test suite.
- **name** is optional. The default name is the class name and can be replaced
  with the name field. The name is part of the test name, just like the name
  space in a programming language.
- **requirement** defines the default requirements for this test suite and can
  be rewritten at the test case level. Learn more from [concepts](concepts.md).

See [example tests](../../examples/testsuites) for details.

```python
@TestSuiteMetadata(
    area="provisioning",
    category="functional",
    description="""
    This test suite is to verify if an environment can be provisioned correct or not.

    - The basic smoke test can run on all images to determine if a image can boot and
    reboot.
    - Other provisioning tests verify if an environment can be provisioned with special
    hardware configurations.
    """,
)
class Provisioning(TestSuite):
    ...
```

### Test case body

Refer to the [example tests](../../examples/testsuites) and [Microsoft
tests](../../microsoft/testsuites) are good examples.

The method signature can use environment, node and other arguments like the
following.

```python
def hello(self, case_name: str, node: Node, environment: Environment) -> None:
    ...
```

### Setup and clean-up

There are four methods in two pairs: 1) before_suite, after_suite and 2)
before_case, after_case. They will be called in the corresponding steps. When
writing test cases, they are used to share common logic or variables.

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

## Extensions in code

LISA wraps the shared logic in code in different kinds of extensions with the
following components. When implementing test cases, you may want a new
component, and you are welcome to contribute to it. Read [concepts](concepts.md)
and [how write extensions](extension.md) for further knowledge. This section
focuses on how to use them in the test code.

### Environment and node

The environment and node variables are obtained from the method arguments `def
hello(self, node: Node, environment: Environment)`. If there are multiple nodes
in the environment, you can get them from `environment.nodes`. The node can run
any command, but it is recommended to implement the logic in the tool and obtain
the tool through `node.tools[ToolName]`.

### Tool

When calling `node.tools[ToolName]`, LISA will check if the tool is installed.
If it is not, LISA will install it. After that, an instance of the tool will be
returned.  The instance is available until the node is recycled. Therefore, when
`node.tools[ToolName]` is called again, it will not perform the installation
again.

### Scripts

The script is like the tool and needs to be uploaded to the node before use.
Before using the script, you need to define the following script builder.

```python
self._echo_script = CustomScriptBuilder(
    Path(__file__).parent.joinpath("scripts"), ["echo.sh"]
)
```

Once defined, it can be used like `script: CustomScript =
node.tools[self._echo_script]`.

Please note that it is recommended that you use the tools in LISA instead of
writing scripts. Bash scripts are not as flexible as Python, so we prefer to
write logic in Python.

### Features

This feature needs to be declared in the test requirements of the test suite or
test case, as shown below. This means that the test case requires this feature,
and if the feature is not available in the environment, this test case will be
skipped.

```python
@TestCaseMetadata(
    requirement=simple_requirement(
        supported_features=[SerialConsole],
    ),
)
```

After the declaration, the usage is like the tool, but it is obtained from
`node.features[SerialConsole]`.

## Best practices

### Debug in ready environment

Debugging test cases or tools can be done on a local computer, in the ready
environment, or in the deployed Azure environment. The latter can save a lot of
deployment time.
