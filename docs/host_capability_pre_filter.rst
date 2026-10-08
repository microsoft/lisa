Host Capability Pre-Filter
==========================

Background
----------

Some LISA test suites can only run on hosts that expose a particular
capability. The clearest example is the Microsoft Hypervisor (MSHV)
suites, which require ``/dev/mshv`` on the target host. Historically this
requirement was only enforced at runtime — after a VM was deployed — by
``path_exists("/dev/mshv")`` + ``SkippedException`` guards in
``before_case()`` hooks. LISA would provision an expensive cloud
environment only to immediately skip the incompatible case, wasting time
and cost on runs that target hosts without the capability.

Problem
-------

Selecting MSHV (or other capability-gated) cases against a target that
does not provide the capability still deployed an environment:

-  Wasted deployment cost for a VM whose test case cannot run.
-  Longer end-to-end pipeline duration with no useful test signal.
-  Noisy "Skipped" results that obscure actual validation coverage.

This mirrors the problem solved by the :doc:`distro_pre_filter`, but for
host capabilities rather than the guest OS.

Goals
-----

-  Drop capability-incompatible test cases **before** VM deployment.
-  Preserve existing runtime guards as defense-in-depth.
-  Require no changes to existing runbooks (opt-in via a single variable).
-  Gracefully fall back to the existing runtime mechanism when the gate
   is off.

How It Works
------------

The host-capability pre-filter is an opportunistic optimization that runs
during test case selection, before any environment is deployed. It
mirrors the ``os_type`` / ``platform_type`` pre-filters: it is pure
selection-time metadata and requires no platform capability
advertisement.

1. **Capability metadata** — Test suites and cases declare the host
   capabilities they require via ``supported_host_capabilities`` /
   ``unsupported_host_capabilities`` on their requirement (for example
   ``supported_host_capabilities=["mshv"]``).

2. **Pre-filter** — ``select_testcases()`` accepts an optional
   ``target_capabilities`` parameter. When provided, each case's declared
   ``host_capabilities`` requirement is checked against the capabilities
   the target host provides, and cases that cannot be satisfied are
   dropped. Cases that declare no capability requirement are always kept.

3. **Gate variable** — The runbook variable
   ``enable_capability_pre_filtering`` (default: ``false``) controls
   whether the pre-filter is active. Set to ``true`` to enable.

4. **Target declaration** — When the gate is on, the operator declares
   what the target host provides via ``target_host_capabilities``
   (comma-separated, e.g. ``mshv``).

5. **Graceful fallback** — When the gate is off the pre-filter does
   nothing and all test cases proceed to deployment as before. The
   runtime ``before_case()`` guards remain the authoritative check.

Gate and Target Semantics
--------------------------

The resolver distinguishes three states so that an explicitly empty
declaration is not confused with the gate being off:

.. list-table::
   :header-rows: 1
   :widths: 45 25 30

   * - Runbook configuration
     - Resolved target
     - Capability-gated cases (e.g. MSHV)
   * - Gate off (default) or variable missing
     - ``None``
     - Kept — fully backward-compatible, no case dropped
   * - Gate on, ``target_host_capabilities`` empty or unset
     - ``[]``
     - Dropped at selection time — the target satisfies no capability
   * - Gate on, ``target_host_capabilities: mshv``
     - ``["mshv"]``
     - MSHV cases kept; cases needing other capabilities dropped
   * - Case declares no ``host_capabilities``
     - any
     - Always kept — unaffected

.. important::

   A gate-on run with an empty ``target_host_capabilities`` means "this
   target provides no host capabilities", so every capability-gated case
   is dropped before deployment. This is different from leaving the gate
   off, which disables the pre-filter entirely and keeps all cases.

Enabling the Pre-Filter
-----------------------

.. note::

   The pre-filter is **disabled by default**. The
   ``enable_capability_pre_filtering`` variable defaults to ``false``, so
   existing runbooks and pipelines are unaffected unless you explicitly
   opt in.

Add the ``enable_capability_pre_filtering`` and
``target_host_capabilities`` variables to your runbook or pass them via
the command line:

.. code-block:: yaml

   # In runbook YAML
   variable:
     - name: enable_capability_pre_filtering
       value: true
     - name: target_host_capabilities
       value: "mshv"

Or via CLI:

.. code-block:: bash

   lisa -r runbook.yml -v enable_capability_pre_filtering:true \
       -v target_host_capabilities:mshv

``target_host_capabilities`` accepts a comma-separated string (for
example ``mshv, virtualization``) or, in a runbook, a YAML list.

The pre-filter also works with ``lisa list --type case`` so you can
preview which cases would be selected:

.. code-block:: bash

   lisa list --type case -r runbook.yml -v enable_capability_pre_filtering:true \
       -v target_host_capabilities:mshv

With the gate on and no ``mshv`` target, an MSHV-only runbook reports
``selected count: 0`` and **no VM is deployed**. With ``mshv`` declared,
the case is kept, the VM deploys, and the runtime ``/dev/mshv`` guard
remains in place as defense-in-depth.

Test Selection Flow
-------------------

The full test selection pipeline with the host-capability pre-filter:

1. **Discover all test cases** — LISA loads all registered
   ``TestCaseMetadata`` from the codebase.

2. **Apply distro pre-filter** — if ``enable_distro_pre_filtering``
   is ``true`` and a ``target_os`` can be inferred, cases incompatible
   with that OS are dropped (see :doc:`distro_pre_filter`).

3. **Apply host-capability pre-filter** — if
   ``enable_capability_pre_filtering`` is ``true``, cases whose declared
   ``host_capabilities`` requirement cannot be satisfied by
   ``target_host_capabilities`` are dropped.

4. **Process runbook filters** — criteria (name, area, category,
   priority, tags, maturity) and select actions (include / exclude /
   forceInclude / forceExclude) are applied.

5. **Apply the implicit stable gate** — non-stable tests are dropped
   unless explicitly approved (see :doc:`test_maturity_model`).

6. **Runtime guards** — at execution time, remaining capability checks
   (e.g. ``/dev/mshv`` existence) + ``SkippedException`` in
   ``before_case()`` provide defense-in-depth.

Adding Host Capability Metadata to Test Cases
---------------------------------------------

To benefit from the pre-filter, test suites or cases should declare
``supported_host_capabilities`` or ``unsupported_host_capabilities`` in
their requirement metadata:

.. code-block:: python

   from lisa import TestSuite, TestSuiteMetadata, simple_requirement

   @TestSuiteMetadata(
       area="mshv",
       category="functional",
       description="Tests for the Microsoft Hypervisor root partition",
       requirement=simple_requirement(
           supported_host_capabilities=["mshv"],
       ),
   )
   class MshvHostTestSuite(TestSuite):
       ...

Or to exclude hosts that provide a capability:

.. code-block:: python

   @TestSuiteMetadata(
       area="compute",
       category="functional",
       description="Tests that must not run on an MSHV root partition",
       requirement=simple_requirement(
           unsupported_host_capabilities=["mshv"],
       ),
   )
   class NonMshvSuite(TestSuite):
       ...

.. important::

   When adding ``supported_host_capabilities`` /
   ``unsupported_host_capabilities`` metadata, ensure it matches the
   runtime guard in ``before_case()`` (for example the ``/dev/mshv``
   check). If the two drift, the pre-filter may incorrectly drop (or
   keep) a case. The runtime guard remains authoritative.

Design Constraints and Known Limitations
-----------------------------------------

This is an opportunistic optimization, not a final architecture.

.. list-table::
   :header-rows: 1
   :widths: 25 40 35

   * - Aspect
     - Current
     - Future direction
   * - Intent declaration
     - Dual: ``supported_host_capabilities`` metadata + runtime guard
     - Single decorator driving both
   * - Capability discovery
     - Operator-declared via ``target_host_capabilities``
     - Structured capability metadata advertised by the platform
   * - Failure mode
     - Graceful — gate off = no pre-filter, falls back to current
       behavior
     - Same (this is already correct)
   * - Runtime guards
     - Kept as defense-in-depth; they remain the authoritative check
     - Unified: decorator auto-generates both pre-filter and runtime
       guard

**Key limitations:**

1. **Operator-declared target** — The pre-filter trusts
   ``target_host_capabilities``; it does not query the platform for the
   real capabilities a host provides. An incorrect declaration can drop
   or keep the wrong cases, but the runtime guard still protects
   correctness.

2. **DRY trade-off** — The ``supported_host_capabilities`` metadata and
   runtime guards can drift if an author updates one but not the other.
   The runtime guard is always authoritative.

Summary
-------

The host-capability pre-filter provides a low-risk optimization that
reduces wasted VM deployments by dropping capability-incompatible test
cases (e.g. MSHV) at selection time. It preserves the existing runtime
guards as defense-in-depth and gracefully degrades when the gate is off.
Enable it by setting ``enable_capability_pre_filtering: true`` together
with ``target_host_capabilities`` in your runbook.
