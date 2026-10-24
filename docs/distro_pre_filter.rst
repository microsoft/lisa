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

Ubuntu Release Requirements
---------------------------

``supported_os`` and ``unsupported_os`` accept OS classes as before, and
``OsRequirement`` entries with optional Ubuntu release bounds:

.. code-block:: python

   from lisa import OsRequirement, simple_requirement
   from lisa.operating_system import Oracle, Ubuntu

   requirement = simple_requirement(
       unsupported_os=[
           OsRequirement(Ubuntu, max_version="22.04"),
           Oracle,
       ],
   )

This excludes Ubuntu releases older than 22.04 and every Oracle release.
``min_version`` is inclusive and ``max_version`` is exclusive. For example,
``OsRequirement(Ubuntu, min_version="22.04", max_version="24.04")`` matches
Ubuntu releases from 22.04 up to, but not including, 24.04. In a supported
list it allows that range; in an unsupported list it excludes that range.
Entries in each list are alternatives. Both lists cannot be nonempty.

Bounds must use ``YY.MM`` format. Comparison uses the Ubuntu major/minor
release, so Ubuntu 22.04.5 belongs to the 22.04 release. Point releases,
kernel versions and image publication versions are not supported bounds.
Malformed bounds, empty/reversed ranges and bounds on a non-Ubuntu OS
raise a configuration error. Class-only requirements retain their existing
inheritance behavior; Ubuntu release numbers are never compared against
Debian or another distro's release numbers.

Version pre-filtering uses the existing ``enable_distro_pre_filtering``
switch and is implemented only for Ubuntu. It recognizes:

* Marketplace SKU releases such as ``16.04-LTS``, ``22_04-lts-gen2`` and
  ``pro-fips-22_04-arm64``.
* Marketplace offers such as ``ubuntu-24_04-lts`` and ``ubuntu-25_10``.
* Ubuntu codenames xenial (16.04), bionic (18.04), focal (20.04), jammy
  (22.04), noble (24.04), questing (25.10) and resolute (26.04).
* Clearly identified Ubuntu release/codename tokens in gallery image
  names and VHD filenames.

Gen1/Gen2, ARM64, FIPS and CVM variants share the same release rules.
Marketplace publication versions (the fourth field), gallery publication
versions, URL query strings and kernel versions are not used as releases.
The OS and release must come from the same image variable.

Unknown or conflicting release hints retain the test for runtime checking;
an unknown release must not turn a versioned exclusion into an exclusion of
all Ubuntu versions. Non-Ubuntu targets keep the existing distro-only
filtering, without version checks. Debug logs explain unrecognized or
conflicting Ubuntu release hints and show the requirements of dropped cases.
Both ``lisa run`` and ``lisa list`` use the same gated target resolution.
As with distro-only filtering, ``list --all`` does not bypass the pre-filter.

The actual connected Ubuntu guest's release is checked against the same
requirements at runtime, even when pre-filtering is disabled. Existing
runtime guards remain useful for conditions not expressed by this metadata.

Examples of existing tests using these requirements include SGX and
Secure/Measured Boot (Ubuntu 18.04 minimum), PTP time sync (Ubuntu 19.10
minimum), and the Azure Security Pack and Performance Diagnostics
extensions (discrete supported Ubuntu major versions). Major-version
allowlists use January boundaries to preserve the whole supported release
year, rather than restricting support to LTS releases. Architecture,
generation and kernel-dependent guards remain runtime checks.

SIG Image Naming for Ubuntu Release Inference
--------------------------------------------

For Shared Image Gallery (SIG/Azure Compute Gallery) images, include
``ubuntu`` and a recognizable release or codename in the **image definition
name**. Do not rely on the gallery name or image publication version to
identify the Ubuntu release.

The recommended naming convention is
``ubuntu-<YY.MM>-<architecture>-<generation>``, for example:

.. code-block:: text

   ubuntu-22.04-x64-gen2
   ubuntu-24.04-arm64-gen2
   ubuntu_22_04_x64_gen1
   ubuntu_26_04_arm64_gen2

Numeric release names follow the pattern ``ubuntu[-_]YY[._]MM``:

* Use a hyphen or underscore between ``ubuntu`` and the release.
* Use a dot or underscore between the two-digit year and two-digit month.
  For example, use ``22.04`` or ``22_04``, not ``22.4`` or ``22-04``.
* Put ``ubuntu`` at the start of the name or after a separator. Separate
  trailing labels such as ``arm64`` or ``gen2`` with a hyphen or underscore.
* Matching is case-insensitive. Architecture, generation, FIPS and CVM
  labels do not change the inferred release.

Alternatively, include a supported codename as a separate token:

.. code-block:: text

   ubuntu-jammy-gen2
   ubuntu_noble_arm64
   ubuntu-resolute-x64-gen2

.. list-table:: Supported Ubuntu codenames
   :header-rows: 1
   :widths: 50 50

   * - Codename
     - Release
   * - xenial
     - 16.04
   * - bionic
     - 18.04
   * - focal
     - 20.04
   * - jammy
     - 22.04
   * - noble
     - 24.04
   * - questing
     - 25.10
   * - resolute
     - 26.04

Include ``ubuntu`` as well as the codename: ``jammy-gen2`` alone does not
identify the OS. A custom image definition such as
``ubuntu_jammy_linux-azure_6.8.0-1071.79.22.04.1_x64_gen1`` resolves to
Ubuntu 22.04 through ``jammy``, not through the embedded kernel version.

Example runbook variables:

.. code-block:: yaml

   variable:
     - name: enable_distro_pre_filtering
       value: true
     - name: shared_gallery
       value: "<subscription>/<resource-group>/<gallery>/ubuntu-22.04-gen2/1.0.0"

Wire ``$(shared_gallery)`` to the Azure node requirement's ``shared_gallery``
field as usual. The resolver reads the variable named ``shared_gallery``.
In this example, ``1.0.0`` is the SIG publication version and is ignored for
Ubuntu release inference. For a full Azure resource ID, the resolver uses
the image definition name after ``/images/``, not the value after
``/versions/``.

.. list-table:: Image definition patterns to avoid
   :header-rows: 1
   :widths: 45 55

   * - Image definition name
     - Current inference
   * - ``ubuntu-server-22.04-gen2``
     - Ubuntu detected, release unknown: the numeric release must immediately
       follow ``ubuntu-`` or ``ubuntu_``.
   * - ``ubuntu-22-04-gen2``
     - Release unknown: a hyphen is not a supported year/month separator.
   * - ``ubuntu-22.04.5-gen2``
     - Release unknown: point-release syntax is not recognized for image names.
   * - ``jammy-gen2``
     - OS not identified from this name alone.
   * - ``ubuntu-jammy-ubuntu-24.04``
     - Conflicting recognized releases: version pre-filtering is deferred.
   * - ``ubuntu-jammy-24.04``
     - Resolves to 22.04 through ``jammy``; the standalone ``24.04`` is not
       recognized as an Ubuntu numeric release pattern.

Avoid inconsistent labels even when only one label is recognized.
Unknown releases and conflicting recognized releases retain cases for
runtime validation rather than dropping them through version pre-filtering.

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
