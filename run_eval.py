#!/usr/bin/env python3
"""Ask the Tenant Book - Batch Evaluation Runner.

Runs the grounded RAG engine against questions.jsonl (dev or heldout),
recording verbatim citations, tokens, and latency for grading.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add rag_pipeline to sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / "rag_pipeline"))

from rag_pipeline.engine import TenantBookEngine, answer_question, DEFAULT_API_KEY, DEFAULT_MODEL


def find_default_questions() -> str:
    candidates = [
        "questions/dev.jsonl",
        "openIgloo-frontend/questions/dev.jsonl",
        os.path.join(os.path.dirname(__file__), "questions", "dev.jsonl"),
        "/home/tattabalaji/Desktop/perP/openIgloo-frontend/questions/dev.jsonl",
        "/home/tattabalaji/Desktop/ask-the-tenant-book-20260917/questions/dev.jsonl",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "questions/dev.jsonl"


def find_default_out() -> str:
    if os.path.exists("openIgloo-frontend/results") or os.path.exists("openIgloo-frontend"):
        return "openIgloo-frontend/results/answers.jsonl"
    return "results/answers.jsonl"


def main():
    parser = argparse.ArgumentParser(description="Run batch evaluation on questions")
    parser.add_argument("--questions", default=None, help="Path to questions .jsonl file (default: auto-detected dev.jsonl)")
    parser.add_argument("--out", default=None, help="Output path for answers .jsonl (default: results/answers.jsonl)")
    parser.add_argument("--corpus", default=None, help="Corpus directory (defaults to auto-detected)")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of questions to evaluate")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Model name (e.g. gemini-3.5-flash-lite)")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="Gemini API Key")
    parser.add_argument("--base-url", default=None, help="Optional OpenAI-compatible base URL")
    args = parser.parse_args()

    # Resolve questions file
    questions_path = args.questions or find_default_questions()
    if not os.path.exists(questions_path):
        print(f"Error: Questions file '{questions_path}' not found.", file=sys.stderr)
        sys.exit(1)

    # Resolve output path
    out_path = args.out or find_default_out()
    # Guard against accidental terminal line splits like 'openIgloo-'
    if out_path.endswith("-") or not out_path.endswith(".jsonl"):
        if out_path.endswith("-"):
            out_path = find_default_out()
        elif not out_path.endswith(".jsonl"):
            out_path = os.path.join(out_path, "answers.jsonl")

    # Load engine
    engine = TenantBookEngine(args.corpus)
    print(f"Loaded engine with {len(engine.passages)} passages across {len(engine.manifest)} documents.")
    print(f"Using model: {args.model}")

    # Load questions
    questions = []
    with open(questions_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))

    if args.limit > 0:
        questions = questions[:args.limit]

    print(f"Evaluating {len(questions)} questions from {questions_path}...")
    print(f"Target output file: {out_path}")

    # Ensure output directory exists
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    manifest_out = {
        "model": args.model,
        "questions_count": len(questions),
        "per_question": [],
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_latency_s": 0.0,
    }

    t_start = time.time()
    with open(out_path, "w", encoding="utf-8") as f_out:
        for i, q in enumerate(questions, 1):
            q_id = q.get("id", f"q-{i}")
            print(f"[{i}/{len(questions)}] Processing {q_id} ({q.get('role')}, as of {q.get('as_of')})...", end=" ", flush=True)

            try:
                ans, metrics = answer_question(
                    engine,
                    q,
                    api_key=args.api_key,
                    model=args.model,
                    base_url=args.base_url,
                )
            except Exception as e:
                print(f"ERROR: {e}")
                ans = {
                    "id": q_id,
                    "status": "refused",
                    "answer": None,
                    "refusal_reason": "out_of_corpus",
                    "refusal_message": f"Execution error: {str(e)}",
                    "citations": [],
                    "governing": None,
                    "superseded_notice": None,
                }
                metrics = {"id": q_id, "input_tokens": 0, "output_tokens": 0, "latency_s": 0.0}

            f_out.write(json.dumps(ans, ensure_ascii=False) + "\n")
            f_out.flush()

            manifest_out["per_question"].append(metrics)
            manifest_out["total_input_tokens"] += metrics.get("input_tokens", 0)
            manifest_out["total_output_tokens"] += metrics.get("output_tokens", 0)
            manifest_out["total_latency_s"] += metrics.get("latency_s", 0.0)

            c_count = len(ans.get("citations", []))
            print(f"-> {ans.get('status')} ({c_count} cits, {metrics.get('latency_s')}s)")

            # Gentle pacing between queries to respect API rate limits
            time.sleep(0.5)

    total_time = round(time.time() - t_start, 2)
    manifest_out["total_wall_clock_s"] = total_time
    manifest_out["mean_latency_s"] = round(manifest_out["total_latency_s"] / max(1, len(questions)), 2)

    # Write answers_manifest.json
    manifest_path = out_path.replace(".jsonl", "_manifest.json")
    if manifest_path == out_path:
        manifest_path = out_path + "_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f_mf:
        json.dump(manifest_out, f_mf, indent=2)

    print(f"\n=======================================================")
    print(f" Evaluation Completed in {total_time}s")
    print(f" Output answers: {out_path}")
    print(f" Manifest:       {manifest_path}")
    print(f" Mean latency:   {manifest_out['mean_latency_s']}s/query")
    print(f"=======================================================")


if __name__ == "__main__":
    main()
