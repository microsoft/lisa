Understand test results
=======================

-  `Overview <#overview>`__
-  `Intermediate results <#intermediate-results>`__
-  `Final results <#final-results>`__

Overview
--------

It's essential to understand the results after running tests. LISA has 7
kinds of test results in total: 3 of which are intermediate results, and
4 of which are final results, as explained in sections below. Each test
case can and will be moved from one result to another but can never have
two or more results at the same time.

.. figure:: ../img/test_results.png
   :alt: test_results

Intermediate results
--------------------

An intermediate result shows information of an unfinished test. It will
show up when a test changes its state. If a test run terminates because
of error or exception prior to running a test case, only the
intermediate result will be provided.

-  **QUEUED**

   QUEUED tests are tests that are created, and planned to run (but have
   not started yet). They are pre-selected by extension/runbook
   criteria. You can check log to see which test cases are included by
   such criteria. They suggest that there are some tests waiting to be
   performed.

   QUEUED tests will try to match every created environment. They will
   move forward to ASSIGNED if they match any, and to SKIPPED if they
   match none of the environments.

-  **ASSIGNED**

   ASSIGNED tests are tests that are assigned to an environment, and
   will start to run, if applicable, once the environment is
   deployed/initialized. They suggest some environmental setting up is
   going on.

   ASSIGNED tests will end with FAILED if the environment fails to
   deploy. Otherwise, they move forward to RUNNING. They will also move
   backward to QUEUED if the environment is deployed and initialized
   successfully.

-  **RUNNING**

   RUNNING tests are tests that are in test procedure.

   RUNNING tests will end with one of the following final results.

Final results
-------------

A final result shows information of a terminated test. It provides more
valuable information than the intermediate result. It only appears in
the end of a successful test run.

-  **FAILED**

   FAILED tests are tests that did not finish successfully and
   terminated because of failures like ``LISA exceptions`` or
   ``Assertion failure``. You can use them to trace where the problem
   was and why the problem happened.

-  **PASSED**

   PASSED tests are tests that passed, or at least partially passed,
   with a special ``PASSException`` that warns there are minor errors in
   the run but they do not affect the test result.

-  **SKIPPED**

   SKIPPPED tests are tests that did not start and would no longer run.
   They suggest failure to meet some requirements in the environments
   involved with the test.

-  **ATTEMPTED**

   ATTEMPTED tests are a special category of FAILED tests because of
   known issues, which are not likely to be fixed soon.
