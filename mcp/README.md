# LISA MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that provides AI-native developer tools for the [LISA](https://github.com/microsoft/lisa) test automation framework.

## What It Does

The LISA MCP server gives AI assistants (Claude, GitHub Copilot, etc.) deep knowledge of LISA's conventions, enabling them to:

- **Write LISA tests** — scaffold test suites and cases with correct decorators, metadata, and structure
- **Generate runbooks** — produce valid YAML runbooks from natural language descriptions
- **Analyze logs** — parse LISA run logs, extract failures, and classify error types
- **Debug failures** — diagnose test failures with source correlation and root cause analysis
- **Explain concepts** — answer questions about LISA architecture, APIs, and patterns

## Tools

All tools follow the `lisa_{verb}_{noun}` naming convention to prevent collisions
when multiple MCP servers are connected simultaneously.

### Test Authoring (`test_writer.py`)
| Tool                              | Description                                                                                                                           |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `lisa_get_test_writer_guidelines` | Return the full lisa_test_writer prompt — the authoritative reference for writing LISA tests                                          |
| `lisa_write_test`                 | **Primary tool** — follows the mandatory Gather → Research → Design Plan workflow; returns structured metadata for agent-to-agent use |
| `lisa_scaffold_test_suite`        | Generate a complete test suite skeleton (use after design plan is confirmed)                                                          |
| `lisa_scaffold_test_case`         | Generate a single test case method (use after design plan is confirmed)                                                               |
| `lisa_list_test_requirements`     | Show requirements for a test method                                                                                                   |
| `lisa_save_test`                  | Write a generated test file into the repo at a validated, repo-relative path                                                          |
| `lisa_list_tests`                 | List test cases filtered by area, tier, and feature                                                                                   |

### Runbook (`runbook.py`)
| Tool                    | Description                                                             |
| ----------------------- | ----------------------------------------------------------------------- |
| `lisa_generate_runbook` | Produce a valid YAML runbook from natural language parameters           |
| `lisa_validate_runbook` | Check a runbook for structural issues                                   |
| `lisa_fix_runbook`      | Validate a runbook YAML and return a corrected version with explanation |

### Log Analysis (`log_analysis.py`)
| Tool                            | Description                                                                                                                                                                           |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lisa_analyze_log`              | Ingest a LISA run log, identify failures, and extract meaningful signal                                                                                                               |
| `lisa_explain_failure`          | Classify and explain a test failure — framework vs test vs infra                                                                                                                      |
| `lisa_summarize_run`            | High-level pass/fail/skip summary with failure themes grouped by area                                                                                                                 |
| `lisa_start_log_investigation`  | Bootstrap a full root-cause analysis — returns expert prompts, file listings, initial search hits, and next-step instructions. Accepts local paths or HTTPS URLs (SAS URLs supported) |
| `lisa_download_logs`            | Download log files from a URL (SAS, bearer token, or public) to the server for investigation                                                                                          |
| `lisa_get_log_analysis_prompts` | Expert analysis strategies for host AI reasoning                                                                                                                                      |
| `lisa_search_log_files`         | Regex search across log files in a directory                                                                                                                                          |
| `lisa_read_log_file`            | Read a log file with line range                                                                                                                                                       |
| `lisa_list_log_files`           | List files in a log directory                                                                                                                                                         |
| `lisa_diagnose_bug`             | Given a test name and failure log, reason about root cause and suggest a fix with code                                                                                                |

### Framework Knowledge (`knowledge.py`)
| Tool                     | Description                                                                             |
| ------------------------ | --------------------------------------------------------------------------------------- |
| `lisa_explain_concept`   | Answer framework questions: what is a Feature, how does environment matching work, etc. |
| `lisa_get_api_reference` | Look up a LISA class/function signature                                                 |
| `lisa_find_examples`     | Search test suites for relevant examples                                                |
| `lisa_list_tools`        | List all LISA tools (command wrappers)                                                  |
| `lisa_list_features`     | List all LISA features (platform capabilities)                                          |
| `lisa_explain_error`     | Look up LISA error types and resolution steps                                           |

### Execution (`execution.py`)
| Tool               | Description                                                             |
| ------------------ | ----------------------------------------------------------------------- |
| `lisa_run`         | Execute a runbook locally and return the run log — stdio transport only |
| `lisa_get_config`  | Show `~/.lisa/mcp_config.yaml` and report missing Azure settings        |
| `lisa_save_config` | Persist Azure settings so the user is prompted only once                |

`lisa_run` shells out to the local `lisa` CLI. It is unavailable over SSE: a
remote server has neither your Azure credentials nor a place to run VMs, so it
returns instructions to start `lisa-mcp` locally instead.

## Setup

### Prerequisites
- Python 3.10+
- MCP Python SDK 2.x (installed automatically). The server is built on
  `MCPServer`, which replaced `FastMCP` in SDK 2.0 — SDK 1.x will not work.

### Install

**From the git repository (no local clone needed):**

```bash
pip install "lisa-mcp @ git+https://github.com/microsoft/lisa.git@main#subdirectory=mcp"
```

**From a local clone:**

```bash
cd mcp
pip install -e .
```

### Run

```bash
# Local mode — stdio transport (for Claude Desktop, VS Code, etc.)
lisa-mcp

# Hosted mode — SSE/HTTP transport (for agent-to-agent pipelines, CI systems)
pip install "lisa-mcp[sse]"
export LISA_MCP_API_KEY="<shared secret>"
export LISA_LOG_ROOT="/var/log/lisa"
lisa-mcp --transport sse --port 8080
```

SSE mode exposes `GET /sse`, `POST /messages/`, and `GET /health` for load
balancer probes.

The server **refuses to start** when `--host` is network-reachable (the
default `0.0.0.0`) and `LISA_MCP_API_KEY` is unset. The tools can write test
files into the repo and read logs off disk, so an open listener would hand
those capabilities to anyone who can reach the port. Bind to `127.0.0.1` if
you genuinely want an unauthenticated local-only server.

Over SSE, the log tools additionally require `LISA_LOG_ROOT` and refuse any
path outside it — without that confinement `lisa_read_log_file` and friends
would be an arbitrary file reader for authenticated clients.

### Test execution settings

`lisa_run` needs Azure settings, stored outside the repo in
`~/.lisa/mcp_config.yaml`:

```yaml
azure:
  subscription_id: <your subscription id>
  resource_group: lisa-tests-rg
  location: eastus
  vm_size: Standard_DS2_v2
```

The first `lisa_run` call returns a prompt for whatever is missing; call
`lisa_save_config` with the user's answers to persist them. Each setting is
passed to LISA as a runbook variable — `resource_group` is sent as
`resource_group_name` to match `lisa/microsoft/runbook/azure.yml`.

## Configuration

### Claude Desktop

Add to your `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`, Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "lisa": {
      "command": "/path/to/lisa/.venv/bin/lisa-mcp"
    }
  }
}
```

### VS Code (GitHub Copilot)

Add to your workspace `.vscode/mcp.json`. Point `command` at the interpreter's
launcher rather than a bare `lisa-mcp`, so it works whether or not the
environment is activated and regardless of what is on `PATH`:

```json
{
  "servers": {
    "lisa": {
      "type": "stdio",
      "command": "${workspaceFolder}/.venv/Scripts/lisa-mcp.exe"
    }
  }
}
```

On Linux and macOS the launcher is `${workspaceFolder}/.venv/bin/lisa-mcp`.

A bare `"command": "lisa-mcp"` only works when the install directory is on
`PATH`. `pip install` without an active virtualenv silently falls back to a
per-user location (`%APPDATA%\Python\PythonXY\Scripts` on Windows,
`~/.local/bin` elsewhere) that usually is not, and the client then fails to
start the server.

If the package is installed somewhere other than the repo clone, tell the
server where the repo is — MCP clients sanitise the child environment, so a
shell-level export does not reach it:

```json
{
  "servers": {
    "lisa": {
      "type": "stdio",
      "command": "lisa-mcp",
      "env": { "LISA_REPO_ROOT": "/path/to/lisa" }
    }
  }
}
```

Editable installs (`pip install -e ./mcp`) locate the repo automatically and
need no `env` block.

### Environment Variables

| Variable              | Description                                                                                      |
| --------------------- | ------------------------------------------------------------------------------------------------ |
| `LISA_REPO_ROOT`      | Override auto-detected LISA repo root path. Takes precedence over the install location           |
| `LISA_MCP_CONFIG`     | Override the `~/.lisa/mcp_config.yaml` location                                                  |
| `LISA_MCP_API_KEY`    | SSE mode: shared secret required in the `X-API-Key` header. **Mandatory for non-loopback binds** |
| `LISA_LOG_ROOT`       | Confines the log tools to this directory. **Mandatory in SSE mode**; optional for stdio          |
| `ALLOWED_HOSTS`       | SSE mode: comma-separated `Host` header allowlist (default `localhost,127.0.0.1`)                |
| `FORWARDED_ALLOW_IPS` | SSE mode: proxy IPs permitted to set `X-Forwarded-*` (default `127.0.0.1`)                       |

### Remote Server (recommended for teams)

Run the MCP server centrally so clients don't need the LISA repo locally.

**With Docker:**

The build context must be `mcp/` — the Dockerfile does `COPY . /app/lisa/mcp`,
so building from the repo root copies the whole repository instead.

```bash
cd mcp
docker build -t lisa-mcp .

docker run -d --name lisa-mcp -p 8080:8080 \
  -e LISA_MCP_API_KEY="<shared secret>" \
  -e LISA_LOG_ROOT="/app/logs" \
  -e ALLOWED_HOSTS="your-server,localhost" \
  -v /var/log/lisa:/app/logs:ro \
  lisa-mcp
```

`LISA_MCP_API_KEY` is required — the server exits at startup without it,
because the container binds `0.0.0.0`. `LISA_LOG_ROOT` is required before the
log tools will read from disk in SSE mode; mount the directory holding the
runs you want analysed.

Keep `localhost` in `ALLOWED_HOSTS`. The container's `HEALTHCHECK` curls
`http://localhost:8080/health` from inside, so dropping it makes host
validation reject the probe with 400 and the container is marked unhealthy.

```bash
# Build from a specific branch of the LISA repo
docker build --build-arg LISA_BRANCH=<your-branch> -t lisa-mcp .

# Build where public PyPI is unreachable (corporate proxy, air-gapped CI)
docker build --build-arg PIP_INDEX_URL=https://<your-mirror>/pypi/simple/ \
  -t lisa-mcp .
```

Without a reachable index the build fails inside `pip install` with
`SSLV3_ALERT_HANDSHAKE_FAILURE` against `files.pythonhosted.org`, even though
`apt-get` and `git clone` in the same build succeed.

**Without Docker:**

```bash
git clone https://github.com/microsoft/lisa.git
cd lisa/mcp
pip install -e .
export LISA_MCP_API_KEY="<shared secret>"
export LISA_LOG_ROOT="/var/log/lisa"
lisa-mcp --transport sse --port 8080
```

Then configure clients to connect via URL — no local install required:

**VS Code (`mcp.json`):**

```json
{
  "servers": {
    "lisa": {
      "type": "sse",
      "url": "http://your-server:8080/sse",
      "headers": { "X-API-Key": "<shared secret>" }
    }
  }
}
```

**Claude Desktop (`claude_desktop_config.json`):**

```json
{
  "mcpServers": {
    "lisa": {
      "url": "http://your-server:8080/sse",
      "headers": { "X-API-Key": "<shared secret>" }
    }
  }
}
```

### Local Testing with Docker

Test the MCP server locally before deploying to a remote host:

```bash
# 1. Clone the repo
git clone --branch main https://github.com/microsoft/lisa.git
cd lisa/mcp

# 2. Build the image (add --build-arg PIP_INDEX_URL=... behind a proxy)
docker build -t lisa-mcp .

# 3. Run it
docker run -d --name lisa-mcp -p 8080:8080 \
  -e LISA_MCP_API_KEY=demo-secret \
  -e ALLOWED_HOSTS=localhost,127.0.0.1 \
  lisa-mcp

# 4. Verify
curl http://localhost:8080/health          # {"status":"ok","server":"lisa-mcp"}
curl -X POST http://localhost:8080/messages/   # 401 without the key
docker ps --filter name=lisa-mcp           # "(healthy)" after ~30s
docker logs lisa-mcp
```

Do not `curl` the `/sse` endpoint to check liveness — it is a Server-Sent
Events stream that stays open, so the command appears to hang. Use `/health`,
or connect a real MCP client.

Then in your VS Code workspace, create `.vscode/mcp.json`:

```json
{
  "servers": {
    "lisa": {
      "type": "sse",
      "url": "http://localhost:8080/sse",
      "headers": { "X-API-Key": "demo-secret" }
    }
  }
}
```

Reload VS Code and test via Copilot Chat. On Windows, `localhost:8080` reaches
a container on the WSL backend automatically.

```bash
# Stop when done
docker rm -f lisa-mcp
```

## Architecture

```
mcp/
├── Dockerfile             # Container image for remote SSE deployment
├── server.py              # Convenience entrypoint (delegates to lisa_mcp)
├── pyproject.toml         # Package config, entry point: lisa-mcp
├── lisa_mcp/
│   ├── server.py          # MCP server, tool registration, CLI (main entry point)
│   ├── auth.py            # X-API-Key middleware for SSE deployments
│   ├── config.py          # ~/.lisa/mcp_config.yaml read/write
│   ├── docs_index.yaml    # Manifest mapping tools → .rst/.md doc files
│   ├── context/           # Curated knowledge (supplements the .rst docs)
│   │   ├── concepts.md    # Core concepts explained
│   │   ├── test_patterns.md   # Canonical test writing patterns
│   │   ├── error_patterns.md  # Known errors → root cause → fix
│   │   └── runbook_schema.md  # Annotated runbook field reference
│   └── tools/
│       ├── _repo.py       # Repo root detection, doc/context loading
│       ├── test_writer.py # Test authoring tools (7 tools)
│       ├── runbook.py     # Runbook generate/validate/fix (3 tools)
│       ├── log_analysis.py# Log parsing, failure analysis, diagnosis (9 tools)
│       ├── knowledge.py   # Concept/API/example/error lookup (6 tools)
│       └── execution.py   # Local test execution and config (3 tools)
└── tests/                 # Self-tests for the MCP server
```

**Design principles:**
- **No LISA import required** — tools work against the repo file system and log text. Users don't need a LISA install to use the MCP server.
- **Context assembly, not AI calls** — tools provide structured LISA context to the host AI (Claude/Copilot). The MCP server itself doesn't call any LLM API.
- **Stateless** — each tool call is self-contained with no session state.
- **Test writer prompt integrated** — authoring tools follow the mandatory workflow from `.github/prompts/lisa_test_writer.prompt.md` (Gather → Research → Design Plan → Code).
- **Docs read at runtime** — .rst and .md files from the repo are loaded directly (no conversion needed). A single `docs_index.yaml` manifest maps each tool to its relevant doc files.

## Documentation Integration

The MCP server reads LISA's existing `.rst` documentation directly — no markdown conversion step required. LLMs read `.rst` perfectly well as plain text.

### How it works

A single manifest file, [docs_index.yaml](docs_index.yaml), maps each MCP tool to the relevant doc files:

```yaml
tools:
  lisa_write_test:
    primary: .github/prompts/lisa_test_writer.prompt.md
    supplementary:
      - docs/write_test/write_case.rst
      - docs/write_test/concepts.rst
      - docs/write_test/guidelines.rst

  lisa_explain_concept:
    primary: docs/write_test/concepts.rst
    supplementary:
      - docs/write_test/extension.rst
      - docs/run_test/runbook.rst

topics:
  runbook:     docs/run_test/runbook.rst
  platform:    docs/run_test/platform.rst
  transformer: docs/run_test/transformers.rst
```

- **`tools` section** — maps MCP tool names to their primary + supplementary doc files. Loaded when the tool is called.
- **`topics` section** — maps topic keywords to doc files. Used by `explain_concept` for targeted doc lookup.

### Adding new documentation

When a new `.rst` doc is added to the repo, update `docs_index.yaml` to map it to the relevant tools. No Python code changes needed.

## Test Authoring Workflow

The `write_test` tool implements the mandatory three-stage workflow from the `lisa_test_writer` prompt:

1. **Gather** — automatically searches `lisa/tools/`, `lisa/features/`, and existing test suites for relevant code
2. **Research** — extracts API signatures for discovered tools and features
3. **Design Plan** — produces an Arrange → Act → Assert plan with workspace references

The user confirms the design plan before code is generated via `scaffold_test_suite` or `scaffold_test_case`.

```
User: "Write a test to verify SR-IOV VFs are created"
  → lisa_write_test(description="SR-IOV VFs are created for each NIC", area="network", feature="Sriov")
  → Returns: Design plan with found tools (Lspci), features (Sriov), similar suites + structured JSON metadata
  → User confirms plan
  → lisa_scaffold_test_suite(...) generates the code skeleton
```

## Testing

```bash
cd mcp
python run_tests.py                 # everything (integration tests included)
python run_tests.py --unit          # unit + functional only, no subprocesses
python run_tests.py --smoke         # tool registration only
```

Tests that spawn LISA for real are skipped by default — they need LISA
installed in the same environment as the server and take tens of seconds:

```bash
LISA_MCP_RUN_TESTS=1 python run_tests.py
```

Container tests are skipped unless pointed at a running container:

```bash
LISA_MCP_CONTAINER_URL=http://localhost:8080 \
LISA_MCP_CONTAINER_KEY=demo-secret \
python -m unittest tests.test_mcp_integration.TestContainerDeployment -v
```

They check `/health`, that `/messages/` rejects a missing or wrong key, that an
unknown `Host` header is refused, and that a real SSE session can list tools and
call one that reads the repo baked into the image.

## Contributing

1. Add new tools in the appropriate `tools/` module
2. Register them in the `register_*_tools()` function
3. Update `context/` markdown files when LISA conventions change
4. Add tests in `tests/`
5. Update `docs_index.yaml` so the new tool gets its documentation context

## License

MIT — same as LISA.
