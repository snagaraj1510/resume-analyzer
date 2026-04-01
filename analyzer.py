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

# Cheap models for lightweight tasks (verify key, re-scoring, validation)
# Model routing strategy:
#   MAIN model (Sonnet 4.6 / GPT-4o / Gemini 2.5 Pro):
#     - Full analysis (scoring rubric — requires nuanced judgment)
#     - Resume rewrite (creative + guardrail-aware — requires high quality)
#     - Complex chat interactions (rewriting bullets, strategic advice)
#   LITE model (Haiku 4.5 / GPT-4o-mini / Gemini 2.0 Flash / Ollama):
#     - Re-scoring (structured output, simpler judgment)
#     - API key verification (trivial)
#     - Validation spot-checks (structured, bounded)
#     - Simple chat Q&A (non-rewrite questions)
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
- For SWE: distinguish "Designed the system" (you made arch decisions) vs "Implemented the service" (you wrote code for someone else's design).
- For PM: distinguish "Owned the roadmap" (you decided priorities) vs "Influenced the roadmap" (you provided input).
- **Interview test:** Can the user speak to this bullet for 2-3 minutes with honest, specific details? If no, tone it down.

### G3: BULLET FORMAT & LIMITS
- **Voice:** First-Person Implied — every bullet starts with a strong past-tense action verb (e.g., "Led...", "Built...", "Drove..."). NEVER use "I" or "My". NEVER use third-person ("He led...", "She built...").
- **Character limits:** TARGET <220 chars. FLAG 220-250. HARD CEILING 250 — must be rewritten if exceeded.
- **Trimming priority:** Result > Action > Context (keep impact, tighten setup).
- **Bullet format:** Auto-detect from resume — ACR (Action→Context→Result), STAR-lite (Action→Technical Detail→Impact), or XYZ (Accomplished X by doing Y measured by Z). Apply consistently. If inconsistent, standardize to ACR.
- **Business Impact emphasis (HIGH PRIORITY):** Every bullet MUST end with or contain a quantifiable business outcome — revenue ($), cost savings ($), time saved (%), efficiency gain (%), user/customer impact (count), or growth metric (%). Bullets without measurable impact score significantly lower and prevent reaching 80+ scores. If a metric exists in the fact base, USE it. If derivable, DERIVE it. If neither, use [INSERT METRIC] placeholder. Target: 100% of bullets should have at least one metric.
- **Verb uniqueness:** NO TWO BULLETS on the entire resume may start with the same verb.
- **BANNED as lead verbs:** "Responsible for," "Assisted with," "Helped," "Participated in," "Was involved in"
- **BANNED words/phrases (LLM-isms):** "Spearheaded," "Leveraged," "Synergy," "Passionate," "Dynamic," "Deep dive"
- **NO MARKDOWN IN OUTPUT:** Never use asterisks (**bold**, *italic*), underscores (__text__), or backticks in bullet text. Output plain text only — the Word document handles all formatting.
- Use standard abbreviations: GTM, SaaS, BU, FP&A, API, CI/CD, K8s, ML, NLP, etc.

### G4: SKILL STORY DIVERSITY
- Each bullet should showcase a DIFFERENT capability. Assign each bullet a primary skill tag.
- No more than 2 bullets may share the same primary tag.
- Flag word-level repetition: if any non-trivial word appears in >2 bullets, flag it (exception: JD keywords needed for ATS).

### G5: ROLE-SPECIFIC FRAMING
- Auto-detect the target role type from the JD and apply the appropriate framing lens (see FRAMING LENSES section).
- Same underlying work CAN and SHOULD be framed differently depending on the target function — this is adjusting emphasis, not hallucination.
- If the resume reads as one function but the target is another, reframe where the experience honestly supports it. Flag gaps honestly where it cannot.

### G6: SCORING INTEGRITY
- 85+: passes most ATS screens, clear positive signal. 70-84: submittable with gaps. <70: significant tailoring needed.
- NEVER inflate scores. Large keyword gaps tank the score even if bullets are well-written.
- Flag irreducible gaps honestly: tools never used, years shortfall, industry gaps, degree requirements. These CANNOT be fixed by resume tailoring.
- Before/after scoring must use the SAME rubric. Improvement must be traceable to specific changes.

### G7: CHANGE TRANSPARENCY
- Every change must be documented: original text, revised text, char counts, reason (which JD gap it closes), and guardrail check status.

### G8: USER OVERRIDE PROTOCOL
- Users can override any suggestion, but the tool must WARN if the override violates a guardrail.
- Example: User wants to add Kubernetes to skills but has not used it → "Warning: Kubernetes is not in your Known Tools list. Adding it would violate G1. If you have acquired K8s experience since your profile was last updated, confirm and I will add it. Otherwise, I recommend listing Docker as the closest truthful proxy."
- The user's final decision stands, but the warning is logged.

## EDGE CASES
- **JD requires a tool not in user's experience:** Do NOT add it. Flag in gap analysis as "cannot close on resume." Suggest closest proxy.
- **JD requires more years than user has:** Do NOT inflate tenure. Flag honestly. Suggest framing depth of impact over years.
- **JD is for a completely unrelated function:** If zero relevant experience, say so clearly. Do NOT force-fit. Identify genuinely transferable skills if they exist.
- **Bullet cannot hit 220 chars without losing key JD alignment:** Use standard abbreviations. If truly cannot condense below 250, accept 250 and flag it.
- **User has no profile and refuses to confirm facts:** Deliver analysis with every rewrite marked "UNVERIFIED." Include warning about submitting unverified claims.
- **Resume has non-standard sections (PROJECTS, OPEN SOURCE, PUBLICATIONS, PORTFOLIO):** Parse dynamically, apply same bullet-level analysis, preserve in output.

## ROLE-SPECIFIC FRAMING LENSES
Auto-detect from JD and apply the matching lens. Same work framed through different lenses is NOT hallucination — it is adjusting emphasis and language.

**SOFTWARE ENGINEERING (Backend / Fullstack / Platform):**
  Emphasize: system design, scalability, reliability, performance, code quality, technical leadership, mentoring.
  Keywords: "distributed systems," "microservices," "API," "latency," "throughput," "availability," "observability," "CI/CD," "testing."
  Bullet pattern: Built/Designed [system] using [tech], achieving [metric].

**SOFTWARE ENGINEERING (Frontend / UI):**
  Emphasize: user experience, performance, accessibility, design systems, cross-browser compatibility, component architecture.
  Keywords: "responsive," "accessibility," "component library," "state management," "Core Web Vitals," "design system."

**ML / AI ENGINEERING:**
  Emphasize: model development, training infrastructure, evaluation metrics, production deployment, data pipelines, experimentation.
  Keywords: "model training," "inference," "feature engineering," "A/B testing," "precision/recall," "latency," "GPU utilization," "MLOps."

**DATA SCIENCE / ANALYTICS:**
  Emphasize: statistical analysis, experimentation, insight generation, business impact of findings, stakeholder communication.
  Keywords: "hypothesis testing," "causal inference," "A/B testing," "dashboards," "segmentation," "forecasting," "storytelling with data."

**DATA ENGINEERING:**
  Emphasize: pipeline design, data quality, scale, reliability, warehouse architecture, ETL/ELT, real-time vs batch.
  Keywords: "data pipeline," "ETL," "data warehouse," "data quality," "schema design," "Spark," "Airflow," "real-time," "SLA."

**PRODUCT MANAGEMENT:**
  Emphasize: customer insight, prioritization, roadmap ownership, metric definition, cross-functional leadership, launch execution.
  Keywords: "product roadmap," "user research," "OKRs," "prioritization framework," "product-market fit," "experimentation," "launch."

**PRODUCT DESIGN / UX:**
  Emphasize: user-centered design, research methods, prototyping, design systems, accessibility, collaboration with engineering.
  Keywords: "user research," "usability testing," "wireframes," "prototypes," "design system," "accessibility," "interaction design."

**STRATEGY / CORPORATE STRATEGY:**
  Emphasize: market sizing, growth opportunities, competitive landscape, strategic recommendations, executive/board communication.
  Keywords: "growth strategy," "market assessment," "strategic priorities," "business case," "implementation planning."

**BIZOPS / BUSINESS OPERATIONS:**
  Emphasize: process design, operational efficiency, KPI frameworks, cross-functional program management, scaling.
  Keywords: "operational efficiency," "process improvement," "KPI tracking," "program management," "scaling."

**STRATEGIC FINANCE / FP&A:**
  Emphasize: revenue forecasting, P&L, variance analysis, financial modeling, business partnership, planning cycles.
  Keywords: "revenue forecasting," "P&L," "financial planning," "business partnership," "investment decisions."

**CORP DEV / M&A:**
  Emphasize: due diligence, valuation, partnership evaluation, market assessment, competitive intelligence.
  Keywords: "due diligence," "partnership evaluation," "market entry," "ecosystem," "strategic rationale."

**GTM / REVOPS / SALES OPS:**
  Emphasize: pipeline, territory planning, quota, sales analytics, GTM strategy, conversion metrics.
  Keywords: "pipeline," "GTM," "quota," "territory planning," "revenue operations," "bookings."

**MARKETING / GROWTH:**
  Emphasize: acquisition, retention, conversion, content strategy, SEO/SEM, lifecycle marketing, experimentation.
  Keywords: "CAC," "LTV," "conversion rate," "funnel optimization," "attribution," "growth loops," "retention."

**CONSULTING:**
  Emphasize: client engagement, workstream leadership, hypothesis-driven analysis, implementation planning.
  Keywords: "structured problem solving," "workstream leadership," "client engagement," "implementation," "change management."

**PROGRAM / PROJECT MANAGEMENT:**
  Emphasize: execution, risk management, stakeholder coordination, timeline management, resource allocation, delivery.
  Keywords: "program management," "risk mitigation," "stakeholder management," "on-time delivery," "resource planning," "agile/scrum."

### CROSS-FUNCTION REFRAMING EXAMPLES
Same work, different lenses — this is allowed and encouraged:

An engineer who also defined product requirements:
  SWE target: "Built real-time notification service using WebSockets and Redis, reducing delivery latency 85% for 2M daily users"
  PM target: "Defined and shipped real-time notification system serving 2M daily users, collaborating with design and backend teams to reduce delivery latency 85%"

A finance person who did operational work:
  Finance target: "Built forecasting model for market expansion"
  BizOps target: "Co-developed go-to-market forecasting framework supporting expansion into 10 territories, generating $3M profit"
  Strategy target: "Evaluated new market entry opportunity across 10 territories, projecting $3M annual profit to inform executive go/no-go decision"
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
  B. **Character Length (5 pts):** Target <220 chars. Flag 220-250. Hard ceiling 250. Deduct 0.5pt per bullet over 250 chars.
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

## OUTPUT FORMAT — SUCCINCT

## Resume Score: XX/100

### Detected Role Type: [type]

### Score Breakdown
| Dimension | Points | Score |
|-----------|--------|-------|
| Keyword & ATS Alignment | /40 | X |
| Bullet Quality & Format | /25 | X |
| Role Relevance & Framing | /20 | X |
| Overall Polish | /15 | X |
| **TOTAL** | **/100** | **XX** |

### Gaps to Close (3-5 bullets max)
Do not explain why unless asked. Just list the missing semantic keywords or experience gaps.
- [gap 1: missing keyword/skill/experience]
- [gap 2: ...]
- [gap 3: ...]

### Irreducible Gaps
Honest list of JD requirements that CANNOT be fixed by resume tailoring (max 3). Flag tools never used, years shortfall, or degree requirements only.

### Top 5 Priority Fixes
Ranked by impact. Reference specific [P:X] bullets and JD requirements. One sentence each."""


def analyze_resume(job_title: str, job_description: str, resume_text: str,
                   profile_section: str = "", reference_context: str = "",
                   style_examples: str = "",
                   api_key: str | None = None, provider: str = "Claude (Anthropic)",
                   ollama_model: str | None = None):
    """Stream unified ATS + ACR analysis with weighted scoring."""
    system = ANALYSIS_SYSTEM_PROMPT
    if profile_section:
        system += "\n\n" + profile_section
    if style_examples:
        system += "\n\n" + style_examples

    user_msg = f"Position: {job_title}\n\nJob Description:\n{job_description}\n\nResume Content:\n{resume_text}"
    if reference_context:
        user_msg += f"\n\nAdditional Reference Material:\n{reference_context}"

    return stream_response(system, user_msg, max_tokens=12000, api_key=api_key, provider=provider, ollama_model=ollama_model)


# ---------------------------------------------------------------------------
# Resume Rewrite
# ---------------------------------------------------------------------------

REWRITE_SYSTEM_PROMPT = """You are an expert resume rewriter. You follow a precise multi-step workflow — the same process a senior career coach would use to tailor a resume to a specific job description.

""" + GUARDRAILS + """

## STEP 1: EXTRACT JD SKILL THEMES
Before touching a single bullet, read the JD and extract 6-8 distinct abilities/skill themes it demands.
Examples: "cross-functional leadership", "data-driven decision making", "stakeholder communication",
"financial modeling", "strategic planning", "technical execution", "process optimization", "team management".
These themes become your ASSIGNMENT PALETTE — every bullet on the resume must map to one.

## STEP 2: INVENTORY CURRENT BULLETS
For each existing bullet, note:
- Which skill theme it currently demonstrates (if any)
- Whether it has ACR format (Action → Context → Result)
- Its character count
- Its starting verb

## STEP 3: ASSIGN SKILL THEMES TO BULLETS
Map each bullet to a DIFFERENT JD skill theme from your palette. Rules:
- No two bullets on the entire resume should showcase the same primary skill theme.
- Prioritize the JD's most-repeated or highest-weighted abilities for the most recent roles.
- If a bullet doesn't map to any JD theme and there's no room, it's a candidate for cutting or merging.
- The full resume should "cover" as many of the 6-8 JD themes as possible — this is what makes a recruiter think "this person checks every box."

## STEP 4: REWRITE IN ACR FORMAT
Every bullet must follow Action → Context → Result format:
- **Action:** Strong, unique past-tense verb (Led, Built, Drove, Optimized, Designed, Analyzed...)
- **Context:** What you did it on/with — project, team, stakeholder, tool, scope
- **Result:** Measurable business outcome — $ revenue, % improvement, count, time saved
- The result is what the recruiter remembers. Put it last so it lands.

Example: "Optimized $1B incentive spend through 60+ A/B experiments with 7 cross-functional teams, improving forecast accuracy and growing market share 4%"
  → Action: Optimized | Context: $1B incentive spend, 60+ A/B experiments, 7 teams | Result: forecast accuracy + 4% share growth

## RESUME TYPE DETECTION
Auto-detect the resume type from the content and JD:
- If the resume is Technical/Software Engineering: Focus rewrites on 'Languages', 'Frameworks', system design, and technical impact metrics (latency, throughput, uptime).
- If the resume is Finance/MBA/Strategy: Focus rewrites on 'Metrics', 'Business Impact', revenue, cost savings, and stakeholder influence.
- If the resume is mixed: Prioritize whichever lens the TARGET JD demands.

## ONE-PAGE MANDATE — SPATIAL CONSTRAINT
You are a professional resume architect. The user's career depends on this being 1 page.
- CRITICAL: The final resume MUST fit on 1 page with 0.5" margins, Calibri 10pt, single line spacing. Target under 525 words.
- HARD CONTENT CAP: Total bullet count must not exceed 15 across the entire document. If the user has more, you MUST merge or delete the least relevant bullets from older roles.
- If a bullet would wrap to 2+ lines in a Word document (roughly >200 chars at 10pt Calibri), it is too long. Shorten it.
- If the content is trending long, you MUST consolidate the 'Education' leadership bullets and remove the 2nd or 3rd bullet from roles older than 3 years.
- If the content is too long, consolidate the 'Additional' section into 3-4 lines total and merge the two oldest job roles into single-bullet summaries.
- Do not ask for permission; just ensure it fits. Be ruthless with fluff.
- Condense aggressively — cut filler words, use abbreviations (GTM, SaaS, BU, FP&A).

## DEFAULT STYLE & SECTION ORDER
The output must match the Default_Resume.docx template style:
- Section order: EXPERIENCE → EDUCATION → ADDITIONAL. Education MUST come AFTER work experience.
- Name: centered, ALL CAPS, 14pt bold. Contact: centered, 9.5pt.
- Section headers: ALL CAPS, bold, with bottom border line.
- Company names: ALL CAPS, bold, with right-aligned location. Title: italic, with right-aligned dates.
- Bullets: action-verb led, Calibri 10pt.
- Additional/Skills section: "Label: value" format (label bolded before colon).
- Claude has agency to restructure, merge, or reorder content within these boundaries to ensure a cohesive, polished 1-page document.

## REWRITE RULES
- The resume text has paragraph markers like [P:0], [P:1], etc.
- Output ONLY the paragraphs you want to change.
- Format each changed paragraph as: [P:X] new text here
- Do NOT output paragraphs that should remain unchanged.
- Do NOT add new paragraphs or remove existing ones.

## BULLET QUALITY CHECKLIST (apply to EVERY bullet before outputting)
1. FORMAT: Is it clean ACR? Action verb → Context → Result? Easy for a recruiter to scan in 6 seconds?
2. LENGTH: Is it under 250 characters? (Target <220. Hard ceiling 250. 2 lines max in Word.)
3. VERB: Does it start with a unique past-tense action verb not used by any other bullet on the resume?
4. SKILL THEME: Does it highlight a DIFFERENT JD-required ability than every other bullet?
5. ATS: Does it contain at least one keyword from the JD that wasn't in the original?
6. RESULT: Does it end with a quantifiable business outcome ($, %, count)?
If ANY check fails, fix the bullet before outputting it.

## CRITICAL OUTPUT RULES
- VOICE: Use First-Person Implied. FORMAT: Plain text only. NO asterisks, bolding, or markdown.
- PLAIN TEXT ONLY: Do NOT use any Markdown formatting (**, *, __, `) in your [P:X] output. The text goes directly into a Word document — asterisks and underscores will appear as literal characters and look broken.
- FIRST-PERSON IMPLIED: Start every bullet with a past-tense action verb. Never use "I", "My", "He", "She", or "They".
- BUSINESS IMPACT: Every bullet must end with a measurable outcome ($ revenue, % cost savings, % time reduction, user count, growth %). Bullets without quantifiable impact will score poorly.

## OUTPUT FORMAT — STRICT
Output ONLY lines in this exact format, one per changed paragraph:
[P:X] revised bullet text here

FORBIDDEN in output: NEVER output "Original:", "Reason:", "Checks:", diff reports, explanations, commentary, or any text that is not a [P:X] line. Use those labels for internal validation ONLY — they must NEVER appear in the response. The parser discards everything except [P:X] lines. Keep your reasoning internal — only output the revised text."""


def rewrite_resume(job_title: str, job_description: str, resume_text: str,
                   analysis_result: str,
                   profile_section: str = "", reference_context: str = "",
                   style_examples: str = "",
                   api_key: str | None = None, provider: str = "Claude (Anthropic)",
                   ollama_model: str | None = None) -> str:
    """Non-streaming resume rewrite with guardrail-enforced self-healing.

    For Claude (Anthropic): uses an agentic tool-calling loop. The model writes bullets,
    then calls the validate_bullets tool (backed by validate_resume()) to inspect its own
    output. It fixes violations autonomously and re-validates until all guardrails pass
    or max iterations is reached — no manual orchestration needed.

    For all other providers (GPT-4o, Gemini, Ollama): uses the original manual
    self-healing loop — rewrite → validate → correction pass, up to 2 passes.

    All providers share the same metric injection pass after the main rewrite loop.
    """
    import re as _rr
    from document_handler import parse_rewrite_response as _parse_rr
    import time as _time

    system = REWRITE_SYSTEM_PROMPT
    if profile_section:
        system += "\n\n" + profile_section
    if style_examples:
        system += "\n\n" + style_examples

    user_msg = (
        f"Target Position: {job_title}\n\n"
        f"Job Description:\n{job_description}\n\n"
        f"Current Resume (with paragraph markers):\n{resume_text}\n\n"
        f"Analysis Results:\n{analysis_result}"
    )
    if reference_context:
        user_msg += f"\n\nResume Writing Best Practices:\n{reference_context}"
    user_msg += "\n\nRewrite the paragraphs that need improvement. Output ONLY changed paragraphs in [P:X] format."

    current_response = ""

    # ── Anthropic: agent-based self-directed validation loop ──────────────────
    if provider == "Claude (Anthropic)":
        for _attempt in range(3):
            try:
                current_response = _agent_rewrite_anthropic(
                    system=system,
                    user_msg=user_msg,
                    resume_text=resume_text,
                    profile_section=profile_section,
                    api_key=api_key,
                )
                break
            except Exception as _e:
                err_str = str(_e)
                if any(code in err_str for code in ("500", "529", "503", "overloaded")):
                    if _attempt < 2:
                        _time.sleep(2 ** _attempt)
                        continue
                raise
        if not current_response:
            return ""

    # ── Other providers: manual self-healing loop (rewrite → validate → fix) ──
    else:
        raw_response = None
        for _attempt in range(3):
            try:
                raw_response = full_response(
                    system, user_msg, max_tokens=12000,
                    api_key=api_key, provider=provider, ollama_model=ollama_model,
                )
                break
            except Exception as _e:
                err_str = str(_e)
                if any(code in err_str for code in ("500", "529", "503", "overloaded")):
                    if _attempt < 2:
                        _time.sleep(2 ** _attempt)
                        continue
                raise
        if raw_response is None:
            return ""

        current_response = raw_response
        MAX_CORRECTION_PASSES = 2

        for pass_num in range(MAX_CORRECTION_PASSES):
            new_bullets = _parse_rr(current_response)
            if not new_bullets:
                break

            # Merge rewrites into the original resume text for validation
            merged_lines = []
            for line in resume_text.strip().split("\n"):
                m = _rr.match(r'\[P:(\d+)\]\s*(.*)', line)
                if m:
                    idx = int(m.group(1))
                    if idx in new_bullets:
                        merged_lines.append(f"[P:{idx}] {new_bullets[idx]}")
                    else:
                        merged_lines.append(line)
                else:
                    merged_lines.append(line)
            merged_text = "\n".join(merged_lines)

            validation = validate_resume(merged_text, profile_section)
            all_failures = validation.issues + validation.warnings
            if not all_failures:
                break

            # Build list of failed bullets with specific violations
            failed_map: dict[int, list[str]] = {}
            for msg in all_failures:
                idxs = _rr.findall(r'\[P:(\d+)\]', msg)
                for idx_str in idxs:
                    failed_map.setdefault(int(idx_str), []).append(msg)

            failed_bullets_to_fix = []
            for p_idx, violations in failed_map.items():
                bullet_text = new_bullets.get(p_idx)
                if bullet_text:
                    failed_bullets_to_fix.append({
                        "index": p_idx,
                        "text": bullet_text,
                        "violations": list(set(violations)),
                    })

            if not failed_bullets_to_fix:
                break

            violation_lines = []
            for fb in failed_bullets_to_fix:
                violation_lines.append(f"[P:{fb['index']}] {fb['text']}")
                for v in fb["violations"]:
                    violation_lines.append(f"  - {v}")
            violations_block = "\n".join(violation_lines)

            correction_prompt = (
                f"The following bullets failed validation:\n{violations_block}\n\n"
                "Fix each bullet to satisfy ALL of these requirements:\n"
                "1. UNDER 250 characters (hard ceiling, target <220).\n"
                "2. Starts with a UNIQUE high-impact action verb — no duplicates within the same experience block or across the resume.\n"
                "3. Follows ACR format: [Strong Verb] + [Context/Project] + [Quantifiable Result with $, %, or #].\n"
                "4. NO markdown/asterisks — plain text only.\n"
                "Output ONLY fixed [P:X] lines. No commentary."
            )

            try:
                fix_response = full_response(
                    system, correction_prompt, max_tokens=4000,
                    api_key=api_key, provider=provider, ollama_model=ollama_model,
                )
                fix_bullets = _parse_rr(fix_response)
                if fix_bullets:
                    new_bullets.update(fix_bullets)
                    response_lines = []
                    for idx in sorted(new_bullets.keys()):
                        response_lines.append(f"[P:{idx}] {new_bullets[idx]}")
                    current_response = "\n".join(response_lines)
                else:
                    break
            except Exception:
                break

    # ── Metric injection pass (all providers) ─────────────────────────────────
    final_bullets = _parse_rr(current_response)
    if final_bullets:
        metric_bullets = sum(
            1 for t in final_bullets.values()
            if _rr.search(r'[\$%]|\d+%|\d+\+?\s*(users|customers|teams|regions|markets)', t)
        )
        total_bullets = len(final_bullets)
        metric_ratio = metric_bullets / total_bullets if total_bullets > 0 else 1.0

        if metric_ratio < 0.7:
            metric_prompt = (
                "METRIC INJECTION PASS — Maximizing Business Impact and Quantitative Results.\n\n"
                "The following rewritten bullets lack quantifiable business outcomes. "
                "Every bullet MUST contain at least one metric: $ revenue, % improvement, "
                "count of users/teams/markets, or time saved. "
                "If a real metric exists in the resume or profile, USE it. "
                "If derivable, DERIVE it. If neither, use [INSERT METRIC] placeholder.\n\n"
                "Bullets to improve:\n"
            )
            for idx, text in final_bullets.items():
                if not _rr.search(r'[\$%]|\d+%|\d+\+?\s*(users|customers|teams|regions|markets)', text):
                    metric_prompt += f"[P:{idx}] {text}\n"
            metric_prompt += "\nOutput ONLY fixed [P:X] lines. No commentary."

            try:
                metric_response = full_response(
                    system, metric_prompt, max_tokens=4000,
                    api_key=api_key, provider=provider, ollama_model=ollama_model,
                )
                metric_fixes = _parse_rr(metric_response)
                if metric_fixes:
                    final_bullets.update(metric_fixes)
                    response_lines = []
                    for idx in sorted(final_bullets.keys()):
                        response_lines.append(f"[P:{idx}] {final_bullets[idx]}")
                    current_response = "\n".join(response_lines)
            except Exception:
                pass

    return current_response


# ---------------------------------------------------------------------------
# Interactive Chat
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = """You are an expert resume writing coach having an interactive conversation about the user's resume.

""" + GUARDRAILS + """

## CHAT BEHAVIOR
You have access to the user's current resume (with [P:X] paragraph markers), the target job description, prior analysis results, and the user's profile constraints.

When the user asks you to modify specific bullets or sections:
1. Output your BEST rewrite for each bullet as a [P:X] line — these are applied directly to the resume document
2. After the [P:X] lines, briefly explain what you changed and which JD gap it closes
3. Verify verb uniqueness against other bullets on the resume
4. Apply the correct role-specific framing lens
5. Keep each bullet under 250 characters in ACR format

When the user gives a style directive (e.g., "make it punchier", "more metrics", "tighten everything"):
- Rewrite ALL relevant bullets and output them as [P:X] lines
- Changes are applied automatically to generate an updated resume

When the user asks general questions, respond conversationally with expert advice.

If the user wants to add a tool/skill not in their profile, warn them per Guardrail G1 but respect their final decision.

CRITICAL FORMAT: When outputting revised bullets, ALWAYS use the [P:X] format. Each [P:X] line you output will be applied directly to the resume document. Example:
[P:5] Orchestrated cross-functional migration of 3 legacy systems to cloud infrastructure, reducing deployment time by 40%

CRITICAL: Use PLAIN TEXT ONLY in [P:X] lines — no asterisks, no underscores, no backticks, no Markdown, no character counts in parentheses. The text is injected directly into a Word document."""


# ---------------------------------------------------------------------------
# Slim Re-Score (score-only, uses lite model)
# ---------------------------------------------------------------------------

RESCORE_SYSTEM_PROMPT = """You are an expert resume scorer. Given a resume and job description, output ONLY the score breakdown table — no bullet analysis, no keyword tables, no rewrites. Score CANDIDLY and realistically.

## SCORING PHILOSOPHY
Your goal is to MAXIMIZE the score while staying honest. A well-tailored resume for a genuinely relevant role should score 80-85+. Push the score as high as the evidence supports.

## SCORING RULES
- If the JD requires fundamentally different skills than the resume demonstrates (e.g., JD wants Senior Java Developer but resume is Junior Marketing Manager), reflect a realistic score (30-50). Do NOT hallucinate a match. Maximize alignment where genuine overlap exists.
- For a resume that IS relevant to the role:
  - Score generously on dimensions where the candidate genuinely matches
  - Give full credit for transferable skills and reframed experience
  - Bullets in proper ACR format with results should score near-max on Bullet Quality
  - Unique verbs, concise bullets (<250 chars), and clear outcomes earn top marks
- Duplicate starting verbs: deduct 2 points per pair from Bullet Quality.
- Any bullet over 250 chars: automatic -3 from Bullet Quality.
- If the maximum achievable score is below 85, clearly explain in "Irreducible Gaps" what prevents a higher score (e.g., years of experience shortfall, missing certifications, lack of specific domain experience) and note that a cover letter could address these.

### OUTPUT FORMAT (output ONLY this, nothing else — no markdown bold):

## Resume Score: XX/100

### Score Breakdown
| Dimension | Points | Score |
|-----------|--------|-------|
| Keyword & ATS Alignment | /40 | X |
| Bullet Quality & Format | /25 | X |
| Role Relevance & Framing | /20 | X |
| Overall Polish | /15 | X |
| TOTAL | /100 | XX |

### Top 3 Remaining Improvements
Brief bullet list of the 3 highest-impact changes still available.

### Irreducible Gaps
Any JD requirements that cannot be fixed by resume tailoring."""


def _apply_score_adjustments(raw_score_text: str, resume_text: str) -> str:
    """Apply hard penalty if any bullet exceeds 250 characters.

    - If ANY bullet exceeds 250 characters: final_score *= 0.8
    """
    import re as _sr

    # Parse bullets from resume text
    bullets = []
    for line in resume_text.strip().split("\n"):
        m = _sr.match(r'\[P:\d+\]\s*(.+)', line)
        if m:
            text = m.group(1).strip()
            is_bullet = (
                text.startswith(("•", "-", "–", "▪"))
                or (len(text) > 30 and text[0].isupper() and not text.isupper())
            )
            if is_bullet:
                clean = _sr.sub(r'^[•\-–▪■]\s*', '', text)
                bullets.append(clean)

    # Check for over-limit bullets
    has_overlimit = any(len(b) > 250 for b in bullets)

    if not has_overlimit:
        return raw_score_text  # No adjustments needed

    # Parse the total score from the LLM output
    score_match = _sr.search(r'Resume Score:\s*(\d+)', raw_score_text)
    if not score_match:
        score_match = _sr.search(r'TOTAL\s*\|\s*/100\s*\|\s*(\d+)', raw_score_text)
    if not score_match:
        return raw_score_text  # Can't parse — return as-is

    original_score = int(score_match.group(1))
    adjusted_score = int(original_score * 0.8)

    adjustment_note = f"\n\n### Score Adjustments Applied\n"
    adjustment_note += f"- Raw LLM Score: {original_score}/100\n"
    adjustment_note += f"- Over-250-char penalty: x0.8 (at least one bullet exceeds 250 chars)\n"
    adjustment_note += f"- **Final Adjusted Score: {adjusted_score}/100**\n"

    updated_text = _sr.sub(
        r'(Resume Score:\s*)\d+(/100)',
        f'\\g<1>{adjusted_score}\\2',
        raw_score_text,
        count=1,
    )
    updated_text += adjustment_note

    return updated_text


def rescore_resume(job_title: str, job_description: str, resume_text: str,
                   profile_section: str = "",
                   api_key: str | None = None, provider: str = "Claude (Anthropic)",
                   ollama_model: str | None = None):
    """Lightweight re-score using lite model with post-hoc score adjustments.

    After the LLM produces a raw score, applies:
    - Hard multiplier (x0.8) if any bullet exceeds 250 characters
    """
    system = RESCORE_SYSTEM_PROMPT
    if profile_section:
        system += "\n\n" + profile_section

    user_msg = f"Position: {job_title}\n\nJob Description:\n{job_description}\n\nResume Content:\n{resume_text}"

    # Collect the full response first (non-streaming) so we can post-process
    # Retry up to 3 times on transient API errors (500, 529, etc.)
    import time as _time
    raw_text = None
    for _attempt in range(3):
        try:
            raw_text = full_response(system, user_msg, max_tokens=1500, api_key=api_key,
                                     provider=provider, lite=True, ollama_model=ollama_model)
            break
        except Exception as _e:
            err_str = str(_e)
            if any(code in err_str for code in ("500", "529", "503", "overloaded")):
                if _attempt < 2:
                    _time.sleep(2 ** _attempt)  # 1s, 2s backoff
                    continue
            raise

    if raw_text is None:
        yield "Re-scoring failed after retries. Please try again."
        return

    adjusted_text = _apply_score_adjustments(raw_text, resume_text)

    # Yield as a single chunk so Streamlit's write_stream still works
    yield adjusted_text


VERIFY_SYSTEM_PROMPT = """You are a strict resume quality checker. Given a set of rewritten resume bullets and a user's fact base, check for violations. Output ONLY a JSON array of issues found, or an empty array [] if all bullets pass.

Check each bullet for:
1. CHARACTER LIMIT: Is the bullet over 250 characters? (count carefully)
2. FABRICATION: Does the bullet claim metrics, tools, or experiences NOT in the fact base?
3. BANNED PHRASES: Does it start with "Responsible for," "Assisted with," "Helped," "Participated in," or "Was involved in"?
4. SENIORITY INFLATION: Does it claim to have "Directed," "Managed," "Oversaw," or "Supervised" a senior stakeholder?

Output format (JSON only, no markdown):
[{"bullet": "P:X", "issue": "description of issue", "severity": "error|warning"}]
Or if no issues: []"""


def verify_rewrites(rewrites_text: str, profile_section: str = "",
                    api_key: str | None = None, provider: str = "Claude (Anthropic)",
                    ollama_model: str | None = None) -> str:
    """Use lite model to spot-check rewrite outputs for guardrail violations.

    This is a cheap verification pass that catches obvious errors from any model tier.
    Returns the raw verification response (JSON array of issues or []).
    """
    system = VERIFY_SYSTEM_PROMPT
    if profile_section:
        system += f"\n\nUser Fact Base:\n{profile_section}"

    user_msg = f"Rewritten bullets to verify:\n{rewrites_text}"

    return full_response(system, user_msg, max_tokens=2000, api_key=api_key,
                         provider=provider, lite=True, ollama_model=ollama_model)


CORRECTION_SYSTEM_PROMPT = """You are a resume bullet fixer. You receive bullets that FAILED validation checks and must fix ONLY the specific violations listed. Do NOT change bullets that passed.

## RULES
- Output ONLY the fixed bullets in [P:X] format. Nothing else — no explanations, no diff reports.
- PLAIN TEXT ONLY — no Markdown (**, *, __, `).
- First-Person Implied — start every bullet with a past-tense action verb. No "I", "My".
- Every bullet must end with a measurable business outcome ($, %, count).
- Preserve the original meaning and fact base — do NOT fabricate.

## CONSTRAINTS PER VIOLATION TYPE
- OVER_LIMIT (>250 chars): Condense to <220 chars. Trimming priority: keep Result, tighten Action, cut Context. Use abbreviations (GTM, SaaS, BU, FP&A).
- DUPLICATE_VERB: Change the starting verb to a unique synonym not used elsewhere on the resume.
- BANNED_PHRASE: Replace the banned opening with an appropriate action verb.
- MISSING_ACR: Restructure as Action → Context → Result with a quantifiable outcome.

Output format (ONLY this, nothing else):
[P:X] fixed bullet text here
[P:Y] fixed bullet text here"""


def correction_pass(failed_bullets: list[dict], full_resume_text: str,
                    profile_section: str = "",
                    api_key: str | None = None, provider: str = "Claude (Anthropic)",
                    ollama_model: str | None = None) -> str:
    """Run a targeted correction pass on bullets that failed validation.

    Uses the MAIN model (not lite) because corrections require the same quality
    as the initial rewrite to avoid introducing new errors.

    Args:
        failed_bullets: list of dicts with keys 'index', 'text', 'violations' (list of error strings)
        full_resume_text: the full resume text for verb-uniqueness context
        profile_section: user profile for fact-base grounding
    Returns:
        Raw LLM response with [P:X] formatted corrections.
    """
    system = CORRECTION_SYSTEM_PROMPT
    if profile_section:
        system += f"\n\n{profile_section}"

    # Build the user message with specific violations
    lines = ["Fix ONLY the bullets listed below. Each bullet has specific violations that must be resolved.\n"]
    lines.append("## FAILED BULLETS\n")
    for fb in failed_bullets:
        lines.append(f"[P:{fb['index']}] {fb['text']}")
        lines.append(f"  VIOLATIONS: {'; '.join(fb['violations'])}")
        lines.append("")

    # Provide full resume context so the model can check verb uniqueness
    lines.append("## FULL RESUME (for verb-uniqueness context — do NOT rewrite bullets not listed above):")
    lines.append(full_resume_text)

    user_msg = "\n".join(lines)

    return full_response(system, user_msg, max_tokens=4000, api_key=api_key,
                         provider=provider, ollama_model=ollama_model)


# ---------------------------------------------------------------------------
# Agent-based Rewrite — Anthropic tool-calling
# ---------------------------------------------------------------------------

# Tool definition exposed to the Claude agent for self-directed validation.
# The implementation is backed by validate_resume() — all G1-G8 rules enforced.
_VALIDATE_TOOL_DEF = {
    "name": "validate_bullets",
    "description": (
        "Run the automated guardrail validation pipeline on resume bullets. "
        "Call this after writing or revising bullets to check for violations. "
        "Returns 'passed' (bool), 'issues' (must-fix list), and 'warnings' (review-recommended list). "
        "Fix ALL issues before outputting your final bullets."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "resume_text": {
                "type": "string",
                "description": (
                    "Full resume text with [P:X] paragraph markers, "
                    "with your rewritten bullets merged in place of the originals."
                ),
            }
        },
        "required": ["resume_text"],
    },
}

_AGENT_WORKFLOW_ADDENDUM = """

## AGENT VALIDATION WORKFLOW
You have access to a validate_bullets tool. Use it as follows after your initial rewrite:
1. Merge your [P:X] rewrites into the original resume text (replace matching [P:X] lines with your versions).
2. Call validate_bullets with the full merged resume text.
3. If the result contains 'issues' (must-fix violations): fix EVERY issue, then call validate_bullets again.
4. If the result contains only 'warnings': fix warnings that meaningfully improve bullet quality.
5. When validate_bullets returns passed=true (or no issues remain): output your final [P:X] lines and stop.
6. Maximum 3 validation rounds — after round 3, output your best available version regardless.

CRITICAL: Your final output must contain ONLY [P:X] lines — no commentary, no explanations."""


def _agent_rewrite_anthropic(
    system: str,
    user_msg: str,
    resume_text: str,
    profile_section: str,
    api_key: str | None,
    max_iterations: int = 4,
) -> str:
    """Claude-native agentic rewrite using tool_use for self-directed guardrail validation.

    The agent writes bullets, calls validate_bullets to check its own output,
    fixes violations, and iterates until all guardrails pass or max_iterations is reached.
    The validate_bullets tool is backed by validate_resume() — all G1-G8 rules remain
    fully enforced without any changes to the validation logic.

    Args:
        system: Full system prompt (REWRITE_SYSTEM_PROMPT + profile section)
        user_msg: User message with JD, resume text, and prior analysis
        resume_text: Original resume text (for agent to merge rewrites into)
        profile_section: User profile for blocklist/fact-base checking
        api_key: Anthropic API key
        max_iterations: Max tool-call rounds before returning best-effort output

    Returns:
        Raw response string containing [P:X] formatted bullet rewrites.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    full_system = system + _AGENT_WORKFLOW_ADDENDUM
    messages = [{"role": "user", "content": user_msg}]
    last_text_output = ""

    for _iteration in range(max_iterations):
        response = client.messages.create(
            model=PROVIDERS["Claude (Anthropic)"]["model"],
            max_tokens=12000,
            system=full_system,
            tools=[_VALIDATE_TOOL_DEF],
            messages=messages,
        )

        # Collect text output ([P:X] lines) and any tool_use calls
        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(block)

        text_output = "\n".join(text_parts).strip()
        if text_output:
            last_text_output = text_output

        # Append assistant turn to conversation history
        messages.append({"role": "assistant", "content": response.content})

        # No tool calls — agent is satisfied with its output
        if response.stop_reason == "end_turn" or not tool_calls:
            break

        # Execute validate_bullets calls and return structured results to the agent
        tool_results = []
        for tc in tool_calls:
            if tc.name == "validate_bullets":
                merged_text = tc.input.get("resume_text", resume_text)
                result = validate_resume(merged_text, profile_section)
                tool_result_content = _json.dumps({
                    "passed": result.passed,
                    "issues": result.issues,
                    "warnings": result.warnings,
                    "summary": result.summary(),
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    "content": tool_result_content,
                })

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    return last_text_output


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


# ---------------------------------------------------------------------------
# Automated Validation Pipeline (Guardrail 7)
# ---------------------------------------------------------------------------

import re as _re
from dataclasses import dataclass as _dataclass


@_dataclass
class ValidationResult:
    """Result of the automated validation pipeline."""
    passed: bool
    issues: list[str]
    warnings: list[str]
    bullet_details: list[dict]

    def summary(self) -> str:
        lines = []
        if self.passed:
            lines.append("### Validation: PASSED")
        else:
            lines.append("### Validation: FAILED — issues must be fixed")
        if self.issues:
            lines.append("\n**Issues (must fix):**")
            for i in self.issues:
                lines.append(f"- {i}")
        if self.warnings:
            lines.append("\n**Warnings (review recommended):**")
            for w in self.warnings:
                lines.append(f"- {w}")
        return "\n".join(lines)


def validate_resume(resume_text: str, profile_section: str = "") -> "ValidationResult":
    """Run the automated validation pipeline on a resume.

    Checks that can be done programmatically (no LLM needed):
    - Character limits per bullet
    - Verb uniqueness
    - Banned verbs/phrases
    - Word repetition across bullets
    - Blocklisted tools (if profile provided)
    """
    issues = []
    warnings = []
    bullet_details = []

    # Parse resume text into paragraphs
    lines = resume_text.strip().split("\n")
    bullets = []
    for line in lines:
        m = _re.match(r'\[P:(\d+)\]\s*(.+)', line)
        if m:
            idx = int(m.group(1))
            text = m.group(2).strip()
            # Heuristic: bullets typically start with a verb or bullet char
            is_bullet = (
                text.startswith(("•", "-", "–", "▪"))
                or (len(text) > 30 and text[0].isupper() and not text.isupper())
            )
            if is_bullet:
                clean = _re.sub(r'^[•\-–▪■]\s*', '', text)
                bullets.append({"index": idx, "text": clean, "original": text})

    # 1. Character limit check
    CHAR_TARGET = 220
    CHAR_FLAG = 250
    CHAR_HARD = 250
    for b in bullets:
        char_count = len(b["text"])
        status = "OK"
        if char_count > CHAR_HARD:
            issues.append(f"[P:{b['index']}] OVER HARD LIMIT: {char_count} chars (max 250). Must rewrite.")
            status = "OVER_LIMIT"
        elif char_count > CHAR_TARGET:
            warnings.append(f"[P:{b['index']}] Over target: {char_count} chars (target <220).")
            status = "FLAGGED"
        bullet_details.append({"index": b["index"], "chars": char_count, "char_status": status})

    # 2. Verb uniqueness check
    verbs = {}
    for b in bullets:
        clean = _re.sub(r'^[•\-–▪■]\s*', '', b["text"])
        first_word = clean.split()[0].rstrip(",") if clean.split() else ""
        first_word_lower = first_word.lower()
        if first_word_lower in verbs:
            issues.append(
                f"Duplicate starting verb '{first_word}': [P:{verbs[first_word_lower]}] and [P:{b['index']}]"
            )
        else:
            verbs[first_word_lower] = b["index"]

    # 3. Banned verbs/phrases check
    BANNED_STARTS = [
        "responsible for", "assisted with", "helped", "participated in", "was involved in",
    ]
    BANNED_WORDS = ["spearheaded", "leveraged", "synergy", "passionate", "dynamic", "deep dive"]
    for b in bullets:
        text_lower = b["text"].lower()
        for banned in BANNED_STARTS:
            if text_lower.startswith(banned):
                issues.append(f"[P:{b['index']}] Starts with banned phrase '{banned}'")
        for banned in BANNED_WORDS:
            if banned in text_lower:
                warnings.append(f"[P:{b['index']}] Contains LLM-ism '{banned}'")

    # 4. Word repetition check (non-trivial words appearing in >2 bullets)
    STOP_WORDS = {
        "the", "a", "an", "and", "or", "to", "in", "of", "for", "with", "by", "on",
        "at", "from", "as", "is", "was", "are", "were", "be", "been", "being", "have",
        "has", "had", "do", "does", "did", "will", "would", "could", "should", "may",
        "might", "shall", "can", "that", "this", "these", "those", "it", "its", "not",
        "but", "if", "then", "than", "so", "no", "nor", "both", "each", "all", "any",
        "such", "into", "over", "per", "up", "out", "across", "through", "using",
        "via", "about", "between", "more", "also", "new", "key",
    }
    word_to_bullets: dict[str, list[int]] = {}
    for b in bullets:
        words = set(_re.findall(r'[a-z]+', b["text"].lower()))
        words -= STOP_WORDS
        words = {w for w in words if len(w) > 3}  # skip short words
        for w in words:
            word_to_bullets.setdefault(w, []).append(b["index"])
    for word, idxs in word_to_bullets.items():
        if len(idxs) > 2:
            warnings.append(
                f"Word '{word}' appears in {len(idxs)} bullets: {['P:'+str(i) for i in idxs]}"
            )

    # 5. Blocklisted tools check (if profile provided)
    if profile_section:
        blocklist_match = _re.search(
            r'Tools NOT Used.*?BLOCKLIST.*?\n((?:\s+-\s+.+\n)*)', profile_section
        )
        if blocklist_match:
            blocklist_items = _re.findall(r'-\s+(.+)', blocklist_match.group(1))
            full_text = " ".join(b["text"] for b in bullets).lower()
            for tool in blocklist_items:
                tool_clean = tool.strip().lower()
                if tool_clean and tool_clean in full_text:
                    issues.append(f"BLOCKLISTED tool '{tool.strip()}' found in resume text!")

    # 6. ACR format check — each bullet should have a result/outcome signal
    _RESULT_SIGNALS = _re.compile(
        r'[\$%]|\d+%|\d+\+?\s*'
        r'(users|customers|teams|regions|markets|points|products|units|clients|deals|'
        r'territories|countries|events|members|children|business\s*units)'
        r'|reduc|improv|increas|grew|generat|sav|deliver|driv|lift|boost|cut|streamlin|enabl',
        _re.IGNORECASE,
    )
    bullets_missing_result = []
    for b in bullets:
        if not _RESULT_SIGNALS.search(b["text"]):
            bullets_missing_result.append(b["index"])
    if bullets_missing_result:
        warnings.append(
            f"Bullets missing clear ACR result/outcome: "
            f"{['P:'+str(i) for i in bullets_missing_result]}. "
            f"Each bullet should end with a measurable impact."
        )

    # 7. Skill diversity check — flag if bullets are too thematically similar
    # Use lightweight keyword clusters to detect repeated skill themes
    _SKILL_CLUSTERS = {
        "data_analytics": {"data", "analytics", "analysis", "analyzed", "dashboards", "insights", "metrics", "sql", "tableau", "power"},
        "leadership": {"led", "managed", "directed", "oversaw", "mentored", "coordinated", "organized"},
        "financial": {"revenue", "profit", "forecast", "pricing", "budget", "cost", "financial", "p&l", "margin"},
        "cross_functional": {"cross-functional", "stakeholder", "collaborated", "partnered", "teams", "alignment"},
        "strategy": {"strategy", "strategic", "roadmap", "planning", "initiative", "priorit"},
        "communication": {"presented", "communicated", "reporting", "storytelling", "stakeholder"},
        "process_ops": {"process", "operational", "efficiency", "streamlined", "optimized", "automated", "workflow"},
        "technical": {"built", "designed", "implemented", "developed", "architected", "engineered", "platform", "system", "infrastructure"},
    }
    bullet_themes: dict[int, list[str]] = {}
    for b in bullets:
        text_lower = b["text"].lower()
        themes = []
        for theme, keywords in _SKILL_CLUSTERS.items():
            if any(kw in text_lower for kw in keywords):
                themes.append(theme)
        bullet_themes[b["index"]] = themes

    # Check if any theme appears in >3 bullets (signals lack of diversity)
    theme_counts: dict[str, list[int]] = {}
    for b_idx, themes in bullet_themes.items():
        for t in themes:
            theme_counts.setdefault(t, []).append(b_idx)
    for theme, idxs in theme_counts.items():
        if len(idxs) > 3:
            warnings.append(
                f"Skill theme '{theme}' dominates {len(idxs)} bullets: "
                f"{['P:'+str(i) for i in idxs]}. "
                f"Consider diversifying to cover more JD-required abilities."
            )

    passed = len(issues) == 0
    return ValidationResult(passed=passed, issues=issues, warnings=warnings, bullet_details=bullet_details)
