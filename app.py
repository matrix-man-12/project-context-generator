"""
Streamlit UI — Interactive portal context generation.

Run with: streamlit run app.py
"""

import asyncio
import logging
import os
import zipfile
from io import BytesIO
from pathlib import Path

import streamlit as st

from portal_context.config import PortalConfig
from portal_context.pipeline import run_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ── Page Config ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="Portal Context Generator",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom Styling ───────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { max-width: 1200px; margin: 0 auto; }
    .status-box {
        padding: 1rem; border-radius: 0.5rem;
        border: 1px solid #444; margin: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)


# ── Sidebar Configuration ───────────────────────────────────────────
with st.sidebar:
    st.title("⚙️ Configuration")

    st.subheader("LLM Provider")
    provider = st.selectbox("Provider", ["gemini", "openai", "custom"],
                            help="Choose your LLM backend")

    api_key = ""
    model = ""
    llm_url = ""
    req_field = "input"
    res_field = "output"

    if provider == "gemini":
        api_key = st.text_input("Gemini API Key", type="password",
                                value=os.getenv("GEMINI_API_KEY", ""))
        model = st.text_input("Model", value="gemini-2.0-flash")

    elif provider == "openai":
        llm_url = st.text_input("LLM Base URL", value=os.getenv("LLM_BASE_URL", ""),
                                placeholder="http://your-llm:8080/v1")
        api_key = st.text_input("API Key", type="password",
                                value=os.getenv("LLM_API_KEY", ""))
        model = st.text_input("Model", value=os.getenv("LLM_MODEL", "default"))

    elif provider == "custom":
        llm_url = st.text_input("LLM Endpoint URL",
                                value=os.getenv("LLM_BASE_URL", ""),
                                placeholder="http://your-llm:5000/generate")
        req_field = st.text_input("Request field", value="input")
        res_field = st.text_input("Response field", value="output")
        api_key = st.text_input("API Key (optional)", type="password", value="")

    st.divider()
    st.subheader("Crawl Settings")
    max_depth = st.slider("Max depth", 1, 10, 3)
    max_pages = st.slider("Max pages", 10, 500, 100)
    max_interactions = st.slider("Max interactions/page", 5, 50, 20)
    screenshots = st.checkbox("Capture screenshots", value=True)

    st.divider()
    st.subheader("Authentication")
    auth = st.selectbox("Auth method", ["none", "profile", "cdp"])
    chrome_profile = ""
    cdp_url = ""
    if auth == "profile":
        chrome_profile = st.text_input("Chrome profile directory",
                                       placeholder="C:/Users/.../User Data")
    elif auth == "cdp":
        cdp_url = st.text_input("CDP URL", placeholder="http://localhost:9222")


# ── Main Content ─────────────────────────────────────────────────────
st.title("🔍 Portal Context Generator")
st.markdown("Generate comprehensive documentation from any internal portal URL.")

col1, col2 = st.columns([2, 1])

with col1:
    portal_url = st.text_input("Portal URL", placeholder="https://portal.internal.com")
    portal_name = st.text_input("Portal Name (optional)",
                                placeholder="Auto-derived from URL",
                                help="Leave empty to auto-derive from the URL")

with col2:
    output_dir = st.text_input("Output Directory", value="./output")

# Supplementary Input
with st.expander("📄 Supplementary Input", expanded=False):
    uploaded_files = st.file_uploader(
        "Upload supporting documents (PDF, DOCX, PPTX, MD, TXT)",
        accept_multiple_files=True,
        type=["pdf", "docx", "pptx", "md", "txt"],
    )
    user_notes = st.text_area(
        "Additional notes about the portal",
        placeholder="E.g., This portal is used by content ops for VOD curation...",
        height=100,
    )

# ── Generate Button ──────────────────────────────────────────────────
st.divider()

if st.button("🚀 Generate Portal Context", type="primary", use_container_width=True):
    if not portal_url:
        st.error("Please enter a portal URL")
        st.stop()

    # Save uploaded files to temp location
    doc_paths = []
    if uploaded_files:
        temp_docs = Path("./temp_docs")
        temp_docs.mkdir(exist_ok=True)
        for f in uploaded_files:
            p = temp_docs / f.name
            p.write_bytes(f.read())
            doc_paths.append(str(p))

    config = PortalConfig(
        portal_url=portal_url,
        portal_name=portal_name,
        llm_provider=provider,
        llm_model=model or ("gemini-2.0-flash" if provider == "gemini" else "default"),
        llm_api_key=api_key,
        llm_base_url=llm_url,
        llm_request_field=req_field,
        llm_response_field=res_field,
        max_depth=max_depth,
        max_pages=max_pages,
        max_interactions_per_page=max_interactions,
        capture_screenshots=screenshots,
        output_dir=output_dir,
        auth_method=auth,
        chrome_profile_dir=chrome_profile,
        cdp_url=cdp_url,
        doc_paths=doc_paths,
        user_notes=user_notes,
    )

    errors = config.validate()
    if errors:
        for e in errors:
            st.error(f"Config error: {e}")
        st.stop()

    # Progress UI
    progress_bar = st.progress(0, text="Starting...")
    status_area = st.empty()
    log_area = st.expander("📋 Logs", expanded=False)
    log_text = []

    def on_progress(phase, msg, pct):
        progress_bar.progress(pct, text=f"{phase}: {msg}")
        log_text.append(f"[{phase}] {msg}")
        with log_area:
            st.code("\n".join(log_text[-20:]))

    try:
        output_path = asyncio.run(run_pipeline(config, progress_callback=on_progress))

        st.success(f"✅ Portal context generated at: `{output_path}`")

        # Show preview of generated files
        st.subheader("📂 Generated Files")
        out_dir = Path(output_path)

        for md_file in sorted(out_dir.rglob("*.md")):
            rel = md_file.relative_to(out_dir)
            with st.expander(f"📄 {rel}"):
                st.markdown(md_file.read_text(encoding="utf-8"))

        # ZIP download
        zip_buf = BytesIO()
        with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in out_dir.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(out_dir))
        zip_buf.seek(0)

        st.download_button(
            "📥 Download as ZIP",
            data=zip_buf,
            file_name=f"{config.portal_name}_context.zip",
            mime="application/zip",
            use_container_width=True,
        )

    except Exception as e:
        st.error(f"❌ Generation failed: {e}")
        st.exception(e)

# ── Footer ───────────────────────────────────────────────────────────
st.divider()
st.caption("Portal Context Generator v0.1.0 — Generates documentation, not data.")
