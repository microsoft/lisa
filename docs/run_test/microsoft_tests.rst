Microsoft tests
===============

-  `Overview <#overview>`__
-  `Some terms <#some-terms>`__

   -  `Test priority <#test-priority>`__
   -  `Test tier <#test-tier>`__

-  `How to run Microsoft tests <#how-to-run-microsoft-tests>`__

   -  `Advanced <#advanced>`__

-  `Storage queue-request experiment <#storage-queue-request-experiment>`__

-  `Test cases specification <#test-cases-specification>`__

Overview
--------

The test suite in LISA is called Microsoft tests, which are provided by
Microsoft Linux System Group. This document introduces how Microsoft
tests were defined, categorized, and how to have the appropriate
coverage.

Some terms
----------

Test priority
~~~~~~~~~~~~~

The priority of each test case is determined by the impact if it's
failed. The smaller number means the higher priority. For example, if a
high-priority test case fails, it means the operating system cannot
start. If a lower-priority test case fails, it may mean that a function
does not work.

Note that when multiple test cases fail, we should first check the
failure of high-priority test cases to speed up the analysis.

-  **P0**. The system fails/hangs on start/restart using default
   settings.
-  **P1**. The system fails/hangs on start/restart using popular
   configurations, for example, add firewall rules, install some popular
   packages. There is data loss with popular configurations. The system
   cannot be connected via network with default settings. The system
   performance drops significantly, like SRIOV doesn't work as expected;
   only one CPU core works on multiple core machine; an important
   feature doesn't work with default settings; or the system can be used
   with limited functionality.
-  **P2**. The system fails/hangs on start/restart using unpopular
   configurations. Data loss with unpopular configurations. The system
   cannot be connected with popular configurations. The system
   performance drops obviously. An important feature doesn't work with
   popular configurations.
-  **P3**. A feature doesn't work with unpopular configurations with low
   impact.
-  **P4**. The system has obvious but not serious problems on long-haul,
   stress or performance test scenarios.
-  **P5**. Test cases that require more than 1 day to execute or utility
   test cases that don't verify meaningful functionality for validation.

Please Note that the above examples do not cover all situations and are
for reference. For example, in a cloud environment, one host version may
cause problems of some Linux virtual machines. The impact is affected by
the percentage the problematic version also.

Test tier
~~~~~~~~~

Ideally, all tests should be run to maximize the coverage. But the time
and resource are limited, and the risks need to be minimized based on
the limitations. In LISA, Microsoft tests are organized into several
tiers to have the appropriate coverage using limited resource.

Test tiers can be T0, T1, T2, T3, T4. It maps to priorities of test
cases. For example, T0 means all P0 test cases are selected in a test
run. T2 means all P0, P1, P2 test cases are selected in a test run.

.. list-table::
   :header-rows: 1

   * - name
     - test priorities
     - time restriction
     - resource restriction
     - automation requirement
   * - T0
     - P0
     - 5 minutes
     - single VM
     - 100% automation, and no need for manual analysis of results.
   * - T1
     - P0, P1
     - 2 hours
     - 2 environments, and two VMs in each one
     - 100% automation, and no need for manual analysis of results.
   * - T2
     - P0, P1, P2
     - 8 hours
     - 2 environments
     - 100% automation
   * - T3
     - P0, P1, P2, P3
     - 16 hours
     - 2 environments
     - 100% automation
   * - T4
     - P0, P1, P2, P3, P4
     - no limitation
     - no limitation
     - 100% automation

How to run Microsoft tests
--------------------------

Microsoft tests are organized under the folder ``microsoft/runbook``.
The root folder contains runbooks for azure, ready, and local. Learn
more from :doc:`how to run LISA tests <run>` to run different tiers on
an image or existing environment.

.. note::
   To access Microsoft's internal test cases, you need to set
   ``import_builtin_tests: true`` in your runbook. This will import
   built-in test cases from the ``lisa/microsoft`` directory.
   See :doc:`runbook reference <runbook>` for more details.

LISA comes with a set of test suites to verify Linux distro/kernel
quality on Microsoft's platforms (including Azure, and HyperV). The test
cases in those test suites are organized with multiple test ``Tiers``
(``T0``, ``T1``, ``T2``, ``T3``, ``T4``).

You can specify the test cases by the test tier, with
``-v tier:<tier id>``:

.. code:: bash

   lisa -r ./microsoft/runbook/azure.yml -v subscription_id:<subscription id> -v "admin_private_key_file:<private key file>" -v tier:<tier id>

Advanced
~~~~~~~~

If you want to verify on specified conditions, like to select some VM size in
azure, or select test cases by names, learn more from :doc:`runbook reference
<runbook>`.

Storage queue-request experiment
--------------------------------

The ``StoragePerformance`` cases using the shared premium-data-disk helper
accept the optional ``fio_nr_requests_limit`` variable. This includes the
Premium SSD, Premium SSD v2, Ultra Disk and Standard SSD variants, including
their 4K, 1024K and io_uring cases where available.

To investigate whether block-layer request allocation contributes to NVMe
timeouts or low IOPS, first declare this optional, case-visible variable in
your existing runbook's ``variable`` section:

.. code:: yaml

   - name: fio_nr_requests_limit
     value: null
     is_case_visible: true

``is_case_visible`` is required for LISA to pass the variable to the test.
The null default keeps the experiment disabled. Run the existing case once
without an override (baseline), then repeat it with a positive integer ceiling:

.. code:: bash

   lisa -r <your-existing-runbook>
   lisa -r <your-existing-runbook> -v fio_nr_requests_limit:64

``64`` is a suggested initial trial, not a proven optimal value or a default
change to validation. A further trial at ``128`` can help compare the effect.
Omitting the variable or specifying ``0`` preserves the existing workload
and queue settings.

Without changing the runbook, set the case-visible environment variable
``CV_LISA_fio_nr_requests_limit`` in the actual LISA process/job/container.
Use ``64`` for the trial or ``0`` for an explicit baseline. LISA also accepts
uppercase environment-variable names, as used by Azure Pipelines. This still
requires an execution environment containing the updated LISA implementation.

The Linux-only experiment resolves only the selected raw data disks, logs
their original ``queue/nr_requests`` and scheduler, and lowers values above
the requested ceiling. It never increases a smaller value, changes the
scheduler, or writes to the OS/resource disks through a wildcard. The setting
is applied to each whole data disk, even though fio targets its partition.
It is read back before fio runs, and original values are restored on success,
workload failure or partial setup failure. Restoration errors are surfaced;
cleanup is attempted for every changed disk. Restoration requires a reachable
guest and cannot be guaranteed after a guest crash or runner termination.

The requested ceiling and effective per-device values are recorded in the
test result's ``information`` as ``fio_nr_requests_limit`` and
``fio_nr_requests_effective``. Review the original values in the log: if all
are already at or below the ceiling, the trial makes no queue changes.
Unsupported writes, unexpected readback or invalid values fail explicitly
rather than claiming the experiment was applied.

``nr_requests`` controls block-layer request allocation per block device,
not a single controller-wide NVMe outstanding-I/O limit. Its effect depends
on the kernel, scheduler and driver; an accepted value does not prove a
hardware queue-depth cap. See the `kernel sysfs block ABI documentation
<https://github.com/torvalds/linux/blob/v6.12/Documentation/ABI/stable/sysfs-block>`__.
The experiment leaves fio jobs, iodepth, runtime and performance reporting
unchanged. Compare IOPS, bandwidth and latency using matched image/kernel,
SKU, disk configuration and fio settings, and separately inspect console/kernel
logs for NVMe timeouts/resets even if fio and the case pass. This is a hypothesis
test, not a product fix or a reason to waive the original performance target.

Test cases specification
------------------------

Refer to :doc:`Test specification <test_spec>`.
