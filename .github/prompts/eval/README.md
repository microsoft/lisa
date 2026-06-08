# LISA Prompt Evaluation Framework

Automated quality gate for `lisa_test_writer.prompt.md` — ensures prompt changes
don't degrade test-writing guidance quality.

## Architecture

```
eval/
├── README.md              ← this file
├── cases.jsonl            ← evaluation inputs & rubrics (the baselines)
└── scripts/
    ├── eval_runner.py     ← orchestrator: LLM call → judge → score
    └── results.json       ← output (not git-ignored by default; prefer an output path outside this repo or add a local .gitignore rule)
```

## How It Works

```
                 ┌─────────────────────┐
                 │ cases.jsonl         │
                 │ (user requests +    │
                 │  rubrics)           │
                 └────────┬────────────┘
                          │
                          ▼
  ┌──────────────────────────────────────────┐
  │  eval_runner.py                          │
  │                                          │
  │  For each case:                          │
  │   1. Send case.input to LLM              │
  │      (system = lisa_test_writer.prompt)  │
  │   2. Send LLM response to Judge LLM      │
  │      (system = scoring rubric)           │
  │   3. Score: must_have / should_have      │
  │             / must_not_have              │
  └──────────────────────────────────────────┘
                          │
                          ▼
               ┌─────────────────────┐
               │ results.json        │
               │ (per-case scores,   │
               │  evidence, summary) │
               └─────────────────────┘
```

## Quick Start

### Prerequisites

Install the base package (required for all providers except Anthropic-only):
```bash
pip install openai>=1.0
```

### Set API credentials

Pick **any one** of these providers — no Azure account required.

#### How to get API keys

| Provider          | How to get a key                                                                                                              |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| **Ollama**        | No key needed — runs locally for free                                                                                         |
| **Groq**          | Sign up at [console.groq.com/keys](https://console.groq.com/keys) — free tier, very fast inference                            |
| **Google Gemini** | Sign up at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) — free tier (region-dependent)                    |
| **Anthropic**     | Sign up at [console.anthropic.com](https://console.anthropic.com/) → Settings → API Keys → Create Key (starts with `sk-ant-`) |
| **OpenAI**        | Sign up at [platform.openai.com](https://platform.openai.com/) → API Keys → Create new secret key (starts with `sk-`)         |
| **Azure OpenAI**  | In [Azure Portal](https://portal.azure.com/) → create an Azure OpenAI resource → Keys and Endpoint                            |

**Option 1: Ollama (local, free, no API key)**

> **Note:** Local models run on CPU by default and can be very slow (30-60 minutes
> for all 10 cases). If you have an NVIDIA GPU, Ollama will use it automatically
> and run much faster. For quick iteration, consider using a cloud provider
> (Options 2-7) which typically completes in under 2 minutes.

```bash
1stly you need to install Ollama
# Windows:   winget install Ollama.Ollama
# macOS:     brew install ollama
# Linux:     curl -fsSL https://ollama.com/install.sh | sh

pip install openai>=1.0       # required dependency

ollama pull llama3.1          # or any model you prefer
ollama serve                  # starts on :11434 (skip if already running)

cd .github/prompts/eval/scripts
python eval_runner.py --base-url http://localhost:11434/v1 --model llama3.1 --threshold 65
```

**Option 2: Groq (free, fast inference)**

Get a free key at [console.groq.com/keys](https://console.groq.com/keys).

Linux/macOS:
```bash
pip install openai>=1.0
export LLM_API_KEY="your-groq-key"
cd .github/prompts/eval/scripts
python eval_runner.py --base-url https://api.groq.com/openai/v1 --model llama-3.3-70b-versatile
```

Windows PowerShell:
```powershell
pip install openai>=1.0
$env:LLM_API_KEY = "your-groq-key"
cd .github/prompts/eval/scripts
python eval_runner.py --base-url https://api.groq.com/openai/v1 --model llama-3.3-70b-versatile
```

**Option 3: Google Gemini (free tier)**

Get a free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey).

Linux/macOS:
```bash
pip install openai>=1.0
export LLM_API_KEY="your-gemini-key"
cd .github/prompts/eval/scripts
python eval_runner.py --base-url https://generativelanguage.googleapis.com/v1beta/openai/ --model gemini-2.0-flash
```

Windows PowerShell:
```powershell
pip install openai>=1.0
$env:LLM_API_KEY = "your-gemini-key"
cd .github/prompts/eval/scripts
python eval_runner.py --base-url https://generativelanguage.googleapis.com/v1beta/openai/ --model gemini-2.0-flash
```

**Option 4: Anthropic Claude**

Linux/macOS:
```bash
pip install anthropic
export ANTHROPIC_API_KEY="your-key"
cd .github/prompts/eval/scripts
python eval_runner.py --model claude-opus-4-20250514
```

Windows PowerShell:
```powershell
pip install anthropic
$env:ANTHROPIC_API_KEY = "your-key"
cd .github/prompts/eval/scripts
python eval_runner.py --model claude-opus-4-20250514

# Also works with other Claude models:
python eval_runner.py --model claude-sonnet-4-20250514
```

**Option 5: OpenAI**

Linux/macOS:
```bash
pip install openai>=1.0
export OPENAI_API_KEY="your-key"
cd .github/prompts/eval/scripts
python eval_runner.py --model gpt-4o
```

Windows PowerShell:
```powershell
pip install openai>=1.0
$env:OPENAI_API_KEY = "your-key"
cd .github/prompts/eval/scripts
python eval_runner.py --model gpt-4o
```

**Option 6: Azure OpenAI**

Linux/macOS:
```bash
pip install openai>=1.0
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
export AZURE_OPENAI_API_KEY="your-key"
export AZURE_OPENAI_DEPLOYMENT="gpt-4o"   # optional, overrides --model
cd .github/prompts/eval/scripts
python eval_runner.py
```

Windows PowerShell:
```powershell
pip install openai>=1.0
$env:AZURE_OPENAI_ENDPOINT = "https://your-resource.openai.azure.com/"
$env:AZURE_OPENAI_API_KEY = "your-key"
$env:AZURE_OPENAI_DEPLOYMENT = "gpt-4o"   # optional, overrides --model
cd .github/prompts/eval/scripts
python eval_runner.py
```

**Option 7: LM Studio / vLLM / any OpenAI-compatible server**

Linux/macOS:
```bash
pip install openai>=1.0
export LLM_API_KEY="your-key"   # only if server requires auth
cd .github/prompts/eval/scripts
python eval_runner.py --base-url http://localhost:1234/v1 --model my-model
```

Windows PowerShell:
```powershell
pip install openai>=1.0
$env:LLM_API_KEY = "your-key"   # only if server requires auth
cd .github/prompts/eval/scripts
python eval_runner.py --base-url http://localhost:1234/v1 --model my-model
```

> **Resolution order**: `--base-url` > Anthropic (ANTHROPIC_API_KEY or model=claude-*) > Azure OpenAI > OpenAI

### Run all eval cases

```bash
cd .github/prompts/eval/scripts
python eval_runner.py
```

### Run specific cases

```bash
cd .github/prompts/eval/scripts
python eval_runner.py --filter basic_tool_test,reject_non_test
```

### Custom model / threshold

```bash
cd .github/prompts/eval/scripts
# Compare multiple models side by side
python eval_runner.py --base-url http://localhost:11434/v1 --model llama3.1 --output results_llama.json
python eval_runner.py --base-url http://localhost:11434/v1 --model qwen2.5 --output results_qwen.json
python eval_runner.py --model claude-opus-4-20250514 --output results_claude.json
python eval_runner.py --model gpt-4o --output results_gpt4o.json

# Adjust pass threshold
python eval_runner.py --threshold 65
```

## Eval Cases Design

Cases are organized by **capability dimension**, not by test group.
Each case tests whether the prompt correctly guides the LLM in a specific aspect:

| Category                 | What It Tests                                | Prompt Steps  |
| ------------------------ | -------------------------------------------- | ------------- |
| `structure_and_aaa`      | Decorators, file paths, AAA pattern          | Step 4, 5, 6  |
| `feature_requirement`    | Feature declarations in `simple_requirement` | Step 3, 5     |
| `multi_node`             | Multi-node environment handling              | Step 5, 6     |
| `node_hygiene`           | `mark_dirty()`, cleanup, `after_case`        | Step 8        |
| `anti_pattern_rejection` | Refuses non-test requests                    | Step 1, 9, 10 |
| `complex_feature`        | Multi-feature + OS constraints               | Step 3, 5     |
| `skip_conditions`        | Precondition checks, skip vs fail            | Step 8        |
| `storage_validation`     | Disk operations, data integrity              | Step 3, 6     |
| `wait_patterns`          | Bounded retries, no `time.sleep()`           | Step 8        |
| `platform_operations`    | Platform-level ops (resize, stop/start)      | Step 5, 6     |

## Scoring

Each case has a rubric with three sections:

- **must_have** (60% weight) — criteria that MUST appear in the response
- **should_have** (25% weight) — criteria that SHOULD appear
- **must_not_have** (15% penalty) — anti-patterns that must NOT appear

```
score = (passed_must / total_must) × 60
      + (passed_should / total_should) × 25
      − (violations / total_must_not) × 15
```

Thresholds:
- **PASS**: score >= 70
- **WARN**: 50 <= score < 70
- **FAIL**: score < 50

## Adding New Cases

Add a new JSON line to `cases.jsonl`:

```json
{
  "id": "unique_case_id",
  "category": "capability_dimension",
  "difficulty": "easy|medium|hard",
  "description": "What this case tests",
  "input": "The user request sent to the LLM",
  "rubric": {
    "must_have": ["criterion_1", "criterion_2"],
    "should_have": ["criterion_3"],
    "must_not_have": ["anti_pattern_1"]
  },
  "expected_references": {
    "tools": ["ToolName"],
    "features": ["FeatureName"],
    "area": "test_area"
  },
  "notes": "Why this case matters"
}
```

### Guidelines for new cases

1. **One capability per case** — each case should primarily test one prompt rule
2. **Specific rubric criteria** — avoid vague criteria like "good code"
3. **Include anti-patterns** — `must_not_have` catches regressions effectively
4. **Vary difficulty** — maintain a mix of easy/medium/hard
5. **Real-world user requests** — write inputs as actual users would ask

## CI Integration

Add to your CI pipeline (GitHub Actions example):

```yaml
- name: Evaluate prompt quality
  env:
    AZURE_OPENAI_ENDPOINT: ${{ secrets.AZURE_OPENAI_ENDPOINT }}
    AZURE_OPENAI_API_KEY: ${{ secrets.AZURE_OPENAI_API_KEY }}
  run: |
    pip install openai>=1.0
    python .github/prompts/eval/scripts/eval_runner.py --threshold 70
```

The script exits with code 1 if the average score falls below `--threshold`.

## Interpreting Results

Output `results.json` contains per-case details:

```json
{
  "case_id": "basic_tool_test",
  "total_score": 82.5,
  "must_have": {
    "design_plan_before_code": {"pass": true, "evidence": "..."},
    "TestSuiteMetadata_decorator": {"pass": true, "evidence": "..."}
  },
  "summary": "Response correctly follows Design Plan workflow..."
}
```

**When a case regresses** after a prompt change:
1. Check the `evidence` field to understand what went wrong
2. Compare `raw_response` between old and new results
3. Adjust the prompt to fix the regression without breaking other cases
