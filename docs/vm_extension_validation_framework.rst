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

VM Applications: Windows and Linux Without SSH
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The VM applications suites use CRP application-profile and VM-application child
APIs, not direct extension installation. CRP selects the handler version.
Application-version updates and downgrades are tested; handler upgrades,
version pinning, VMSS, host-response injection and timeout/retry-exhaustion
scenarios are intentionally excluded.

Run either serial, private-VM runbook:

.. code-block:: powershell

   python -m lisa list -t case -r .\lisa\microsoft\runbook\vm_applications.yml
   python -m lisa run -r .\lisa\microsoft\runbook\vm_applications.yml
   python -m lisa run -r .\lisa\microsoft\runbook\vm_applications_windows.yml

Supply normal Azure subscription/authentication variables and Windows
provisioning credentials through your normal secret-variable mechanism.
The defaults are Ubuntu 22.04 Gen2 and Windows Server 2022 Azure Edition.
Linux requires Python 3; Windows uses Windows PowerShell and .NET ZIP support.
Neither suite establishes SSH, RDP or WinRM connections, and Windows SSH
bootstrap is disabled. Managed Run Command is the only guest setup/validation
channel. Its resource is updated in place.

Each OS defines the same 16 preview cases. Four custom-action cases are
temporarily disabled pending the PIR metadata issue described below, leaving
12 active cases: nine functional cases and three reboot cases (CRP restart
persistence, installation with ``None``, and installation with ``Rerun``).
Windows and Linux share the scenario implementations,
publishing, CRP operations, failure validation and cleanup. Only the guest
scripts, command bootstrap, image and OS requirements differ.

Related checks share application installations and profile updates within four
grouped cases, rather than repeating per-case setup and cleanup:

* ``verify_installation_and_configuration`` installs apps with default/custom
  filenames, no/default/overridden configuration and a manually managed
  companion in one profile update. It then checks that invalid CRP requests
  neither change the profile nor execute guest commands.
* ``verify_application_lifecycle`` installs once, checks identical/unrelated
  updates, performs a native update and downgrade, and finishes with
  remove/install replacement while retaining an unchanged companion app.
* ``verify_ordered_failure_and_recovery`` checks peers, unordered continuation
  and higher-order skipping, removes the skipped entry without running its
  remove command, then recovers with a good version and reinstalls that entry.
* ``verify_removal_and_reuse`` removes an app with modified cached files while
  preserving another, removes the remaining app normally, and reinstalls using
  the same handler.

Each group logs its phases and checks execution history at phase boundaries.
Failures stop later dependent phases; normal case cleanup still runs. Ordered
mixed operations, deployment-failure flags, failed replacement/removal, child
resource APIs and all three reboot scenarios remain separate cases.
Guest fixtures and gallery publishing are unchanged, so grouping does not
require republishing application versions.

Defined coverage, including the temporarily disabled custom-action cases, includes:

* Root/LocalSystem execution, working directory, exact downloaded bytes,
  default/custom filenames, no/default/overridden configuration, and literal
  custom-action parameters and defaults.
* No-op settings and unrelated updates, native update, remove/install fallback,
  application downgrade, failed replacement removal, and recovery.
* Ordered operations, same-order peers, higher-order skips, unordered
  continuation, skipped-entry cleanup, and install/update deployment-failure
  flags both enabled and disabled.
* Remove failure reporting, modified cached files, individual/all application
  removal, preservation of an unrelated sentinel and independent audit
  directory, and re-addition.
* Custom-action invocation, unique-identifier replay protection, failure
  reporting/recovery, and CRP action/parameter rejection.
* Child PUT/PATCH/GET/LIST/DELETE and tag-only updates, manual-management
  exclusion, and invalid profile/OS/reference/configuration rejection without
  guest execution.
* Three bounded reboot scenarios. Installer-triggered reboots have a durable
  one-shot guard; these are not reboot-loop or timeout tests.

Use one dedicated VM per OS and concurrency one. Both suites opt into
``reuse_deployed_environment``; the runner preserves the deployed VM and skips
post-case SSH probes. The reuse logic matches the CSE branch, while this
branch's existing ``remote_connection_required`` compatibility path remains
available for Hibernate and disables Windows SSH bootstrap here. A reuse case
that unexpectedly connects its environment causes it to be discarded.

The suites refuse to replace customer application profiles. Test applications
are removed after each case, but the VM, resource group and CRP-managed
extension are not deleted between cases. Failures during cleanup are explicit
and mark the environment dirty. Audit records carry a fresh case identifier;
the application commands validate their own inputs, and Run Command verifies
execution counts, ordering, state and cleanup. Public per-application instance
view is checked separately using VM API ``2025-04-01``, the first version
exposing the ``vmApplications`` instance-view collection.
For remove/custom-action results not retained in public instance view,
Run Command reads the latest handler status file without
editing it. An ARM/authentication error cannot satisfy an expected handler
failure.

Failure-policy cases require the original CRP VM-update operation to report a
VM Applications extension failure and the per-application result to report
failure. They do not require a later VM GET to retain a failed provisioning
state: another operation may have updated that VM-wide state. An unrelated
extension failure (for example, policy-installed Defender) does not count as
the expected application failure.

The install/update failure-policy matrix uses independent scenarios. After
checking an intentional install failure, it removes that entry and installs
successfully before injecting an update failure. This tests update-failure
propagation from an installed application rather than chaining two failed
operations. Audit events are checked at each failure and after the successful
installation. Recovery from a failed install is covered separately by
``verify_ordered_failure_and_recovery``.

Failed replacement removal can be retried on subsequent goal states, including
those generated by Managed Run Command inspection. That case requires the old
version to remain installed and allows only failed removal attempts after its
initial installation; any successful removal or new-version execution fails
the case. No-op/idempotency checks in the normal lifecycle remain exact.

The child-resource lifecycle creates applications through child PUT before
PATCH or DELETE: adding an application through the VM profile alone does not
register that child resource with ARM. Manually managed applications may appear
in public instance view as empty name-only entries; the tests allow those
placeholders but reject any reported version, result or action for them, and
independently verify that no guest command ran.

Fixtures reuse the regional shared storage account and
``lisa_shared_resource``; no resource group is created per case. The private
``lisa-vmapplications`` container uses Entra-authenticated uploads and read-only
user-delegation SAS. If the account is absent, the separate storage ARM template
creates it with HTTPS/TLS 1.2, OAuth defaults, Shared Key disabled and public
blob access disabled. Like JsonADDomain staging, creation grants the deployer
Storage Blob Data Contributor on that new account. Existing accounts are not
reconfigured and existing caller permissions are not escalated.

The caller needs VM update, VM-application child API and managed Run Command
permissions, plus gallery/application/version and deployment permissions in
the fixture resource group. Existing storage requires Blob Data Contributor
and account-level delegation-key generation permission; a container-scoped
data role needs a separate account-scoped delegation role. New account
creation also requires role-assignment permission. New-role propagation is
bounded and logged; authorization failures against existing accounts fail
immediately.

Optional case-visible variables:

* ``vm_applications_storage_account``
* ``vm_applications_storage_resource_group``
* ``vm_applications_gallery_name``
* ``vm_applications_gallery_resource_group``

By default, publishing creates five fixture application definitions and nine
versions per OS, including one opposite-OS version used only for CRP rejection.
Packages/default configuration use page blobs, following the synthetic;
configuration overrides use a private block blob. The gallery ARM template
keeps SAS-bearing source properties in a secure-object parameter. Application
names are content-versioned, existing fixture tags are checked, and regional
replication must complete before testing. Immutable gallery fixtures and their
source blobs deliberately survive runs to avoid repeated publication.
Windows custom filenames use ``payload-data.zip`` and ``settings-data.json``;
the gallery service rejected the space-containing package filename used by the
Linux fixture. Linux retains its spaced filenames for quoting coverage.
Changing fixture scripts or the publishing schema creates a new fixture
generation. The filename correction bumps the schema so failed immutable
versions from earlier runs are not reused. Do not remove the shared
gallery/account/container as part of case cleanup.

The custom-action execution, replay, failure/recovery and validation cases are
temporarily disabled in both OS suites by commenting out their
``TestCaseMetadata`` decorators. Each has a TODO to re-enable it after the PIR
issue preventing CRP from receiving custom-action metadata is fixed. The
published action definitions and shared test implementations remain intact.

After re-enabling, the cases may expose additional handler compatibility issues:
the supplied CRP source serializes custom-action parameters as an object, while
the supplied handler source expects name/value entries in an array. Such a
mismatch must fail rather than be hidden by protected-settings injection.
Likewise, a custom-action failure missing from handler status is a test failure.
Same-version configuration/manual-management changes are not assumed to force
execution; those scenarios use fresh applications or explicit
application-version changes.

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
