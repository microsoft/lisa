# How to write extensions in LISA

- [Notifier](#notifier)
- [Tool](#tool)
- [CustomScript](#customscript)
- [Feature](#feature)
  - [Support an existing feature in a platform](#support-an-existing-feature-in-a-platform)
  - [Create a new feature](#create-a-new-feature)
  - [Use a feature](#use-a-feature)
- [Combinator](#combinator)
- [Transformer](#transformer)
- [Platform](#platform)
- [Hooks](#hooks)
  - [Implement a hook](#implement-a-hook)
  - [`get_environment_information`](#get_environment_information)
  - [`azure_deploy_failed`](#azure_deploy_failed)
  - [`azure_update_arm_template`](#azure_update_arm_template)
- [Some notes](#some-notes)
  - [Extend schema](#extend-schema)
  - [Which method must be implemented](#which-method-must-be-implemented)

LISA uses extensions to share code in test cases and makes it flexibly
applicable to various situations. Before starting to extend, please make sure
you understand the [concepts](concepts.md) of each extension.

The following content links to the code, which will be constructed using
docstrings in the future.

## Notifier

The base class is the `Notifier` in [notifier.py](../../lisa/notifier.py). All
examples are in [notifier](../../lisa/notifiers).

- [console.py](../../lisa/notifiers/console.py) is the simplest example.
- [html.py](../../lisa/notifiers/html.py) is a complete example.

If the notifier needs to be set up from the runbook, implement `TypedSchema`.
Learn more from `ConsoleSchema` in
[console.py](../../lisa/notifiers/console.py).

Note that the current implementation does not process messages in isolated
threads, so if the implementation is slow, it may slow down the overall
operation speed.

## Tool

The base class is the `Tool` in [executable.py](../../lisa/executable.py). All
examples are in [tools](../../lisa/tools).

- [cat.py](../../lisa/tools/cat.py) is the simplest example.
- [gcc.py](../../lisa/tools/gcc.py) supports installation.
- [echo.py](../../lisa/tools/echo.py) supports Windows.
- [ntttcp.py](../../lisa/tools/ntttcp.py) shows how to specify dependencies
  between tools through the `dependencies` property.
- [lsvmbus.py](../../lisa/tools/lsvmbus.py) is a complex example, that handles
  different behaviors of Linux distributions and returns structured results to
  test cases.

In simple terms, the tool runs the command, returns the output, and parses it
into a structure. When implementing tools, try to avoid returning original
results to test cases, instead, parse the result and return a structured object,
such as in [lsvmbus.py](../../lisa/tools/lsvmbus.py). This code logic is
preferred because it allows more coherence.

> Note, although in [using extensions](write_case.md#extensions) we told you
that installation is automatically checked and done, yet you must implement the
`_install` method with the correct dependency as a prerequisite. See
[gcc.py](../../lisa/tools/gcc.py).

Learn more about how to use the tool from
[helloworld.py](../../examples/testsuites/helloworld.py).

```python
echo = node.tools[Echo]
...
result = echo.run(hello_world)
assert_that(result.stdout).is_equal_to(hello_world)
```

## CustomScript

The `CustomScript` is like a lightweight tool. However, **please avoid using
it** unless there are serious performance issues or other reasons, because it
will return the original results to the test case. You can also package custom
scripts as tools.

The base class is the `CustomScript` in
[executable.py](../../lisa/executable.py).

To use the scripts,

1. Define the scripts using `CustomScriptBuilder`.

    ```python
    self._echo_script = CustomScriptBuilder(
        Path(__file__).parent.joinpath("scripts"), ["echo.sh"]
    )
    ```

2. Use it like a tool.

    ```python
    script: CustomScript = node.tools[self._echo_script]
    result1 = script.run()
    ```

3. Learn more from [withscript.py](../../examples/testsuites/withscript.py).

## Feature

The base class is [feature.py](../../lisa/feature.py). All examples are in
[features](../../lisa/features) and Azure's
[features.py](../../lisa/sut_orchestrator/azure/features.py).

The following content takes `SerialConsole` as an example to introduce the
feature.

### Support an existing feature in a platform

1. Implement the feature, so that it can work normally. Learn more from the
   `SerialConsole` implementation in Azure's
   [features.py](../../lisa/sut_orchestrator/azure/features.py).

2. The platform should declare which features it supports, and where the
   implementations of features are.

    ```python
    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        return [features.StartStop, features.SerialConsole]
    ```

3. When preparing an environment, the platform should set the supported features
   on nodes.

    ```python
    node_space.features = search_space.SetSpace[str](is_allow_set=True)
    node_space.features.update(
        [features.StartStop.name(), features.SerialConsole.name()]
    )
    ```

4. Learn more from Azure's
   [platform_.py](../../lisa/sut_orchestrator/azure/platform_.py).

### Create a new feature

To create a new feature, you need to implement a base class that is called by
the test cases, as to keep a common and shareable code logic. Learn more from
`SerialConsole` in [serial_console.py](../../lisa/features/serial_console.py).

### Use a feature

1. Declare in the metadata which features are required. If the environment does
   not support this feature, the test case will be skipped.

    ```python
    requirement=simple_requirement(
        supported_features=[SerialConsole],
    ```

2. Using features is like using tools.

    ```python
    serial_console = node.features[SerialConsole]
    # if there is any panic, fail before partial pass
    serial_console.check_panic(saved_path=case_path, stage="reboot")
    ```

3. Learn more from
   [provisioning.py](../../microsoft/testsuites/core/provisioning.py).

## Combinator

The base class is [combinator.py](../../lisa/combinator.py). All examples are in
[combinators](../../lisa/combinators).

- [grid_combinator.py](../../lisa/combinators/grid_combinator.py) supports a
  full matrix combination.
- [batch_combinator.py](../../lisa/combinators/batch_combinator.py) supports a
  batch combination.

## Transformer

The base class is [transformer.py](../../lisa/transformer.py). All examples are
in [transformers](../../lisa/transformers).

- [to_list.py](../../lisa/transfomers/to_list.py) is the simplest example.

## Platform

The base class is [platform_.py](../../lisa/platform_.py). 

- [ready.py](../../lisa/sut_orchestrator/ready.py) is the simplest example. 
- [platform_.py](../../lisa/sut_orchestrator/azure/platform_.py) is a complete
  example of Azure.

If a platform needs to specify settings in runbook, it can be implemented in two
places.

1. Platform schema. Learn more from `AzurePlatformSchema` in Azure's
   [platform_.py](../../lisa/sut_orchestrator/azure/platform_.py).

1. Node schema. Learn more from `AzureNodeSchema` in Azure's
   [common.py](../../lisa/sut_orchestrator/azure/common.py).

1. Use them in the platform code. Learn more from Azure's
   [platform_.py](../../lisa/sut_orchestrator/azure/platform_.py).

    ```python
    azure_runbook: AzurePlatformSchema = self._runbook.get_extended_runbook(
        AzurePlatformSchema
    )
    azure_node_runbook = node_space.get_extended_runbook(
        AzureNodeSchema, type_name=AZURE
    )
    ```

## Hooks

Hooks are imported by [pluggy](https://pluggy.readthedocs.io/en/latest/). They
are used to insert extension logic in the platform. The current list of hooks
will expand due to new requirements. Take a look at [A definitive
example](https://github.com/pytest-dev/pluggy/blob/master/README.rst) to quickly
get started with [pluggy](https://pluggy.readthedocs.io/en/latest/).

### Implement a hook

1. Create a hook specification namespace.

    ```python
    class AzureHookSpec:

        @hookspec
        def azure_deploy_failed(self, error_message: str) -> None:
            ...
    ```

2. Define a hook and add some functions.

    ```python
    class Platform(...):

        @hookimpl  # type: ignore
        def get_environment_information(self, environment: Environment) -> Dict[str, str]:
            ...
    ```

3. Add the spec to the manager and register the hook in place.

    ```python
    plugin_manager.add_hookspecs(AzureHookSpec)
    plugin_manager.register(AzureHookSpecDefaultImpl())
    ```

4. Learn more from hooks in [platform_.py](../../lisa/platform_.py).

### `get_environment_information`

It returns the information of an environment. It's called when a test case is
completed.

Please note that to avoid the mutual influence of hooks, there is no upper
`try...except...`. If a hook fails, it will fail the entire run. If you find
such a problem, please solve it first.

```python
@hookimpl  # type: ignore
def get_environment_information(self, environment: Environment) -> Dict[str, str]:
    information: Dict[str, str] = {}
```

### `azure_deploy_failed`

Called when Azure deployment fails. This is an opportunity to return a better
error message. Learn from example in
[hooks.py](../../lisa/sut_orchestrator/azure/hooks.py).

```python
@hookimpl  # type: ignore
def azure_deploy_failed(self, error_message: str) -> None:
    for message, pattern, exception_type in self.__error_maps:
        if pattern.findall(error_message):
            raise exception_type(f"{message}. {error_message}")
```

### `azure_update_arm_template`

Called when it needs to update ARM template before deploying to Azure.

```python
    @hookimpl
    def azure_update_arm_template(
        self, template: Any, environment: Environment
    ) -> None:
        ...
```

## Some notes

### Extend schema

Extensions such as platforms and notifications support extended schema in
runbook.

The runbook uses [dataclass](https://docs.python.org/3/library/dataclasses.html)
for definition, [dataclass-json](https://github.com/lidatong/dataclasses-json/)
for deserialization, and
[marshmallow](https://marshmallow.readthedocs.io/en/3.0/api_reference.html) to
validate the schema.

See more examples in [schema.py](../../lisa/schema.py), if you need to extend
runbook schema.

### Which method must be implemented

If a method in a parent class needs to be implemented in child class, it may
raise a `NotImplementedError` inside the method body in the parent class and be
annotated with `@abstractmethod`. Be careful with `@abstractmethod` to use use
it only with `NotImplementedError` and nowhere else, because it is not support
as a type in `typing`.

---

Back to [how to write tests](write_case.md).