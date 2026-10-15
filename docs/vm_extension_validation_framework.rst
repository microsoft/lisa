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

**Pattern 1: Dedicated suites** — each extension uses a scoped version variable:

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

**Pattern 2: Generic suite** — uses ``extension_*`` variables for backward
compatibility with existing runbooks and pipelines:

.. code-block:: yaml

   variable:
     - name: extension_publisher
       value: "Microsoft.Azure.Monitor"
     - name: extension_type
       value: "AzureMonitorLinuxAgent"
     - name: extension_version
       value: "1.7.1"

When ``extension_*`` variables are present, they take priority over class
constants. All three must be specified together — partial specification
raises ``SkippedException`` with a clear error message.

**Resolution order:**

- Publisher: ``extension_publisher`` → ``PUBLISHER`` (class constant)
- Type: ``extension_type`` → ``EXTENSION_TYPE`` (class constant)
- Version: ``extension_version`` → ``{EXTENSION_KEY}_version`` →
  ``DEFAULT_VERSION`` (code fallback)

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

Windows Runtime Extension Boot Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Windows runtime suites require Azure, ``AzureExtension``, and a Windows
guest. They are preview, priority-5 installation smoke tests, not VM reboot
tests. The shared ``_boot_validation()`` helper verifies provisioning, checks
the installed candidate version when a full version is requested, checks VM
reachability, and removes the extension even when validation fails.

.. list-table::
   :header-rows: 1
   :widths: 25 40 35

   * - Extension
     - Test method
     - Scoped candidate version variable
   * - ``Microsoft.Compute.CustomScriptExtension``
     - ``microsoft_compute_customscriptextension_boot_validation_test``
     - ``custom_script_windows_version``
   * - ``Microsoft.CPlat.Core.RunCommandWindows``
     - ``microsoft_cplat_core_runcommandwindows_boot_validation_test``
     - ``run_command_windows_version``

Set the scoped variable for each selected suite, or use ``extension_version``
to override it. Boot validation requires an explicit two-, three-, or four-part
version and never uses a code-level default. Supply a three- or four-part
version to require the exact candidate; a two-part version lets Azure choose
the patch. Filter by the exact test name or the case's lowercase
``publisher.type`` tag to avoid selecting Linux counterparts.

Azure may publish and report a full candidate using three components. A
four-part input with a zero revision (for example, ``1.10.24.0``) matches the
equivalent reported ``1.10.24``. The shared version comparison ignores trailing
zero components, but rejects a different patch or nonzero revision.

Custom Script executes a harmless inline PowerShell command using
``commandToExecute``. Run Command executes a harmless PowerShell command using
the Windows handler's public ``script`` array; this is action Run Command,
not ``RunCommandHandlerWindows`` (Managed Run Command). Neither case needs a
storage account, script download, or protected settings.

RunCommandWindows requires an SSH-ready VM whose preparation has not already
established an incompatible action Run Command handler. When a Windows VM's
SSH port is closed, LISA's Azure platform invokes ``RunPowerShellScript`` through
action Run Command to configure OpenSSH before test execution. This can establish
an implicit RunCommandWindows handler whose requested version conflicts with the
test's requested ``major.minor`` version. A fresh VM alone does not prevent this;
use an image with SSH already configured or bootstrap SSH without action Run
Command. The Linux platform path skips this Windows-specific bootstrap.

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

Windows Network Watcher Boot Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``NetworkWatcherAgentWindowsTests`` validates
``Microsoft.Azure.NetworkWatcher.NetworkWatcherAgentWindows`` using the shared
``_boot_validation()`` lifecycle and a candidate-specific process check.

- Case: ``microsoft_azure_networkwatcher_networkwatcheragentwindows_boot_validation_test``
- Suite and case tag: ``microsoft.azure.networkwatcher.networkwatcheragentwindows``
- Required version: ``network_watcher_agent_windows_version`` or the overriding
  ``extension_version`` variable. There is no default candidate version.
- Empty public settings and no protected settings: the extension does not
  support user-supplied configuration.
- After provisioning and SSH checks, poll for ``NetworkWatcherAgent.exe``
  running from the actually installed handler's directory under
  ``C:\Packages\Plugins``. Do not substitute the executable's file version for
  the extension handler version.
- Skip if the requested publisher/type is already installed, regardless of
  resource name, rather than replacing a policy-managed or user-owned agent.
  Use a fresh VM without a pre-existing Network Watcher extension.

This validates initial agent startup, not reboot survival, packet capture,
connection monitoring, or successful communication with the Network Watcher
service. It does not create a storage account, restart the agent, or change
firewall rules. The VM must allow the documented Azure platform connections:
TCP port 80 to ``169.254.169.254`` and TCP port 8037 to ``168.63.129.16``.
Windows Server 2025 is listed among the supported operating systems.

See `Manage Network Watcher Agent virtual machine extension
<https://learn.microsoft.com/azure/network-watcher/network-watcher-agent-manage>`_
for the supported operating systems, default-settings contract, and network
prerequisites.

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
