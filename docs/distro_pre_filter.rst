Distro Pre-Filter
=================

Background
----------

LISA test suites declare OS compatibility via ``supported_os`` and
``unsupported_os`` metadata on their requirements. However, this
information was previously only enforced at runtime — after a VM was
deployed — by ``isinstance`` + ``SkippedException`` guards in
``before_case()`` hooks. This means LISA would provision expensive
cloud environments only to immediately skip incompatible test cases,
wasting time and cost on partner runs targeting a single distro.

Problem
-------

Running tests against a single target image (e.g. an Ubuntu or SUSE
marketplace image) still selected the full test catalog, including
cases that would inevitably be skipped:

-  Wasted deployment cost for environments whose test cases cannot run.
-  Longer end-to-end pipeline duration with no useful test signal.
-  Noisy "Skipped" results that obscure actual validation coverage.

Goals
-----

-  Drop incompatible test cases **before** VM deployment.
-  Preserve existing runtime guards as defense-in-depth.
-  Require no changes to existing runbooks (opt-in via a single variable).
-  Gracefully fall back to the existing runtime mechanism when the
   target OS cannot be determined.

How It Works
------------

The distro pre-filter is an opportunistic optimization that runs during
test case selection, before any environment is deployed.

1. **OS inference** — A resolver module (``lisa.util.os_resolver``)
   infers the target OS from image-related runbook variables
   (``marketplace_image``, ``shared_gallery``, ``community_gallery_image``,
   ``vhd``, ``image``) using an alias dictionary that maps distro names
   and publisher names to LISA ``OperatingSystem`` subclasses.

2. **Pre-filter** — ``select_testcases()`` accepts an optional
   ``target_os`` parameter. When set, it uses bidirectional
   ``issubclass`` to check each case's ``supported_os`` /
   ``unsupported_os`` against the target and drops incompatible cases.

3. **Gate variable** — The runbook variable
   ``enable_distro_pre_filtering`` (default: ``false``) controls whether
   the pre-filter is active. Set to ``true`` to enable.

4. **Graceful fallback** — If the image string is unrecognized or no
   image variable is set, the pre-filter does nothing and all test cases
   proceed to deployment as before.

Enabling the Pre-Filter
------------------------

.. note::

   The pre-filter is **disabled by default**. The
   ``enable_distro_pre_filtering`` variable defaults to ``false``, so
   existing runbooks and pipelines are unaffected unless you explicitly
   opt in.

Add the ``enable_distro_pre_filtering`` variable to your runbook or
pass it via the command line:

.. code-block:: yaml

   # In runbook YAML
   variable:
     - name: enable_distro_pre_filtering
       value: true
     - name: marketplace_image
       value: "Canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest"

Or via CLI:

.. code-block:: bash

   lisa -r runbook.yml -v enable_distro_pre_filtering:true \
       -v "marketplace_image:Canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest"

The pre-filter also works with ``lisa list --type case`` so you can
preview which cases would be selected:

.. code-block:: bash

   lisa list --type case -r runbook.yml -v enable_distro_pre_filtering:true \
       -v "marketplace_image:Canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest"

OS Inference
------------

The resolver recognizes image strings from multiple sources:

.. list-table::
   :header-rows: 1
   :widths: 30 40 30

   * - Variable
     - Example Value
     - Inferred OS
   * - ``marketplace_image``
     - ``Canonical 0001-com-ubuntu-server-jammy 22_04-lts-gen2 latest``
     - Ubuntu
   * - ``marketplace_image``
     - ``RedHat RHEL 9_4 latest``
     - Redhat
   * - ``marketplace_image``
     - ``suse sles-15-sp6 gen2 latest``
     - SLES
   * - ``marketplace_image``
     - ``almalinux almalinux-arm 9-arm-gen2 latest``
     - AlmaLinux
   * - ``vhd``
     - ``https://storage.blob.core.windows.net/vhds/ubuntu-22.04.vhd``
     - Ubuntu
   * - ``shared_gallery``
     - ``/subscriptions/.../galleries/.../images/cbl-mariner-2-gen2``
     - CBLMariner

The alias dictionary covers common distro names, publisher names, and
abbreviations:

.. list-table::
   :header-rows: 1
   :widths: 40 30 30

   * - Aliases
     - Resolved Class
     - Family
   * - ubuntu, canonical
     - Ubuntu
     - Debian
   * - debian
     - Debian
     - Debian
   * - rhel, redhat
     - Redhat
     - Red Hat
   * - centos, openlogic
     - CentOs
     - Red Hat
   * - almalinux, alma
     - AlmaLinux
     - Red Hat
   * - oracle, ol
     - Oracle
     - Red Hat
   * - suse, sles, opensuse
     - Suse / SLES
     - SUSE
   * - fedora
     - Fedora
     - Fedora
   * - azurelinux, azlinux, azl, mariner, cblmariner
     - CBLMariner
     - Azure Linux
   * - freebsd, openbsd, bsd
     - FreeBSD / OpenBSD / BSD
     - BSD
   * - alpine
     - Alpine
     - Alpine
   * - coreos, flatcar, kinvolk
     - CoreOs
     - CoreOS

Test Selection Flow
-------------------

The full test selection pipeline with the distro pre-filter:

1. **Discover all test cases** — LISA loads all registered
   ``TestCaseMetadata`` from the codebase.

2. **Apply distro pre-filter** — if ``enable_distro_pre_filtering``
   is ``true`` and a ``target_os`` can be inferred, cases incompatible
   with that OS are dropped.

3. **Process runbook filters** — criteria (name, area, category,
   priority, tags, maturity) and select actions (include / exclude /
   forceInclude / forceExclude) are applied.

4. **Apply the implicit stable gate** — non-stable tests are dropped
   unless explicitly approved (see :doc:`test_maturity_model`).

5. **Runtime guards** — at execution time, remaining ``isinstance`` +
   ``SkippedException`` checks in ``before_case()`` provide
   defense-in-depth.

Adding OS Metadata to Test Cases
---------------------------------

To benefit from the pre-filter, test suites should declare
``supported_os`` or ``unsupported_os`` in their requirement metadata:

.. code-block:: python

   from lisa import simple_requirement
   from lisa.operating_system import CBLMariner, Debian, Ubuntu

   @TestSuiteMetadata(
       area="network",
       category="functional",
       description="Network tests for Debian-family distros",
       requirement=simple_requirement(
           supported_os=[Debian],  # Includes Ubuntu and all Debian descendants
       ),
   )
   class DebianNetworkSuite(TestSuite):
       ...

Or to exclude specific distros:

.. code-block:: python

   @TestSuiteMetadata(
       area="storage",
       category="functional",
       description="Storage tests not supported on FreeBSD",
       requirement=simple_requirement(
           unsupported_os=[FreeBSD],
       ),
   )
   class StorageSuite(TestSuite):
       ...

.. important::

   When adding ``supported_os`` / ``unsupported_os`` metadata, ensure it
   matches the runtime ``isinstance`` guard in ``before_case()``. If the
   two drift, the pre-filter may incorrectly drop (or keep) a case. The
   runtime guard remains authoritative.

Design Constraints and Known Limitations
-----------------------------------------

This is a **v1 opportunistic optimization**, not a final architecture.

.. list-table::
   :header-rows: 1
   :widths: 25 40 35

   * - Aspect
     - Current (v1)
     - Future direction
   * - Intent declaration
     - Dual: ``supported_os`` metadata + ``isinstance`` runtime guard
     - Single ``@requires_distro`` decorator driving both
   * - Image resolution
     - Name-based heuristic (substring matching on image string)
     - Structured metadata from Azure API (publisher/offer/sku fields)
   * - Failure mode
     - Graceful — unknown image = no pre-filter, falls back to current
       behavior
     - Same (this is already correct)
   * - Runtime guards
     - Kept as defense-in-depth; they remain the authoritative check
     - Unified: decorator auto-generates both pre-filter and runtime
       guard

**Key limitations:**

1. **Heuristic-based inference** — The OS resolver uses substring
   matching on image strings. Unusual image names or typos may not be
   recognized, in which case the pre-filter is silently skipped.

2. **DRY trade-off** — The ``supported_os`` metadata and runtime
   ``isinstance`` guards can drift if an author updates one but not the
   other. The runtime guard is always authoritative.

3. **Short alias false positives** — Aliases shorter than 4 characters
   (e.g. ``ol``, ``azl``) require token-boundary matching to avoid
   false hits from substrings in unrelated image names.

Summary
-------

The distro pre-filter provides a low-risk optimization that reduces
wasted VM deployments by dropping clearly incompatible test cases at
selection time. It preserves the existing runtime guards as
defense-in-depth and gracefully degrades when the target OS cannot be
determined. Enable it by setting ``enable_distro_pre_filtering: true``
in your runbook.
