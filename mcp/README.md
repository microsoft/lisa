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
| Tool | Description |
|------|-------------|
| `lisa_get_test_writer_guidelines` | Return the full lisa_test_writer prompt — the authoritative reference for writing LISA tests |
| `lisa_write_test` | **Primary tool** — follows the mandatory Gather → Research → Design Plan workflow; returns structured metadata for agent-to-agent use |
| `lisa_scaffold_test_suite` | Generate a complete test suite skeleton (use after design plan is confirmed) |
| `lisa_scaffold_test_case` | Generate a single test case method (use after design plan is confirmed) |
| `lisa_list_test_requirements` | Show requirements for a test method |

### Runbook (`runbook.py`)
| Tool | Description |
|------|-------------|
| `lisa_generate_runbook` | Produce a valid YAML runbook from natural language parameters |
| `lisa_validate_runbook` | Check a runbook for structural issues |
| `lisa_fix_runbook` | Validate a runbook YAML and return a corrected version with explanation |

### Log Analysis (`log_analysis.py`)
| Tool | Description |
|------|-------------|
| `lisa_analyze_log` | Ingest a LISA run log, identify failures, and extract meaningful signal |
| `lisa_explain_failure` | Classify and explain a test failure — framework vs test vs infra |
| `lisa_summarize_run` | High-level pass/fail/skip summary with failure themes grouped by area |
| `lisa_start_log_investigation` | Bootstrap a full root-cause analysis — returns expert prompts, file listings, initial search hits, and next-step instructions. Accepts local paths or HTTPS URLs (SAS URLs supported) |
| `lisa_download_logs` | Download log files from a URL (SAS, bearer token, or public) to the server for investigation |
| `lisa_get_log_analysis_prompts` | Expert analysis strategies for host AI reasoning |
| `lisa_search_log_files` | Regex search across log files in a directory |
| `lisa_read_log_file` | Read a log file with line range |
| `lisa_list_log_files` | List files in a log directory |
| `lisa_diagnose_bug` | Given a test name and failure log, reason about root cause and suggest a fix with code |

### Framework Knowledge (`knowledge.py`)
| Tool | Description |
|------|-------------|
| `lisa_explain_concept` | Answer framework questions: what is a Feature, how does environment matching work, etc. |
| `lisa_get_api_reference` | Look up a LISA class/function signature |
| `lisa_find_examples` | Search test suites for relevant examples |
| `lisa_list_tools` | List all LISA tools (command wrappers) |
| `lisa_list_features` | List all LISA features (platform capabilities) |
| `lisa_explain_error` | Look up LISA error types and resolution steps |

### Execution (`execution.py`)
| Tool | Description |
|------|-------------|
| `lisa_run` | Run LISA tests locally via stdio transport (placeholder — requires local LISA install) |

## Setup

### Prerequisites
- Python 3.10+

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
lisa-mcp --transport sse --port 8080
```

## Configuration

### Claude Desktop

Add to your `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`, Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "lisa": {
      "command": "lisa-mcp"
    }
  }
}
```

### VS Code (GitHub Copilot)

Add to your workspace `.vscode/mcp.json`:

```json
{
  "servers": {
    "lisa": {
      "type": "stdio",
      "command": "lisa-mcp"
    }
  }
}
```

Or use `uvx` for a no-install option:

```json
{
  "servers": {
    "lisa": {
      "command": "uvx",
      "args": ["--from", "./mcp", "lisa-mcp"]
    }
  }
}
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `LISA_REPO_ROOT` | Override auto-detected LISA repo root path |

### Remote Server (recommended for teams)

Run the MCP server centrally so clients don't need the LISA repo locally.

**With Docker:**

```bash
# Build
cd mcp
docker build -t lisa-mcp .

# Run
docker run -p 8080:8080 lisa-mcp

# Build from a specific branch
docker build --build-arg LISA_BRANCH=<your-branch> -t lisa-mcp .
```

**Without Docker:**

```bash
git clone https://github.com/microsoft/lisa.git
cd lisa/mcp
pip install -e .
lisa-mcp --transport sse --port 8080
```

Then configure clients to connect via URL — no local install required:

**VS Code (`mcp.json`):**

```json
{
  "servers": {
    "lisa": {
      "type": "sse",
      "url": "http://your-server:8080/sse"
    }
  }
}
```

**Claude Desktop (`claude_desktop_config.json`):**

```json
{
  "mcpServers": {
    "lisa": {
      "url": "http://your-server:8080/sse"
    }
  }
}
```

### Local Testing with Docker (WSL)

Test the MCP server locally before deploying to a remote host:

```bash
# 1. Clone the repo
cd ~
git clone --branch main https://github.com/microsoft/lisa.git
cd lisa/mcp

# 2. Build the Docker image
docker build -t lisa-mcp .

# 3. Run the container
docker run -p 8080:8080 lisa-mcp

# 4. Verify (in a new terminal)
curl http://localhost:8080/sse
```

Then in your VS Code workspace, create `.vscode/mcp.json`:

```json
{
  "servers": {
    "lisa": {
      "type": "sse",
      "url": "http://localhost:8080/sse"
    }
  }
}
```

Reload VS Code and test via Copilot Chat — `localhost:8080` from Windows reaches the WSL container automatically.

```bash
# Stop when done
docker stop $(docker ps -q --filter ancestor=lisa-mcp)
```

## Architecture

```
mcp/
├── Dockerfile             # Container image for remote SSE deployment
├── server.py              # Convenience entrypoint (delegates to lisa_mcp)
├── pyproject.toml         # Package config, entry point: lisa-mcp
├── lisa_mcp/
│   ├── server.py          # MCP server, tool registration, CLI (main entry point)
│   ├── docs_index.yaml    # Manifest mapping tools → .rst/.md doc files
│   ├── context/           # Curated knowledge (supplements the .rst docs)
│   │   ├── concepts.md    # Core concepts explained
│   │   ├── test_patterns.md   # Canonical test writing patterns
│   │   ├── error_patterns.md  # Known errors → root cause → fix
│   │   └── runbook_schema.md  # Annotated runbook field reference
│   └── tools/
│       ├── _repo.py       # Repo root detection, doc/context loading
│       ├── test_writer.py # Test authoring tools (5 tools)
│       ├── runbook.py     # Runbook generate/validate/fix (3 tools)
│       ├── log_analysis.py# Log parsing, failure analysis, diagnosis (9 tools)
│       ├── knowledge.py   # Concept/API/example/error lookup (6 tools)
│       └── execution.py   # Local test execution (1 tool)
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

## Contributing

1. Add new tools in the appropriate `tools/` module
2. Register them in the `register_*_tools()` function
3. Update `context/` markdown files when LISA conventions change
4. Add tests in `tests/`

## License

MIT — same as LISA.
