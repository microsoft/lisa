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

Linux Custom Script: SSH-Free Coverage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the serial, private-VM runbook with:

.. code-block:: powershell

   python -m lisa -r .\lisa\microsoft\runbook\custom_script.yml

Pass normal Azure subscription/authentication variables as required by
``azure.yml``. Override ``custom_script_version`` to select a candidate. A full
patch version is checked against the installed handler. The guest must already
have Python 3 and a functioning Azure Linux Agent.

The suite opts into ``reuse_deployed_environment`` and never initializes a
guest SSH connection. This opt-in preserves deployed-only environments between
cases, provided a case does not connect them internally. Keep concurrency at
one, as in this runbook, and do not request new environments per case. One
Linux VM and one CSE resource are reused; an existing CSE resource is adopted.
Only the explicit uninstall/reinstall case deletes the extension. Other
extension suites retain their existing lifecycle behavior.

Checks are combined to minimize extension updates rather than exhaustively
enumerating settings/policy matrices:

* Public/protected commands, multiple downloads, Python and shell scripts.
* Public/protected plain and gzip/base64 scripts; the exact 256-KiB encoded
  boundary. The invalid-script case (invalid base64, corrupt gzip and oversized
  input) is explicitly skipped until the existing handler source fixes are
  deployed.
* Root execution, working directory, script/output permissions, stdout/stderr
  and their 4-KiB retained tails, nonzero exits and recovery.
* CRLF, UTF-8 BOM, extensionless shebang scripts, unchanged binary downloads
  and ``skipDos2Unix``.
* Representative schema rejection, without executing the rejected command.
  Command/script conflict and missing-command rejection are temporarily
  disabled until the handler's existing logical-validation fix is deployed.
* Unchanged settings, timestamp and force-update reexecution, and old
  sequence/settings cleanup.
* Loopback-only 429/503 fixtures, each recovering on its second request, plus
  a permanent 404 with no command execution. These exercise approximately
  six seconds of deliberate CSE retry backoff in total, without timeout or
  retry-exhaustion tests. Interrupted-response coverage is temporarily disabled
  until the handler's retry file-offset bug is fixed. Failures report request
  counts or received file bytes to distinguish retry and content-corruption
  errors.
* Private SAS, optional Shared Key, system-assigned identity, user-assigned
  identity selected by client/object ID, and an identity without blob-read
  permission.
* Runtime-policy command/hash allow and deny paths, policy removal, and
  exactly one invalid-JSON policy fallback case. A handler lacking policy
  support is explicitly skipped; select a policy-capable candidate to cover
  these paths. Inline-policy/signature matrices are intentionally omitted.
* Extension-owned data removal on uninstall, preservation of unrelated
  files, and successful reinstall.

CSE scripts verify their own results and emit operation-specific markers.
After the Azure update operation completes, validation uses handler
instance-view success/failure and fresh script output. ARM can continue to
report ``Updating`` after the handler has finished; that state alone does not
fail a case. Missing or stale handler results are refreshed for up to 30 seconds
using read-only checks, without rerunning the script. Positive checks still
reject terminal ARM failures and failed handler statuses.
Negative checks require handler errors, not unrelated ARM/authentication
failures. Managed Run Command is used only for independent setup, loopback
fixtures, identity readiness, policy placement and checks that cannot be
performed by the execution being tested. Its resource is also updated in place.
Temporary fixture files, processes and blobs are removed after each case.

The suite reuses LISA's shared regional storage account and creates a private
``lisa-cse-validation`` container. It never enables public access or Shared
Key. The Shared Key case is skipped if that authentication method is disabled;
an existing permitted account can be selected with
``custom_script_storage_account`` and
``custom_script_storage_resource_group``.

The caller needs VM/extension/managed-Run-Command permissions, Storage Blob
Data Contributor on the fixture container or account, storage-account-scoped
permission to generate user-delegation keys, identity management rights in
``lisa_shared_resource``, VM identity assignment permission and role-assignment
management permission on the container. Account-level Blob Data Contributor
includes delegation-key generation; a container-scoped assignment needs that
permission separately, for example through Storage Blob Delegator or existing
management rights. The suite does not grant data access to the caller.

Two dedicated user-assigned identities, ``lisa-cse-<region>-reader`` and
``lisa-cse-<region>-denied``, survive runs in ``lisa_shared_resource``. Missing
identities are created; existing identities and the reader's container-scoped
Storage Blob Data Reader assignment are reused. The denied identity must not
have inherited blob-read access. Identity creation uses API ``2024-11-30`` so
Azure Policy can apply ``isolationScope`` restrictions without changing the
subscription's policy. These identities, the reader role and the empty
container deliberately remain after a run. System-assigned identity is
VM-scoped and cannot outlive its VM; its test-created reader assignment is
removed after the case. Readiness is checked before testing CSE; propagation
can wait up to five minutes, with immediate continuation when access works.

No duplicate settings/extension scenarios, command timeout tests, exhaustive
policy matrices, long retry-exhaustion cases or live SSH-login checks are
included. Azure resource-operation time still dominates a full suite run.

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

Windows Application Health Boot Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``ApplicationHealthWindowsTests`` validates
``Microsoft.ManagedServices.ApplicationHealthWindows`` using the shared
``_boot_validation()`` lifecycle with an explicit TCP health probe.

- Case: ``microsoft_managedservices_applicationhealthwindows_boot_validation_test``
- Suite and case tag: ``microsoft.managedservices.applicationhealthwindows``
- Required candidate: ``application_health_windows_version`` or the overriding
  ``extension_version`` variable. There is no default version.
- Verify a successful TCP handshake to ``localhost`` on the guest SSH port
  before installation. Use the guest port, not a public/NAT-forwarded port.
  Do not install IIS, download a sample application, modify SSH, open firewall
  ports, or substitute an unrelated always-healthy endpoint.
- Configure ``protocol=tcp``, the verified guest port,
  ``intervalInSeconds=5`` and ``numberOfProbes=2``. Omit ``requestPath`` and
  protected settings. TCP probing is supported by binary and rich health
  handlers; the candidate version remains an explicit runbook input.
- Check provisioning, the installed handler version for a full candidate,
  and SSH connectivity using the shared lifecycle.
- While the candidate is installed, verify the TCP endpoint again and capture
  a UTC watermark from the guest clock. Poll Azure VM instance view for
  ``vmHealth.status.code == HealthState/healthy`` with a timezone-aware
  ``status.time`` at or after that watermark. A historical Healthy result,
  missing timestamp, or missing health object does not pass.
- Retry health assertions 31 times, ten seconds apart (up to five minutes
  of polling delays, plus API request time). API errors and malformed guest
  responses fail directly. Log every observed health code and timestamp.
- Require a fresh isolated environment and mark the node dirty before
  installation. Use shared install cleanup; where another resource already
  owns the same handler, the shared same-publisher/type cleanup is required
  before this test can replace it.

This validates initial candidate enablement, TCP probing and fresh application
health reporting. It does not test HTTP/HTTPS response bodies, negative health
transitions, reboot survival, VMSS orchestration, or automatic repairs.
Normal cleanup removes the test extension; it does not restore previously
configured health monitoring. A retained local validation must suppress only
final uninstall, not pre-install cleanup or any assertions.

Official references:

- `Application Health extension for Azure VMs
  <https://learn.microsoft.com/azure/virtual-machines/extensions/health-extension>`_
  documents TCP settings, ``vmHealth`` inspection and Windows diagnostics.
- `Application Health extension for VM scale sets
  <https://learn.microsoft.com/azure/virtual-machine-scale-sets/virtual-machine-scale-sets-health-extension>`_
  describes binary/rich health semantics and local probe prerequisites.
- `Virtual Machines - Instance View
  <https://learn.microsoft.com/rest/api/compute/virtual-machines/instance-view>`_
  documents the API used to read application health.

Windows GenevaMonitoring Boot Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``GenevaMonitoringWindowsTests`` validates
``Microsoft.Azure.Geneva.GenevaMonitoring`` using the shared
``_boot_validation()`` lifecycle with standby-readiness checks.

- Case: ``microsoft_azure_geneva_genevamonitoring_boot_validation_test``
- Suite and case tag: ``microsoft.azure.geneva.genevamonitoring``
- Required candidate: ``geneva_monitoring_windows_version`` or a complete
  generic ``extension_*`` specification. There is no default version.
- Empty public and protected settings: do not configure a telemetry tenant
  or supply placeholder accounts, namespaces or credentials.
- Verify provisioning, installed handler version for a full candidate
  version, and SSH connectivity before inspecting guest readiness.
- Require running ``MonAgentManager.exe`` and ``MonAgentHost.exe`` processes
  under the actually installed candidate directory. A process from another
  version or a similarly prefixed directory does not satisfy the check.
- Read machine-scoped ``MonAgentClientLocation`` and verify its
  ``MonAgentClient.exe`` exists under the same candidate. Do not hardcode a
  client subdirectory or rely on a stale SSH-session environment.
- Read ``JsonDropDirectory`` from
  ``HKLM\SOFTWARE\Microsoft\Geneva\MonitoringAgent\MultiTenant`` and verify
  that the registered directory exists. All guest checks are read-only.
- Retry readiness and command-exit assertions six times, ten seconds apart.
  Malformed output and non-assertion execution errors fail directly.
- Skip Windows kernels older than 6.3 (the Windows Server 2012 R2 baseline).
- Require an isolated environment and use shared pre-install cleanup to
  remove existing matching publisher/type installations, including handlers
  installed under another resource name. Mark the node dirty before
  installation because the extension manages machine-wide monitoring state.

This case validates installation and standby startup only. It does not
launch a telemetry tenant or require ``MonAgentCore.exe`` and other
tenant-specific collection processes. It does not submit configuration
files, validate telemetry ingestion, or test reboot survival. Normal cleanup
removes the test extension; it is not a restoration of previous monitoring
configuration, including any pre-existing handler removed before installation.
Use an isolated disposable VM.

Public Azure API references:

- `Service Fabric node type create/update
  <https://learn.microsoft.com/rest/api/servicefabric/managedclusters/node-types/create-or-update>`_
  includes a ``GenevaMonitoring`` extension example with empty settings.
- `Azure VM extension features for Windows
  <https://learn.microsoft.com/azure/virtual-machines/extensions/features-windows>`_
  describes extension lifecycle and instance-view status inspection.

Windows IaaSAntimalware Boot Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``IaaSAntimalwareWindowsTests`` validates
``Microsoft.Azure.Security.IaaSAntimalware`` using the shared
``_boot_validation()`` lifecycle and a Defender readiness check.

- Case: ``microsoft_azure_security_iaasantimalware_boot_validation_test``
- Suite and case tag: ``microsoft.azure.security.iaasantimalware``
- Required version: ``iaas_antimalware_windows_version`` or overriding
  ``extension_version``. There is no default candidate version.
- Public settings: ``AntimalwareEnabled=true`` and
  ``RealtimeProtectionEnabled=true``. No exclusions or protected settings.
- After provisioning, handler-version and SSH checks, poll
  ``Get-MpComputerStatus`` for ``AMServiceEnabled``, ``AntivirusEnabled`` and
  ``RealTimeProtectionEnabled``. Each must be a JSON boolean ``true``.
  Retry readiness and command-exit assertions six times, ten seconds apart.
  Malformed output and non-assertion execution errors fail directly.
- Skip legacy Windows kernels (major version below 10) and any pre-existing
  matching publisher/type, regardless of extension resource name.
- Require a new environment and mark the VM dirty before installation.
  Extension configuration replaces existing Defender settings, including
  exclusions; deleting the extension must not be treated as restoring those
  settings. Use an isolated disposable VM, not a user-owned environment.

On Windows Server 2016 and later the extension configures built-in Defender;
it does not install a separate antivirus service. Consequently, the test does
not look for a candidate-owned antivirus executable or compare Defender's
engine version with the extension handler version. This is startup/readiness
validation, not malware detection, scan execution, signature freshness or
reboot survival. No protection is disabled and no test malware is introduced.

Official references:

- `Microsoft Antimalware extension for Windows
  <https://learn.microsoft.com/azure/virtual-machines/extensions/iaas-antimalware-windows>`_
  describes the settings, supported platforms and network prerequisites.
- `Microsoft Antimalware code samples
  <https://learn.microsoft.com/azure/security/fundamentals/antimalware-code-samples>`_
  documents the configuration and warning about replacing existing policies.
- `Get-MpComputerStatus
  <https://learn.microsoft.com/powershell/module/defender/get-mpcomputerstatus>`_
  documents the runtime status query and readiness properties.

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
