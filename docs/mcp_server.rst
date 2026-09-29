Use the LISA MCP server
=======================

The LISA Model Context Protocol (MCP) server gives AI assistants access to
LISA-specific tools and documentation. It can help users author tests, create
and validate runbooks, investigate logs, diagnose failures, and look up LISA
concepts and APIs.

The server does not call an AI model. It gathers structured information from
the LISA repository and returns that context to the AI assistant connected to
it.

Why LISA uses MCP
-----------------

Writing a LISA test requires knowledge of decorators, metadata conventions,
tool and feature APIs, environment matching, and cleanup requirements.
Runbooks have a detailed schema, and investigating logs requires correlating
failure patterns with framework and test code.

MCP turns these workflows into discoverable operations that an AI assistant
can call from a natural-language conversation. The server supplies
LISA-specific context so the assistant reasons about LISA instead of treating
it as a generic Python project.

Capabilities
------------

All LISA MCP tool names use the ``lisa_{verb}_{noun}`` convention so they do
not collide with tools from other MCP servers.

Tools belong to one of two categories:

* **Context assembly tools** load relevant LISA documentation, source
  references, patterns, and user input. The client AI interprets the returned
  context.
* **Mechanical tools** perform deterministic work such as parsing,
  validation, file I/O, or process execution.

Test authoring
~~~~~~~~~~~~~~

The test-authoring tools follow LISA's design-first workflow:

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Tool
     - Purpose
   * - ``lisa_write_test``
     - Research existing tools, features, and tests, then produce a design
       plan for a new test.
   * - ``lisa_get_test_writer_guidelines``
     - Return the authoritative LISA test-writing guidance.
   * - ``lisa_scaffold_test_suite``
     - Generate a test suite skeleton after the design plan is approved.
   * - ``lisa_scaffold_test_case``
     - Generate one test case method after the design plan is approved.
   * - ``lisa_list_test_requirements``
     - Show the requirements declared for a test.
   * - ``lisa_save_test``
     - Save generated test code to a validated path in the repository.
   * - ``lisa_list_tests``
     - Find existing tests by area, tier, or feature.

Runbooks
~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Tool
     - Purpose
   * - ``lisa_generate_runbook``
     - Generate a YAML runbook from a natural-language description.
   * - ``lisa_validate_runbook``
     - Check a runbook for structural and schema issues.
   * - ``lisa_fix_runbook``
     - Return a corrected runbook and explain the changes.

Log analysis and debugging
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Tool
     - Purpose
   * - ``lisa_start_log_investigation``
     - Start a root-cause investigation with file listings, initial search
       results, analysis guidance, and recommended next steps.
   * - ``lisa_download_logs``
     - Download logs from an HTTPS URL for investigation.
   * - ``lisa_analyze_log``
     - Extract failures and useful signals from a LISA run log.
   * - ``lisa_explain_failure``
     - Classify and explain a framework, test, or infrastructure failure.
   * - ``lisa_summarize_run``
     - Summarize pass, fail, and skip results and group failure themes.
   * - ``lisa_get_log_analysis_prompts``
     - Return expert strategies for log analysis by the host AI.
   * - ``lisa_search_log_files``
     - Search log files with a regular expression.
   * - ``lisa_read_log_file``
     - Read a selected range from a log file.
   * - ``lisa_list_log_files``
     - List files available in a log directory.
   * - ``lisa_diagnose_bug``
     - Correlate a test failure with source code and suggest a root cause and
       fix.

Framework knowledge
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Tool
     - Purpose
   * - ``lisa_explain_concept``
     - Explain LISA concepts such as features and environment matching.
   * - ``lisa_get_api_reference``
     - Look up the signature of a LISA class or function.
   * - ``lisa_find_examples``
     - Find relevant examples in existing test suites.
   * - ``lisa_list_tools``
     - List LISA command-wrapper classes.
   * - ``lisa_list_features``
     - List LISA platform capability classes.
   * - ``lisa_explain_error``
     - Look up known error types and resolution guidance.

Test execution and configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 32 68

   * - Tool
     - Purpose
   * - ``lisa_run``
     - Run LISA locally with the configured Azure settings. This tool is
       available only over the ``stdio`` transport.
   * - ``lisa_get_config``
     - Show the effective MCP configuration and any missing Azure settings.
   * - ``lisa_save_config``
     - Save Azure settings outside the repository.

Prerequisites
-------------

The MCP server requires:

* Python 3.10 or later.
* MCP Python SDK 2.x. The package installs the supported SDK automatically.
* A local LISA checkout for repository-aware tools. An editable installation
  detects its checkout automatically.
* LISA and valid Azure configuration when using ``lisa_run``.

Install the server
------------------

Install directly from the LISA repository:

.. code-block:: bash

   pip install "lisa-mcp @ git+https://github.com/microsoft/lisa.git@main#subdirectory=mcp"

This clones the whole LISA repository into a temporary directory even though
only the ``mcp`` subdirectory is installed.

.. note::

   On Windows this fails during checkout with ``Filename too long``. Some
   sample logs under ``lisa/ai/data`` sit near the 260 character limit, and
   pip's temporary directory name consumes about a hundred characters before
   them. Enable long paths in Git — the ``LongPathsEnabled`` registry
   setting does not cover Git:

   .. code-block:: powershell

      git config --global core.longpaths true

For development, install from a local checkout:

.. code-block:: bash

   cd mcp
   pip install -e .

If the package is not installed from a LISA checkout, set
``LISA_REPO_ROOT`` to the repository path so repository-aware tools can find
the source and documentation.

Run locally with stdio
----------------------

The default ``stdio`` transport is intended for a local MCP client such as
Visual Studio Code or Claude Desktop:

.. code-block:: bash

   lisa-mcp

.. note::

   ``lisa-mcp: The term 'lisa-mcp' is not recognized`` (or
   ``command not found``) means the launcher was installed somewhere that is
   not on ``PATH``, not that the installation failed. Installing with a
   Python whose ``Scripts`` directory is not writable — the usual case for
   ``C:\Program Files\PythonXXX`` — makes pip fall back to a per-user
   location that is off ``PATH`` by default:

   * Windows: ``%APPDATA%\Python\PythonXXX\Scripts``
   * Linux and macOS: ``~/.local/bin``

   Find the launcher and run it by full path, or activate the virtual
   environment it belongs to:

   .. code-block:: powershell

      Get-ChildItem -Recurse -Filter lisa-mcp.exe "$env:APPDATA\Python", ".venv"
      .\.venv\Scripts\Activate.ps1

   Installing into a virtual environment avoids the problem, and MCP client
   configurations should use the full path in any case — see below.

Configure Visual Studio Code
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add a server definition to ``.vscode/mcp.json`` in the workspace. On Linux
and macOS:

.. code-block:: json

   {
     "servers": {
       "lisa": {
         "type": "stdio",
         "command": "${workspaceFolder}/.venv/bin/lisa-mcp"
       }
     }
   }

On Windows, use
``${workspaceFolder}/.venv/Scripts/lisa-mcp.exe`` as the command.

Pointing to the virtual environment's launcher is more reliable than using
the bare ``lisa-mcp`` command because MCP clients may not inherit the user's
shell ``PATH``.

If the package is installed outside the repository checkout, pass the
repository location explicitly:

.. code-block:: json

   {
     "servers": {
       "lisa": {
         "type": "stdio",
         "command": "lisa-mcp",
         "env": {
           "LISA_REPO_ROOT": "/path/to/lisa"
         }
       }
     }
   }

Configure Claude Desktop
~~~~~~~~~~~~~~~~~~~~~~~~

Add the server to ``claude_desktop_config.json``:

.. code-block:: json

   {
     "mcpServers": {
       "lisa": {
         "command": "/path/to/lisa/.venv/bin/lisa-mcp"
       }
     }
   }

On Windows, use ``C:/path/to/lisa/.venv/Scripts/lisa-mcp.exe``. As with
Visual Studio Code, give the full path rather than a bare ``lisa-mcp``.

Configure local test execution
------------------------------

``lisa_run`` reads Azure settings from ``~/.lisa/mcp_config.yaml`` by
default:

.. code-block:: yaml

   azure:
     subscription_id: <subscription id>
     resource_group: lisa-tests-rg
     location: eastus
     vm_size: Standard_DS2_v2

When required values are missing, ``lisa_run`` returns a prompt describing
them. The AI assistant can collect the values and call
``lisa_save_config``. The server stores this file outside the repository and,
on platforms that support POSIX permissions, restricts it to the current
user.

Use ``LISA_MCP_CONFIG`` to select a different configuration file.

Run as a remote server
----------------------

The ``sse`` transport exposes the MCP server over HTTP for team services and
agent-to-agent pipelines:

.. code-block:: bash

   pip install "lisa-mcp[sse]"
   export LISA_MCP_API_KEY="<shared secret>"
   export LISA_LOG_ROOT="/var/log/lisa"
   lisa-mcp --transport sse --host 0.0.0.0 --port 8080

The server exposes:

* ``GET /sse`` for the MCP Server-Sent Events connection.
* ``POST /messages/`` for MCP client messages.
* ``GET /health`` for unauthenticated health probes.

Deployment mode comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 25 37 38

   * - Attribute
     - Local ``stdio``
     - Remote ``sse``
   * - Connection
     - Standard input and output
     - HTTP and Server-Sent Events
   * - Lifetime
     - Started and stopped by the MCP client
     - Persistent service
   * - ``lisa_run``
     - Available
     - Unavailable
   * - Credentials
     - Uses the local user's credentials
     - Test execution credentials are not stored on the server
   * - Authentication
     - Not required because no network port is opened
     - ``X-API-Key`` shared-secret authentication
   * - Typical use
     - Individual contributors
     - Shared team services, CI, and agent-to-agent workflows

Remote client configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Configure a Visual Studio Code client with the server URL and shared key:

.. code-block:: json

   {
     "servers": {
       "lisa": {
         "type": "sse",
         "url": "https://lisa-mcp.example.com/sse",
         "headers": {
           "X-API-Key": "<shared secret>"
         }
       }
     }
   }

The same URL and header can be used by any MCP client that supports the SSE
transport.

Security requirements
~~~~~~~~~~~~~~~~~~~~~

The MCP tools can read logs and write test files. Apply the following
controls when hosting the server:

* Set ``LISA_MCP_API_KEY``. The server refuses to bind to a
  network-reachable address without a key. An unauthenticated listener is
  permitted only on a loopback address.
* Send the key in the ``X-API-Key`` header. Use TLS so the key is not sent
  over plaintext networks.
* Set ``LISA_LOG_ROOT``. In remote mode, log tools reject paths outside this
  directory.
* Set ``LISA_ALLOWED_STORAGE_ACCOUNTS`` before downloading logs from Azure
  Storage with an identity. SAS URLs use their own authorization and do not
  require an allowlist entry.
* Set ``ALLOWED_HOSTS`` to the public host names accepted by the service.
* Set ``FORWARDED_ALLOW_IPS`` only to trusted reverse-proxy addresses.
* Do not use the ``/sse`` endpoint as a liveness probe because it is a
  long-running event stream. Use ``/health``.

Downloads accept only HTTPS URLs. The server rejects destinations that
resolve to private, loopback, or link-local addresses and checks redirected
destinations again.

Environment variables
---------------------

.. list-table::
   :header-rows: 1
   :widths: 34 66

   * - Variable
     - Description
   * - ``LISA_REPO_ROOT``
     - Override the auto-detected LISA repository root.
   * - ``LISA_MCP_CONFIG``
     - Override the default ``~/.lisa/mcp_config.yaml`` path.
   * - ``LISA_MCP_API_KEY``
     - Shared secret for remote requests. Required for non-loopback binds.
   * - ``LISA_LOG_ROOT``
     - Directory to which log tools are confined. Required in remote mode.
   * - ``LISA_ALLOWED_STORAGE_ACCOUNTS``
     - Comma-separated Azure Storage accounts to which the server may
       authenticate. Required in remote mode for identity-based downloads.
   * - ``AZURE_STORAGE_TOKEN``
     - Optional pre-fetched storage bearer token. When omitted,
       ``DefaultAzureCredential`` is used.
   * - ``LISA_LOG_RETENTION_DAYS``
     - Retention period for downloaded log directories. The default is 7.
   * - ``LISA_LOG_MAX_DOWNLOADS``
     - Maximum number of downloaded log directories to retain. The default
       is 20.
   * - ``ALLOWED_HOSTS``
     - Comma-separated HTTP ``Host`` header allowlist.
   * - ``FORWARDED_ALLOW_IPS``
     - Reverse-proxy addresses trusted to supply ``X-Forwarded-*`` headers.

Container deployment
--------------------

Use the ``mcp`` directory as the Docker build context:

.. code-block:: bash

   cd mcp
   docker build -t lisa-mcp .
   docker run -d --name lisa-mcp -p 8080:8080 \
     -e LISA_MCP_API_KEY="<shared secret>" \
     -e LISA_LOG_ROOT="/app/logs" \
     -e ALLOWED_HOSTS="lisa-mcp.example.com,localhost" \
     -v lisa-downloads:/app/logs \
     -v /var/log/lisa:/app/logs/runs:ro \
     lisa-mcp

.. note::

   Where public PyPI is unreachable, the build fails inside ``pip install``
   with ``SSLV3_ALERT_HANDSHAKE_FAILURE`` against ``files.pythonhosted.org``
   even though ``apt-get`` and ``git clone`` in the same build succeed. Pass
   a mirror:

   .. code-block:: bash

      docker build --build-arg PIP_INDEX_URL=https://<your-mirror>/pypi/simple/ \
        -t lisa-mcp .

   Use ``--build-arg LISA_BRANCH=<branch>`` to build from a branch other than
   ``main``.

``LISA_LOG_ROOT`` must be writable because downloaded logs are retained
beneath it. Existing run logs may be mounted read-only in a child directory,
as shown above.

Keep ``localhost`` in ``ALLOWED_HOSTS`` when using the included container
health check. The health check connects to ``http://localhost:8080/health``
inside the container.

Verify a deployment
~~~~~~~~~~~~~~~~~~~

Check the health endpoint and authentication behavior:

.. code-block:: bash

   curl https://lisa-mcp.example.com/health
   curl -X POST https://lisa-mcp.example.com/messages/

The health request returns ``{"status":"ok","server":"lisa-mcp"}``. The
message request without a valid ``X-API-Key`` returns HTTP status 401.

Agent-to-agent workflow
-----------------------

An external automation framework with its own AI model can discover and call
the same LISA tools as a human-facing MCP client. For example, an incident
system can turn an uncovered failure into a proposed LISA test:

.. list-table::
   :header-rows: 1
   :widths: 10 25 65

   * - Step
     - Actor
     - Action
   * - 1
     - External AI agent
     - Detect a test-coverage gap and discover ``lisa_write_test`` through
       MCP tool listing.
   * - 2
     - External AI agent
     - Call ``lisa_write_test`` with the area, feature, tier, platform notes,
       and relevant failure information.
   * - 3
     - LISA MCP server
     - Assemble test-writing guidance, existing patterns, and source
       references, then return them to the external agent.
   * - 4
     - External AI agent
     - Review the context, produce a design, and generate the test after the
       design is approved.
   * - 5
     - LISA MCP server
     - Validate and save the generated file through ``lisa_save_test``.
   * - 6
     - External automation
     - Validate the change and open a pull request for human review.

The MCP server does not retain awareness of the overall workflow. Each tool
call is independent, and the calling agent is responsible for orchestration.

Architecture
------------

The server has five tool modules:

* ``test_writer.py`` for test authoring.
* ``runbook.py`` for runbook generation and validation.
* ``log_analysis.py`` for log investigation and failure diagnosis.
* ``knowledge.py`` for repository and framework knowledge.
* ``execution.py`` for local test execution and Azure configuration.

The implementation follows these principles:

* **No LISA import is required for most tools.** They operate on repository
  files and log text.
* **Context assembly, not model calls.** The connected AI assistant performs
  the reasoning.
* **Stateless tool calls.** Each call contains the information required to
  complete its operation.
* **Runtime documentation.** ``mcp/lisa_mcp/docs_index.yaml`` maps each MCP
  tool to relevant LISA ``.rst`` and ``.md`` files.

Tool naming
~~~~~~~~~~~

New tools must follow these rules:

* Always use the ``lisa_`` prefix.
* Put the verb before the noun, for example ``lisa_analyze_log``.
* Use snake case without abbreviations.
* Use a clear action verb such as ``analyze``, ``diagnose``, ``explain``,
  ``fix``, ``generate``, ``list``, ``run``, ``save``, ``scaffold``,
  ``summarize``, ``validate``, or ``write``.

Test-authoring workflow
-----------------------

LISA test authoring uses three stages:

1. **Gather and research**: ``lisa_write_test`` searches existing tests,
   tools, and features and extracts relevant API signatures.
2. **Design**: the tool returns an Arrange, Act, Assert plan with references
   to related source files. Review and approve this plan before generating
   code.
3. **Implement**: call ``lisa_scaffold_test_suite`` or
   ``lisa_scaffold_test_case``, review the generated code, and persist it with
   ``lisa_save_test``.

Test the MCP server
-------------------

Run the server's test suite from the ``mcp`` directory:

.. code-block:: bash

   python run_tests.py
   python run_tests.py --unit
   python run_tests.py --smoke

Tests that execute LISA are disabled by default. Enable them only in an
environment with LISA installed and valid execution configuration:

.. code-block:: bash

   LISA_MCP_RUN_TESTS=1 python run_tests.py
