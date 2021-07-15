Microsoft tests
===============

-  `Overview <#overview>`__
-  `Some terms <#some-terms>`__

   -  `Test priority <#test-priority>`__
   -  `Test tier <#test-tier>`__

-  `How to run Microsoft tests <#how-to-run-microsoft-tests>`__

   -  `Advanced <#advanced>`__

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

The priority of each test case is determined by the impact if it’s
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
   performance drops significantly, like SRIOV doesn’t work as expected;
   only one CPU core works on multiple core machine; an important
   feature doesn’t work with default settings; or the system can be used
   with limited functionality.
-  **P2**. The system fails/hangs on start/restart using unpopular
   configurations. Data loss with unpopular configurations. The system
   cannot be connected with popular configurations. The system
   performance drops obviously. An important feature doesn’t work with
   popular configurations.
-  **P3**. A feature doesn’t work with unpopular configurations with low
   impact.
-  **P4**. The system has obvious but not serious problems on long-haul,
   stress or performance test scenarios.

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
more from `how to run LISA tests <run.html>`__ to run different tiers on
an image or existing environment.

LISA comes with a set of test suites to verify Linux distro/kernel
quality on Microsoft’s platforms (including Azure, and HyperV). The test
cases in those test suites are organized with multiple test ``Tiers``
(``T0``, ``T1``, ``T2``, ``T3``, ``T4``).

You can specify the test cases by the test tier, with
``-v tier:<tier id>``:

.. code:: bash

   lisa -r ./microsoft/runbook/azure.yml -v subscription_id:<subscription id> -v "admin_private_key_file:<private key file>" -v tier:<tier id>

Advanced
~~~~~~~~

If you want to verify on specified conditions, like to select some VM
size in azure, or select test cases by names, learn more from `runbook
reference <runbook.html>`__.

Test cases specification
------------------------

.. admonition:: TODO

   add spec of LISA test cases.

.. seealso::

   Not migrated `legacy LISAv2
   tests <https://github.com/microsoft/lisa/blob/master/Documents/LISAv2-TestCase-Statistics.html>`__
   for more information.
