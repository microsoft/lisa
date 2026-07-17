VM Extension Test Onboarding Strategy
======================================

Problem Statement
-----------------

As more VM extension publishers onboard functional validation tests to LISA,
the current approach leads to:

- **Redundant lifecycle code** — every publisher re-implements install →
  assert provisioned → uninstall
- **No consistent naming** — variable names, area names, and file structure
  vary across extensions
- **Scalability issues** — with 50+ extensions planned, copy-paste patterns
  create maintenance burden
- **Version hardcoding** — some tests embed extension versions in code,
  requiring PRs for version bumps

Solution: ``VmExtensionTestBase``
---------------------------------

A shared base class that provides reusable lifecycle helpers while allowing
each publisher to own their extension-specific test logic.

Architecture
~~~~~~~~~~~~

::

   ┌─────────────────────────────────────────────────────────────┐
   │              VmExtensionTestBase (base class)               │
   │                                                             │
   │  Reusable lifecycle helpers:                                │
   │  • _install(node, variables, settings)                      │
   │  • _assert_provisioned(result)                              │
   │  • _uninstall(node)                                         │
   │  • _assert_vm_reachable(node)                               │
   │  • _full_lifecycle(node, log, variables, settings)          │
   └────────────────────────────┬────────────────────────────────┘
                                │ inherits
          ┌─────────────────────┼─────────────────────┐
          │                     │                     │
          ▼                     ▼                     ▼
   ┌──────────────┐   ┌─────────────────┐   ┌───────────────┐
   │ CustomScript │   │ AzureMonitor    │   │ RunCommandV2  │
   │ Tests        │   │ AgentTests      │   │ Tests         │
   │              │   │                 │   │               │
   │ Extension-   │   │ Extension-      │   │ Extension-    │
   │ specific     │   │ specific        │   │ specific      │
   │ tests ONLY   │   │ tests ONLY      │   │ tests ONLY    │
   └──────────────┘   └─────────────────┘   └───────────────┘

Key Design Decisions
~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Decision
     - Rationale
   * - Publisher + type are class constants
     - They rarely change and uniquely identify the extension
   * - Version is always a runbook variable
     - Versions change frequently; no code changes needed for bumps
   * - Each extension has its own variable name
     - Enables testing multiple extensions in a single run
   * - ``EXTENSION_KEY`` drives all naming
     - One constant → consistent file names, area names, variables, tags
   * - Generic test remains as utility
     - Zero-code triage/smoke tool for ad-hoc validation

Naming Convention
~~~~~~~~~~~~~~~~~

Each extension declares an ``EXTENSION_KEY`` (snake_case). Everything derives
from it:

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * - Concern
     - Convention
     - Example (CustomScript)
   * - File name
     - ``{key}.py``
     - ``custom_script.py``
   * - Class name
     - ``{Key}Tests``
     - ``CustomScriptTests``
   * - Area name
     - ``vm_extension`` (shared)
     - ``vm_extension``
   * - Version variable
     - ``{key}_version``
     - ``custom_script_version``
   * - Azure resource name
     - ``{key}``
     - ``custom_script``
   * - Tags
     - ``["VM_Extension", "{ExtensionType}"]``
     - ``["VM_Extension", "CustomScript"]``
   * - Test method prefix
     - ``verify_{key}_*``
     - ``verify_custom_script_inline_cmd``

Runbook Configuration
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

   variable:
     # Each extension uses its own scoped variable — multiple extensions per run
     - name: custom_script_version
       value: "2.1"
     - name: azure_monitor_linux_agent_version
       value: "1.33"
     - name: run_command_v2_version
       value: "1.3"

- **Variable present** → extension tests run
- **Variable missing** → tests are skipped (not failed)
- **No code changes needed** to test a different version

Filtering Tests in Runbooks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All extension suites share ``area="vm_extension"``. To run tests for a
single extension, use the extension-specific tag in your runbook criteria:

.. code-block:: yaml

   # Run ALL VM extension tests
   - criteria:
       area: vm_extension

   # Run ONLY CustomScript tests
   - criteria:
       tags: CustomScript

   # Run ONLY RunCommand v2 tests
   - criteria:
       tags: RunCommandV2

   # Run by test name pattern (regex)
   - criteria:
       name: ".*customscript.*"

Each publisher suite **must** include both ``"VM_Extension"`` (shared) and an
extension-specific tag (typically the ``EXTENSION_TYPE`` value) in its
``@TestSuiteMetadata(tags=...)``.

Onboarding Checklist
~~~~~~~~~~~~~~~~~~~~

What publishers **must do**:

1. Pick an ``EXTENSION_KEY`` (unique, snake_case)
2. Create ``lisa/microsoft/testsuites/vm_extensions/runtime_extensions/{key}.py``
3. Subclass ``VmExtensionTestBase``, set ``PUBLISHER``, ``EXTENSION_TYPE``,
   ``EXTENSION_KEY``
4. Write **only** extension-specific test cases (unique behavior validation)
5. Use ``_full_lifecycle()`` for basic lifecycle validation — do NOT rewrite it
6. Start tests at ``Experimental`` maturity; promote to ``Stable`` after
   validation

What publishers **must NOT do**:

- Hardcode extension versions in test code
- Re-implement install/assert/delete logic
- Write tests that only check ``provisioning_state == "Succeeded"``
  (that's what ``_full_lifecycle`` does)
- Modify other publishers' test files

Rule for New Test Cases
~~~~~~~~~~~~~~~~~~~~~~~

   A publisher-specific test case is justified **only** if it validates
   behavior beyond basic lifecycle (e.g., output validation, specific
   settings, error scenarios, multi-extension interaction). If it's just
   install → assert provisioned → delete, call ``_full_lifecycle()``.

Extension-Specific Test Cases
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each extension has unique features that go beyond basic lifecycle validation.
Publishers should write test cases that exercise **their extension's specific
capabilities**. Below are examples of what extension-specific tests look like:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Extension
     - Feature-Specific Test Examples
   * - **CustomScript**
     - Validate inline ``commandToExecute`` stdout output; test ``fileUris``
       with public/private blobs; verify base64-encoded script execution; test
       gzipped script payload; assert failure on missing command
   * - **RunCommand v2**
     - Validate script output via ``instanceView``; test
       ``runAsUser``/``runAsPassword``; verify ``outputBlobUri`` upload; test
       ``errorBlobUri`` on failure; test timeout handling
   * - **VMAccess**
     - Validate password reset; verify SSH key injection; test user creation;
       verify certificate-based auth
   * - **AzureMonitorAgent**
     - Verify agent heartbeat in Log Analytics Workspace; validate metrics
       collection; test custom data collection rules
   * - **AzureDiskEncryption**
     - Verify disk encryption status; test encrypt/decrypt lifecycle; validate
       key vault integration

Example: CustomScript with output validation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   class CustomScriptTests(VmExtensionTestBase):
       PUBLISHER = "Microsoft.Azure.Extensions"
       EXTENSION_TYPE = "CustomScript"
       EXTENSION_KEY = "custom_script"

       @TestCaseMetadata(
           description="Validates inline commandToExecute produces expected output.",
           priority=3,
       )
       def verify_custom_script_inline_command_output(
           self, log: Logger, node: Node, variables: Dict[str, Any]
       ) -> None:
           # This test is justified because it validates CSE-specific behavior:
           # the command actually runs and produces correct output.
           settings = {"commandToExecute": "echo 'CSE test success'"}
           result = self._install(node, variables, settings=settings)
           try:
               self._assert_provisioned(result)
               # Extension-specific: validate the command output
               stdout = (
                   result.get("instance_view", {})
                   .get("substatuses", [{}])[0]
                   .get("message", "")
               )
               assert_that(stdout).contains("CSE test success")
           finally:
               self._uninstall(node)

       @TestCaseMetadata(
           description="Validates CSE fails gracefully with invalid command.",
           priority=3,
       )
       def verify_custom_script_invalid_command_fails(
           self, log: Logger, node: Node, variables: Dict[str, Any]
       ) -> None:
           # Extension-specific: validates error handling behavior
           settings = {"commandToExecute": "/nonexistent/command"}
           result = self._install(node, variables, settings=settings)
           try:
               assert_that(result["provisioning_state"]).is_equal_to("Failed")
           finally:
               self._uninstall(node)

Guiding Questions for Publishers
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

When writing extension-specific tests, ask:

1. **Does this test validate something unique to my extension?** If yes, write
   it. If it's just lifecycle, use ``_full_lifecycle()``.
2. **Am I validating the extension's output or side effects?** Command output,
   files created, agent heartbeats, encryption status — these are
   extension-specific.
3. **Am I testing error/edge cases specific to my extension?** Invalid
   settings, unsupported OS, timeout behavior — these justify dedicated tests.
4. **Would this test make sense for a different extension?** If yes, it
   probably belongs in the base class, not your suite.

Coexistence with GenericVmExtension
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 40 40

   * -
     - ``GenericVmExtension``
     - Publisher-owned suite
   * - **Purpose**
     - Ad-hoc triage / smoke check
     - Formal validation coverage
   * - **Requires code**
     - No — runbook variables only
     - Yes — dedicated file
   * - **Who uses it**
     - LISA team, on-call
     - Extension publisher
   * - **Maturity**
     - Stable (utility)
     - Starts Experimental

Benefits
~~~~~~~~

1. **Zero redundancy** — lifecycle logic exists once
2. **Clear ownership** — each publisher has their own file and suite
3. **Scales to 50+** — onboarding is mechanical (3 constants + custom tests)
4. **Runtime flexibility** — version and scope controlled entirely by runbook
5. **Consistent discoverability** — ``EXTENSION_KEY`` drives all naming
   uniformly
6. **Independent evolution** — publishers can add tests without impacting
   others
