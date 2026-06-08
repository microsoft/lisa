#!/usr/bin/env python3
# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

"""
Prompt Evaluation Runner for lisa_test_writer.prompt.md

Reads eval cases from cases.jsonl, sends each case's input to an LLM
(with the LISA test writer prompt as system message), then scores the
response against the rubric defined in each case.

Usage:
    # Ollama (local, free, no API key needed)
    python eval_runner.py --base-url http://localhost:11434/v1 --model llama3.1

    # Any OpenAI-compatible endpoint (LM Studio, vLLM, etc.)
    python eval_runner.py --base-url http://localhost:1234/v1 --model my-model

    # OpenAI
    python eval_runner.py --model gpt-4o

    # Anthropic Claude
    python eval_runner.py --model claude-opus-4-20250514

    # Azure OpenAI
    python eval_runner.py --model gpt-4o

Environment:
    LLM_BASE_URL           – OpenAI-compatible base URL (Ollama, LM Studio, etc.)
    LLM_API_KEY            – API key for the base URL (default: "ollama" if not set)
    --- OR ---
    ANTHROPIC_API_KEY      – Anthropic API key (for Claude models)
    --- OR ---
    OPENAI_API_KEY         – OpenAI API key
    --- OR ---
    AZURE_OPENAI_ENDPOINT  – Azure OpenAI endpoint URL
    AZURE_OPENAI_API_KEY   – Azure OpenAI API key
    AZURE_OPENAI_DEPLOYMENT – deployment name (overrides --model)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Judge prompt – used to score LLM responses against rubrics
# ---------------------------------------------------------------------------
_JUDGE_SYSTEM = textwrap.dedent(
    """\
You are an expert evaluator for a LISA test-writing AI assistant.
You will receive:
  1. The ORIGINAL USER REQUEST (what the user asked the AI to write).
  2. The AI RESPONSE (the output produced by the assistant).
  3. A RUBRIC with three sections:
     - must_have:  criteria that MUST appear in the response (scored 0 or 1 each)
     - should_have: criteria that SHOULD appear (scored 0 or 1 each, weighted 0.5)
     - must_not_have: anti-patterns that must NOT appear (scored 0 or 1 each,
       1 = violation found)

Return ONLY a JSON object (no markdown fences) with this schema:
{
  "must_have": {"<criterion>": {"pass": true/false, "evidence": "..."}, ...},
  "should_have": {"<criterion>": {"pass": true/false, "evidence": "..."}, ...},
  "must_not_have": {"<criterion>": {"violation": true/false, "evidence": "..."}, ...},
  "total_score": <float 0-100>,
  "summary": "<one paragraph overall assessment>"
}

Scoring formula:
  must_score     = (passed must_have) / (total must_have)           * 60
  should_score   = (passed should_have) / (total should_have)       * 25
  penalty        = (violations in must_not_have) / (total must_not)  * 15
  total_score    = must_score + should_score - penalty

Be strict but fair. Judge based on the rubric criteria only.
"""
)


@dataclass
class EvalCase:
    id: str
    category: str
    difficulty: str
    description: str
    input: str
    rubric: dict[str, list[str]]
    expected_references: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


@dataclass
class EvalResult:
    case_id: str
    category: str
    difficulty: str
    total_score: float
    must_have: dict[str, Any]
    should_have: dict[str, Any]
    must_not_have: dict[str, Any]
    summary: str
    raw_response: str


# ---------------------------------------------------------------------------
# LLM client abstraction
# ---------------------------------------------------------------------------
class LLMClient:
    """Thin wrapper supporting Ollama, any OpenAI-compatible endpoint,
    Anthropic Claude, OpenAI, and Azure OpenAI.

    Resolution order:
      1. Explicit base_url parameter  (--base-url or LLM_BASE_URL env)
      2. Anthropic Claude             (ANTHROPIC_API_KEY, or model starts with 'claude')
      3. Azure OpenAI                 (AZURE_OPENAI_ENDPOINT + KEY)
      4. OpenAI                       (OPENAI_API_KEY)
    """

    def __init__(
        self, model: str, base_url: str | None = None, api_version: str | None = None
    ) -> None:
        self._model = model
        self._base_url = base_url or os.environ.get("LLM_BASE_URL", "")
        self._api_version = api_version or "2024-12-01-preview"
        self._client = self._create_client()

    @property
    def provider_name(self) -> str:
        """Human-readable provider description for logging."""
        return self._provider

    def _create_client(self) -> Any:
        try:
            import openai  # noqa: F811
        except ImportError:
            print(
                "ERROR: 'openai' package not installed. "
                "Run: pip install openai>=1.0",
                file=sys.stderr,
            )
            sys.exit(1)

        # --- Priority 1: Explicit base URL (Ollama, LM Studio, vLLM, etc.) ---
        if self._base_url:
            api_key = os.environ.get("LLM_API_KEY", "ollama")
            self._provider = f"OpenAI-compatible ({self._base_url})"
            return openai.OpenAI(base_url=self._base_url, api_key=api_key)

        # --- Priority 2: Anthropic Claude ---
        api_key_anthropic = os.environ.get("ANTHROPIC_API_KEY", "")
        if api_key_anthropic or self._model.startswith("claude"):
            if not api_key_anthropic:
                print(
                    "ERROR: Model name starts with 'claude' but "
                    "ANTHROPIC_API_KEY is not set.",
                    file=sys.stderr,
                )
                sys.exit(1)
            self._provider = "Anthropic"
            self._is_anthropic = True
            return self._create_anthropic_client(api_key_anthropic)

        # --- Priority 3: Azure OpenAI ---
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        api_key_azure = os.environ.get("AZURE_OPENAI_API_KEY", "")
        if endpoint and api_key_azure:
            deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", self._model)
            self._model = deployment
            self._provider = f"Azure OpenAI ({endpoint})"
            return openai.AzureOpenAI(
                azure_endpoint=endpoint,
                api_key=api_key_azure,
                api_version=self._api_version,
            )

        # --- Priority 3: OpenAI ---
        api_key_openai = os.environ.get("OPENAI_API_KEY", "")
        if api_key_openai:
            self._provider = "OpenAI"
            return openai.OpenAI(api_key=api_key_openai)

        print(
            "ERROR: No LLM provider configured. Set one of:\n"
            "  --base-url URL          (Ollama, LM Studio, vLLM, etc.)\n"
            "  LLM_BASE_URL env var    (same, via environment)\n"
            "  ANTHROPIC_API_KEY       (Anthropic Claude)\n"
            "  OPENAI_API_KEY          (OpenAI)\n"
            "  AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_API_KEY  (Azure OpenAI)",
            file=sys.stderr,
        )
        sys.exit(1)

    @staticmethod
    def _create_anthropic_client(api_key: str) -> Any:
        try:
            import anthropic
        except ImportError:
            print(
                "ERROR: 'anthropic' package not installed. "
                "Run: pip install anthropic",
                file=sys.stderr,
            )
            sys.exit(1)
        return anthropic.Anthropic(api_key=api_key)

    def chat(self, system: str, user: str, temperature: float = 0.2) -> str:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                return self._chat_once(system, user, temperature)
            except Exception as e:
                err_str = str(e).lower()
                is_rate_limit = "rate" in err_str or "429" in err_str
                if is_rate_limit and attempt < max_retries - 1:
                    wait = 2**attempt * 10  # 10s, 20s, 40s
                    print(f"    Rate limited, retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise
        return ""  # unreachable

    def _chat_once(self, system: str, user: str, temperature: float) -> str:
        if getattr(self, "_is_anthropic", False):
            response = self._client.messages.create(
                model=self._model,
                max_tokens=8192,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return response.content[0].text

        response = self._client.chat.completions.create(
            model=self._model,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Core evaluation logic
# ---------------------------------------------------------------------------
def load_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    with open(path, encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"WARNING: skipping line {lineno}: {e}", file=sys.stderr)
                continue
            cases.append(
                EvalCase(
                    id=obj["id"],
                    category=obj.get("category", ""),
                    difficulty=obj.get("difficulty", ""),
                    description=obj.get("description", ""),
                    input=obj["input"],
                    rubric=obj["rubric"],
                    expected_references=obj.get("expected_references", {}),
                    notes=obj.get("notes", ""),
                )
            )
    return cases


def generate_response(client: LLMClient, system_prompt: str, case: EvalCase) -> str:
    """Send the eval case input to the LLM with the LISA prompt as system."""
    return client.chat(system=system_prompt, user=case.input, temperature=0.2)


def judge_response(client: LLMClient, case: EvalCase, response: str) -> dict[str, Any]:
    """Use LLM-as-judge to score the response against the rubric."""
    judge_user = json.dumps(
        {
            "user_request": case.input,
            "ai_response": response,
            "rubric": case.rubric,
        },
        indent=2,
    )
    raw = client.chat(system=_JUDGE_SYSTEM, user=judge_user, temperature=0.0)

    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {
            "must_have": {},
            "should_have": {},
            "must_not_have": {},
            "total_score": 0.0,
            "summary": f"Judge returned unparseable output: {raw[:500]}",
        }


def run_eval(
    prompt_path: Path,
    cases_path: Path,
    model: str,
    output_path: Path | None,
    case_filter: str | None = None,
    base_url: str | None = None,
    api_version: str | None = None,
) -> list[EvalResult]:
    system_prompt = prompt_path.read_text(encoding="utf-8")
    cases = load_cases(cases_path)

    if case_filter:
        filter_ids = {c.strip() for c in case_filter.split(",")}
        cases = [c for c in cases if c.id in filter_ids]

    if not cases:
        print("No eval cases to run.", file=sys.stderr)
        return []

    client = LLMClient(model, base_url=base_url, api_version=api_version)
    results: list[EvalResult] = []

    print(f"Running {len(cases)} eval case(s)")
    print(f"  Provider: {client.provider_name}")
    print(f"  Model:    {model}\n")

    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case.id} ({case.category}, {case.difficulty})")

        # Step 1: Generate response using the LISA prompt
        print("  Generating response...")
        response = generate_response(client, system_prompt, case)

        # Step 2: Judge the response
        print("  Judging response...")
        judgment = judge_response(client, case, response)

        score = judgment.get("total_score", 0.0)
        result = EvalResult(
            case_id=case.id,
            category=case.category,
            difficulty=case.difficulty,
            total_score=score,
            must_have=judgment.get("must_have", {}),
            should_have=judgment.get("should_have", {}),
            must_not_have=judgment.get("must_not_have", {}),
            summary=judgment.get("summary", ""),
            raw_response=response,
        )
        results.append(result)
        status = "PASS" if score >= 70 else "WARN" if score >= 50 else "FAIL"
        print(f"  Score: {score:.1f}/100 [{status}]\n")

    # Summary
    _print_summary(results)

    # Save results
    if output_path:
        output_data = {
            "model": model,
            "prompt_file": str(prompt_path),
            "cases_file": str(cases_path),
            "results": [
                {
                    "case_id": r.case_id,
                    "category": r.category,
                    "difficulty": r.difficulty,
                    "total_score": r.total_score,
                    "must_have": r.must_have,
                    "should_have": r.should_have,
                    "must_not_have": r.must_not_have,
                    "summary": r.summary,
                    "raw_response": r.raw_response,
                }
                for r in results
            ],
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(output_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nResults saved to {output_path}")

    return results


def _print_summary(results: list[EvalResult]) -> None:
    print("=" * 60)
    print("EVALUATION SUMMARY")
    print("=" * 60)

    if not results:
        print("No results.")
        return

    scores = [r.total_score for r in results]
    avg = sum(scores) / len(scores)
    passed = sum(1 for s in scores if s >= 70)
    warned = sum(1 for s in scores if 50 <= s < 70)
    failed = sum(1 for s in scores if s < 50)

    print(f"Total cases:  {len(results)}")
    print(f"Average score: {avg:.1f}/100")
    print(f"PASS (>=70):  {passed}")
    print(f"WARN (50-69): {warned}")
    print(f"FAIL (<50):   {failed}")
    print()

    # Per-category breakdown
    categories: dict[str, list[float]] = {}
    for r in results:
        categories.setdefault(r.category, []).append(r.total_score)

    print(f"{'Category':<30} {'Avg Score':>10} {'Count':>6}")
    print("-" * 50)
    for cat, cat_scores in sorted(categories.items()):
        cat_avg = sum(cat_scores) / len(cat_scores)
        print(f"{cat:<30} {cat_avg:>9.1f} {len(cat_scores):>6}")

    print()

    # Flag regressions
    for r in results:
        if r.total_score < 50:
            print(f"  REGRESSION: {r.case_id} scored {r.total_score:.1f}")


def _find_repo_root() -> Path:
    """Walk up from __file__ to find the repo root (contains .git or pyproject.toml)."""
    current = Path(__file__).resolve().parent
    for parent in [current, *current.parents]:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent
    # Fallback: assume standard 4-level nesting .github/prompts/eval/scripts/
    return Path(__file__).resolve().parent.parent.parent.parent


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate LISA test writer prompt quality",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """\
            Examples:
              # Run all cases
              python eval_runner.py

              # Run specific cases
              python eval_runner.py --filter basic_tool_test,reject_non_test

              # Ollama (local, no API key needed)
              python eval_runner.py --base-url http://localhost:11434/v1 --model llama3.1 # noqa: E501

              # LM Studio / vLLM / any OpenAI-compatible server
              python eval_runner.py --base-url http://localhost:1234/v1 --model my-model

              # Anthropic Claude
              python eval_runner.py --model claude-opus-4-20250514

              # OpenAI
              python eval_runner.py --model gpt-4o-mini

              # Azure OpenAI
              python eval_runner.py --model gpt-4o
        """
        ),
    )
    repo_root = _find_repo_root()
    prompts_dir = repo_root / ".github" / "prompts"
    eval_dir = prompts_dir / "eval"
    default_prompt = prompts_dir / "lisa_test_writer.prompt.md"
    default_cases = eval_dir / "cases.jsonl"
    default_output = eval_dir / "scripts" / "results.json"

    parser.add_argument(
        "--prompt",
        type=Path,
        default=default_prompt,
        help="Path to the system prompt file (default: %(default)s)",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=default_cases,
        help="Path to eval cases JSONL file (default: %(default)s)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=None,
        help="OpenAI-compatible base URL (Ollama, LM Studio, vLLM, etc.)",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        help="Model/deployment name (default: %(default)s)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help="Output JSON file for results (default: %(default)s)",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        help="Comma-separated list of case IDs to run",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=70.0,
        help="Minimum average score to pass (default: 70.0)",
    )
    parser.add_argument(
        "--api-version",
        type=str,
        default=None,
        help="Azure OpenAI API version (default: 2024-12-01-preview)",
    )

    args = parser.parse_args()

    if not args.prompt.exists():
        print(f"ERROR: Prompt file not found: {args.prompt}", file=sys.stderr)
        sys.exit(1)
    if not args.cases.exists():
        print(f"ERROR: Cases file not found: {args.cases}", file=sys.stderr)
        sys.exit(1)

    results = run_eval(
        prompt_path=args.prompt,
        cases_path=args.cases,
        model=args.model,
        output_path=args.output,
        case_filter=args.filter,
        base_url=args.base_url,
        api_version=args.api_version,
    )

    if results:
        avg_score = sum(r.total_score for r in results) / len(results)
        if avg_score < args.threshold:
            print(
                f"\nFAILED: Average score {avg_score:.1f} "
                f"is below threshold {args.threshold}",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            print(
                f"\nPASSED: Average score {avg_score:.1f} "
                f">= threshold {args.threshold}"
            )


if __name__ == "__main__":
    main()
