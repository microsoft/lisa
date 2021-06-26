# How to write extensions in LISA

- [Components](#components)
  - [Common](#common)
    - [Extend schema](#extend-schema)
    - [Which method must be implemented](#which-method-must-be-implemented)
  - [Notifier](#notifier)
  - [Tool](#tool)
  - [CustomScript](#customscript)
  - [Feature](#feature)
    - [Create a new feature](#create-a-new-feature)
    - [Support an existing feature in a platform](#support-an-existing-feature-in-a-platform)
    - [Use a feature](#use-a-feature)
  - [Combinator](#combinator)
  - [Transformer](#transformer)
  - [Platform](#platform)
- [Hooks](#hooks)
  - [Implement a hook](#implement-a-hook)
  - [`get_environment_information`](#get_environment_information)
  - [`azure_deploy_failed`](#azure_deploy_failed)
  - [`azure_update_arm_template`](#azure_update_arm_template)

LISA uses extensions to share code in test cases and makes it flexibly
applicable to various situations. There are two kinds of extensions.

The following content links to the code, which will be constructed using
docstrings in the future.

## Components

Before starting to extend, please learn the [concepts](./concepts.md) of
components.

### Common

#### Extend schema

Components such as the platform and notification program support extended schema
in runbook.

The runbook uses [dataclass](https://docs.python.org/3/library/dataclasses.html)
for definition, [dataclass-json](https://github.com/lidatong/dataclasses-json/)
performs deserialization, and then
[marshmallow](https://marshmallow.readthedocs.io/en/3.0/api_reference.html)
validates the schema.

See more examples in [schema.py](../lisa/schema.py), if you need to extend
runbook schema.

#### Which method must be implemented

If a method needs to be implemented, it may raise `NotImplementedError` in the
body or annotate with `@abstractmethod`. The `@abstractmethod` is not used
everywhere, because it does not support to be used as a type in typing.

### Notifier

The base class is Notifier in [notifier.py](../lisa/notifier.py). The simplest
example is [console.py](../lisa/notifiers/console.py). A completed example is
[html.py](../lisa/notifiers/html.py).

If the notifier needs to set up from the runbook, implement `TypedSchema`. Learn
more from `ConsoleSchema` in [console.py](../lisa/notifiers/console.py).

Note that the current implementation does not process messages in isolated
threads, so if the implementation is slow, it may slow down the overall
operation speed.

### Tool

The base class is the `Tool` in [executable.py](../lisa/executable.py). All
examples are in [tools](../lisa/tools).

- [cat.py](../lisa/tools/cat.py) is the simplest example.
- [gcc.py](../lisa/tools/gcc.py) supports installation.
- [echo.py](../lisa/tools/echo.py) supports Windows.
- [ntttcp.py](../lisa/tools/ntttcp.py) shows how to specify dependencies between
  tools through the `dependencies` property.
- [lsvmbus.py](../lisa/tools/lsvmbus.py) is a complex example. It handles
  different behaviors of Linux distributions and returns structured results to
  test cases.

In simple terms, the tool runs the command, returns the output, and parses it
into a structure. When implementing tools, avoid returning original results to
test cases. It needs to parse the result and return a structured object, such as
[lsvmbus.py](../lisa/tools/lsvmbus.py). This allows more logic to be shared.

Learn more about how to use the tool from
[helloworld.py](../examples/testsuites/helloworld.py).

```python
echo = node.tools[Echo]
...
result = echo.run(hello_world)
assert_that(result.stdout).is_equal_to(hello_world)
```

### CustomScript

The `CustomScript` is like a lightweight tool. However, unless there are serious
performance issues or other reasons, please avoid using it because it will
return the original results to the test case. You can also package custom
scripts as tools.

To use the scripts,

1. Define the scripts through `CustomScriptBuilder`. Learn more from
   [withscript.py](../examples/testsuites/withscript.py).

    ```python
    self._echo_script = CustomScriptBuilder(
        Path(__file__).parent.joinpath("scripts"), ["echo.sh"]
    )
    ```

2. Use it like a tool. Learn more from
   [withscript.py](../examples/testsuites/withscript.py).

    ```python
    script: CustomScript = node.tools[self._echo_script]
    result1 = script.run()
    ```

### Feature

The following content takes `SerialConsole` as an example to introduce the
feature.

#### Create a new feature

It needs to implement a base class that is called by the test cases. It needs to
implement common and shareable logic. Learn more from `SerialConsole` in
[serial_console.py](../lisa/features/serial_console.py).

#### Support an existing feature in a platform

1. Implement the feature, so that it can work normally. Learn more from the
   `SerialConsole` implementation in Azure's
   [features.py](../lisa/sut_orchestrator/azure/features.py).

1. The platform should declare which features it supports, and where is the
   implementations of features. Learn more from Azure's
   [platform_.py](../lisa/sut_orchestrator/azure/platform_.py).

    ```python
    @classmethod
    def supported_features(cls) -> List[Type[Feature]]:
        return [features.StartStop, features.SerialConsole]
    ```

1. When preparing an environment, the platform should set the supported features
   on nodes. Learn more from Azure's
   [platform_.py](../lisa/sut_orchestrator/azure/platform_.py).

    ```python
    node_space.features = search_space.SetSpace[str](is_allow_set=True)
    node_space.features.update(
        [features.StartStop.name(), features.SerialConsole.name()]
    )
    ```

#### Use a feature

1. Declare in the metadata which features are required. If the environment does
   not support this feature, the test case will be skipped. Learn more from
   [provisioning.py](../microsoft/testsuites/core/provisioning.py).

    ```python
    requirement=simple_requirement(
        supported_features=[SerialConsole],
    ```

1. Using features is like using tools. Learn more from
   [provisioning.py](../microsoft/testsuites/core/provisioning.py).

    ```python
    serial_console = node.features[SerialConsole]
    # if there is any panic, fail before partial pass
    serial_console.check_panic(saved_path=case_path, stage="reboot")
    ```

### Combinator

The base class is [combinator.py](../lisa/combinator.py). The full matrix
implementation is [grid_combinator.py](../lisa/combinators/grid_combinator.py).

### Transformer

The base class is [transformer.py](../lisa/transformer.py). The simple example
is [to_list.py](../lisa/transfomers/to_list.py).

### Platform

The base class is [platform_.py](../lisa/platform_.py). The simplest example is
[ready.py](../lisa/sut_orchestrator/ready.py). A complete example is Azure's
[platform_.py](../lisa/sut_orchestrator/azure/platform_.py).

If a platform needs to specify settings in runbook, it can be implemented in two
places.

1. Platform schema. Learn more from `AzurePlatformSchema` in Azure's
   [platform_.py](../lisa/sut_orchestrator/azure/platform_.py).

1. Node schema. Learn more from `AzureNodeSchema` in Azure's
   [common.py](../lisa/sut_orchestrator/azure/common.py).

1. Use them in the platform code. Learn more from Azure's
   [platform_.py](../lisa/sut_orchestrator/azure/platform_.py).

    ```python
    azure_runbook: AzurePlatformSchema = self._runbook.get_extended_runbook(
        AzurePlatformSchema
    )
    azure_node_runbook = node_space.get_extended_runbook(
        AzureNodeSchema, type_name=AZURE
    )
    ```

## Hooks

Hooks are supported by [pluggy](https://pluggy.readthedocs.io/en/latest/). Hooks
are used to insert extension logic in the platform. The list of hooks will
increase due to new requirements.

### Implement a hook

1. Implement a hook. Learn more from [platform_.py](../lisa/platform_.py).

    ```python
    @hookimpl  # type: ignore
    def get_environment_information(self, environment: Environment) -> Dict[str, str]:
        ...
    ```

2. Register the hook in place. Learn more from
   [platform_.py](../lisa/platform_.py)

    ```python
    plugin_manager.register(self)
    ```

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
[hooks.py](../lisa/sut_orchestrator/azure/hooks.py).

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
