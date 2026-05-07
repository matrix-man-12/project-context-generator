"""
Phase 3: LLM Synthesis — Generates context documentation from UI analysis.

Uses LLM to understand pages, discover processes, generate overview,
and merge user-provided context.
"""

import logging
from dataclasses import dataclass, field

from portal_context.ui_analyzer import PageUIAnalysis

logger = logging.getLogger(__name__)


# ── Prompt templates ────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a portal documentation specialist. You analyze internal web portal UIs and generate clear, structured documentation about what the portal does and how to use it.

CRITICAL RULES:
- Do NOT expand abbreviations unless the portal itself shows the expansion (in tooltips, help text, labels, or a glossary)
- Preserve all internal terminology exactly as shown in the portal
- Focus on OPERATIONS and UI STRUCTURE, never on data content
- Be concise and accurate
- Use markdown formatting"""

PAGE_UNDERSTANDING_PROMPT = """Analyze this portal page and describe what it does.

**Page URL**: {url}
**Page Title**: {title}

**Navigation Items**: {navigation}
**Breadcrumbs**: {breadcrumbs}
**Sections/Headings**: {sections}
**Tabs**: {tabs}

**Forms**:
{forms}

**Action Buttons**: {buttons}

**Table Columns** (reveals entity structure): {tables}

**Dynamic UI States** (elements that appear/disappear on interaction):
{dynamic_states}

**Page Markdown Content**:
{markdown_excerpt}

---

Provide the following in markdown:
1. **Purpose**: What is this page for? (1-2 sentences)
2. **Operations**: What can a user do on this page?
3. **Entities**: What data entities does this page manage?
4. **Forms**: Describe each form and its fields
5. **Dynamic Behavior**: Any UI that changes based on user interaction
6. **Navigation Context**: Where does this page sit in the portal structure?"""


PORTAL_OVERVIEW_PROMPT = """Based on all analyzed pages of this portal, write a high-level overview.

**Portal URL**: {portal_url}
**Portal Name**: {portal_name}

**All Pages Analyzed**:
{page_summaries}

**User-Provided Notes**:
{user_notes}

**User-Provided Documentation Summary**:
{doc_summary}

---

Write a portal overview in markdown with these sections:
1. **What This Portal Is** — One paragraph explanation
2. **What It Does** — Bullet list of capabilities
3. **Key Entities** — What data entities the portal manages
4. **Portal Sections** — Table of sections and their purposes
5. **Internal Terminology** — Table of abbreviations/terms found (DO NOT expand unless the portal shows the expansion)"""


PROCESS_DISCOVERY_PROMPT = """Based on all analyzed pages with their UI elements and dynamic states, identify the distinct end-to-end processes a user can complete.

**Portal**: {portal_name}

**All Pages With Their Operations**:
{page_details}

---

For each process, provide in markdown:
1. **Process Name** — A clear, descriptive name
2. **Task** — What this process accomplishes (one sentence)
3. **Steps** — Sequential steps:
   - Which page to go to
   - What action to take
   - What result to expect
4. **Conditional Branches** — Any if/then logic
5. **Alternative Flows** — Other ways to complete the same task"""


@dataclass
class PageSynthesis:
    """LLM-generated understanding of a single page."""
    url: str = ""
    title: str = ""
    llm_analysis: str = ""


@dataclass
class PortalSynthesis:
    """Complete LLM-generated portal context."""
    portal_name: str = ""
    portal_url: str = ""
    overview: str = ""
    page_analyses: list[PageSynthesis] = field(default_factory=list)
    processes: str = ""
    manifest: str = ""


async def synthesize_portal_context(
    config,
    llm_provider,
    page_analyses: list[PageUIAnalysis],
    dynamic_states: dict[str, list],
    page_markdowns: dict[str, str],
    doc_text: str = "",
) -> PortalSynthesis:
    """
    Phase 3: Use LLM to generate complete portal context documentation.
    """
    logger.info("Phase 3: Synthesizing portal context with LLM")
    synthesis = PortalSynthesis(
        portal_name=config.portal_name,
        portal_url=config.portal_url,
    )

    # Pass 1: Page Understanding
    logger.info("  Pass 1: Analyzing individual pages...")
    for i, page in enumerate(page_analyses):
        logger.info(f"    Analyzing page {i+1}/{len(page_analyses)}: {page.url}")
        try:
            page_result = await _analyze_single_page(
                llm_provider, page,
                dynamic_states.get(page.url, []),
                page_markdowns.get(page.url, ""),
            )
            synthesis.page_analyses.append(page_result)
        except Exception as e:
            logger.error(f"    Failed to analyze {page.url}: {e}")
            synthesis.page_analyses.append(PageSynthesis(
                url=page.url, title=page.title,
                llm_analysis=f"*Analysis failed: {e}*"
            ))

    # Pass 2: Portal Overview
    logger.info("  Pass 2: Generating portal overview...")
    try:
        synthesis.overview = await _generate_overview(
            llm_provider, config, synthesis.page_analyses,
            config.user_notes, doc_text,
        )
    except Exception as e:
        logger.error(f"  Overview generation failed: {e}")
        synthesis.overview = f"*Overview generation failed: {e}*"

    # Pass 3: Process Discovery
    logger.info("  Pass 3: Discovering processes...")
    try:
        synthesis.processes = await _discover_processes(
            llm_provider, config, synthesis.page_analyses,
        )
    except Exception as e:
        logger.error(f"  Process discovery failed: {e}")
        synthesis.processes = f"*Process discovery failed: {e}*"

    # Generate manifest
    synthesis.manifest = _generate_manifest(config, page_analyses, synthesis)

    logger.info("Phase 3 complete")
    return synthesis


async def _analyze_single_page(
    llm, page: PageUIAnalysis, states: list, markdown: str
) -> PageSynthesis:
    """Pass 1: Analyze a single page."""
    # Format form info
    forms_text = ""
    for form in page.forms:
        forms_text += f"\n  Form: {form.form_name or form.form_id or '(unnamed)'}\n"
        for f in form.fields:
            req = " (required)" if f.required else ""
            opts = f" — Options: {', '.join(f.options[:10])}" if f.options else ""
            forms_text += f"    - {f.label or f.name}: {f.field_type}{req}{opts}\n"

    # Format dynamic states
    states_text = ""
    for state in states:
        states_text += f"\n  - Trigger: {state.get('trigger_label', '')} ({state.get('trigger_type', '')})"
        states_text += f"\n    Action: {state.get('trigger_action', 'click')}\n"

    prompt = PAGE_UNDERSTANDING_PROMPT.format(
        url=page.url,
        title=page.title,
        navigation=", ".join(n.text for n in page.navigation[:20]),
        breadcrumbs=" → ".join(page.breadcrumbs),
        sections=", ".join(page.sections[:15]),
        tabs=", ".join(page.tabs) if page.tabs else "None",
        forms=forms_text or "None",
        buttons=", ".join(b.text for b in page.action_buttons[:15]),
        tables=str(page.table_headers[:5]) if page.table_headers else "None",
        dynamic_states=states_text or "None observed",
        markdown_excerpt=markdown[:3000] if markdown else "(not available)",
    )

    result = await llm.generate(prompt, system_prompt=SYSTEM_PROMPT)
    return PageSynthesis(url=page.url, title=page.title, llm_analysis=result)


async def _generate_overview(llm, config, pages, user_notes, doc_text):
    """Pass 2: Generate portal overview."""
    summaries = ""
    for p in pages:
        summaries += f"\n### {p.title or p.url}\n{p.llm_analysis[:500]}\n"

    prompt = PORTAL_OVERVIEW_PROMPT.format(
        portal_url=config.portal_url,
        portal_name=config.portal_name,
        page_summaries=summaries,
        user_notes=user_notes or "(none provided)",
        doc_summary=doc_text[:3000] if doc_text else "(none provided)",
    )
    return await llm.generate(prompt, system_prompt=SYSTEM_PROMPT)


async def _discover_processes(llm, config, pages):
    """Pass 3: Discover processes from page analyses."""
    details = ""
    for p in pages:
        details += f"\n### {p.title or p.url}\n{p.llm_analysis[:800]}\n"

    prompt = PROCESS_DISCOVERY_PROMPT.format(
        portal_name=config.portal_name,
        page_details=details,
    )
    return await llm.generate(prompt, system_prompt=SYSTEM_PROMPT)


def _generate_manifest(config, page_analyses, synthesis) -> str:
    """Generate a machine-readable portal manifest."""
    lines = [
        f"# Portal Manifest: {config.portal_name}",
        f"",
        f"> **URL**: {config.portal_url}",
        f"> **Pages**: {len(page_analyses)}",
        f"",
        f"## Page Index",
        f"",
        f"| # | URL | Title | Forms | Buttons | Tables |",
        f"|---|-----|-------|-------|---------|--------|",
    ]
    for i, page in enumerate(page_analyses, 1):
        lines.append(
            f"| {i} | {page.url} | {page.title} | "
            f"{len(page.forms)} | {len(page.action_buttons)} | "
            f"{len(page.table_headers)} |"
        )
    return "\n".join(lines)
