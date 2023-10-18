How to write test suites/cases
==============================

-  `Preparation <#preparation>`__
-  `Test composition <#test-composition>`__

   -  `Metadata <#metadata>`__

      -  `Metadata in test suite <#metadata-in-test-suite>`__
      -  `Metadata in test case <#metadata-in-test-case>`__

   -  `Test case body <#test-case-body>`__
   -  `Setup and clean-up <#setup-and-clean-up>`__

-  `Using extensions <#using-extensions>`__

   -  `Environment and node <#environment-and-node>`__
   -  `Tool <#tool>`__
   -  `Scripts <#scripts>`__
   -  `Features <#features>`__
   -  `Hooks <#hooks>`__

      -  `get_environment_information <#get-environment-information>`__
      -  `azure_deploy_failed <#azure-deploy-failed>`__
      -  `azure_update_arm_template <#azure-update-arm-template>`__

-  `Best practices <#best-practices>`__

   -  `Debug in ready environment <#debug-in-ready-environment>`__

Preparation
-----------

Before getting down to do some exciting coding, we recommend that you read the
following documents to ensure a better LISA development experience. We believe
that the engineering excellence is equally important in addition to new test
cases, since any test case will be run thousands of times, and many people will
read and troubleshoot it. Therefore, a good test case following the guidelines
can save everyone's time.

-  :doc:`Basic concepts <concepts>` introduces design considerations
   and how components work together in LISA. We recommend every LISA developer
   go through this before coding.
-  :doc:`Coding guidelines <guidelines>` covers our coding guidelines
   such as naming, code, comment conventions, etc.
-  :doc:`Development setup <dev_setup>` introduces how to setup
   environment and code checks.
-  :doc:`Extensions <extension>` introduces how to develop extensions
   for LISA. In some cases, you may need to improve or implement extensions for
   new test cases.

Test composition
----------------

A typical test case includes definition, setup, run, and validation.

   .. figure:: ../img/sample.png
      :alt: sample test case


Test definition
~~~~~~~~~~~~~~~

The test definitions provides documentations and settings for test cases and
test suites, illustrates the main test logic, and is used to generate
specifications. Both of the following examples are taken from `provision.py
<https://github.com/microsoft/lisa/blob/main/microsoft/testsuites/core/provisioning.py>`__.
See `example tests
<https://github.com/microsoft/lisa/tree/main/examples/testsuites>`__ for more
examples.

Definition in test suite
^^^^^^^^^^^^^^^^^^^^^^^^

A test suite is a set of test cases with similar test purposes or shared
steps.

.. code:: python

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
       owner="Microsoft",
   )
   class Provisioning(TestSuite):
       ...

-  **area** classifies test suites by their task field. When it needs to
   have a special validation on some area, it can be used to filter test
   cases. It can be provisioning, CPU, memory, storage, network, etc.
-  **category** categorizes test cases by test type. It includes
   functional, performance, stress, and community. Performance and
   stress test cases take longer time to run, which are not included in
   regular operations. Community test cases are wrappers that help
   provide results comparable to the community.
-  **description** introduces purpose, coverage, why these test cases
   are bundled together and other content of the test suite, which makes
   clarity the test suite.
-  **name** is optional. The default name is the class name and will be
   overridden by this field if provided. It is part of the test name,
   just like the namespace in a programming language.
-  **requirement** is optional. A test case without this field means it
   does not have any requirement. It defines the default requirement for
   this test suite and can be overwritten at the test case level. Learn
   more from :ref:`write_test/concepts:requirement and capability`.
-  **owner** defines the owner of this test case. The default value is
   "Microsoft". The owner information displays in test list, and used for support.


Definition in test case
^^^^^^^^^^^^^^^^^^^^^^^

.. code:: python

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
       timeout=3600,
       use_new_environment=False,
       owner="",
   )
   def smoke_test(self, case_name: str) -> None:
       ...

-  **description** explains the purpose and procedures of the test. As
   said before, it is also used to generate test specification
   documents.
-  **priority** depends on the impact of the test case and is used to
   determine how often to run the case. A lower priority means a test
   case of more importance, and thus it will be run more often. The
   lowest value (most prioritized) is ``0``.
-  **requirement** defines the requirements in this case. If no
   requirement specified, the test suite's or the default global
   requirements will apply.
-  **timeout** defines when the test case will be ended by timeout. The default
   value is 3600 seconds. It applies to test method and before/after test case
   methods as well. The timeout of before/after suite is 3600, which is not
   changeable.
-  **use_new_environment** specify if this test case need a new environment. The
   default value is False. If it's True, the test case will run in a new
   deployed environment.
-  **owner** Refer to the owner property of test suite.

Note for a regression test case, which deals with further issues that
the fixed bug might cause, the related bugs should be presented. It is
also helpful to include impact of failure in metadata.

Test case body
~~~~~~~~~~~~~~

The test case body contains the actual implementations of the test. You
can import existing ``tools`` to verify certain purposes. If existing
``tools`` cannot realize your test purpose, it is recommended that you
wrap your test codes into functions, integrate them into new ``tools``,
and then only call functions like ``assert_that`` in test case body to
verify. The section below explains how to do this.

The method accepts ``environment``, ``node`` and other arguments as follows. An
example from `helloworld.py
<https://github.com/microsoft/lisa/blob/main/examples/testsuites/helloworld.py>`__:

.. code:: python

   def hello(self, case_name: str, node: Node, environment: Environment) -> None:
       ...
       assert_that(result.stdout).is_equal_to(hello_world)
       assert_that(result.stderr).is_equal_to("")
       assert_that(result.exit_code).is_equal_to(0)

Find more examples in `example tests
<https://github.com/microsoft/lisa/tree/main/examples/testsuites>`__ and
`Microsoft tests
<https://github.com/microsoft/lisa/tree/main/microsoft/testsuites>`__.

Setup and clean-up
~~~~~~~~~~~~~~~~~~

There are two methods to setup and cleanup for test cases: ``before_case`` and
``after_case``.

They are used to share common logic or variables among test cases. They
will be called in the corresponding step.

The kwargs supports variables similar to those in test methods.

The ``before_case`` is used to setup environment or prepare test data. It will
be called before each test case in the same test suite. If it fails, the test
case will be skipped.

The ``after_case`` is used to cleanup and recover the environment. It will be
called after each test case in the same test suite. It's called regardless the
test result. It doesn't affect the test result, when it fails.

.. code:: python

   def before_case(self, **kwargs: Any) -> None:
       ...

   def after_case(self, **kwargs: Any) -> None:
       ...

Using extensions
----------------

When implementing test cases, you may need to use some existing
extensions, or you are welcome to create your own. This section focuses
on how to use them in the test code.

Read :doc:`concepts <concepts>` to understand which extension does what and
:doc:`how to write extensions <extension>` to develop new extensions.

Environment and node
~~~~~~~~~~~~~~~~~~~~

The ``environment`` and ``node`` variables are obtained from the method
arguments ``def hello(self, node: Node, environment: Environment)``. If
there are multiple nodes in the environment, you can use
``environment.nodes`` to get them. The node per se can run any command,
but it is recommended to implement the logic in ``tools`` and obtain the
tool by ``node.tools[ToolName]``.

Tool
~~~~

As said, call ``node.tools[ToolName]`` to obtain the tool. When called,
LISA will first check if the tool is installed. If not, LISA will
install it, and after that, an instance of the tool will be returned.
The instance is available until the node is recycled, which means the
same tool is already ready to use when ``node.tools[ToolName]`` is
called again, as to avoid the redundant installation.

Scripts
~~~~~~~

The ``script``, like the ``tool``, needs to be uploaded to the node
before use. In addition, you need to define the following script builder
before using the script.

.. code:: python

   self._echo_script = CustomScriptBuilder(
       Path(__file__).parent.joinpath("scripts"), ["echo.sh"]
   )

Once defined, the script can be used like
``script: CustomScript = node.tools[self._echo_script]``.

Please note that it is recommended that you use the tools in LISA
instead of writing scripts. Bash scripts are not as flexible as Python,
so we prefer to write logic in Python.

Features
~~~~~~~~

The ``feature`` needs to be declared in the requirements of the test
suite or test case, as shown below. It means that the test case requires
the feature, and if the feature is not available in the environment, the
test case will be skipped.

.. code:: python

   @TestCaseMetadata(
       requirement=simple_requirement(
           supported_features=[SerialConsole],
       ),
   )

After the declaration, you can use the feature just like the tool, by
calling ``node.features[SerialConsole]``.

Hooks
~~~~~

Hooks are used to insert extension logic in the platform.

update_test_result_message
^^^^^^^^^^^^^^^^^^^^^^^^^^

Called when a test result message will be sent to notifier. In this hook, the
result message can be modified for extension. But be carefully, it may break
other functionality.

.. code:: python

      @hookimpl
      def update_test_result_message(
            self, message: TestResultMessage
      ) -> None:
            ...

get_environment_information
^^^^^^^^^^^^^^^^^^^^^^^^^^^

It returns the information of an environment. It's called when a test
case is completed.

Please note that to avoid the mutual influence of hooks, there is no
upper ``try...except...``. If a hook fails, it will fail the entire run.
If you find such a problem, please solve it first.

.. code:: python

   @hookimpl  # type: ignore
   def get_environment_information(self, environment: Environment) -> Dict[str, str]:
       information: Dict[str, str] = {}

azure_deploy_failed
^^^^^^^^^^^^^^^^^^^

Called when Azure deployment fails. This is an opportunity to return a better
error message. Learn from example in `hooks.py
<https://github.com/microsoft/lisa/blob/main/lisa/sut_orchestrator/azure/hooks.py>`__.

.. code:: python

   @hookimpl  # type: ignore
   def azure_deploy_failed(self, error_message: str) -> None:
       for message, pattern, exception_type in self.__error_maps:
           if pattern.findall(error_message):
               raise exception_type(f"{message}. {error_message}")

azure_update_arm_template
^^^^^^^^^^^^^^^^^^^^^^^^^

Called when it needs to update ARM template before deploying to Azure.

.. code:: python

       @hookimpl
       def azure_update_arm_template(
           self, template: Any, environment: Environment
       ) -> None:
           ...


Best practices
--------------

Debug in ready environment
~~~~~~~~~~~~~~~~~~~~~~~~~~

Debugging test cases or tools can be done on a local computer, in the
ready environment, or in the deployed Azure environment. We recommend
the latter two methods as they can save a lot of deployment time.
