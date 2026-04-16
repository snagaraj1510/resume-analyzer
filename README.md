# Resume Analyzer

[![Open in Streamlit](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://snagaraj1510-resume-analyzer-app-xrsimr.streamlit.app/)

**Live app:** https://snagaraj1510-resume-analyzer-app-xrsimr.streamlit.app/

A Streamlit web app that analyzes, scores, and rewrites resumes against job descriptions using AI. Supports multiple LLM providers and enforces strict guardrails to keep rewrites honest and interview-ready.

## Features

- **Multi-provider LLM** — Claude (Anthropic), GPT-4o (OpenAI), Gemini 2.5 Pro (Google), or Ollama (free, local)
- **100-point scoring rubric** — grades your resume across impact, relevance, formatting, and ATS compatibility
- **Agentic rewrite (Claude)** — Claude rewrites bullets then autonomously calls a validation tool, inspects results, fixes violations, and iterates until all guardrails pass
- **Self-healing rewrite (GPT-4o / Gemini / Ollama)** — rule-based rewrite → validate → correction pass loop, up to 2 passes
- **Metric injection pass** — all providers: if <70% of bullets have quantifiable outcomes, a dedicated pass adds or flags missing metrics
- **8-tier guardrail enforcement** — anti-hallucination, seniority honesty, ACR format, character limits, banned phrases, skill diversity, role framing, and change transparency
- **Sidebar chat** — ask questions, request targeted rewrites, or give vibe directives ("make it punchier") without leaving the app
- **Format preservation** — uploads and exports `.docx` with original styling intact; PDF and `.txt` input supported
- **User profiles** — save fact base (metrics, tools, constraints) across sessions for grounded, guardrail-compliant rewrites
- **JD auto-fetching** — paste a job posting URL and the app extracts the description automatically

## Guardrails

Every rewrite is enforced against 8 rules (G1–G8):

| Rule | Description |
|------|-------------|
| G1 — Fact Base | Every metric, tool, and stakeholder must trace to your original resume or saved profile. No invented numbers. |
| G2 — Seniority Honesty | Verbs accurately reflect your relationship to senior stakeholders. "Directed" vs. "Partnered with." |
| G3 — Bullet Format | ACR format (Action → Context → Result), <220 char target, 250 hard ceiling, no repeated lead verbs, no banned LLM-isms. |
| G4 — Skill Diversity | No more than 2 bullets share the same primary skill tag — resume covers the full JD requirement surface. |
| G5 — Role Framing | Auto-detects target role type (Strategy, BizOps, Finance, GTM, SWE, PM, etc.) and frames bullets accordingly. |
| G6 — Scoring Integrity | Re-scores after rewrite on the same rubric to verify measurable improvement. |
| G7 — Change Transparency | Every changed bullet is logged with before/after text and reason. |
| G8 — User Override | Users can override suggestions; the app warns if the override violates a guardrail. |

## How the Agentic Rewrite Works (Claude)

When using Claude as the provider, the rewrite step uses Anthropic's tool-calling API instead of a fixed loop:

1. Claude receives the resume, job description, and prior analysis
2. Claude writes its initial set of `[P:X]` bullet rewrites
3. Claude autonomously calls the `validate_bullets` tool with its proposed output
4. The tool runs the full validation pipeline (all G1–G8 rules) and returns structured violations
5. Claude reads the violations, fixes every issue, and calls `validate_bullets` again
6. The loop continues until `passed=true` or a maximum of 3 validation rounds
7. A final metric injection pass runs across all providers — if <70% of bullets are quantified, Claude adds metrics or inserts `[INSERT METRIC]` placeholders

For GPT-4o, Gemini, and Ollama, the same validation pipeline runs in a manually orchestrated loop (up to 2 correction passes) followed by the same metric injection pass.

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your API key

```bash
cp .env.example .env
# Add your key(s) to .env:
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# GOOGLE_API_KEY=...
```

Or enter the key directly in the app sidebar — no `.env` required.

### 3. Run

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

## Deploying to Streamlit Cloud

1. Push the repo to GitHub (see below)
2. Go to [share.streamlit.io](https://share.streamlit.io) and connect your repo
3. Set `app.py` as the main file
4. Add your API keys under **Settings → Secrets**:

```toml
ANTHROPIC_API_KEY = "sk-ant-..."
OPENAI_API_KEY = "sk-..."
GOOGLE_API_KEY = "..."
```

Streamlit Cloud exposes these as environment variables — no code changes needed.

## Using Ollama (Free, No API Key)

1. Install [Ollama](https://ollama.com)
2. Pull a model: `ollama pull llama3.1:8b`
3. Start Ollama: `ollama serve`
4. Select **Ollama (Local)** in the app sidebar

Note: Ollama does not support tool-calling — it uses the manual self-healing loop.

## File Structure

```
resume-analyzer/
├── app.py                      # Streamlit UI
├── analyzer.py                 # LLM prompts, agent rewrite, scoring, chat logic
├── document_handler.py         # .docx/.pdf read-write with formatting preservation
├── profile_manager.py          # User profile persistence
├── requirements.txt
├── references/                 # Bundled reference material for analysis
└── user_profiles/              # Saved user profiles (excluded from git)
```

## Supported File Types

| Input | Output |
|-------|--------|
| `.docx` | `.docx` (formatting preserved) |
| `.pdf` | `.docx` |
| `.txt` | `.docx` |

## User Profiles

Profiles store your fact base — real metrics, known tools, skill blocklists, and experience facts — so the LLM can ground every rewrite without hallucinating.

Save a profile in the app, then reload it across sessions. Profile files are excluded from git by default to keep personal data private.
