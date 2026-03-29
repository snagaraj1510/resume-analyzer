# Resume Analyzer

A Streamlit web app that analyzes, scores, and rewrites resumes against job descriptions using AI. Supports multiple LLM providers and enforces strict guardrails to keep rewrites honest and interview-ready.

## Features

- **Multi-provider LLM** — Claude (Anthropic), GPT-4o (OpenAI), Gemini 2.5 Pro (Google), or Ollama (free, local)
- **100-point scoring rubric** — grades your resume across impact, relevance, formatting, and ATS compatibility
- **AI rewrite** — rewrites bullets in ACR format (Action → Context → Result) optimized for the target role
- **Resume Architect guardrails** — anti-hallucination enforcement, seniority honesty, bullet character limits, banned LLM-isms
- **Sidebar chat** — ask questions, request targeted rewrites, get coaching without leaving the app
- **Format preservation** — uploads and exports `.docx` with original styling intact; PDF input supported
- **User profiles** — save preferences and context across sessions
- **JD fetching** — paste a job posting URL and the app extracts the description automatically

## Guardrails

Every rewrite is enforced against 6 rules:

| Rule | Description |
|------|-------------|
| G1 — Fact Base | Every metric, tool, and stakeholder must trace back to your original resume. No invented numbers. |
| G2 — Seniority Honesty | Verbs accurately reflect your relationship to senior stakeholders. |
| G3 — Bullet Format | ACR format, <220 chars target, 250 hard ceiling, no repeated lead verbs. |
| G4 — Skill Diversity | No more than 2 bullets share the same primary skill tag. |
| G5 — Role Framing | Auto-detects target role type (Strategy, BizOps, Finance, GTM) and frames bullets accordingly. |
| G6 — Scoring Integrity | Re-scores after rewrite to verify improvement. |

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

## Using Ollama (Free, No API Key)

1. Install [Ollama](https://ollama.com)
2. Pull a model: `ollama pull llama3.1:8b`
3. Start Ollama: `ollama serve`
4. Select **Ollama (Local)** in the app sidebar

## File Structure

```
resume-analyzer/
├── app.py                      # Streamlit UI
├── analyzer.py                 # LLM prompts, scoring, rewrite, chat logic
├── document_handler.py         # .docx/.pdf read-write with formatting preservation
├── profile_manager.py          # User profile persistence
├── claude_project_instructions.md  # Full guardrail spec and scoring rubric
├── requirements.txt
├── data/                       # Temp storage for uploads
├── references/                 # Bundled reference material for analysis
└── user_profiles/              # Saved user profiles
```

## Supported File Types

| Input | Output |
|-------|--------|
| `.docx` | `.docx` (formatting preserved) |
| `.pdf` | `.docx` |
| `.txt` | `.docx` |
