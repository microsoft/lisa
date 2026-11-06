PR validation case and image selection
======================================

The Azure DevOps PR pipeline uses ``.github/scripts/ai_select_cases.py`` to
produce ``ai_selection/ai_selected_cases.json``. This plan, rather than the
legacy YAML selection fragment, is the authoritative input to execution.

Automatic validation targets pull requests into ``main``. Draft pull requests
do not trigger runs (``pr.drafts: false``), including model selection and guest
execution. Mark a PR ready for review to enable normal PR validation. This
trigger filter does not prevent an explicitly queued manual run.

PR triggers read the YAML in the PR source branch. Existing branches must pick
up this configuration, for example by merging the latest ``main``, for the
Draft filter to apply.

Selection rules
---------------

* Changed test methods, including metadata edits, are required. Shared helper
  edits conservatively include cases from the affected file or testsuite area.
  Changes in multiple files are accumulated.
* Removing complete decorated test methods without changing remaining code
  produces ``not_required`` with no model call or guest execution. Complete
  test-only suite/file removals are also skipped; deleted helper or other
  executable code is not treated as case-only removal. The selector checks the
  original Git blob from the full PR diff against the current AST. Renames still
  require the new case name. Mixed changes retain coverage for remaining case,
  helper, tool, or framework edits, without selecting a case merely because it
  follows a removed method. References to removed test methods retain
  conservative suite coverage rather than being classified as safe deletion.
* Framework feature and tool changes require at least one matching test for
  every detected feature/tool. AI ranks related candidates; it cannot remove
  these obligations. Priority and naming conventions are not evidence that a
  different test covers the same path.
* OS implementation changes follow public OS wrappers and in-file test helpers
  to find direct test callers. For example, changing ``Suse._update_packages``
  recalls tests that call ``node.os.update_packages``, rather than treating the
  OS change as an unrelated smoke-test request.
* The selector imports only the selected testsuite modules and checks their
  registered OS and platform requirements. Ambiguous method names are errors.
* Images come exclusively from the reviewed list in
  ``.github/copilot-instructions.md``. Changed OS classes and enclosing OS
  branches constrain image selection. For example, a SUSE-specific change cannot
  fall back to Ubuntu. Compatible cases are grouped by image.
* Version comparisons or changes affecting both architectures/generations need
  explicit images. Set the pipeline's ``validationImages`` parameter to a JSON
  array of exact strings from the reviewed list, for example:

  .. code-block:: json

     ["suse sles-12-sp5 gen2 latest", "suse sles-15-sp6 gen2 latest"]

  Explicit images are checked against the affected OS constraints. Reviewers
  must ensure these images cover the relevant version boundaries; the selector
  does not attempt to prove arbitrary conditional expressions.
* Documentation/comment-only changes produce ``not_required`` with no guest
  tests. Missing mappings, unsupported target distributions/platforms, invalid
  model responses with no covered obligations, and model API failures are not
  replaced with a successful-looking smoke run.
* Known non-Azure suites (including OpenVMM/MSHV host coverage), and cases whose
  registered platform requirement excludes Azure, produce ``manual_required``.
  The plan contains suite-qualified ``recommendations`` with platform/host
  prerequisites, reasons, required-case flags, and ``not_executed`` status.
  Image/version selection does not turn these cases into ordinary Azure tests.
  No execution groups or executable legacy filters are emitted. Mixed Azure
  and dedicated-platform selections are conservatively deferred together;
  validate the Azure cases separately rather than treating partial coverage as
  completion. Missing case mappings still fail explicitly.
  The pipeline publishes recommendations in its summary, selection artifact,
  and PR comment without deploying Azure VMs or publishing fake JUnit results.
  Unsupported platforms are recommendation-only and do not fail the pipeline.
  A successful pipeline means the recommendations were published, not that the
  suggested tests passed or that regressions were excluded. Dedicated host
  validation remains unexecuted; other selection, CI, or publication errors
  still fail normally.
  PR comments show a summary table followed by one row per recommended case,
  including its platform, execution status, prerequisites, and selection reason.
  The same recommendation table appears in the pipeline summary and the
  selector's GitHub step summary. Empty images are shown as ``Not applicable``.
  The PR overview reports ``Test execution result``, not the overall pipeline
  job status. With no executable cases, this is ``Skipped`` even when the job
  successfully publishes recommendations. For executed plans, it reflects raw
  head outcomes: ``Passed``, ``Failed``, ``Skipped``, or ``Incomplete``.
  Missing execution reports remain ``Not completed``. A matching baseline
  failure does not turn a failed head test into ``Passed``.

Model configuration
-------------------

Selection uses the Azure OpenAI v1 Responses API. Pipeline variables continue
to supply the API key, endpoint, and deployment name:

* ``azure_openai_api_key``: the existing secret API key.
* ``azure_openai_endpoint``: either the HTTPS resource root or its
  ``/openai/v1`` base URL, optionally with a trailing slash.
* ``azure_openai_deployment``: the actual Azure deployment name, for example
  ``gpt-5.4`` when a deployment with that name exists.

No ``azure_openai_api_version`` variable is needed. The request posts to
``/openai/v1/responses`` with the deployment in the ``model`` field. Authentication
remains API-key based; no Entra ID or service-connection change is required.
Reasoning-only, refused, incomplete, and empty responses are explicit errors,
not empty successful selections. The client does not send a ``temperature``
parameter, so deployments that do not support it can be used.

Execution and results
---------------------

The PR validation job has a total timeout of 360 minutes (six hours), including
setup, execution, and any failure-triggered baseline runs. Individual LISA test
case timeouts remain unchanged.

``run_selected_cases.py`` runs inside the Azure CLI service-connection task.
Before deploying guests, it queries every selected image in the configured
region using ``az vm image show`` and resolves ``latest`` to a concrete version.
An unavailable target fails validation rather than switching distributions.

Groups run sequentially with exact method-name filters. The plan records
suite-qualified identities and rejects ambiguous method names. LISA retains
responsibility for VM capability/SKU matching; the selector's preflight checks
OS and platform, not every hardware or runtime prerequisite. Both stable and
preview cases can be selected so directly changed preview tests are not silently
excluded.

Each group has a fresh runtime log directory, passed to LISA as an absolute
``--log_path`` so execution and JUnit verification use the same directory.
Relative log paths would be prefixed with LISA's own runtime directory.
Execution uses a head-first, failure-triggered baseline comparison. The pipeline
records the checked-out candidate SHA and a fixed target ancestor SHA before
execution. Only cases with JUnit failures/errors on head are rerun on that base.
Head PASS cases do not consume additional baseline VMs.

Baseline code is checked out in a detached worktree and installed with its own
``.[azure]`` dependencies in a separate virtual environment. Both sides use
fresh environments, the same resolved image version, region and subscription.
Baseline VM size is pinned to the observed head deployment. Deployment
configuration signatures also compare image, OS disk size, capability
maximization and recorded disk/network/security settings. Ambiguous,
heterogeneous or different VM topologies make the comparison incomplete rather
than accepting an unfair comparison. Groups run sequentially; environment
reuse is disabled and deletion is awaited.

Results distinguish:

* ``suspected_regression``: head fails, base passes. Blocks validation.
* ``same_failure``: both fail with the same failure type and diagnostic
  signature. Does not block the regression gate, but is **not** a test PASS or
  proof that the PR is correct. A shared failure can mask later regressions.
* ``different_failure``: both fail with different signatures. Blocks validation.
* ``inconclusive``: missing/skipped/inconsistent results, malformed JUnit,
  baseline setup/deployment failure, or an invalid comparison. Blocks validation.

Signatures ignore checkout paths and traceback line numbers, but preserve
semantic diagnostic values. Flaky or environment-dependent failures can still
require reviewer-directed paired reruns. A FAIL alone is never classified as a
regression without a valid base comparison. Without ``--base-sha``, failures
remain blocking and no baseline is run.

The ``pr_validation_results.json`` artifact records per-case head/base outcomes,
signatures, compared SHAs, resolved image versions and comparison verdicts.
Raw head and baseline JUnit reports are published separately, retaining actual
failures instead of relabeling them as PASS. The runner, not raw JUnit publication,
controls the regression gate. Other groups still run after a group fails.

Limitations
-----------

Static impact detection is conservative, not a coverage proof. In particular,
dynamic dispatch, indirect OS-specific helpers, runtime skips, hardware
requirements, and arbitrary version predicates still need reviewer attention.
Historical failure/flakiness data is not used as a selection input. Tests added
only by the PR have no base result and cannot be excused as existing failures.
This policy does not compare performance thresholds or every PASS case against
base. Bug-fix validation should still include explicit baseline reproduction.
A passing gate demonstrates the selected comparisons, not every affected path.
