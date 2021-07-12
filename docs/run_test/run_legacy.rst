How to run Legacy LISAv2 tests
==============================

`LISAv2 <https://github.com/microsoft/lisa>`__ brings incredible value
to Linux quality on Microsoft virtualization platforms. To increase the
value of LISA, we decide to continue to invest and have more innovation
on LISA. So, we started the next version.

During the transition time, we keep validating Linux kernels and
distributions. We cannot and don’t want to stop to wait for the exciting
current LISA. The two versions will be co-existing for a while. So, the
current LISA version supports to invoke previous LISAv2.

With this document, you will know how to run LISAv2 tests in the current
LISA. The current LISA clones the LISAv2 repo, start LISAv2, and parse
LISAv2 log to generate test results with new format.


.. attention::

   |:construction:| WIP |:construction:|
   Currently we are migrating previous LISAv2 test cases to this
   LISA framework. Before we complete the test case migration, only T0 test
   cases can be launched on LISA. Other test cases can be executed in LISA
   with “Compatibility mode”, which will invoke a shim layer to call
   LISAv2; so you need to run LISA on a Windows computer and provide the
   secret file.

Preparation
-----------

LISAv2 should run in the latest Windows 10 client 64 bits, or Windows
Server 2019 editions.

Follow `LISAv2
document <https://github.com/microsoft/lisa/blob/master/README.html>`__
to understand prerequisites and prepare secret files.

Note, you don’t need to clone the LISAv2 yourself, the current LISA will
clone it when running.

Limitations
-----------

1. The Test in Parallel of LISAv2 doesn’t support with the current LISA
   together. The current LISA implements test matrix to replace current
   test in parallel in LISAv2. There is no plan for compatibility with
   LISAv2 on this.
2. The LISAv2 results is possible to be missed in a rare race condition.
   There may be accessing conflict of LISAv2 test log. If it happens on
   key logs which relates to test result parsing, it may cause the
   status of results are not shown correctly.

Road map
--------

We’re migrating LISAv2 test cases to current LISA by test case priority.
We will keep t0 to tx runbooks update to date. When test cases migrated,
they will be included in current LISA, and remove from LISAv2. It’s
transparent when running LISA tests.
