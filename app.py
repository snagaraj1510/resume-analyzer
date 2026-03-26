"""Resume Analyzer — Streamlit app with unified scoring, sidebar chat, and Resume Architect guardrails."""

import os
import streamlit as st
from document_handler import (
    parse_docx, extract_plain_text, parse_rewrite_response,
    rebuild_docx, parse_pdf, parse_pdf_resume, build_docx_from_text,
    chunk_reference_material, docx_to_pdf, load_bundled_references,
)
from profile_manager import UserProfile, save_profile, load_profile, list_profiles
from analyzer import (
    analyze_resume, rewrite_resume, rescore_resume,
    build_chat_system, chat_response, full_response, PROVIDERS,
    detect_ollama, OLLAMA_PROVIDER,
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
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ── Helper ──────────────────────────────────────────────────────────────────
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


# ── Layout: Main (left) + Chat Sidebar (right) ─────────────────────────────
main_col, chat_col = st.columns([3, 2])

# ═══════════════════════════════════════════════════════════════════════════
# LEFT SIDEBAR — Inputs & Profile
# ═══════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("📄 Resume Analyzer")

    # Provider & API Key
    st.subheader("AI Provider")

    # Detect Ollama and build provider list
    ollama_models = detect_ollama()
    provider_list = list(PROVIDERS.keys())
    if ollama_models:
        provider_list.insert(0, OLLAMA_PROVIDER)

    provider = st.selectbox("Select Provider", provider_list, key="provider_select")
    ollama_model = None

    if provider == OLLAMA_PROVIDER:
        ollama_model = st.selectbox("Ollama Model", ollama_models, key="ollama_model_select")
        st.success(f"Ollama detected — running locally (no API key needed)")
        api_key = None

        if st.button("✅ Verify Connection", key="btn_verify_key"):
            with st.spinner("Testing Ollama..."):
                try:
                    result = full_response(
                        "Respond with only the word: Connected",
                        "Test",
                        max_tokens=10,
                        provider=OLLAMA_PROVIDER,
                        ollama_model=ollama_model,
                    )
                    st.success(f"Connected to Ollama — using {ollama_model}")
                except Exception as e:
                    st.error(f"Ollama connection failed: {str(e)[:200]}")
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
            st.success(f"API key loaded from .env ({env_var})")

        st.text_input(
            f"API Key for {provider}",
            type="password", key="api_key_input",
            placeholder=placeholder,
            help=f"Get your key at {help_url}",
        )

        api_key = get_api_key(provider)
        if not api_key:
            st.warning(f"Enter an API key for {provider} to use the analyzer.")
        else:
            if st.button("✅ Verify Key", key="btn_verify_key"):
                with st.spinner("Testing connection..."):
                    try:
                        result = full_response(
                            "Respond with only the word: Connected",
                            "Test",
                            max_tokens=10,
                            api_key=api_key,
                            provider=provider,
                            lite=True,
                        )
                        st.success(f"Key verified — {provider} is connected!")
                    except Exception as e:
                        error_msg = str(e)
                        if "401" in error_msg or "auth" in error_msg.lower():
                            st.error("Invalid API key. Please check and try again.")
                        elif "balance" in error_msg.lower() or "quota" in error_msg.lower():
                            st.error("API key valid but no credits/quota. Add billing to your account.")
                        else:
                            st.error(f"Connection failed: {error_msg[:200]}")

    # Job info
    st.subheader("Job Details")
    st.session_state["job_title"] = st.text_input(
        "Position Title", value=st.session_state["job_title"]
    )
    st.session_state["job_description"] = st.text_area(
        "Job Description", value=st.session_state["job_description"], height=200
    )

    # Resume upload
    st.subheader("Resume")
    resume_file = st.file_uploader("Upload Resume (.docx or .pdf)", type=["docx", "pdf"])
    if resume_file is not None:
        file_bytes = resume_file.read()
        if file_bytes != st.session_state["resume_bytes"]:
            st.session_state["resume_bytes"] = file_bytes
            st.session_state["resume_filename"] = resume_file.name
            is_pdf = resume_file.name.lower().endswith(".pdf")
            st.session_state["resume_is_pdf"] = is_pdf
            if is_pdf:
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
                st.info("PDF uploaded — formatting can't be preserved. Output will be a new .docx/.pdf.")
    else:
        # File was removed — clear all cached resume data
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
        with st.expander("Preview Resume Text"):
            st.text(st.session_state["resume_text"][:3000])

    # Reference materials
    st.subheader("Reference Materials")

    # Silently load bundled references on the backend
    REFERENCES_DIR = os.path.join(os.path.dirname(__file__), "references")
    if "bundled_ref_text" not in st.session_state:
        bundled = load_bundled_references(REFERENCES_DIR)
        st.session_state["bundled_ref_text"] = bundled

    # User can upload additional files
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
        st.success(f"Loaded {len(ref_files)} additional file(s)")

    # Combine bundled + uploaded references (only current uploads, no stale cache)
    combined_ref = st.session_state.get("bundled_ref_text", "")
    if uploaded_ref:
        combined_ref = combined_ref + "\n\n" + uploaded_ref if combined_ref else uploaded_ref
    if combined_ref:
        chunks = chunk_reference_material(combined_ref)
        st.session_state["reference_text"] = chunks[0] if chunks else ""
    else:
        st.session_state["reference_text"] = ""

    # ── Profile Manager ─────────────────────────────────────────────────────
    st.subheader("User Profile")
    existing = list_profiles()
    profile_action = st.radio(
        "Profile", ["New / Edit", "Load Existing"],
        horizontal=True, label_visibility="collapsed",
    )

    if profile_action == "Load Existing" and existing:
        selected = st.selectbox("Select Profile", existing)
        if st.button("Load Profile"):
            loaded = load_profile(selected)
            if loaded:
                st.session_state["profile"] = loaded
                st.success(f"Loaded profile: {selected}")
                st.rerun()

    prof: UserProfile = st.session_state["profile"]

    with st.expander("Edit Profile", expanded=(profile_action == "New / Edit")):
        prof.name = st.text_input("Profile Name", value=prof.name)

        st.markdown("**Experience Facts** (ground truth — what you actually did)")
        experience_text = st.text_area(
            "One fact per line (roles, projects, metrics, stakeholders)",
            value="\n".join(prof.experience_facts),
            key="experience_facts_input", height=120,
        )
        prof.experience_facts = [s.strip() for s in experience_text.split("\n") if s.strip()]

        st.markdown("**Known Tools & Skills**")
        skills_have_text = st.text_area(
            "One per line — only these may appear on your resume",
            value="\n".join(prof.skills_have),
            key="skills_have_input", height=100,
        )
        prof.skills_have = [s.strip() for s in skills_have_text.split("\n") if s.strip()]

        st.markdown("**Tools NOT Used — Blocklist**")
        skills_missing_text = st.text_area(
            "One per line — will NEVER be added to your resume",
            value="\n".join(prof.skills_missing),
            key="skills_missing_input", height=100,
        )
        prof.skills_missing = [s.strip() for s in skills_missing_text.split("\n") if s.strip()]

        st.markdown("**Title Adjustment Rules**")
        title_rules_text = st.text_area(
            "E.g., 'Financial Analyst -> Financial Analyst, Product Strategy is VALID'",
            value="\n".join(prof.title_rules),
            key="title_rules_input", height=80,
        )
        prof.title_rules = [s.strip() for s in title_rules_text.split("\n") if s.strip()]

        st.markdown("**Constraints / Facts**")
        constraints_text = st.text_area(
            "E.g., 'No direct reports', '3 years experience not 5'",
            value="\n".join(prof.constraints),
            key="constraints_input", height=80,
        )
        prof.constraints = [s.strip() for s in constraints_text.split("\n") if s.strip()]

        st.markdown("**Style Preferences**")
        preferences_text = st.text_area(
            "E.g., 'ACR format', '1 page only', 'Target <185 chars'",
            value="\n".join(prof.preferences),
            key="preferences_input", height=80,
        )
        prof.preferences = [s.strip() for s in preferences_text.split("\n") if s.strip()]

        if st.button("💾 Save Profile"):
            save_profile(prof)
            st.success(f"Saved: {prof.name}")


# ── Profile prompt section ──────────────────────────────────────────────────
profile_section = prof.to_prompt_section() if (
    prof.experience_facts or prof.skills_have or prof.skills_missing
    or prof.title_rules or prof.constraints or prof.preferences
) else ""


# ═══════════════════════════════════════════════════════════════════════════
# MAIN COLUMN — Analysis & Rewrite
# ═══════════════════════════════════════════════════════════════════════════
with main_col:
    st.title("Resume Analyzer")
    provider_display = {
        "Claude (Anthropic)": "Claude Sonnet 4.6",
        "GPT-4o (OpenAI)": "OpenAI GPT-4o",
        "Gemini 2.5 Pro (Google)": "Google Gemini 2.5 Pro",
    }
    if provider == OLLAMA_PROVIDER and ollama_model:
        display_name = f"Ollama ({ollama_model})"
    else:
        display_name = provider_display.get(provider, provider)
    st.caption(f"Powered by {display_name} — Unified Scoring · ACR Factory · AI Rewrite · Live Chat")
    ready = api_key or provider == OLLAMA_PROVIDER

    tab_analysis, tab_rewrite = st.tabs(["📊 Analysis & Score", "✏️ Rewrite & Download"])

    # ── Tab 1: Unified Analysis ─────────────────────────────────────────────
    with tab_analysis:
        st.header("Resume Analysis — Unified Score")
        st.markdown(
            "Combines **ATS keyword matching**, **ACR bullet scoring**, **semantic density**, "
            "and **skill diversity** into a single weighted score out of 100."
        )

        if not ready:
            st.error("Select a provider and enter an API key in the sidebar to run analysis.")
        elif not st.session_state["resume_text"] or not st.session_state["job_description"]:
            st.warning("Upload a resume and paste a job description in the sidebar to begin.")
        else:
            if st.button("Run Full Analysis", key="btn_analysis", type="primary"):
                gen = analyze_resume(
                    st.session_state["job_title"],
                    st.session_state["job_description"],
                    st.session_state["resume_text"],
                    profile_section=profile_section,
                    reference_context=st.session_state["reference_text"],
                    api_key=api_key,
                    provider=provider,
                    ollama_model=ollama_model,
                )
                st.write_stream(capture_stream(gen, "analysis_result"))

            if st.session_state["analysis_result"]:
                st.markdown("---")
                st.markdown(st.session_state["analysis_result"])

    # ── Tab 2: Rewrite & Download ───────────────────────────────────────────
    with tab_rewrite:
        st.header("Resume Rewrite & Download")

        analysis_done = st.session_state["analysis_result"] is not None
        st.metric("Analysis", "✅ Done" if analysis_done else "⏳ Pending")

        if not ready:
            st.error("Select a provider and enter an API key in the sidebar.")
        elif not analysis_done:
            st.info("Run the full analysis first before generating a rewrite.")
        else:
            if st.button("Generate Improved Resume", key="btn_rewrite", type="primary"):
                with st.spinner("Rewriting resume — this may take a moment..."):
                    result = rewrite_resume(
                        st.session_state["job_title"],
                        st.session_state["job_description"],
                        st.session_state["resume_text"],
                        st.session_state["analysis_result"],
                        profile_section=profile_section,
                        reference_context=st.session_state["reference_text"],
                        api_key=api_key,
                        provider=provider,
                        ollama_model=ollama_model,
                    )
                    st.session_state["rewrite_result"] = result
                    rewrites = parse_rewrite_response(result)
                    st.session_state["current_rewrites"] = rewrites
                    if st.session_state["resume_is_pdf"]:
                        modified = build_docx_from_text(rewrites, st.session_state["resume_structure"])
                    else:
                        modified = rebuild_docx(
                            st.session_state["resume_bytes"],
                            st.session_state["resume_structure"],
                            rewrites,
                        )
                    st.session_state["modified_docx"] = modified

                    # Re-score the improved resume (slim prompt, lite model)
                    improved_structure = parse_docx(modified)
                    improved_text = extract_plain_text(improved_structure)
                    st.subheader("New Fit Score")
                    rescore_gen = rescore_resume(
                        st.session_state["job_title"],
                        st.session_state["job_description"],
                        improved_text,
                        profile_section=profile_section,
                        api_key=api_key,
                        provider=provider,
                        ollama_model=ollama_model,
                    )
                    st.write_stream(capture_stream(rescore_gen, "rescore_result"))

            if st.session_state.get("rescore_result"):
                st.markdown("---")
                st.subheader("Improved Resume Score")
                st.markdown(st.session_state["rescore_result"])

            if st.session_state["rewrite_result"]:
                st.subheader("Changes Made")
                rewrites = st.session_state["current_rewrites"]
                structure = st.session_state["resume_structure"]
                if rewrites and structure:
                    orig_map = {p.index: p.full_text for p in structure.paragraphs}
                    for idx, new_text in sorted(rewrites.items()):
                        orig = orig_map.get(idx, "(original not found)")
                        with st.expander(f"[P:{idx}] — Changed", expanded=True):
                            c1, c2 = st.columns(2)
                            with c1:
                                st.markdown("**Original:**")
                                st.text(orig)
                            with c2:
                                st.markdown("**Improved:**")
                                st.text(new_text)
                else:
                    st.markdown(st.session_state["rewrite_result"])

            if st.session_state["modified_docx"]:
                orig_name = st.session_state["resume_filename"] or "resume"
                base_name = orig_name.rsplit(".", 1)[0]

                dl_col1, dl_col2 = st.columns(2)
                with dl_col1:
                    st.download_button(
                        "⬇️ Download as .docx",
                        data=st.session_state["modified_docx"],
                        file_name=f"{base_name}_improved.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key="btn_dl_docx",
                    )
                with dl_col2:
                    if st.button("⬇️ Generate PDF", key="btn_gen_pdf"):
                        with st.spinner("Converting to PDF (requires Microsoft Word)..."):
                            pdf_bytes = docx_to_pdf(st.session_state["modified_docx"])
                            if pdf_bytes:
                                st.session_state["modified_pdf"] = pdf_bytes
                            else:
                                st.error("PDF conversion failed. Make sure Microsoft Word is installed.")

                if st.session_state.get("modified_pdf"):
                    st.download_button(
                        "⬇️ Download as .pdf",
                        data=st.session_state["modified_pdf"],
                        file_name=f"{base_name}_improved.pdf",
                        mime="application/pdf",
                        key="btn_dl_pdf",
                    )


# ═══════════════════════════════════════════════════════════════════════════
# RIGHT COLUMN — Persistent Chat
# ═══════════════════════════════════════════════════════════════════════════
with chat_col:
    st.header("💬 Chat")

    if not ready:
        st.info("Select a provider to chat.")
    elif not st.session_state["resume_text"]:
        st.info("Upload a resume to start chatting.")
    else:
        st.caption("Refine bullets, adjust tone, or ask questions. Changes can be applied directly.")

        # Scrollable chat history container
        chat_container = st.container(height=500)
        with chat_container:
            for msg in st.session_state["chat_messages"]:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

        # Chat input
        if user_input := st.chat_input(
            "e.g., 'Make bullet 3 more technical'",
            key="chat_input_main",
        ):
            st.session_state["chat_messages"].append({"role": "user", "content": user_input})

            # Build system prompt with full context
            system = build_chat_system(
                st.session_state["job_title"],
                st.session_state["job_description"],
                st.session_state["resume_text"],
                profile_section=profile_section,
                analysis_result=st.session_state.get("analysis_result", ""),
                reference_context=st.session_state["reference_text"],
            )

            # Build messages for Claude
            api_messages = [
                {"role": m["role"], "content": m["content"]}
                for m in st.session_state["chat_messages"]
            ]

            # Stream response
            gen = chat_response(system, api_messages, api_key=api_key, provider=provider, ollama_model=ollama_model)
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(user_input)
                with st.chat_message("assistant"):
                    response_text = st.write_stream(gen)

            full_text = response_text if isinstance(response_text, str) else ""

            st.session_state["chat_messages"].append({"role": "assistant", "content": full_text})

            # Check for [P:X] markers
            new_rewrites = parse_rewrite_response(full_text)
            if new_rewrites:
                st.session_state["_pending_chat_rewrites"] = new_rewrites
            st.rerun()

        # Apply changes button
        if st.session_state.get("_pending_chat_rewrites"):
            pending = st.session_state["_pending_chat_rewrites"]
            st.info(f"Claude suggested changes to {len(pending)} paragraph(s).")

            structure = st.session_state["resume_structure"]
            if structure:
                orig_map = {p.index: p.full_text for p in structure.paragraphs}
                for idx, new_text in sorted(pending.items()):
                    orig = orig_map.get(idx, "(original not found)")
                    with st.expander(f"[P:{idx}]", expanded=True):
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown("**Current:**")
                            st.text(orig)
                        with c2:
                            st.markdown("**Proposed:**")
                            st.text(new_text)

            if st.button("✅ Apply These Changes", key="btn_apply_chat"):
                all_rewrites = st.session_state.get("current_rewrites", {})
                all_rewrites.update(pending)
                st.session_state["current_rewrites"] = all_rewrites

                if st.session_state["resume_is_pdf"]:
                    modified = build_docx_from_text(all_rewrites, st.session_state["resume_structure"])
                else:
                    modified = rebuild_docx(
                        st.session_state["resume_bytes"],
                        st.session_state["resume_structure"],
                        all_rewrites,
                    )
                st.session_state["modified_docx"] = modified

                new_structure = parse_docx(modified)
                st.session_state["resume_structure"] = new_structure
                st.session_state["resume_text"] = extract_plain_text(new_structure)
                st.session_state["resume_bytes"] = modified

                del st.session_state["_pending_chat_rewrites"]
                st.success("Changes applied!")
                st.rerun()

        # Download button always available
        if st.session_state["modified_docx"]:
            orig_name = st.session_state["resume_filename"] or "resume"
            base_name = orig_name.rsplit(".", 1)[0]
            st.download_button(
                "⬇️ Download Latest Resume (.docx)",
                data=st.session_state["modified_docx"],
                file_name=f"{base_name}_improved.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key="btn_download_chat",
            )
