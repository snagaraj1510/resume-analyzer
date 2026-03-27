#!/usr/bin/env python3
"""Stress test for the Resume Analyzer rewrite pipeline.

Loads data/resume.md and data/jd.md, runs rewrite_resume, and asserts:
  1. Every bullet is under 250 characters.
  2. All starting verbs are unique (no duplicates).

Usage:
    python stress_test.py                          # Uses default provider (needs API key)
    python stress_test.py --provider "Ollama (Local)" --ollama-model llama3

Exit code 0 = all assertions pass. Exit code 1 = failure.
"""

import os
import re
import sys
import argparse

# Ensure the project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analyzer import rewrite_resume, validate_resume, PROVIDERS, OLLAMA_PROVIDER
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_file(filename: str) -> str:
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        print(f"FATAL: {path} not found.")
        sys.exit(1)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def extract_bullets(text: str) -> list[dict]:
    """Extract bullets from [P:X] formatted text."""
    bullets = []
    for line in text.strip().split("\n"):
        m = re.match(r'\[P:(\d+)\]\s*(.+)', line)
        if m:
            idx = int(m.group(1))
            raw = m.group(2).strip()
            is_bullet = (
                raw.startswith(("•", "-", "–", "▪"))
                or (len(raw) > 30 and raw[0].isupper() and not raw.isupper())
            )
            if is_bullet:
                clean = re.sub(r'^[•\-–▪■]\s*', '', raw)
                first_word = clean.split()[0].rstrip(",").lower() if clean.split() else ""
                bullets.append({
                    "index": idx,
                    "text": clean,
                    "chars": len(clean),
                    "verb": first_word,
                })
    return bullets


def main():
    parser = argparse.ArgumentParser(description="Stress test the resume rewrite pipeline.")
    parser.add_argument("--provider", default="Claude (Anthropic)", help="LLM provider name")
    parser.add_argument("--ollama-model", default=None, help="Ollama model name (if using Ollama)")
    parser.add_argument("--api-key", default=None, help="API key (overrides .env)")
    args = parser.parse_args()

    provider = args.provider
    ollama_model = args.ollama_model
    api_key = args.api_key

    if provider != OLLAMA_PROVIDER and not api_key:
        env_var = PROVIDERS.get(provider, {}).get("env_key", "")
        api_key = os.environ.get(env_var, "")
        if not api_key:
            print(f"FATAL: No API key found for {provider}. Set {env_var} or pass --api-key.")
            sys.exit(1)

    resume_text = load_file("resume.md")
    jd_text = load_file("jd.md")

    print(f"Provider: {provider}")
    print(f"Resume: {len(resume_text)} chars, JD: {len(jd_text)} chars")
    print("Running rewrite_resume (with self-healing validation loop)...")

    # Use a minimal analysis result to trigger rewrites
    analysis_stub = (
        "## Resume Score: 65/100\n"
        "### Top 5 Priority Fixes\n"
        "1. Add ATS keywords: strategy, operations, structured problem solving\n"
        "2. Reframe bullets for Strategy & Ops lens\n"
        "3. Add quantifiable metrics to all bullets\n"
        "4. Ensure verb uniqueness across all bullets\n"
        "5. Tighten bullet lengths to <220 chars\n"
    )

    result = rewrite_resume(
        job_title="Senior Strategy & Operations Analyst",
        job_description=jd_text,
        resume_text=resume_text,
        analysis_result=analysis_stub,
        api_key=api_key,
        provider=provider,
        ollama_model=ollama_model,
    )

    print(f"\nRewrite response length: {len(result)} chars")
    print("=" * 60)

    # Merge rewrites into original text for full validation
    from document_handler import parse_rewrite_response
    rewrites = parse_rewrite_response(result)
    print(f"Paragraphs rewritten: {len(rewrites)}")

    merged_lines = []
    for line in resume_text.strip().split("\n"):
        m = re.match(r'\[P:(\d+)\]\s*(.*)', line)
        if m:
            idx = int(m.group(1))
            if idx in rewrites:
                merged_lines.append(f"[P:{idx}] {rewrites[idx]}")
            else:
                merged_lines.append(line)
        else:
            merged_lines.append(line)
    merged_text = "\n".join(merged_lines)

    bullets = extract_bullets(merged_text)
    print(f"Bullets found: {len(bullets)}")
    print()

    # ── ASSERTION 1: Every bullet under 250 chars ──
    failures = []
    for b in bullets:
        if b["chars"] > 250:
            failures.append(f"  FAIL [P:{b['index']}] {b['chars']} chars (>250): {b['text'][:80]}...")
        else:
            print(f"  OK   [P:{b['index']}] {b['chars']} chars")

    if failures:
        print("\nCHAR LIMIT FAILURES:")
        for f in failures:
            print(f)

    # ── ASSERTION 2: All starting verbs are unique ──
    verbs = [b["verb"] for b in bullets]
    unique_verbs = set(verbs)
    verb_ok = len(unique_verbs) == len(verbs)

    print(f"\nVerbs ({len(verbs)} total, {len(unique_verbs)} unique):")
    verb_counts = {}
    for v in verbs:
        verb_counts[v] = verb_counts.get(v, 0) + 1
    for v, count in sorted(verb_counts.items()):
        status = "OK" if count == 1 else f"DUPLICATE (x{count})"
        print(f"  {v}: {status}")

    # ── ASSERTION 3: No markdown artifacts ──
    md_failures = []
    for b in bullets:
        if re.search(r'[*_]{2}', b["text"]):
            md_failures.append(f"  FAIL [P:{b['index']}] Contains markdown: {b['text'][:80]}...")

    print()
    print("=" * 60)

    # ── FINAL VERDICT ──
    all_ok = True

    if failures:
        print("ASSERTION 1 (char limit <250): FAILED")
        all_ok = False
    else:
        print("ASSERTION 1 (char limit <250): PASSED")

    if not verb_ok:
        print("ASSERTION 2 (unique verbs):    FAILED")
        all_ok = False
    else:
        print("ASSERTION 2 (unique verbs):    PASSED")

    if md_failures:
        print("ASSERTION 3 (no markdown):     FAILED")
        for f in md_failures:
            print(f)
        all_ok = False
    else:
        print("ASSERTION 3 (no markdown):     PASSED")

    # Also run the full validation pipeline
    validation = validate_resume(merged_text)
    if validation.issues:
        print(f"\nValidation issues remaining: {len(validation.issues)}")
        for issue in validation.issues:
            print(f"  - {issue}")

    print()
    if all_ok:
        print("ALL ASSERTIONS PASSED")
        sys.exit(0)
    else:
        print("SOME ASSERTIONS FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
