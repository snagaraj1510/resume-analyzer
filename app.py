"""Resume Analyzer — Streamlit app with unified scoring, sidebar chat, and Resume Architect guardrails."""

import io
import os
import streamlit as st
import streamlit.components.v1 as components
import mammoth
from document_handler import (
    parse_docx, extract_plain_text, parse_rewrite_response,
    rebuild_docx, parse_pdf, parse_pdf_resume, parse_txt_resume,
    build_docx_from_text, build_docx_from_template,
    chunk_reference_material, docx_to_pdf,
    load_bundled_references, fetch_jd_from_url,
)
from profile_manager import UserProfile
from analyzer import (
    analyze_resume, rewrite_resume, rescore_resume, validate_resume,
    verify_rewrites, build_chat_system, chat_response,
    full_response, PROVIDERS, detect_ollama, OLLAMA_PROVIDER,
)

st.set_page_config(page_title="Resume Analyzer", page_icon="📄", layout="wide")

# ── Session State Defaults ──────────────────────────────────────────────────
DEFAULTS = {
    "resume_bytes": None,
    "resume_structure": None,
    "resume_text": None,
    "resume_filename": "",
    "job_title": "",
    "job_description": "",
    "reference_text": "",
    "analysis_result": None,
    "rewrite_result": None,
    "modified_docx": None,
    "chat_messages": [],
    "profile": UserProfile(),
    "current_rewrites": {},
    "resume_is_pdf": False,
    "user_preferences": [],
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── Helpers ────────────────────────────────────────────────────────────────
def capture_stream(generator, state_key: str):
    """Wrap a generator to capture full output into session state while streaming."""
    chunks = []
    for chunk in generator:
        chunks.append(chunk)
        yield chunk
    st.session_state[state_key] = "".join(chunks)


def get_api_key(provider: str) -> str | None:
    """Return the API key from sidebar input or env var for the selected provider."""
    ui_key = st.session_state.get("api_key_input", "")
    if ui_key:
        return ui_key
    env_var = PROVIDERS[provider]["env_key"]
    env_key = os.environ.get(env_var, "")
    return env_key if env_key else None


def _render_resume_preview(docx_bytes: bytes):
    """Render a live document preview from docx bytes using mammoth."""
    with io.BytesIO(docx_bytes) as docx_buf:
        result = mammoth.convert_to_html(docx_buf)
        html_body = result.value

    preview_html = f"""
    <div style="
        background: white; color: black;
        font-family: Calibri, 'Segoe UI', Arial, sans-serif;
        font-size: 10pt; padding: 0.5in;
        max-width: 8.5in; margin: 0 auto;
        border: 1px solid #ddd; border-radius: 6px;
        box-shadow: 0 2px 12px rgba(0,0,0,0.08);
        line-height: 1.35;
    ">
    <style>
        .resume-preview p {{ margin: 2px 0; }}
        .resume-preview h1 {{ font-size: 14pt; text-align: center; margin: 0 0 4px 0; }}
        .resume-preview h2 {{ font-size: 10pt; text-transform: uppercase; border-bottom: 1px solid #000; padding-bottom: 2px; margin: 10px 0 4px 0; }}
        .resume-preview h3 {{ font-size: 10pt; margin: 6px 0 2px 0; }}
        .resume-preview ul {{ margin: 2px 0; padding-left: 18px; }}
        .resume-preview li {{ margin: 1px 0; }}
        .resume-preview table {{ border-collapse: collapse; width: 100%; }}
        .resume-preview td, .resume-preview th {{ padding: 2px 4px; }}
    </style>
    <div class="resume-preview">{html_body}</div>
    </div>
    """
    components.html(preview_html, height=800, scrolling=True)


# ── Vibe command detection ─────────────────────────────────────────────────
_VIBE_KEYWORDS = [
    "punchier", "more technical", "more concise", "shorter",
    "more aggressive", "tone", "rewrite", "redo", "refresh", "make it",
    "tighten", "sharpen", "cut fluff", "condense", "slim down",
    "more impactful", "stronger verbs", "more metrics", "quantify",
]

def _is_vibe_command(text: str) -> bool:
    return any(kw in text.lower() for kw in _VIBE_KEYWORDS)


def _apply_rewrites_to_doc(new_rewrites: dict):
    """Merge new rewrites into state, rebuild the docx, and update all state."""
    all_rewrites = st.session_state.get("current_rewrites", {})
    all_rewrites.update(new_rewrites)
    st.session_state["current_rewrites"] = all_rewrites
    if st.session_state["resume_is_pdf"]:
        modified = build_docx_from_template(all_rewrites, st.session_state["resume_structure"])
    else:
        modified = rebuild_docx(
            st.session_state["resume_bytes"],
            st.session_state["resume_structure"],
            all_rewrites,
        )
    st.session_state["modified_docx"] = modified
    st.session_state["modified_pdf"] = None
    new_structure = parse_docx(modified)
    st.session_state["resume_structure"] = new_structure
    st.session_state["resume_text"] = extract_plain_text(new_structure)
    st.session_state["resume_bytes"] = modified


# ═══════════════════════════════════════════════════════════════════════════
# SIDEBAR — Setup & Inputs
# ═══════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("📄 Resume Analyzer")

    # ── Step 1: Provider & API Key ──
    st.subheader("1. Connect AI Provider")

    ollama_models = detect_ollama()
    provider_list = list(PROVIDERS.keys())
    if ollama_models:
        provider_list.insert(0, OLLAMA_PROVIDER)

    provider = st.selectbox("Provider", provider_list, key="provider_select")
    ollama_model = None

    if provider == OLLAMA_PROVIDER:
        ollama_model = st.selectbox("Ollama Model", ollama_models, key="ollama_model_select")
        st.success(f"Running locally with {ollama_model} (no API key needed)")
        api_key = None

        if st.button("Verify Connection", key="btn_verify_key"):
            with st.spinner("Testing..."):
                try:
                    full_response("Respond with only the word: Connected", "Test",
                                  max_tokens=10, provider=OLLAMA_PROVIDER, ollama_model=ollama_model)
                    st.success(f"Connected to {ollama_model}")
                except Exception as e:
                    st.error(f"Connection failed: {str(e)[:200]}")
    else:
        key_hints = {
            "Claude (Anthropic)": ("sk-ant-...", "console.anthropic.com/settings/keys"),
            "GPT-4o (OpenAI)": ("sk-...", "platform.openai.com/api-keys"),
            "Gemini 2.5 Pro (Google)": ("AI...", "aistudio.google.com/apikey"),
        }
        placeholder, help_url = key_hints[provider]

        env_var = PROVIDERS[provider]["env_key"]
        env_key = os.environ.get(env_var, "")
        if env_key:
            st.success(f"API key loaded from environment")

        st.text_input(
            "API Key", type="password", key="api_key_input",
            placeholder=placeholder, help=f"Get your key at {help_url}",
        )

        api_key = get_api_key(provider)
        if not api_key:
            st.warning("Enter an API key to get started.")
        else:
            if st.button("Verify Key", key="btn_verify_key"):
                with st.spinner("Testing..."):
                    try:
                        full_response("Respond with only the word: Connected", "Test",
                                      max_tokens=10, api_key=api_key, provider=provider, lite=True)
                        st.success("Key verified!")
                    except Exception as e:
                        error_msg = str(e)
                        if "401" in error_msg or "auth" in error_msg.lower():
                            st.error("Invalid API key. Please check and try again.")
                        elif "balance" in error_msg.lower() or "quota" in error_msg.lower():
                            st.error("API key valid but no credits. Add billing to your account.")
                        else:
                            st.error(f"Connection failed: {error_msg[:200]}")

    st.divider()

    # ── Step 2: Job Details ──
    st.subheader("2. Job Details")
    st.session_state["job_title"] = st.text_input(
        "Position Title", value=st.session_state["job_title"],
        placeholder="e.g., Senior Product Manager",
    )

    jd_url = st.text_input("Job Posting URL (optional)", placeholder="https://...", key="jd_url_input")
    if jd_url and st.button("Fetch from URL", key="btn_fetch_jd"):
        with st.spinner("Fetching job description..."):
            fetched = fetch_jd_from_url(jd_url)
            if fetched:
                st.session_state["job_description"] = fetched
                st.success("Job description fetched!")
                st.rerun()
            else:
                st.error("Could not fetch from that URL. Please paste the text manually.")

    st.session_state["job_description"] = st.text_area(
        "Job Description", value=st.session_state["job_description"], height=200,
        placeholder="Paste the full job description here...",
    )

    st.divider()

    # ── Step 3: Resume Upload ──
    st.subheader("3. Upload Resume")
    resume_file = st.file_uploader(
        "Drag and drop or browse", type=["docx", "pdf", "txt"],
        help="Supported formats: .docx, .pdf, .txt",
    )
    if resume_file is not None:
        file_bytes = resume_file.read()
        if file_bytes != st.session_state["resume_bytes"]:
            st.session_state["resume_bytes"] = file_bytes
            st.session_state["resume_filename"] = resume_file.name
            fname_lower = resume_file.name.lower()
            is_pdf = fname_lower.endswith(".pdf")
            is_txt = fname_lower.endswith(".txt")
            st.session_state["resume_is_pdf"] = is_pdf or is_txt
            if is_txt:
                text_content = file_bytes.decode("utf-8", errors="replace")
                structure = parse_txt_resume(text_content)
            elif is_pdf:
                structure = parse_pdf_resume(file_bytes)
            else:
                structure = parse_docx(file_bytes)
            st.session_state["resume_structure"] = structure
            st.session_state["resume_text"] = extract_plain_text(structure)
            st.session_state["analysis_result"] = None
            st.session_state["rewrite_result"] = None
            st.session_state["modified_docx"] = None
            st.session_state["modified_pdf"] = None
            st.session_state["current_rewrites"] = {}
            st.session_state["chat_messages"] = []
            st.success(f"Loaded: {resume_file.name}")
            if is_pdf:
                st.caption("PDF detected — output will be a freshly formatted .docx/.pdf.")
            elif is_txt:
                st.caption("Text file detected — output will use the default resume template.")
    else:
        if st.session_state["resume_bytes"] is not None:
            st.session_state["resume_bytes"] = None
            st.session_state["resume_structure"] = None
            st.session_state["resume_text"] = None
            st.session_state["resume_filename"] = ""
            st.session_state["resume_is_pdf"] = False
            st.session_state["analysis_result"] = None
            st.session_state["rewrite_result"] = None
            st.session_state["modified_docx"] = None
            st.session_state["modified_pdf"] = None
            st.session_state["current_rewrites"] = {}
            st.session_state["chat_messages"] = []

    if st.session_state["resume_text"]:
        with st.expander("Preview uploaded text", expanded=False):
            st.text(st.session_state["resume_text"][:3000])

    # ── Reference materials (collapsed by default) ──
    with st.expander("Advanced: Reference Materials", expanded=False):
        REFERENCES_DIR = os.path.join(os.path.dirname(__file__), "references")
        if "bundled_ref_text" not in st.session_state:
            bundled = load_bundled_references(REFERENCES_DIR)
            st.session_state["bundled_ref_text"] = bundled

        ref_files = st.file_uploader(
            "Upload books/PDFs for best practices (optional)",
            type=["pdf", "docx"],
            accept_multiple_files=True,
        )
        uploaded_ref = ""
        if ref_files:
            ref_texts = []
            for rf in ref_files:
                rf_bytes = rf.read()
                if rf.name.endswith(".pdf"):
                    ref_texts.append(f"## {rf.name}\n{parse_pdf(rf_bytes)}")
                elif rf.name.endswith(".docx"):
                    ref_struct = parse_docx(rf_bytes)
                    ref_texts.append(f"## {rf.name}\n{extract_plain_text(ref_struct)}")
            uploaded_ref = "\n\n".join(ref_texts)
            st.success(f"Loaded {len(ref_files)} file(s)")

        combined_ref = st.session_state.get("bundled_ref_text", "")
        if uploaded_ref:
            combined_ref = combined_ref + "\n\n" + uploaded_ref if combined_ref else uploaded_ref
        if combined_ref:
            chunks = chunk_reference_material(combined_ref)
            st.session_state["reference_text"] = chunks[0] if chunks else ""
        else:
            st.session_state["reference_text"] = ""


# ── Profile section (built from chat-provided preferences) ────────────────
_prefs = st.session_state.get("user_preferences", [])
profile_section = "\n".join(f"- {p}" for p in _prefs) if _prefs else ""

# ── Shared state ──────────────────────────────────────────────────────────
ready = api_key or provider == OLLAMA_PROVIDER
provider_display = {
    "Claude (Anthropic)": "Claude Sonnet 4.6",
    "GPT-4o (OpenAI)": "OpenAI GPT-4o",
    "Gemini 2.5 Pro (Google)": "Google Gemini 2.5 Pro",
}
if provider == OLLAMA_PROVIDER and ollama_model:
    display_name = f"Ollama ({ollama_model})"
else:
    display_name = provider_display.get(provider, provider)


# ═══════════════════════════════════════════════════════════════════════════
# LAYOUT — Main (left) + Chat (right)
# ═══════════════════════════════════════════════════════════════════════════
main_col, chat_col = st.columns([3, 2])

# ═══════════════════════════════════════════════════════════════════════════
# MAIN COLUMN — Analysis, Preview & Download
# ═══════════════════════════════════════════════════════════════════════════
with main_col:
    st.title("Resume Analyzer")
    st.caption(f"Powered by {display_name}")

    # ── Welcome / status bar ──
    has_key = ready
    has_resume = bool(st.session_state["resume_text"])
    has_jd = bool(st.session_state["job_description"])
    has_results = bool(st.session_state.get("modified_docx"))

    if not has_key:
        st.info("**Step 1:** Select an AI provider and enter your API key in the sidebar to get started.")
    elif not has_resume and not has_jd:
        st.info("**Step 2:** Upload your resume and paste a job description in the sidebar.")
    elif not has_resume:
        st.info("**Step 2:** Upload your resume in the sidebar.")
    elif not has_jd:
        st.info("**Step 2:** Paste a job description in the sidebar.")
    elif not has_results:
        st.success("Ready to go! Click the button below to analyze and optimize your resume.")

    # ── Optimize button ──
    if has_key and has_resume and has_jd:
        if st.button("Analyze & Optimize Resume", key="btn_optimize", type="primary", use_container_width=True):
            progress = st.progress(0, text="Starting analysis...")

            # Step 1: Analysis
            progress.progress(10, text="Analyzing resume against job description...")
            analysis_gen = analyze_resume(
                st.session_state["job_title"],
                st.session_state["job_description"],
                st.session_state["resume_text"],
                profile_section=profile_section,
                reference_context=st.session_state["reference_text"],
                api_key=api_key, provider=provider, ollama_model=ollama_model,
            )
            analysis_chunks = []
            for chunk in analysis_gen:
                analysis_chunks.append(chunk)
            st.session_state["analysis_result"] = "".join(analysis_chunks)

            # Step 2: Rewrite
            progress.progress(40, text="Rewriting resume bullets in ACR format...")
            result = rewrite_resume(
                st.session_state["job_title"],
                st.session_state["job_description"],
                st.session_state["resume_text"],
                st.session_state["analysis_result"],
                profile_section=profile_section,
                reference_context=st.session_state["reference_text"],
                api_key=api_key, provider=provider, ollama_model=ollama_model,
            )
            st.session_state["rewrite_result"] = result
            rewrites = parse_rewrite_response(result)
            st.session_state["current_rewrites"] = rewrites
            if st.session_state["resume_is_pdf"]:
                modified = build_docx_from_template(rewrites, st.session_state["resume_structure"])
            else:
                modified = rebuild_docx(
                    st.session_state["resume_bytes"],
                    st.session_state["resume_structure"],
                    rewrites,
                )
            st.session_state["modified_docx"] = modified

            # Post-rewrite validation
            progress.progress(70, text="Validating rewritten bullets...")
            improved_structure = parse_docx(modified)
            improved_text = extract_plain_text(improved_structure)
            validation = validate_resume(improved_text, profile_section)
            st.session_state["validation_result"] = validation

            # Step 3: Re-score
            progress.progress(80, text="Scoring your improved resume...")
            rescore_gen = rescore_resume(
                st.session_state["job_title"],
                st.session_state["job_description"],
                improved_text,
                profile_section=profile_section,
                api_key=api_key, provider=provider, ollama_model=ollama_model,
            )
            rescore_chunks = []
            for chunk in rescore_gen:
                rescore_chunks.append(chunk)
            st.session_state["rescore_result"] = "".join(rescore_chunks)

            # Background verification
            if profile_section and result:
                try:
                    verify_result = verify_rewrites(
                        result, profile_section=profile_section,
                        api_key=api_key, provider=provider, ollama_model=ollama_model,
                    )
                    st.session_state["verify_result"] = verify_result
                except Exception:
                    pass

            progress.progress(100, text="Done!")

    # ── Results display ──
    if has_results:
        # Tabs for organized output
        tab_preview, tab_analysis, tab_details = st.tabs(["Resume Preview", "Score & Analysis", "Change Details"])

        with tab_preview:
            # Download buttons at top of preview
            orig_name = st.session_state["resume_filename"] or "resume"
            base_name = orig_name.rsplit(".", 1)[0]

            dl_col1, dl_col2, dl_col3 = st.columns(3)
            with dl_col1:
                st.download_button(
                    "Download .docx",
                    data=st.session_state["modified_docx"],
                    file_name=f"{base_name}_improved.docx",
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    key="btn_dl_docx",
                    use_container_width=True,
                )
            with dl_col2:
                if st.button("Generate PDF", key="btn_gen_pdf", use_container_width=True):
                    with st.spinner("Converting..."):
                        pdf_bytes = docx_to_pdf(st.session_state["modified_docx"])
                        if pdf_bytes:
                            st.session_state["modified_pdf"] = pdf_bytes
                        else:
                            st.error("PDF conversion failed. Ensure Microsoft Word is installed.")
            with dl_col3:
                if st.session_state.get("modified_pdf"):
                    st.download_button(
                        "Download .pdf",
                        data=st.session_state["modified_pdf"],
                        file_name=f"{base_name}_improved.pdf",
                        mime="application/pdf",
                        key="btn_dl_pdf",
                        use_container_width=True,
                    )

            # Live preview
            _render_resume_preview(st.session_state["modified_docx"])

        with tab_analysis:
            if st.session_state.get("rescore_result"):
                st.subheader("Improved Resume Score")
                st.markdown(st.session_state["rescore_result"])
                st.divider()

            if st.session_state["analysis_result"]:
                st.subheader("Original Analysis")
                st.markdown(st.session_state["analysis_result"])

            # Debug info — tucked away
            debug_mode = st.toggle("Show validation details", value=False, key="debug_toggle")
            if debug_mode:
                if st.session_state.get("validation_result"):
                    validation = st.session_state["validation_result"]
                    if validation.passed:
                        st.success("All guardrails passed.")
                    else:
                        st.warning("Validation found remaining issues:")
                        st.markdown(validation.summary())

                if st.session_state.get("verify_result"):
                    import json
                    try:
                        verify_issues = json.loads(st.session_state["verify_result"])
                        if verify_issues:
                            st.warning(f"Lite-model verification: {len(verify_issues)} potential issue(s)")
                            for vi in verify_issues:
                                severity = vi.get("severity", "warning")
                                icon = "!!" if severity == "error" else "?"
                                st.markdown(f"[{icon}] **{vi.get('bullet', '?')}**: {vi.get('issue', '')}")
                    except (json.JSONDecodeError, TypeError):
                        pass

        with tab_details:
            st.subheader("What Changed")
            rewrites = st.session_state["current_rewrites"]
            structure = st.session_state["resume_structure"]
            if rewrites and structure:
                st.caption(f"{len(rewrites)} bullet(s) were rewritten")
                orig_map = {p.index: p.full_text for p in structure.paragraphs}
                for idx, new_text in sorted(rewrites.items()):
                    orig = orig_map.get(idx, "(original not found)")
                    with st.expander(f"Bullet {idx}", expanded=False):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown("**Before:**")
                            st.text(orig)
                        with c2:
                            st.markdown("**After:**")
                            st.text(new_text)
            else:
                st.info("No changes to show yet.")


# ═══════════════════════════════════════════════════════════════════════════
# CHAT INPUT — root level (st.chat_input doesn't work inside st.columns)
# ═══════════════════════════════════════════════════════════════════════════

user_input = st.chat_input(
    "Ask a question or request changes — e.g., 'Make bullet 3 more technical'",
    key="chat_input_main",
)

if user_input:
    if not ready:
        st.toast("Connect an AI provider first (see sidebar).")
    else:
        st.session_state["chat_messages"].append({"role": "user", "content": user_input})
        st.session_state["_chat_pending_input"] = user_input
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════════
# CHAT PROCESSING — runs before chat column renders
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state.get("_chat_pending_input"):
    _pending_input = st.session_state.pop("_chat_pending_input")
    has_resume = bool(st.session_state.get("resume_text"))
    is_vibe = _is_vibe_command(_pending_input)

    if not has_resume:
        # No resume yet — store as preference
        st.session_state["user_preferences"].append(_pending_input)
        assistant_msg = (
            f"Got it! I'll remember: \"{_pending_input}\"\n\n"
            "Upload your resume and job description in the sidebar, "
            "and I'll factor this into the analysis."
        )
        st.session_state["chat_messages"].append({"role": "assistant", "content": assistant_msg})
    elif is_vibe and st.session_state.get("analysis_result"):
        # Vibe command: full rewrite pass
        result = rewrite_resume(
            st.session_state["job_title"],
            st.session_state["job_description"],
            st.session_state["resume_text"],
            st.session_state["analysis_result"] + "\n\n## USER DIRECTIVE:\n" + _pending_input,
            profile_section=profile_section,
            reference_context=st.session_state["reference_text"],
            api_key=api_key, provider=provider, ollama_model=ollama_model,
        )
        new_rewrites = parse_rewrite_response(result)
        if new_rewrites:
            _apply_rewrites_to_doc(new_rewrites)
            assistant_msg = f"Done! Rewrote {len(new_rewrites)} bullet(s) based on your feedback. The preview and download have been updated."
        else:
            assistant_msg = "No changes were needed based on that request."
        st.session_state["chat_messages"].append({"role": "assistant", "content": assistant_msg})
    else:
        # Normal chat flow
        system = build_chat_system(
            st.session_state["job_title"],
            st.session_state["job_description"],
            st.session_state["resume_text"],
            profile_section=profile_section,
            analysis_result=st.session_state.get("analysis_result", ""),
            reference_context=st.session_state["reference_text"],
        )
        api_messages = [
            {"role": m["role"], "content": m["content"]}
            for m in st.session_state["chat_messages"]
        ]
        response_chunks = []
        try:
            for chunk in chat_response(system, api_messages, api_key=api_key, provider=provider, ollama_model=ollama_model):
                response_chunks.append(chunk)
        except Exception as e:
            response_chunks = [f"Something went wrong: {str(e)[:300]}"]
        full_text = "".join(response_chunks)
        st.session_state["chat_messages"].append({"role": "assistant", "content": full_text})

        # Auto-apply any [P:X] rewrites from the response
        new_rewrites = parse_rewrite_response(full_text)
        if new_rewrites:
            _apply_rewrites_to_doc(new_rewrites)
            st.session_state["chat_messages"].append({
                "role": "assistant",
                "content": f"Applied {len(new_rewrites)} change(s) to your resume. The preview and download have been updated.",
            })


# ═══════════════════════════════════════════════════════════════════════════
# RIGHT COLUMN — Chat Display
# ═══════════════════════════════════════════════════════════════════════════
with chat_col:
    st.subheader("Chat")

    if not ready:
        st.info("Connect an AI provider to start chatting.")
    elif not st.session_state["resume_text"]:
        st.caption(
            "No resume uploaded yet. You can chat now to set preferences "
            "(e.g., tone, focus areas) that will be applied to your analysis."
        )
    else:
        st.caption("Ask questions or request changes. Edits are applied directly to your resume.")

    # Stored preferences indicator
    if st.session_state.get("user_preferences") and not st.session_state["resume_text"]:
        with st.expander(f"Saved Preferences ({len(st.session_state['user_preferences'])})", expanded=True):
            for pref in st.session_state["user_preferences"]:
                st.markdown(f"- {pref}")

    # Chat history
    chat_container = st.container(height=500)
    with chat_container:
        if not st.session_state["chat_messages"]:
            st.markdown(
                "<div style='text-align:center; color:#888; padding:40px 20px;'>"
                "<p style='font-size:1.1em;'>Type a message below to get started</p>"
                "<p style='font-size:0.85em;'>Try: \"Focus on leadership and strategy\" or<br>"
                "\"Make bullet 3 more technical\"</p>"
                "</div>",
                unsafe_allow_html=True,
            )
        for msg in st.session_state["chat_messages"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    # Quick download in chat column
    if st.session_state.get("modified_docx"):
        orig_name = st.session_state["resume_filename"] or "resume"
        base_name = orig_name.rsplit(".", 1)[0]
        st.download_button(
            "Download Latest Resume",
            data=st.session_state["modified_docx"],
            file_name=f"{base_name}_improved.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            key="btn_download_chat",
            use_container_width=True,
        )
