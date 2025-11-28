How to write an extension in LISA
=================================

-  `Notifier <#notifier>`__
-  `Tool <#tool>`__
-  `CustomScript <#customscript>`__
-  `Feature <#feature>`__

   -  `Support an existing feature in a
      platform <#support-an-existing-feature-in-a-platform>`__
   -  `Create a new feature <#create-a-new-feature>`__
   -  `Use a feature <#use-a-feature>`__

-  `Combinator <#combinator>`__
-  `Transformer <#transformer>`__
-  `Platform <#platform>`__
-  `Hooks <#hooks>`__

   -  `Implement a hook <#implement-a-hook>`__

-  `Azure Template <#azure-template>`__
-  `Some notes <#some-notes>`__

   -  `Extend schema <#extend-schema>`__
   -  `Which method must be
      implemented <#which-method-must-be-implemented>`__

LISA uses extensions to share code in test cases and makes it flexibly
applicable to various situations. Before starting to extend, please make
sure you understand the :doc:`concepts <concepts>` of each extension.

The following content links to the code, which will be constructed using
docstrings in the future.

Notifier
--------

The base class is the :class:`Notifier` in ``notifiers``. All examples are in
`notifier <https://github.com/microsoft/lisa/tree/main/lisa/notifiers>`__.

.. autoclass:: lisa.notifier.Notifier

-  `console.py
   <https://github.com/microsoft/lisa/blob/main/lisa/notifiers/console.py>`__ is
   the simplest example.
-  `html.py
   <https://github.com/microsoft/lisa/blob/main/lisa/notifiers/html.py>`__ is a
   complete example.

If the notifier needs to be set up from the runbook, implement ``TypedSchema``.
Learn more from ``ConsoleSchema`` in `console.py
<https://github.com/microsoft/lisa/blob/main/lisa/notifiers/console.py>`__.

Note that the current implementation does not process messages in isolated
threads, so if the implementation is slow, it may slow down the overall
operation speed.

Tool
----

The base class is the :class:`Tool` in ``executable``. All examples
are in `tools <https://github.com/microsoft/lisa/blob/main/lisa/tools>`__.

.. autoclass:: lisa.executable.Tool

-  `cat.py
   <https://github.com/microsoft/lisa/blob/main/lisa/base_tools/cat.py>`__
   is the simplest example.
-  `gcc.py <https://github.com/microsoft/lisa/blob/main/lisa/tools/gcc.py>`__
   supports installation.
-  `echo.py <https://github.com/microsoft/lisa/blob/main/lisa/tools/echo.py>`__
   supports Windows.
-  `ntttcp.py
   <https://github.com/microsoft/lisa/blob/main/lisa/tools/ntttcp.py>`__ shows
   how to specify dependencies between tools through the ``dependencies``
   property.
-  `lsvmbus.py
   <https://github.com/microsoft/lisa/blob/main/lisa/tools/lsvmbus.py>`__ is a
   complex example, that handles different behaviors of Linux distributions and
   returns structured results to test cases.

In simple terms, the tool runs the command, returns the output, and parses it
into a structure. When implementing tools, try to avoid returning original
results to test cases, instead, parse the result and return a structured object,
such as in `lsvmbus.py
<https://github.com/microsoft/lisa/blob/main/lisa/tools/lsvmbus.py>`__. This
code logic is preferred because it allows more coherence.

.. note:

   Although in `using extensions <write_case.html#extensions>`__ we told
   you that installation is automatically checked and done, yet you must
   implement the ``_install`` method with the correct dependency as a
   prerequisite. See `gcc.py
   <https://github.com/microsoft/lisa/blob/main/lisa/tools/gcc.py>`__.

Learn more about how to use the tool from `helloworld.py
<https://github.com/microsoft/lisa/blob/main/examples/testsuites/helloworld.py>`__.

.. code:: python

   echo = node.tools[Echo]
   ...
   result = echo.run(hello_world)
   assert_that(result.stdout).is_equal_to(hello_world)

CustomScript
------------

The ``CustomScript`` is like a lightweight tool, which is composited by one or
more script files. However, **please avoid using it** unless there are serious
performance concerns, compatible with existing test cases or other reasons,
because it doesn't leverage all advantages of LISA. For example, the script runs
on nodes, the output may not be dumped into LISA log. The distro-agnostic
modules of tools cannot be leveraged.

The base class is the :class:`CustomScript` in ``executable``.

.. autoclass:: lisa.executable.CustomScript

To use the scripts,

1. Define the scripts using ``CustomScriptBuilder``.

   .. code:: python

      self._echo_script = CustomScriptBuilder(
          Path(__file__).parent.joinpath("scripts"), ["echo.sh"]
      )

2. Use it like a tool.

   .. code:: python

      script: CustomScript = node.tools[self._echo_script]
      result1 = script.run()

3. Learn more from
   `withscript.py
   <https://github.com/microsoft/lisa/blob/main/examples/testsuites/withscript.py>`__.

Feature
-------

The base class is :class:`Feature` in ``feature``. All examples are in `features
<https://github.com/microsoft/lisa/tree/main/lisa/features>`__ and Azure's
`features.py
<https://github.com/microsoft/lisa/blob/main/lisa/sut_orchestrator/azure/features.py>`__.

.. autoclass:: lisa.feature.Feature

The following content takes ``SerialConsole`` as an example to introduce
the feature.

Support an existing feature in a platform
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. Implement the feature, so that it can work normally. Learn more from
   the ``SerialConsole`` implementation in Azure's `features.py
   <https://github.com/microsoft/lisa/blob/main/lisa/sut_orchestrator/azure/features.py>`__.

2. The platform should declare which features it supports, and where the
   implementations of features are.

   .. code:: python

      @classmethod
      def supported_features(cls) -> List[Type[Feature]]:
          return [features.StartStop, features.SerialConsole]

3. When preparing an environment, the platform should set the supported
   features on nodes.

   .. code:: python

      node_space.features = search_space.SetSpace[str](is_allow_set=True)
      node_space.features.update(
          [features.StartStop.name(), features.SerialConsole.name()]
      )

4. Learn more from Azure's
   `platform_.py
   <https://github.com/microsoft/lisa/blob/main/lisa/sut_orchestrator/azure/platform_.py>`__.

Create a new feature
~~~~~~~~~~~~~~~~~~~~

To create a new feature, you need to implement a base class that is called by
the test cases, as to keep a common and shareable code logic. Learn more from
``SerialConsole`` in `serial_console.py
<https://github.com/microsoft/lisa/blob/main/lisa/features/serial_console.py>`__.

Use a feature
~~~~~~~~~~~~~

1. Declare in the metadata which features are required. If the
   environment does not support this feature, the test case will be
   skipped.

   .. code:: python

      requirement=simple_requirement(
          supported_features=[SerialConsole],
          ...
          )

2. Using features is like using tools.

   .. code:: python

      serial_console = node.features[SerialConsole]
      # if there is any panic, fail before partial pass
      serial_console.check_panic(saved_path=case_path, stage="reboot")

3. Learn more from
   `provisioning.py
   <https://github.com/microsoft/lisa/blob/main/microsoft/testsuites/core/provisioning.py>`__.

Combinator
----------

The base class is :class:`Combinator` in ``combinator``. All examples are in
`combinators <https://github.com/microsoft/lisa/tree/main/lisa/combinators>`__.

.. autoclass:: lisa.combinator.Combinator

-  `grid_combinator.py
   <https://github.com/microsoft/lisa/blob/main/lisa/combinators/grid_combinator.py>`__
   supports a full matrix combination.
-  `batch_combinator.py
   <https://github.com/microsoft/lisa/blob/main/lisa/combinators/batch_combinator.py>`__
   supports a batch combination.

Transformer
-----------

The base class is :class:`Transformer` in ``transformer``. All examples are in
`transformers
<https://github.com/microsoft/lisa/tree/main/lisa/transformers>`__.

.. autoclass:: lisa.transformer.Transformer

-  `to_list.py
   <https://github.com/microsoft/lisa/blob/main/lisa/transformers/to_list.py>`__
   is the simplest example.

Platform
--------

The base class is :class:`Platform` in ``platform_``.

.. autoclass:: lisa.platform_.Platform
   :undoc-members:

-  `ready.py
   <https://github.com/microsoft/lisa/blob/main/lisa/sut_orchestrator/ready.py>`__
   is the simplest example.
-  `platform_.py
   <https://github.com/microsoft/lisa/blob/main/lisa/sut_orchestrator/azure/platform_.py>`__
   is a complete example of Azure.

If a platform needs to specify settings in runbook, it can be
implemented in two places.

1. Platform schema. Learn more from ``AzurePlatformSchema`` in Azure's
   `platform_.py
   <https://github.com/microsoft/lisa/blob/main/lisa/sut_orchestrator/azure/platform_.py>`__.

2. Node schema. Learn more from ``AzureNodeSchema`` in Azure's
   `common.py
   <https://github.com/microsoft/lisa/blob/main/lisa/sut_orchestrator/azure/common.py>`__.

3. Use them in the platform code. Learn more from Azure's
   `platform_.py
   <https://github.com/microsoft/lisa/blob/main/lisa/sut_orchestrator/azure/platform_.py>`__.

   .. code:: python

      azure_runbook: AzurePlatformSchema = self._runbook.get_extended_runbook(
          AzurePlatformSchema
      )
      azure_node_runbook = node_space.get_extended_runbook(
          AzureNodeSchema, type_name=AZURE
      )

Hooks
-----

Hooks are imported by `pluggy <https://pluggy.readthedocs.io/en/latest/>`__. The
current list of hooks will expand due to new requirements. Take a look at `A
definitive example
<https://github.com/pytest-dev/pluggy/blob/master/README.rst>`__ to quickly get
started with `pluggy <https://pluggy.readthedocs.io/en/latest/>`__.

Implement a hook
~~~~~~~~~~~~~~~~

1. Create a hook specification namespace.

   .. code:: python

      class AzureHookSpec:

          @hookspec
          def azure_deploy_failed(self, error_message: str) -> None:
              ...

2. Define a hook and add some functions.

   .. code:: python

      class Platform(...):

          @hookimpl  # type: ignore
          def get_environment_information(self, environment: Environment) -> Dict[str, str]:
              ...

3. Add the spec to the manager and register the hook in place.

   .. code:: python

      plugin_manager.add_hookspecs(AzureHookSpec)
      plugin_manager.register(AzureHookSpecDefaultImpl())

4. Learn more from hooks in `platform_.py
<https://github.com/microsoft/lisa/blob/main/lisa/platform_.py>`__.

Azure Template
--------------

When provisioning resources in Azure, you have the flexibility to choose between utilizing the Azure template generated by Bicep or retaining the default ARM template currently in use. Learn more from :doc:`azure template reference <azure_template>`.

Some notes
----------

Extend schema
~~~~~~~~~~~~~

Extensions such as platforms and notifications support extended schema
in runbook.

The runbook uses
`dataclass <https://docs.python.org/3/library/dataclasses.html>`__ for
definition,
`dataclass-json <https://github.com/lidatong/dataclasses-json/>`__ for
deserialization, and
`marshmallow <https://marshmallow.readthedocs.io/en/3.0/api_reference.html>`__
to validate the schema.

See more examples in `schema.py
<https://github.com/microsoft/lisa/blob/main/lisa/schema.py>`__, if you need to
extend runbook schema.

Which method must be implemented
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

If a method in a parent class needs to be implemented in child class, it
may raise a ``NotImplementedError`` inside the method body in the parent
class and be annotated with ``@abstractmethod``. Be careful with
``@abstractmethod`` to use use it only with ``NotImplementedError`` and
nowhere else, because it is not support as a type in ``typing``.

--------------

Back to :doc:`how to write tests <write_case>`.
