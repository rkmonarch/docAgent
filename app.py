"""
DocAgent — AI-powered documentation generator.
Streamlit multi-step intake wizard → CrewAI crew → multi-format export.
"""

import io
import json
import os
import zipfile
from datetime import datetime

import streamlit as st

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="DocAgent · Documentation Generator",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Light-theme CSS ───────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* ── Global resets ── */
    html, body, [data-testid="stAppViewContainer"] {
        background: #ffffff !important;
    }
    /* sidebar kept visible — provider config lives there */
    div[data-testid="stForm"] { border: none !important; padding: 0; box-shadow: none; }

    /* ── Hero banner ── */
    .hero {
        background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
        border-radius: 16px;
        padding: 2.5rem 2rem 2rem;
        margin-bottom: 2rem;
        color: #fff;
    }
    .hero h1 { margin: 0 0 .35rem; font-size: 2rem; font-weight: 800; letter-spacing: -.5px; }
    .hero p  { margin: 0; opacity: .85; font-size: 1rem; }

    /* ── Step progress bar ── */
    .step-bar { display: flex; gap: 6px; margin-bottom: 2rem; }
    .step-pill {
        flex: 1; padding: 7px 0; border-radius: 999px;
        text-align: center; font-size: .78rem; font-weight: 700;
        border: 2px solid transparent; transition: all .2s;
    }
    .step-pill.done   { background: #D1FAE5; color: #065F46; border-color: #6EE7B7; }
    .step-pill.active { background: #4F46E5; color: #fff;    border-color: #4F46E5; }
    .step-pill.todo   { background: #F3F4F6; color: #9CA3AF; border-color: #E5E7EB; }

    /* ── Section heading ── */
    .section-heading {
        font-size: 1.25rem; font-weight: 700; color: #111827;
        margin: 0 0 .25rem; display: flex; align-items: center; gap: .5rem;
    }
    .section-sub {
        font-size: .875rem; color: #6B7280; margin: 0 0 1.25rem;
        padding-left: 1.85rem;
    }

    /* ── Tip / info box ── */
    .tip {
        background: #EEF2FF; border-left: 4px solid #4F46E5;
        border-radius: 6px; padding: .7rem 1rem; margin: .75rem 0 1.25rem;
        font-size: .85rem; color: #3730A3;
    }

    /* ── Review cards ── */
    .r-card {
        background: #FAFAFA; border: 1px solid #E5E7EB;
        border-radius: 12px; padding: 1.25rem 1.5rem; margin-bottom: .75rem;
    }
    .r-card-title {
        font-size: .7rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: .08em; color: #6B7280; margin-bottom: .5rem;
    }
    .r-card-body { font-size: .9rem; color: #111827; }
    .r-card-body b { color: #4F46E5; }

    /* ── Chips / tags ── */
    .chip {
        display: inline-block; background: #EEF2FF; color: #4338CA;
        border-radius: 999px; padding: 2px 10px; font-size: .75rem;
        margin: 2px; border: 1px solid #C7D2FE; font-weight: 600;
    }
    .chip-green {
        display: inline-block; background: #D1FAE5; color: #065F46;
        border-radius: 999px; padding: 2px 10px; font-size: .75rem;
        margin: 2px; border: 1px solid #6EE7B7; font-weight: 600;
    }

    /* ── Export format cards ── */
    .export-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; margin-bottom: 1rem; }
    .export-card {
        background: #F9FAFB; border: 2px solid #E5E7EB;
        border-radius: 10px; padding: 1rem; cursor: pointer;
        transition: border-color .15s, background .15s;
    }
    .export-card:hover { border-color: #4F46E5; background: #EEF2FF; }
    .export-card .ec-icon { font-size: 1.5rem; margin-bottom: .3rem; }
    .export-card .ec-title { font-weight: 700; font-size: .9rem; color: #111827; }
    .export-card .ec-desc  { font-size: .78rem; color: #6B7280; margin-top: .15rem; }

    /* ── Divider ── */
    hr { border: none; border-top: 1px solid #E5E7EB; margin: 1.5rem 0; }

    /* ── Streamlit widget overrides ── */
    [data-testid="stTextInput"] input,
    [data-testid="stTextArea"] textarea {
        border: 1px solid #D1D5DB !important;
        border-radius: 8px !important;
        background: #fff !important;
    }
    [data-testid="stTextInput"] input:focus,
    [data-testid="stTextArea"] textarea:focus {
        border-color: #4F46E5 !important;
        box-shadow: 0 0 0 3px rgba(79,70,229,.12) !important;
    }
    .stButton > button {
        border-radius: 8px !important;
        font-weight: 600 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Session-state defaults ────────────────────────────────────────────────────
DEFAULTS: dict = {
    "step": 1,
    "intake": {},
    "crew_output": None,
    "export_files": {},   # {filename: content}
    "running": False,
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

TOTAL_STEPS = 5
STEP_LABELS = ["Project", "Codebase", "Audience", "Preferences", "Review"]


# ── Helpers ───────────────────────────────────────────────────────────────────
def _pill(label: str, idx: int) -> str:
    step = st.session_state.step
    cls = "done" if idx < step else ("active" if idx == step else "todo")
    icon = "✓ " if idx < step else f"{idx}. "
    return f'<div class="step-pill {cls}">{icon}{label}</div>'


def render_progress() -> None:
    pills = "".join(_pill(lbl, i + 1) for i, lbl in enumerate(STEP_LABELS))
    st.markdown(f'<div class="step-bar">{pills}</div>', unsafe_allow_html=True)


def tip(text: str) -> None:
    st.markdown(f'<div class="tip">{text}</div>', unsafe_allow_html=True)


def section(icon: str, title: str, subtitle: str = "") -> None:
    st.markdown(
        f'<div class="section-heading">{icon} {title}</div>'
        + (f'<div class="section-sub">{subtitle}</div>' if subtitle else ""),
        unsafe_allow_html=True,
    )


def nav(back: bool = True) -> tuple[bool, bool]:
    cols = st.columns([1, 4, 1] if back else [5, 1])
    prev = cols[0].form_submit_button("← Back", use_container_width=True) if back else False
    nxt  = cols[-1].form_submit_button("Continue →", use_container_width=True, type="primary")
    return prev, nxt


def save(key: str, value) -> None:
    st.session_state.intake[key] = value


# ── Step 1: Project ───────────────────────────────────────────────────────────
def step1_project() -> None:
    section("📦", "Project Overview", "Start with the basics — name, purpose, and type.")
    tip("The richer your description, the more accurate and tailored your documentation will be.")

    with st.form("step1"):
        col_a, col_b = st.columns([3, 1])
        name    = col_a.text_input("Project name *", value=st.session_state.intake.get("project_name", ""), placeholder="e.g. FastPay SDK")
        version = col_b.text_input("Version", value=st.session_state.intake.get("version", ""), placeholder="1.0.0")

        tagline = st.text_input(
            "One-line tagline *",
            value=st.session_state.intake.get("tagline", ""),
            placeholder="e.g. Embeddable payment processing for Python web apps",
        )
        description = st.text_area(
            "Full project description *",
            value=st.session_state.intake.get("description", ""),
            height=150,
            placeholder=(
                "Describe what the project does, the problem it solves, who uses it, "
                "and any important design decisions or constraints…"
            ),
        )

        col_c, col_d = st.columns(2)
        project_type = col_c.selectbox(
            "Project type *",
            ["Python Library / SDK", "REST / GraphQL API", "CLI Tool",
             "Web Application", "Data Pipeline", "ML / AI Model", "Other"],
            index=["Python Library / SDK", "REST / GraphQL API", "CLI Tool",
                   "Web Application", "Data Pipeline", "ML / AI Model", "Other"]
            .index(st.session_state.intake.get("project_type", "Python Library / SDK")),
        )
        license_ = col_d.selectbox(
            "License",
            ["MIT", "Apache 2.0", "GPL-3.0", "BSD-3-Clause", "Proprietary / Other"],
            index=["MIT", "Apache 2.0", "GPL-3.0", "BSD-3-Clause", "Proprietary / Other"]
            .index(st.session_state.intake.get("license", "MIT")),
        )

        _, next_clicked = nav(back=False)

    if next_clicked:
        errors = []
        if not name.strip():      errors.append("Project name is required.")
        if not tagline.strip():   errors.append("Tagline is required.")
        if len(description.strip()) < 30: errors.append("Description must be at least 30 characters.")
        if errors:
            for e in errors: st.error(e)
        else:
            save("project_name", name.strip()); save("tagline", tagline.strip())
            save("description", description.strip()); save("project_type", project_type)
            save("version", version.strip()); save("license", license_)
            st.session_state.step = 2; st.rerun()


# ── Step 2: Codebase ──────────────────────────────────────────────────────────
def step2_codebase() -> None:
    section("💻", "Codebase & Tech Stack", "Point DocAgent at your code to extract APIs and examples automatically.")
    tip("Public GitHub repos give the best results. Private repos: use file upload instead.")

    with st.form("step2"):
        source_type = st.radio(
            "How do you want to provide your codebase?",
            ["GitHub URL", "Paste code snippets", "Upload files", "None — description only"],
            index=["GitHub URL", "Paste code snippets", "Upload files", "None — description only"]
            .index(st.session_state.intake.get("source_type", "GitHub URL")),
            horizontal=True,
        )

        github_url = ""; code_snippets = ""; uploaded_files_info: list[dict] = []

        if source_type == "GitHub URL":
            github_url = st.text_input(
                "GitHub repository URL *",
                value=st.session_state.intake.get("github_url", ""),
                placeholder="https://github.com/org/repo",
            )
        elif source_type == "Paste code snippets":
            code_snippets = st.text_area(
                "Paste your key source files *",
                value=st.session_state.intake.get("code_snippets", ""),
                height=260,
                placeholder="# --- file: src/client.py ---\nclass Client:\n    ...",
            )
        elif source_type == "Upload files":
            uploads = st.file_uploader(
                "Upload source files",
                accept_multiple_files=True,
                type=["py","ts","tsx","js","go","rs","java","md","yaml","yml","json","toml"],
            )
            if uploads:
                for f in uploads:
                    uploaded_files_info.append({"name": f.name, "content": f.read().decode("utf-8", errors="replace")})
                st.success(f"{len(uploads)} file(s) ready.")

        st.markdown("---")

        tech_stack = st.multiselect(
            "Tech stack / languages *",
            ["Python","TypeScript","JavaScript","Go","Rust","Java","C#","C/C++","Ruby","PHP",
             "Swift","Kotlin","FastAPI","Django","Flask","Next.js","React","Vue",
             "PostgreSQL","MySQL","MongoDB","Redis","Docker","Kubernetes"],
            default=st.session_state.intake.get("tech_stack", []),
        )
        col_e, col_f = st.columns(2)
        dependencies  = col_e.text_input("Key dependencies (comma-separated)", value=st.session_state.intake.get("dependencies",""), placeholder="pydantic, httpx, SQLAlchemy")
        repo_structure = col_f.text_input("Repo structure summary (optional)", value=st.session_state.intake.get("repo_structure",""), placeholder="src/ lib, tests/, examples/")

        prev_clicked, next_clicked = nav()

    if prev_clicked: st.session_state.step = 1; st.rerun()
    if next_clicked:
        errors = []
        if source_type == "GitHub URL" and not github_url.strip(): errors.append("GitHub URL required.")
        if source_type == "Paste code snippets" and not code_snippets.strip(): errors.append("Please paste some code.")
        if not tech_stack: errors.append("Select at least one technology.")
        if errors:
            for e in errors: st.error(e)
        else:
            save("source_type", source_type); save("github_url", github_url.strip())
            save("code_snippets", code_snippets.strip()); save("uploaded_files", uploaded_files_info)
            save("tech_stack", tech_stack); save("dependencies", dependencies.strip())
            save("repo_structure", repo_structure.strip())
            st.session_state.step = 3; st.rerun()


# ── Step 3: Audience ──────────────────────────────────────────────────────────
def step3_audience() -> None:
    section("👥", "Audience & Scope", "DocAgent tailors tone, depth, and examples to your readers.")

    with st.form("step3"):
        primary_audience = st.multiselect(
            "Primary audience *",
            ["Backend developers","Frontend developers","Full-stack developers",
             "Data scientists / ML engineers","DevOps / SRE","Mobile developers",
             "Technical writers","Open-source contributors","Enterprise / B2B integration teams"],
            default=st.session_state.intake.get("primary_audience", []),
        )
        skill_level = st.select_slider(
            "Assumed reader skill level",
            options=["Beginner", "Intermediate", "Advanced", "Expert"],
            value=st.session_state.intake.get("skill_level", "Intermediate"),
        )
        use_cases = st.text_area(
            "Top 3–5 use cases / jobs-to-be-done *",
            value=st.session_state.intake.get("use_cases", ""),
            height=110,
            placeholder="1. Accept payments in < 10 lines\n2. Handle webhooks\n3. Migrate from Stripe…",
        )

        st.markdown("---")
        st.markdown("**Diátaxis sections to generate**")
        c1, c2, c3, c4 = st.columns(4)
        gen_tutorial    = c1.checkbox("Tutorial + Quickstart", value=st.session_state.intake.get("gen_tutorial", True))
        gen_howto       = c2.checkbox("How-to Guides",         value=st.session_state.intake.get("gen_howto", True))
        gen_reference   = c3.checkbox("API Reference",         value=st.session_state.intake.get("gen_reference", True))
        gen_explanation = c4.checkbox("Explanation / Concepts",value=st.session_state.intake.get("gen_explanation", True))

        st.markdown("**Extras**")
        ce1, ce2 = st.columns(2)
        agent_friendly = ce1.checkbox("Agent-friendly extras (llms.txt, JSON Schema, TypeScript types)", value=st.session_state.intake.get("agent_friendly", True))
        mkdocs         = ce2.checkbox("MkDocs / Material theme config", value=st.session_state.intake.get("mkdocs", False))

        prev_clicked, next_clicked = nav()

    if prev_clicked: st.session_state.step = 2; st.rerun()
    if next_clicked:
        errors = []
        if not primary_audience: errors.append("Select at least one audience segment.")
        if not use_cases.strip(): errors.append("Use cases are required.")
        if not any([gen_tutorial, gen_howto, gen_reference, gen_explanation]): errors.append("Select at least one section.")
        if errors:
            for e in errors: st.error(e)
        else:
            save("primary_audience", primary_audience); save("skill_level", skill_level)
            save("use_cases", use_cases.strip()); save("gen_tutorial", gen_tutorial)
            save("gen_howto", gen_howto); save("gen_reference", gen_reference)
            save("gen_explanation", gen_explanation); save("agent_friendly", agent_friendly)
            save("mkdocs", mkdocs)
            st.session_state.step = 4; st.rerun()


# ── Step 4: Preferences ───────────────────────────────────────────────────────
def step4_preferences() -> None:
    section("🎨", "Style & Preferences", "Fine-tune tone, formatting, and extra context before generation.")

    with st.form("step4"):
        col_a, col_b = st.columns(2)
        tone = col_a.select_slider(
            "Documentation tone",
            options=["Very formal","Formal","Neutral","Friendly","Casual / Dev-friendly"],
            value=st.session_state.intake.get("tone", "Friendly"),
        )
        code_style = col_b.radio(
            "Code example style",
            ["Minimal","Full working examples","Both"],
            index=["Minimal","Full working examples","Both"]
            .index(st.session_state.intake.get("code_style", "Full working examples")),
        )

        cd1, cd2 = st.columns(2)
        include_diagrams    = cd1.checkbox("Mermaid diagram suggestions", value=st.session_state.intake.get("include_diagrams", True))
        include_admonitions = cd2.checkbox("Callout boxes (note / warning / tip)", value=st.session_state.intake.get("include_admonitions", True))

        st.markdown("---")
        existing_docs_url = st.text_input("Existing docs URL (for gap analysis, optional)", value=st.session_state.intake.get("existing_docs_url",""), placeholder="https://docs.myproject.dev")
        changelog = st.text_area("Recent changelog / release notes (optional)", value=st.session_state.intake.get("changelog",""), height=80, placeholder="v1.4.2 — Added retry logic…")
        special_instructions = st.text_area(
            "Special instructions for DocAgent (optional)",
            value=st.session_state.intake.get("special_instructions",""),
            height=90,
            placeholder="Focus on async API.\nInclude migration guide from v1 → v2.\nAvoid mentioning legacy endpoints…",
        )

        prev_clicked, next_clicked = nav()

    if prev_clicked: st.session_state.step = 3; st.rerun()
    if next_clicked:
        save("tone", tone); save("code_style", code_style)
        save("include_diagrams", include_diagrams); save("include_admonitions", include_admonitions)
        save("existing_docs_url", existing_docs_url.strip())
        save("changelog", changelog.strip()); save("special_instructions", special_instructions.strip())
        st.session_state.step = 5; st.rerun()


# ── Step 5: Review & Generate ─────────────────────────────────────────────────
def step5_review() -> None:
    section("🚀", "Review & Generate", "Everything looks good? Hit Generate to start the agent crew.")

    intake = st.session_state.intake

    col1, col2 = st.columns(2)

    with col1:
        sections_list = []
        if intake.get("gen_tutorial"):    sections_list.append("Tutorial + Quickstart")
        if intake.get("gen_howto"):       sections_list.append("How-to Guides")
        if intake.get("gen_reference"):   sections_list.append("API Reference")
        if intake.get("gen_explanation"): sections_list.append("Explanation")
        if intake.get("agent_friendly"):  sections_list.append("llms.txt + Schemas")
        if intake.get("mkdocs"):          sections_list.append("MkDocs Config")

        chips_proj = f'<span class="chip">{intake.get("project_type","")}</span> <span class="chip">{intake.get("license","")}</span>'
        chips_tech = " ".join(f'<span class="chip">{t}</span>' for t in intake.get("tech_stack",[]))
        chips_sec  = " ".join(f'<span class="chip-green">{s}</span>' for s in sections_list)

        st.markdown(
            f"""
            <div class="r-card">
              <div class="r-card-title">Project</div>
              <div class="r-card-body">
                <b>{intake.get('project_name','—')}</b> {intake.get('version','')}
                <br><span style="color:#6B7280;font-size:.85rem">{intake.get('tagline','')}</span>
                <br><br>{chips_proj}
              </div>
            </div>
            <div class="r-card">
              <div class="r-card-title">Tech Stack</div>
              <div class="r-card-body">{chips_tech or '—'}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        st.markdown(
            f"""
            <div class="r-card">
              <div class="r-card-title">Sections to Generate</div>
              <div class="r-card-body">{chips_sec or '—'}</div>
            </div>
            <div class="r-card">
              <div class="r-card-title">Audience & Style</div>
              <div class="r-card-body">
                <b>Audience:</b> {', '.join(intake.get('primary_audience',[]))}<br>
                <b>Level:</b> {intake.get('skill_level','—')}<br>
                <b>Tone:</b> {intake.get('tone','—')}<br>
                <b>Source:</b> {intake.get('source_type','—')}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")
    left, _, right = st.columns([1, 4, 1])
    if left.button("← Back", use_container_width=True):
        st.session_state.step = 4; st.rerun()
    if right.button("Generate Documentation", type="primary", use_container_width=True,
                    disabled=st.session_state.running):
        _run_crew()


# ── Crew runner ───────────────────────────────────────────────────────────────
def _run_crew() -> None:
    st.session_state.running = True
    provider_id = st.session_state.get("provider_id", "groq")
    bar = st.progress(0, text="Initialising DocAgent crew…")
    try:
        from crew.doc_crew import DocCrew  # type: ignore
        bar.progress(10, text="Crew assembled — analysing intake…")
        crew_instance = DocCrew(intake=st.session_state.intake, provider_id=provider_id)
        bar.progress(20, text="Researching codebase…")
        result = crew_instance.run()
        bar.progress(90, text="Assembling output files…")
        st.session_state.crew_output = result
        st.session_state.export_files = result.get("files", {})
        bar.progress(100, text="Done!")
        st.session_state.step = 6
        st.session_state.running = False
        st.rerun()
    except ImportError as exc:
        st.error(f"Could not import DocCrew: {exc}")
        st.session_state.running = False
    except Exception as exc:
        st.error(f"Crew run failed: {exc}")
        st.session_state.running = False


# ── Export helpers ────────────────────────────────────────────────────────────
def _build_zip(files: dict, include_mkdocs: bool = False) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    buf.seek(0)
    return buf.read()


def _build_single_md(files: dict, project_name: str) -> bytes:
    parts = [f"# {project_name} — Complete Documentation\n",
             f"*Generated by DocAgent on {datetime.now().strftime('%Y-%m-%d')}*\n\n---\n"]
    md_files = {k: v for k, v in files.items() if k.endswith(".md")}
    for path, content in md_files.items():
        parts.append(f"\n\n---\n<!-- FILE: {path} -->\n\n{content}")
    return "\n".join(parts).encode("utf-8")


def _build_llms_txt(files: dict) -> bytes | None:
    content = files.get("docs/llms.txt") or files.get("llms.txt")
    return content.encode("utf-8") if content else None


def _build_docusaurus_zip(files: dict, project_name: str) -> bytes:
    """Wrap docs in a minimal Docusaurus-compatible structure."""
    buf = io.BytesIO()
    slug = project_name.lower().replace(" ", "-")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, content in files.items():
            if path.endswith(".md"):
                zf.writestr(f"docs/{path}", content)
        docusaurus_cfg = f"""// docusaurus.config.js (minimal)
module.exports = {{
  title: '{project_name}',
  url: 'https://your-site.com',
  baseUrl: '/',
  presets: [['classic', {{ docs: {{ sidebarPath: require.resolve('./sidebars.js') }} }}]],
}};
"""
        zf.writestr("docusaurus.config.js", docusaurus_cfg)
        zf.writestr("README.md", f"# {project_name} Docs\n\nGenerated by DocAgent. Run `npx docusaurus start` to preview.\n")
    buf.seek(0)
    return buf.read()


# ── Step 6: Results & Export ──────────────────────────────────────────────────
def step6_results() -> None:
    files: dict = st.session_state.export_files
    intake = st.session_state.intake
    project_name = intake.get("project_name", "project")
    slug = project_name.lower().replace(" ", "-")

    st.balloons()
    st.markdown(
        f"""
        <div style="background:#D1FAE5;border:1px solid #6EE7B7;border-radius:10px;
                    padding:1rem 1.25rem;margin-bottom:1.5rem;display:flex;align-items:center;gap:.75rem">
          <span style="font-size:1.5rem">✅</span>
          <div>
            <div style="font-weight:700;color:#065F46;font-size:1rem">Documentation generated!</div>
            <div style="color:#047857;font-size:.85rem">{len(files)} files ready to export</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    section("📥", "Export Your Docs", "Choose the format that best fits your workflow.")

    # ── Format descriptions ───────────────────────────────────────────────────
    st.markdown(
        """
        <div class="export-grid">
          <div class="export-card">
            <div class="ec-icon">📦</div>
            <div class="ec-title">ZIP of Markdown files</div>
            <div class="ec-desc">Full structured folder — works with GitHub, GitLab wikis, MkDocs, Nextra, and any static site generator.</div>
          </div>
          <div class="export-card">
            <div class="ec-icon">📄</div>
            <div class="ec-title">Single Markdown file</div>
            <div class="ec-desc">All docs merged into one .md — great for pasting into Notion, Confluence, or sharing with LLMs.</div>
          </div>
          <div class="export-card">
            <div class="ec-icon">🤖</div>
            <div class="ec-title">llms.txt</div>
            <div class="ec-desc">Machine-readable project summary for AI agents (Cursor, Copilot, Claude). Standard llms.txt spec.</div>
          </div>
          <div class="export-card">
            <div class="ec-icon">⚛️</div>
            <div class="ec-title">Docusaurus-ready ZIP</div>
            <div class="ec-desc">Docs wrapped in a Docusaurus v3 scaffold — the most popular docs framework for JS/TS/Python projects.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── Download buttons ──────────────────────────────────────────────────────
    b1, b2, b3, b4 = st.columns(4)

    zip_bytes = _build_zip(files)
    b1.download_button(
        label="📦 Download ZIP",
        data=zip_bytes,
        file_name=f"{slug}-docs.zip",
        mime="application/zip",
        use_container_width=True,
        type="primary",
    )

    single_md = _build_single_md(files, project_name)
    b2.download_button(
        label="📄 Single .md",
        data=single_md,
        file_name=f"{slug}-docs.md",
        mime="text/markdown",
        use_container_width=True,
    )

    llms_txt = _build_llms_txt(files)
    if llms_txt:
        b3.download_button(
            label="🤖 llms.txt",
            data=llms_txt,
            file_name="llms.txt",
            mime="text/plain",
            use_container_width=True,
        )
    else:
        b3.button("🤖 llms.txt", disabled=True, use_container_width=True, help="Not generated (agent_friendly was off)")

    docu_zip = _build_docusaurus_zip(files, project_name)
    b4.download_button(
        label="⚛️ Docusaurus ZIP",
        data=docu_zip,
        file_name=f"{slug}-docusaurus.zip",
        mime="application/zip",
        use_container_width=True,
    )

    # ── File preview ──────────────────────────────────────────────────────────
    st.markdown("---")
    section("👁️", "Preview Files")

    md_files   = {k: v for k, v in files.items() if k.endswith(".md")}
    other_files = {k: v for k, v in files.items() if not k.endswith(".md")}

    preview_files = dict(list(md_files.items())[:6]) | dict(list(other_files.items())[:2])

    if preview_files:
        tab_labels = list(preview_files.keys())
        tabs = st.tabs(tab_labels)
        for tab, (fname, content) in zip(tabs, preview_files.items()):
            with tab:
                if fname.endswith((".md", ".txt")):
                    st.markdown(content)
                elif fname.endswith((".yaml", ".yml")):
                    st.code(content, language="yaml")
                elif fname.endswith(".json"):
                    st.code(content, language="json")
                elif fname.endswith(".ts"):
                    st.code(content, language="typescript")
                else:
                    st.code(content)
    else:
        st.info("No files to preview.")

    st.markdown("---")
    if st.button("Start over — document another project", use_container_width=True):
        for k, v in DEFAULTS.items():
            st.session_state[k] = v
        st.rerun()


# ── Sidebar: LLM provider config ─────────────────────────────────────────────

_PROVIDER_META = {
    "groq": {
        "label": "Groq — DeepSeek R1 + Llama 3.3",
        "key_name": "GROQ_API_KEY",
        "key_placeholder": "gsk_...",
        "signup": "https://console.groq.com",
        "note": "Free · 14,400 req/day · fastest hosted inference",
        "needs_key": True,
        "models": "deepseek-r1-distill-llama-70b · llama-3.3-70b-versatile",
        "badge": "Recommended",
        "badge_color": "#065F46",
        "badge_bg": "#D1FAE5",
    },
    "deepseek": {
        "label": "DeepSeek — V3 + R1",
        "key_name": "DEEPSEEK_API_KEY",
        "key_placeholder": "sk-...",
        "signup": "https://platform.deepseek.com",
        "note": "$5 free credit · best coding & reasoning model",
        "needs_key": True,
        "models": "deepseek-reasoner (R1) · deepseek-chat (V3)",
        "badge": "Best quality",
        "badge_color": "#1E3A5F",
        "badge_bg": "#DBEAFE",
    },
    "mistral": {
        "label": "Mistral AI — open-source models",
        "key_name": "MISTRAL_API_KEY",
        "key_placeholder": "...",
        "signup": "https://console.mistral.ai",
        "note": "Free tier · EU-based · fully open weights",
        "needs_key": True,
        "models": "mistral-small-latest · open-mistral-7b",
        "badge": "Free tier",
        "badge_color": "#92400E",
        "badge_bg": "#FEF3C7",
    },
    "cerebras": {
        "label": "Cerebras — Llama 3.3 70B",
        "key_name": "CEREBRAS_API_KEY",
        "key_placeholder": "csk-...",
        "signup": "https://cloud.cerebras.ai",
        "note": "Free tier · 2,000+ tokens/sec · fastest available",
        "needs_key": True,
        "models": "llama-3.3-70b",
        "badge": "Fastest",
        "badge_color": "#4C1D95",
        "badge_bg": "#EDE9FE",
    },
    "ollama": {
        "label": "Ollama — local, no API key",
        "key_name": None,
        "key_placeholder": None,
        "signup": "https://ollama.com",
        "note": "Zero cost · runs on your machine · full privacy",
        "needs_key": False,
        "models": "deepseek-r1:7b · llama3.2 · mistral · any Ollama model",
        "badge": "No key needed",
        "badge_color": "#065F46",
        "badge_bg": "#D1FAE5",
    },
    "openrouter": {
        "label": "OpenRouter — free :free models",
        "key_name": "OPENROUTER_API_KEY",
        "key_placeholder": "sk-or-...",
        "signup": "https://openrouter.ai",
        "note": "Free DeepSeek R1 + Llama · unified API for 100+ models",
        "needs_key": True,
        "models": "deepseek-r1:free · llama-3.3-70b-instruct:free",
        "badge": "Free models",
        "badge_color": "#1E3A5F",
        "badge_bg": "#DBEAFE",
    },
    "together": {
        "label": "Together AI — $1 free credit",
        "key_name": "TOGETHER_API_KEY",
        "key_placeholder": "...",
        "signup": "https://api.together.ai",
        "note": "$1 free credit · DeepSeek R1 + Llama 3.3 Turbo",
        "needs_key": True,
        "models": "DeepSeek-R1 · Llama-3.3-70B-Instruct-Turbo",
        "badge": "$1 credit",
        "badge_color": "#92400E",
        "badge_bg": "#FEF3C7",
    },
}


_OLLAMA_PRESETS = [
    "deepseek-r1:7b", "deepseek-r1:14b", "deepseek-r1:32b",
    "llama3.2", "llama3.1:8b", "llama3.1:70b",
    "mistral", "mistral-nemo", "mixtral:8x7b",
    "qwen2.5:7b", "qwen2.5-coder:7b",
    "phi4", "gemma3:9b",
    "Custom…",
]


def render_sidebar() -> str:
    """Render the LLM provider picker in the sidebar. Returns selected provider id."""
    with st.sidebar:
        st.markdown("## ⚙️ LLM Provider")
        st.caption("All use free, open-source models.")

        provider_keys = list(_PROVIDER_META.keys())
        default_idx = provider_keys.index("deepseek") if "deepseek" in provider_keys else 0
        provider_id = st.selectbox(
            "Provider",
            provider_keys,
            format_func=lambda k: _PROVIDER_META[k]["label"],
            index=default_idx,
            key="provider_id",
        )

        meta = _PROVIDER_META[provider_id]

        # Badge + info card
        st.markdown(
            f'<div style="background:{meta["badge_bg"]};border-radius:8px;'
            f'padding:.6rem .8rem;font-size:.78rem;color:{meta["badge_color"]};margin:.4rem 0">'
            f'<b>{meta["badge"]}</b> · {meta["note"]}<br>'
            f'<span style="opacity:.8">Models: {meta["models"]}</span></div>',
            unsafe_allow_html=True,
        )

        if meta["needs_key"]:
            existing = os.environ.get(meta["key_name"], "")
            api_key = st.text_input(
                meta["key_name"],
                value=existing,
                type="password",
                placeholder=meta["key_placeholder"],
                help=f"Get a free key at {meta['signup']}",
            )
            if api_key:
                os.environ[meta["key_name"]] = api_key
                st.success("Key active for this session.")
            elif not existing:
                st.markdown(
                    f'<a href="{meta["signup"]}" target="_blank" '
                    f'style="font-size:.8rem;color:#4F46E5;font-weight:600">'
                    f'Get free key →</a>',
                    unsafe_allow_html=True,
                )
        else:
            # Ollama configuration
            ollama_host = st.text_input(
                "Ollama host",
                value=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            )
            os.environ["OLLAMA_HOST"] = ollama_host

            preset = st.selectbox("Model", _OLLAMA_PRESETS, index=0)
            if preset == "Custom…":
                custom = st.text_input("Custom model name", placeholder="my-model:latest")
                model_name = custom or "llama3.2"
            else:
                model_name = preset
            os.environ["DOCAGENT_OLLAMA_MODEL"] = model_name

            # Update the crew provider config for Ollama model choice
            from crew.doc_crew import PROVIDERS  # type: ignore
            PROVIDERS["ollama"].smart_model = f"ollama/{model_name}"
            PROVIDERS["ollama"].fast_model  = f"ollama/{model_name}"

            st.caption(f"Run: `ollama pull {model_name}`")

        os.environ["DOCAGENT_PROVIDER"] = provider_id

        st.markdown("---")

        if st.button("Test connection", use_container_width=True):
            with st.spinner("Pinging model…"):
                try:
                    from crew.doc_crew import test_connection  # type: ignore
                    result = test_connection(provider_id)
                    if result == "ok":
                        st.success("Connected!")
                    else:
                        st.error(f"Failed: {result}")
                except Exception as exc:
                    st.error(str(exc))

        st.markdown(
            '<div style="font-size:.75rem;color:#6B7280;margin-top:.5rem">'
            "Smart model → researcher, strategist, reviewer.<br>"
            "Fast model → writer agents."
            "</div>",
            unsafe_allow_html=True,
        )

    return provider_id


# ── Hero + main layout ────────────────────────────────────────────────────────
def render_hero() -> None:
    st.markdown(
        """
        <div class="hero">
          <h1>📚 DocAgent</h1>
          <p>AI-powered documentation generator &nbsp;·&nbsp; Diátaxis framework &nbsp;·&nbsp;
             Human + Agent ready &nbsp;·&nbsp; Multi-format export</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    render_sidebar()
    render_hero()

    step = st.session_state.step
    if step <= TOTAL_STEPS:
        render_progress()

    {
        1: step1_project,
        2: step2_codebase,
        3: step3_audience,
        4: step4_preferences,
        5: step5_review,
        6: step6_results,
    }.get(step, step1_project)()


if __name__ == "__main__":
    main()
