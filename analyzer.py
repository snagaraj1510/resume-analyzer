"""Multi-provider LLM interaction: prompt templates, streaming, and response parsing for resume analysis."""

import os
import urllib.request
import json as _json
from dotenv import load_dotenv

load_dotenv()

# Provider configs
PROVIDERS = {
    "Claude (Anthropic)": {"model": "claude-sonnet-4-6", "env_key": "ANTHROPIC_API_KEY"},
    "GPT-4o (OpenAI)": {"model": "gpt-4o", "env_key": "OPENAI_API_KEY"},
    "Gemini 2.5 Pro (Google)": {"model": "gemini-2.5-pro-preview-06-05", "env_key": "GOOGLE_API_KEY"},
}

# Cheap models for lightweight tasks (verify key, re-scoring)
LITE_MODELS = {
    "Claude (Anthropic)": "claude-haiku-4-5-20251001",
    "GPT-4o (OpenAI)": "gpt-4o-mini",
    "Gemini 2.5 Pro (Google)": "gemini-2.0-flash",
}

OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_PROVIDER = "Ollama (Local)"


def detect_ollama() -> list[str]:
    """Check if Ollama is running locally and return list of available model names."""
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=2) as resp:
            data = _json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Provider-agnostic streaming and response functions
# ---------------------------------------------------------------------------

def _get_model(provider: str, lite: bool = False) -> str:
    """Return the model ID for the given provider. Use lite=True for cheap tasks."""
    if lite:
        return LITE_MODELS.get(provider, PROVIDERS[provider]["model"])
    return PROVIDERS[provider]["model"]


def stream_response(system: str, user_message: str, max_tokens: int = 8192,
                    api_key: str | None = None, provider: str = "Claude (Anthropic)",
                    lite: bool = False, ollama_model: str | None = None):
    """Generator yielding text chunks for Streamlit's write_stream."""
    if provider == OLLAMA_PROVIDER:
        yield from _stream_ollama(system, user_message, max_tokens, ollama_model or "llama3")
    elif provider == "Claude (Anthropic)":
        yield from _stream_anthropic(system, user_message, max_tokens, api_key, lite=lite)
    elif provider == "GPT-4o (OpenAI)":
        yield from _stream_openai(system, user_message, max_tokens, api_key, lite=lite)
    elif provider == "Gemini 2.5 Pro (Google)":
        yield from _stream_gemini(system, user_message, max_tokens, api_key, lite=lite)


def chat_response(system: str, messages: list[dict], max_tokens: int = 8192,
                  api_key: str | None = None, provider: str = "Claude (Anthropic)",
                  ollama_model: str | None = None):
    """Generator yielding text chunks for a multi-turn chat conversation."""
    if provider == OLLAMA_PROVIDER:
        yield from _chat_ollama(system, messages, max_tokens, ollama_model or "llama3")
    elif provider == "Claude (Anthropic)":
        yield from _chat_anthropic(system, messages, max_tokens, api_key)
    elif provider == "GPT-4o (OpenAI)":
        yield from _chat_openai(system, messages, max_tokens, api_key)
    elif provider == "Gemini 2.5 Pro (Google)":
        yield from _chat_gemini(system, messages, max_tokens, api_key)


def full_response(system: str, user_message: str, max_tokens: int = 8192,
                  api_key: str | None = None, provider: str = "Claude (Anthropic)",
                  lite: bool = False, ollama_model: str | None = None) -> str:
    """Non-streaming call that returns the full response text."""
    if provider == OLLAMA_PROVIDER:
        return _full_ollama(system, user_message, max_tokens, ollama_model or "llama3")
    elif provider == "Claude (Anthropic)":
        return _full_anthropic(system, user_message, max_tokens, api_key, lite=lite)
    elif provider == "GPT-4o (OpenAI)":
        return _full_openai(system, user_message, max_tokens, api_key, lite=lite)
    elif provider == "Gemini 2.5 Pro (Google)":
        return _full_gemini(system, user_message, max_tokens, api_key, lite=lite)
    return ""


# ---------------------------------------------------------------------------
# Anthropic (Claude)
# ---------------------------------------------------------------------------

def _stream_anthropic(system, user_message, max_tokens, api_key, lite=False):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    with client.messages.stream(
        model=_get_model("Claude (Anthropic)", lite),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def _chat_anthropic(system, messages, max_tokens, api_key):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    with client.messages.stream(
        model=PROVIDERS["Claude (Anthropic)"]["model"],
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


def _full_anthropic(system, user_message, max_tokens, api_key, lite=False):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    response = client.messages.create(
        model=_get_model("Claude (Anthropic)", lite),
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# OpenAI (GPT-4o)
# ---------------------------------------------------------------------------

def _stream_openai(system, user_message, max_tokens, api_key, lite=False):
    from openai import OpenAI
    client = OpenAI(api_key=api_key) if api_key else OpenAI()
    stream = client.chat.completions.create(
        model=_get_model("GPT-4o (OpenAI)", lite),
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
        stream=True,
    )
    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def _chat_openai(system, messages, max_tokens, api_key):
    from openai import OpenAI
    client = OpenAI(api_key=api_key) if api_key else OpenAI()
    api_messages = [{"role": "system", "content": system}] + messages
    stream = client.chat.completions.create(
        model=PROVIDERS["GPT-4o (OpenAI)"]["model"],
        max_tokens=max_tokens,
        messages=api_messages,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def _full_openai(system, user_message, max_tokens, api_key, lite=False):
    from openai import OpenAI
    client = OpenAI(api_key=api_key) if api_key else OpenAI()
    response = client.chat.completions.create(
        model=_get_model("GPT-4o (OpenAI)", lite),
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------

def _stream_gemini(system, user_message, max_tokens, api_key, lite=False):
    import google.generativeai as genai
    genai.configure(api_key=api_key or os.environ.get("GOOGLE_API_KEY"))
    model = genai.GenerativeModel(
        model_name=_get_model("Gemini 2.5 Pro (Google)", lite),
        system_instruction=system,
    )
    response = model.generate_content(
        user_message,
        generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens),
        stream=True,
    )
    for chunk in response:
        if chunk.text:
            yield chunk.text


def _chat_gemini(system, messages, max_tokens, api_key):
    import google.generativeai as genai
    genai.configure(api_key=api_key or os.environ.get("GOOGLE_API_KEY"))
    model = genai.GenerativeModel(
        model_name=PROVIDERS["Gemini 2.5 Pro (Google)"]["model"],
        system_instruction=system,
    )
    # Convert messages to Gemini format
    history = []
    for msg in messages[:-1]:
        role = "user" if msg["role"] == "user" else "model"
        history.append({"role": role, "parts": [msg["content"]]})
    chat = model.start_chat(history=history)
    last_msg = messages[-1]["content"] if messages else ""
    response = chat.send_message(
        last_msg,
        generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens),
        stream=True,
    )
    for chunk in response:
        if chunk.text:
            yield chunk.text


def _full_gemini(system, user_message, max_tokens, api_key, lite=False):
    import google.generativeai as genai
    genai.configure(api_key=api_key or os.environ.get("GOOGLE_API_KEY"))
    model = genai.GenerativeModel(
        model_name=_get_model("Gemini 2.5 Pro (Google)", lite),
        system_instruction=system,
    )
    response = model.generate_content(
        user_message,
        generation_config=genai.types.GenerationConfig(max_output_tokens=max_tokens),
    )
    return response.text


# ---------------------------------------------------------------------------
# Ollama (Local) — uses OpenAI-compatible API
# ---------------------------------------------------------------------------

def _ollama_client():
    from openai import OpenAI
    return OpenAI(base_url=f"{OLLAMA_BASE_URL}/v1", api_key="ollama")


def _stream_ollama(system, user_message, max_tokens, model):
    client = _ollama_client()
    stream = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def _chat_ollama(system, messages, max_tokens, model):
    client = _ollama_client()
    api_messages = [{"role": "system", "content": system}] + messages
    stream = client.chat.completions.create(
        model=model,
        messages=api_messages,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


def _full_ollama(system, user_message, max_tokens, model):
    client = _ollama_client()
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
        max_tokens=max_tokens,
    )
    return response.choices[0].message.content


# ---------------------------------------------------------------------------
# GUARDRAILS — injected into all prompts
# ---------------------------------------------------------------------------

GUARDRAILS = """
## GUARDRAILS — MANDATORY FOR ALL OUTPUT

### G1: FACT BASE ENFORCEMENT (ANTI-HALLUCINATION)
- Every claim must be traceable to the user's profile or original resume.
- **Metrics:** Every number ($, %, count) must match the fact base or be mathematically derivable. If missing, use **[INSERT METRIC]** placeholder. NEVER invent numbers.
- **Stakeholders:** Every named stakeholder (CTO, VP, Director, etc.) must appear in fact base for that role. Remove if unverified.
- **Tools/Tech:** Every tool must be in the user's Known Tools. If profile has a "Tools NOT Used" blocklist, enforce strictly. NEVER add tools the user hasn't used.
- **Scope:** Team sizes, user counts, regions, percentages must match fact base.
- **Outcomes:** Implicit outcomes may be stated WITHOUT specific metrics ("enabling faster decisions" = OK; "reducing decision time by 30%" = NOT OK without a real number).
- **No fabricated experiences.** Reframing real work through a different lens is allowed. Inventing projects, features, or interactions is NEVER allowed.
- If no user profile exists, flag every rewrite as "UNVERIFIED — confirm with user."

### G2: SENIORITY HONESTY
- When a bullet mentions a senior person, the verb must honestly represent the relationship:
  * ALLOWED with seniors: "Partnered with," "Co-led," "Drove," "Presented to," "Collaborated with"
  * BANNED (implies authority OVER them): "Directed," "Managed," "Oversaw," "Supervised," "Instructed"
- Ownership levels: "Owned" = sole responsibility; "Led" = primary driver; "Co-led" = shared; "Contributed to" = team effort.
- **Interview test:** Can the user speak to this bullet for 2-3 minutes with honest, specific details? If no, tone it down.

### G3: BULLET FORMAT & LIMITS
- **Character limits:** TARGET <185 chars. FLAG 185-220. HARD CEILING 250 — must be rewritten if exceeded.
- **Trimming priority:** Result > Action > Context (keep impact, tighten setup).
- **Bullet format:** Auto-detect from resume — ACR (Action→Context→Result), STAR-lite (Action→Technical Detail→Impact), or XYZ (Accomplished X by doing Y measured by Z). Apply consistently. If inconsistent, standardize to ACR.
- **Verb uniqueness:** NO TWO BULLETS on the entire resume may start with the same verb.
- **BANNED as lead verbs:** "Responsible for," "Assisted with," "Helped," "Participated in," "Was involved in"
- **BANNED words/phrases (LLM-isms):** "Spearheaded," "Leveraged," "Synergy," "Passionate," "Dynamic," "Deep dive"
- Use standard abbreviations: GTM, SaaS, BU, FP&A, API, CI/CD, K8s, ML, NLP, etc.

### G4: SKILL STORY DIVERSITY
- Each bullet should showcase a DIFFERENT capability. Assign each bullet a primary skill tag.
- No more than 2 bullets may share the same primary tag.
- Flag word-level repetition: if any non-trivial word appears in >2 bullets, flag it (exception: JD keywords needed for ATS).

### G5: ROLE-SPECIFIC FRAMING
- Auto-detect the target role type from the JD and apply the appropriate framing lens.
- Same underlying work CAN and SHOULD be framed differently depending on the target function — this is adjusting emphasis, not hallucination.
- If the resume reads as one function but the target is another, reframe where the experience honestly supports it. Flag gaps honestly where it cannot.

### G6: SCORING INTEGRITY
- 85+: passes most ATS screens, clear positive signal. 70-84: submittable with gaps. <70: significant tailoring needed.
- NEVER inflate scores. Large keyword gaps tank the score even if bullets are well-written.
- Flag irreducible gaps honestly: tools never used, years shortfall, industry gaps, degree requirements. These CANNOT be fixed by resume tailoring.

### G7: CHANGE TRANSPARENCY
- Every change must be documented: original text, revised text, char counts, reason (which JD gap it closes), and guardrail check status.
"""


# ---------------------------------------------------------------------------
# Unified Analysis (ATS + ACR + Scoring)
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM_PROMPT = """You are an expert resume analyst. You score resumes against job descriptions on a strict 100-point rubric and provide actionable fixes.

""" + GUARDRAILS + """

## STEP 1: AUTO-DETECT ROLE TYPE
From the JD, classify the target role (e.g., Software Engineering, Product Management, Data Science, Strategic Finance, BizOps, Consulting, Marketing, Design, etc.). State the detected role type — this determines keyword expectations, verb banks, and framing lens.

## STEP 2: PARSE THE JD
Extract:
- Core responsibilities
- Required qualifications (hard requirements)
- Preferred qualifications (nice-to-have)
- Tools, technologies, and languages explicitly named
- Soft skills and cultural signals
- Years of experience required
- Industry/domain signals

## STEP 3: SCORE ON 100-POINT RUBRIC

### Dimension 1: Keyword & ATS Alignment (40 points)
  A. **Hard Skills & Tools (15 pts):** List every tool/tech/language from JD. Check resume for matches. Score = (matched / total) * 15. Only count tools user has ACTUALLY used.
  B. **Domain Keywords from JD Responsibilities (15 pts):** Extract 10-15 key domain phrases from responsibilities. Check each against resume. Score = (matched / total) * 15.
  C. **Role-Function Language (10 pts):** Does the resume speak the target function's language? If resume reads as one function but targets another, penalize heavily.

### Dimension 2: Bullet Quality & Format (25 points)
  A. **Structure Compliance (10 pts):** Each bullet needs clear action + context/scope + result. Deduct 1pt per broken bullet. Flag: no result, starts with noun, lists activities without outcomes, "Responsible for..." framing, listing tech without impact.
  B. **Character Length (5 pts):** Target <185 chars. Flag 185-220. Hard ceiling 250. Deduct 0.5pt per bullet over 220 chars.
  C. **Action Verb Uniqueness (5 pts):** No two bullets may start with the same verb. Deduct 1pt per duplicate pair.
  D. **Skill Story Diversity (5 pts):** Each bullet should showcase a different capability. Tag each bullet. If >2 bullets share a tag, flag the weakest.

### Dimension 3: Role Relevance & Framing (20 points)
  A. **Title Alignment (5 pts):** Do titles signal relevance? Note ethical adjustment opportunities (adding scope descriptor if honest).
  B. **Framing Lens Match (10 pts):** Is the resume framed for the TARGET function? Same work can be framed differently — identify reframing opportunities.
  C. **Seniority Honesty (5 pts):** Verbs match actual authority level? No overclaiming with senior stakeholders?

### Dimension 4: Overall Polish & Presentation (15 points)
  A. **Recruiter Scan Test (5 pts):** Does 6-second scan give the right impression? Most relevant content in top third?
  B. **Section Ordering (3 pts):** Appropriate for seniority level?
  C. **Space Utilization (2 pts):** 1-page constraint. Bullet count appropriate per role?
  D. **Skills Section Optimization (3 pts):** Mirrors JD tool/tech stack? Organized by category for the target function?
  E. **Consistency (2 pts):** Date formatting, punctuation, tense, bullet structure consistent?

## OUTPUT FORMAT

## Resume Score: XX/100

### Detected Role Type: [type]

### Score Breakdown
| Dimension | Sub-score | Points | Score |
|-----------|-----------|--------|-------|
| **Keyword & ATS Alignment** | | **/40** | |
| — Hard Skills & Tools | (X matched / Y in JD) | /15 | X |
| — Domain Keywords | (X matched / Y extracted) | /15 | X |
| — Role-Function Language | | /10 | X |
| **Bullet Quality & Format** | | **/25** | |
| — Structure Compliance | | /10 | X |
| — Character Length | | /5 | X |
| — Verb Uniqueness | | /5 | X |
| — Skill Story Diversity | | /5 | X |
| **Role Relevance & Framing** | | **/20** | |
| — Title Alignment | | /5 | X |
| — Framing Lens Match | | /10 | X |
| — Seniority Honesty | | /5 | X |
| **Overall Polish** | | **/15** | |
| — Recruiter Scan Test | | /5 | X |
| — Section Ordering | | /3 | X |
| — Space Utilization | | /2 | X |
| — Skills Section | | /3 | X |
| — Consistency | | /2 | X |
| **TOTAL** | | | **XX/100** |

### Keyword Gap Table
#### Strong Matches
| Keyword | Where It Appears |
|---------|-----------------|

#### Weak Matches (synonym/variant present)
| JD Keyword | Resume Says Instead | Suggested Fix |
|------------|--------------------| --------------|

#### Missing Keywords
| Keyword | Category | Can Be Added? | How to Incorporate |
|---------|----------|---------------|--------------------|
(If user profile says they don't have this skill: "No — not in user's experience. Closest proxy: [X]")

### Bullet-by-Bullet Audit

For each bullet:

**[P:X] "original bullet text"** (XXX chars)
- Structure: X/10 — [Action: ✓/✗] [Context: ✓/✗] [Result: ✓/✗]
- Char count: [OK / FLAG / OVER LIMIT]
- Verb: [unique / duplicate of P:Y]
- Skill tag: [tag]
- JD alignment: [which JD requirement this addresses, or "weak alignment"]
- Verdict: [KEEP / TWEAK / REWRITE]
- Suggested Rewrites (if TWEAK or REWRITE — provide 2-3 variations each highlighting a different skill story):
  1. "rewrite" (XXX chars) — addresses [JD requirement]
  2. "rewrite" (XXX chars) — addresses [JD requirement]
  3. "rewrite" (XXX chars) — addresses [JD requirement]

### Action Verb Index
List every starting verb across the entire resume — flag duplicates.

### Skill Diversity Map
| Skill Tag | Bullets | Coverage |
|-----------|---------|----------|
(Tags should be role-appropriate. Flag any tag used >2x.)

### Irreducible Gaps
Honest list of JD requirements that CANNOT be fixed by resume tailoring (tools never used, years shortfall, industry gaps, degree requirements). Suggest how to address in cover letter or interviews.

### Top 5 Priority Fixes
Ranked by impact. Each fix should reference specific bullets and JD requirements."""


def analyze_resume(job_title: str, job_description: str, resume_text: str,
                   profile_section: str = "", reference_context: str = "",
                   api_key: str | None = None, provider: str = "Claude (Anthropic)",
                   ollama_model: str | None = None):
    """Stream unified ATS + ACR analysis with weighted scoring."""
    system = ANALYSIS_SYSTEM_PROMPT
    if profile_section:
        system += "\n\n" + profile_section

    user_msg = f"Position: {job_title}\n\nJob Description:\n{job_description}\n\nResume Content:\n{resume_text}"
    if reference_context:
        user_msg += f"\n\nAdditional Reference Material:\n{reference_context}"

    return stream_response(system, user_msg, max_tokens=12000, api_key=api_key, provider=provider, ollama_model=ollama_model)


# ---------------------------------------------------------------------------
# Resume Rewrite
# ---------------------------------------------------------------------------

REWRITE_SYSTEM_PROMPT = """You are an expert resume rewriter. You improve resumes based on prior analysis to close JD gaps and raise scores to 85+.

""" + GUARDRAILS + """

## REWRITE RULES
- The resume text has paragraph markers like [P:0], [P:1], etc.
- Output ONLY the paragraphs you want to change.
- Format each changed paragraph as: [P:X] new text here
- Do NOT output paragraphs that should remain unchanged.
- Do NOT add new paragraphs or remove existing ones.

## REWRITE STANDARDS
- Every rewritten bullet must follow the detected bullet format (ACR, STAR-lite, or XYZ) consistently.
- Every rewritten bullet must be under 185 characters (flag 185-220, hard ceiling 250).
- Every rewritten bullet must start with a unique action verb not used elsewhere on the resume.
- Every rewritten bullet must be grounded in the user's real experience (profile or resume).
- Apply the correct role-specific framing lens for the target function.
- Incorporate missing ATS keywords naturally where truthful.
- Adjust emphasis to match the target function's lens — this is framing, not fabrication.
- If a metric is missing and you cannot derive it, use **[INSERT METRIC]** placeholder.

## DIFF REPORT FORMAT
For each changed paragraph:
[P:X] new bullet text here
- **Original:** "exact original text" (XXX chars)
- **Reason:** Which JD gap this closes
- **Checks:** fact base ✓/✗, seniority honest ✓/✗, under limit ✓/✗, unique verb ✓/✗, new skill tag ✓/✗"""


def rewrite_resume(job_title: str, job_description: str, resume_text: str,
                   analysis_result: str,
                   profile_section: str = "", reference_context: str = "",
                   api_key: str | None = None, provider: str = "Claude (Anthropic)",
                   ollama_model: str | None = None) -> str:
    """Non-streaming resume rewrite. Returns full response for programmatic parsing."""
    system = REWRITE_SYSTEM_PROMPT
    if profile_section:
        system += "\n\n" + profile_section

    user_msg = (
        f"Target Position: {job_title}\n\n"
        f"Job Description:\n{job_description}\n\n"
        f"Current Resume (with paragraph markers):\n{resume_text}\n\n"
        f"Analysis Results:\n{analysis_result}"
    )
    if reference_context:
        user_msg += f"\n\nResume Writing Best Practices:\n{reference_context}"

    user_msg += "\n\nRewrite the paragraphs that need improvement. Output ONLY changed paragraphs in [P:X] format."

    return full_response(system, user_msg, max_tokens=12000, api_key=api_key, provider=provider, ollama_model=ollama_model)


# ---------------------------------------------------------------------------
# Interactive Chat
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = """You are an expert resume writing coach having an interactive conversation about the user's resume.

""" + GUARDRAILS + """

## CHAT BEHAVIOR
You have access to the user's current resume (with [P:X] paragraph markers), the target job description, prior analysis results, and the user's profile constraints.

When the user asks you to modify specific bullets or sections:
1. Provide 2-3 variations for each bullet, each highlighting a different skill story and addressing a different JD requirement
2. Include character count for each suggestion
3. Format changes as [P:X] markers so they can be applied to the document
4. Explain WHY you made each change and which JD gap it closes
5. Verify verb uniqueness against other bullets on the resume
6. Apply the correct role-specific framing lens

When the user asks general questions, respond conversationally with expert advice.

If the user wants to add a tool/skill not in their profile, warn them per Guardrail G1 but respect their final decision.

If you output revised bullets, always use the [P:X] format like:
[P:5] Orchestrated cross-functional migration of 3 legacy systems to cloud infrastructure, reducing deployment time by 40% (142 chars)"""


# ---------------------------------------------------------------------------
# Slim Re-Score (score-only, uses lite model)
# ---------------------------------------------------------------------------

RESCORE_SYSTEM_PROMPT = """You are an expert resume scorer. Given a resume and job description, output ONLY the score breakdown table — no bullet analysis, no keyword tables, no rewrites. Be strict — do NOT inflate scores.

### OUTPUT FORMAT (output ONLY this, nothing else):

## Resume Score: XX/100

### Score Breakdown
| Dimension | Points | Score |
|-----------|--------|-------|
| Keyword & ATS Alignment | /40 | X |
| Bullet Quality & Format | /25 | X |
| Role Relevance & Framing | /20 | X |
| Overall Polish | /15 | X |
| **TOTAL** | **/100** | **XX** |

### Top 3 Remaining Improvements
Brief bullet list of the 3 highest-impact changes still available.

### Irreducible Gaps
Any JD requirements that cannot be fixed by resume tailoring."""


def rescore_resume(job_title: str, job_description: str, resume_text: str,
                   profile_section: str = "",
                   api_key: str | None = None, provider: str = "Claude (Anthropic)",
                   ollama_model: str | None = None):
    """Lightweight re-score using lite model — returns score table only."""
    system = RESCORE_SYSTEM_PROMPT
    if profile_section:
        system += "\n\n" + profile_section

    user_msg = f"Position: {job_title}\n\nJob Description:\n{job_description}\n\nResume Content:\n{resume_text}"

    return stream_response(system, user_msg, max_tokens=1500, api_key=api_key, provider=provider, lite=True, ollama_model=ollama_model)


def build_chat_system(job_title: str, job_description: str, resume_text: str,
                      profile_section: str = "", analysis_result: str = "",
                      reference_context: str = "") -> str:
    """Build the system prompt for chat mode with full context."""
    system = CHAT_SYSTEM_PROMPT

    if profile_section:
        system += "\n\n" + profile_section

    system += f"\n\n## Target Position: {job_title}"
    system += f"\n\n## Job Description:\n{job_description}"
    system += f"\n\n## Current Resume:\n{resume_text}"

    if analysis_result:
        system += f"\n\n## Prior Analysis:\n{analysis_result}"
    if reference_context:
        system += f"\n\n## Reference Material:\n{reference_context}"

    return system
