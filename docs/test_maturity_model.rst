Test Maturity Model
===================

Background
----------

LISA test suites are growing in size and complexity, with frequent
introduction of new tests and evolving validation coverage. Today, all
discovered tests are treated equally unless explicitly filtered via
runbook criteria, which makes it difficult to safely introduce immature
or experimental tests without impacting validation pipelines.

To address this, a test maturity model is proposed to govern both
lifecycle state and default execution behavior of tests.

Problem
-------

New or evolving tests require staged validation before being considered
production ready. Running such tests by default can:

-  Introduce instability into production validation pipelines.
-  Increase noise in failure signals.
-  Require ad-hoc runbook changes to manage execution scope.

At the same time, developers need a simple and consistent way to control
when tests are included in default execution.

Goals
-----

-  Introduce a single, unified concept for test readiness.
-  Ensure production-ready tests continue to run by default.
-  Prevent immature or unreliable tests from executing by default.
-  Preserve backward compatibility with existing LISA test suites.
-  Reuse the existing runbook selection model.

Proposal
--------

Introduce an optional ``maturity`` field in ``TestCaseMetadata`` (and
optionally ``TestSuiteMetadata`` for a suite-wide default):

If omitted, maturity defaults to **stable**, requiring no changes to
existing tests.

Why Not Tags?
~~~~~~~~~~~~~

Tags could theoretically encode maturity (e.g. ``tags: ["preview"]``),
but a dedicated field is preferred for several reasons:

-  **Semantic clarity** — maturity is a lifecycle property, not a
   topical grouping. Mixing the two in tags makes filtering ambiguous.
-  **Validated values** — the ``maturity`` field accepts only the four
   defined levels (``experimental``, ``preview``, ``stable``,
   ``deprecated``). Tags are free-form strings with no validation.
-  **Implicit gate** — the stable gate is applied automatically after
   all other selection rules. Implementing this with tags would require
   every runbook to explicitly exclude non-stable tags, which is
   error-prone and not backward compatible.
-  **Inheritance** — a suite-level maturity default is inherited by all
   its test cases unless overridden. Tags do not support this
   inheritance model.

Suite vs Case Maturity Precedence
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When both ``TestSuiteMetadata`` and ``TestCaseMetadata`` specify a
``maturity`` value, the **case-level value wins**. If the case does not
set ``maturity``, it inherits the suite's value. If neither is set, the
default is ``stable``.

.. code-block:: python

   @TestSuiteMetadata(
       area="example",
       category="functional",
       description="Suite with preview maturity",
       maturity="preview",       # suite-wide default
   )
   class ExampleSuite(TestSuite):

       @TestCaseMetadata(
           description="Inherits suite maturity (preview)",
           priority=2,
       )
       def test_inherits_preview(self, ...) -> None: ...

       @TestCaseMetadata(
           description="Overrides to stable",
           priority=2,
           maturity="stable",    # case-level override
       )
       def test_overrides_to_stable(self, ...) -> None: ...

Test Maturity Levels
--------------------

The ``maturity`` field defines both lifecycle stage and default execution
behavior.

.. list-table::
   :header-rows: 1
   :widths: 20 50 30

   * - Maturity
     - Description
     - Runs by Default
   * - Experimental
     - Early-stage or actively evolving test.
     - No
   * - Preview
     - Functionally complete but still under validation.
     - No
   * - Stable (default)
     - Production-ready.
     - Yes
   * - Deprecated
     - No longer recommended.
     - No

.. note::

   ``experimental``, ``preview``, and ``stable`` describe an entry
   lifecycle of increasing readiness. ``deprecated`` is a separate
   retirement state — a test may be fully mature yet deprecated. All
   non-stable levels share the same default-execution behavior (not run
   by default) but remain distinct lifecycle stages.

Default Behavior
----------------

-  Tests without a ``maturity`` value are treated as **stable**.
-  Only **stable** tests run by default.
-  Other maturity levels are excluded unless explicitly included.

.. important::

   This changes the framework's default selection behavior. Today, when
   no criteria are supplied, LISA selects all discovered cases. Under
   this proposal an implicit "stable-only" gate is applied to the final
   selection. This is backward compatible for test authors (an unset
   maturity defaults to stable) and produces no errors for existing
   runbooks, but the effective set of selected cases will shrink as
   tests are marked non-stable. This is by design.

Enabling Non-Stable Tests
~~~~~~~~~~~~~~~~~~~~~~~~~

Non-stable tests are included by referencing ``maturity`` in runbook
criteria. This requires a new ``maturity`` criterion (see
`Changes Required`_); it is not supported by the existing criteria keys.

Benefits
--------

-  Backward compatible for test authors (unset maturity ⇒ stable).
-  Safe introduction of new tests.
-  Clear and explicit test lifecycle.
-  No breaking changes or errors for existing runbooks (effective
   selection may shrink by design).
-  Encourages gradual promotion (experimental → preview → stable).

Default & Override Behavior
---------------------------

.. admonition:: Principle

   An implicit ``maturity == stable`` gate is applied to the final
   selection. It is augmented (not replaced) by any explicit maturity
   reference and always overridden by ``forceInclude``.

Truth table — does a test of maturity *M* run?

.. list-table::
   :header-rows: 1
   :widths: 18 18 22 22 20

   * - Test maturity
     - (1) No maturity in runbook (default)
     - (2) criteria maturity: [preview], include
     - (3) forceInclude of this test (no maturity key)
     - (4) forceExclude of this test
   * - stable
     - Runs
     - Runs (still default)
     - Runs
     - Excluded
   * - preview
     - Skipped
     - Runs (explicitly included)
     - Runs (force overrides gate)
     - Excluded
   * - experimental
     - Skipped
     - Skipped (not referenced)
     - Runs (force overrides gate)
     - Excluded
   * - deprecated
     - Skipped (+ optional warning if run)
     - Skipped
     - Runs + deprecation warning
     - Excluded

Precedence (highest to lowest):

1. ``forceExclude`` — always wins; the test never runs.
2. ``forceInclude`` — runs the test regardless of maturity (escape hatch
   for experimental/deprecated).
3. **Explicit maturity criteria** — include/exclude rules that name a
   maturity scope selection to those levels.
4. **Implicit stable gate** — applied last; drops any remaining
   non-stable case not covered above.

Test Selection Flow
-------------------

The following describes the step-by-step order of operations when LISA
selects test cases with the maturity model enabled:

1. **Discover all test cases** — LISA loads all registered
   ``TestCaseMetadata`` from the codebase. Each case has a resolved
   maturity (case-level → suite-level → ``stable``).

2. **Apply target OS pre-filter** — if a ``target_os`` is configured,
   cases incompatible with that OS are dropped.

3. **Process runbook filters sequentially** — each filter rule in the
   runbook's ``testcase`` list is applied in order:

   a. Criteria (name, area, category, priority, tags, **maturity**) are
      matched against the case metadata.
   b. The ``select_action`` (include / exclude / forceInclude /
      forceExclude) determines whether matched cases are added to or
      removed from the selection.
   c. If the filter contains a ``maturity`` criterion **and** the action
      is include or forceInclude, all matched cases are recorded in the
      **maturity-approved** set.

4. **Apply the implicit stable gate** — for every case still in the
   selection:

   - If ``maturity == stable`` → **keep** (always passes the gate).
   - If the case is in the **force-included** set → **keep** (force
     overrides the gate).
   - If the case is in the **maturity-approved** set → **keep**
     (explicitly approved by a maturity criterion).
   - Otherwise → **drop** (non-stable case with no explicit approval).

5. **Emit warnings** — any ``deprecated`` case that survived the gate
   (via forceInclude or maturity approval) triggers a deprecation
   warning in the log.

.. note::

   When no filters are specified in the runbook, LISA returns all
   discovered cases. The implicit stable gate still applies, so only
   ``stable`` cases are selected.

Changes Required
----------------

-  Add a ``maturity`` field to ``TestCaseMetadata`` (optional, defaults
   to ``stable``).
-  Add an optional suite-level ``maturity`` default in
   ``TestSuiteMetadata``.
-  Add a ``maturity`` criterion to the runbook selection model.
-  Apply the implicit stable gate in the test selector.

Summary
-------

The test maturity model provides a simple and safe way to introduce and
manage tests in LISA. It preserves existing author behavior while
enabling controlled onboarding and lifecycle progression for new and
evolving tests.
