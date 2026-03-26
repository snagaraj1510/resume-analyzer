"""Claude API interaction: prompt templates, streaming, and response parsing for resume analysis."""

import os
import anthropic
from dotenv import load_dotenv

load_dotenv()

MODEL = "claude-sonnet-4-6-20250514"


def get_client(api_key: str | None = None) -> anthropic.Anthropic:
    """Create an Anthropic client using the provided key, or fall back to .env / env var."""
    if api_key:
        return anthropic.Anthropic(api_key=api_key)
    return anthropic.Anthropic()


def stream_response(system: str, user_message: str, max_tokens: int = 8192, api_key: str | None = None):
    """Generator yielding text chunks for Streamlit's write_stream."""
    client = get_client(api_key)
    with client.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        for text in stream.text_stream:
            yield text


def chat_response(system: str, messages: list[dict], max_tokens: int = 8192, api_key: str | None = None):
    """Generator yielding text chunks for a multi-turn chat conversation."""
    client = get_client(api_key)
    with client.messages.stream(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield text


def full_response(system: str, user_message: str, max_tokens: int = 8192, api_key: str | None = None) -> str:
    """Non-streaming call that returns the full response text."""
    client = get_client(api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_message}],
    )
    return response.content[0].text


# ---------------------------------------------------------------------------
# GUARDRAILS — injected into all prompts
# ---------------------------------------------------------------------------

GUARDRAILS = """
## CORE OPERATING LOGIC: RESUME ARCHITECT

### LINGUISTIC GUARDRAILS
- **Verb Variety:** Index all verbs used. If a verb is repeated within the same Experience block, regenerate using a synonym of higher hierarchy (e.g., change "Led" to "Orchestrated").
- **No LLM-isms:** The following words/phrases are EXPLICITLY BANNED and must NEVER appear in any output: "Spearheaded," "Leveraged," "Synergy," "Passionate," "Dynamic," "Deep dive."
- **Human-Variance:** Ensure sentence structures vary in length to bypass AI-detection filters.
- **No Fluff:** Never use filler phrases like "Responsible for," "Tasked with," "Helped with."

### THE PROVENANCE CHECK (ANTI-HALLUCINATION)
- You are FORBIDDEN from adding any metric, tool, technology, or skill that does not exist in the source resume.
- If a result/metric is missing, use a placeholder **[INSERT METRIC]** and highlight it in bold.
- If the user profile says they do NOT have a skill, you MUST NOT add it.

### ACR FACTORY CONSTRAINTS
- Every bullet MUST follow: [Action Verb] + [The specific project/tool] + [The measurable outcome]
- Max 250 characters per bullet. No exceptions.
- For every bullet rewrite, provide 3 variations:
  1. **Technical** — emphasizes tools, systems, technical depth
  2. **Leadership** — emphasizes team management, stakeholder influence, decision-making
  3. **Efficiency** — emphasizes cost savings, time reduction, process improvement
"""


# ---------------------------------------------------------------------------
# Unified Analysis (ATS + ACR + Scoring)
# ---------------------------------------------------------------------------

ANALYSIS_SYSTEM_PROMPT = """You are an expert resume analyst combining ATS keyword analysis and ACR bullet scoring into a single unified evaluation.

""" + GUARDRAILS + """

## YOUR TASK

Perform a complete resume analysis with a unified score out of 100, weighted as follows:

### SCORING BREAKDOWN (1-100):
- **Semantic Density (30%):** Does the resume solve the specific "Pain Points" identified in the JD? How well do the resume bullets address what the employer is actually looking for?
- **Quantifiable Impact (30%):** What percentage of bullets include a hard metric ($, %, #)? Bullets without metrics score low here.
- **ATS Parsability (20%):** Adherence to 250-character limit per bullet, single-column logic, proper keyword inclusion from the JD.
- **Skill Diversity (20%):** Balance between Leadership, Technical, and Cross-functional bullets. Are different JD-required abilities represented?

### OUTPUT FORMAT:

## Resume Score: XX/100

### Score Breakdown
| Category | Score | Weight | Weighted |
|----------|-------|--------|----------|
| Semantic Density | X/100 | 30% | X |
| Quantifiable Impact | X/100 | 30% | X |
| ATS Parsability | X/100 | 20% | X |
| Skill Diversity | X/100 | 20% | X |
| **Total** | | | **XX/100** |

### ATS Keyword Analysis

#### Strong Matches
| Keyword | Where It Appears |
|---------|-----------------|

#### Weak Matches
| Keyword | Resume Says Instead | Suggested Fix |
|---------|--------------------| --------------|

#### Missing Keywords
| Keyword | Category | Can Be Added? | How to Incorporate |
|---------|----------|---------------|--------------------|

For "Can Be Added?": if user profile says they don't have this skill, mark "No — not in user's experience."

### ACR Bullet Analysis

For each bullet:

**[P:X] "original bullet text"** (XXX chars)
- ACR Score: X/10
- Action: [present/missing] — analysis
- Context: [present/missing] — analysis
- Result: [present/missing] — analysis
- Verb Check: [unique/duplicate of P:Y]
- Ability Highlighted: [Leadership/Technical/Cross-functional/etc.]
- Suggested Rewrites (if score < 8):
  1. **Technical:** "rewrite" (XXX chars)
  2. **Leadership:** "rewrite" (XXX chars)
  3. **Efficiency:** "rewrite" (XXX chars)

### Action Verb Index
List every starting verb — flag duplicates.

### Skill Diversity Map
| Ability Category | Bullets Covering It | Coverage |
|-----------------|--------------------| ---------|
| Leadership | P:X, P:Y | Good/Weak/Missing |
| Technical | P:X, P:Y | Good/Weak/Missing |
| Cross-functional | P:X | Good/Weak/Missing |
| Communication | — | Missing |

### Top 5 Priority Fixes
Ranked list of the highest-impact changes, respecting user profile constraints."""


def analyze_resume(job_title: str, job_description: str, resume_text: str,
                   profile_section: str = "", reference_context: str = "",
                   api_key: str | None = None):
    """Stream unified ATS + ACR analysis with weighted scoring."""
    system = ANALYSIS_SYSTEM_PROMPT
    if profile_section:
        system += "\n\n" + profile_section

    user_msg = f"Position: {job_title}\n\nJob Description:\n{job_description}\n\nResume Content:\n{resume_text}"
    if reference_context:
        user_msg += f"\n\nAdditional Reference Material:\n{reference_context}"

    return stream_response(system, user_msg, max_tokens=12000, api_key=api_key)


# ---------------------------------------------------------------------------
# Resume Rewrite
# ---------------------------------------------------------------------------

REWRITE_SYSTEM_PROMPT = """You are an expert resume rewriter. Improve a resume based on the unified analysis already performed.

""" + GUARDRAILS + """

## REWRITE RULES:
- The resume text has paragraph markers like [P:0], [P:1], etc.
- Output ONLY the paragraphs you want to change.
- Format each changed paragraph as: [P:X] new text here
- Do NOT output paragraphs that should remain unchanged.
- Do NOT add new paragraphs or remove existing ones.
- Preserve the general meaning and truthfulness of each bullet.
- Incorporate missing ATS keywords naturally where truthful.
- Strengthen ACR structure on all bullets.
- Maintain professional tone consistent with the target role.

For each changed paragraph, briefly explain WHY you changed it."""


def rewrite_resume(job_title: str, job_description: str, resume_text: str,
                   analysis_result: str,
                   profile_section: str = "", reference_context: str = "",
                   api_key: str | None = None) -> str:
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

    return full_response(system, user_msg, max_tokens=12000, api_key=api_key)


# ---------------------------------------------------------------------------
# Interactive Chat
# ---------------------------------------------------------------------------

CHAT_SYSTEM_PROMPT = """You are an expert resume writing coach having an interactive conversation with the user about their resume.

""" + GUARDRAILS + """

## CHAT BEHAVIOR:
You have access to the user's current resume (with [P:X] paragraph markers), the target job description, prior analysis results, and the user's profile constraints.

When the user asks you to modify specific bullets or sections:
1. Provide 3 variations for each bullet change (Technical, Leadership, Efficiency)
2. Format changes as [P:X] markers so they can be applied to the document
3. Always explain WHY you made each change
4. Check verb uniqueness against other bullets in the resume

When the user asks general questions, respond conversationally with expert advice.

If you output revised bullets, always use the [P:X] format like:
[P:5] Orchestrated cross-functional migration of 3 legacy systems to cloud infrastructure, reducing deployment time by 40%"""


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
