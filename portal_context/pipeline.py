"""
Pipeline — Orchestrates the three-phase portal context generation.

Phase 1: Page Discovery (Crawl4AI BFS)
Phase 2: UI Exploration (Dynamic element interaction)
Phase 3: LLM Synthesis (Context documentation generation)
"""

import asyncio
import logging

from portal_context.config import PortalConfig
from portal_context.crawler import discover_pages
from portal_context.doc_parser import parse_documents
from portal_context.llm_provider import create_provider
from portal_context.synthesizer import synthesize_portal_context
from portal_context.ui_analyzer import analyze_page_ui
from portal_context.ui_explorer import explore_page_ui
from portal_context.writer import write_output

logger = logging.getLogger(__name__)


async def run_pipeline(config: PortalConfig, progress_callback=None) -> str:
    """
    Run the full three-phase portal context generation pipeline.
    
    Args:
        config: PortalConfig with all settings
        progress_callback: Optional callable(phase, message, progress_pct)
        
    Returns:
        Path to output directory
    """
    def _progress(phase: str, msg: str, pct: float = 0):
        logger.info(f"[{phase}] {msg}")
        if progress_callback:
            progress_callback(phase, msg, pct)

    # Validate config
    errors = config.validate()
    if errors:
        raise ValueError(f"Invalid configuration:\n" + "\n".join(f"  - {e}" for e in errors))

    # Initialize LLM provider
    llm = create_provider(config)

    try:
        # ── Phase 1: Page Discovery ──────────────────────────────
        _progress("Phase 1", "Discovering portal pages...", 0.0)
        pages = await discover_pages(config)
        _progress("Phase 1", f"Found {len(pages)} pages", 0.3)

        if not pages:
            raise RuntimeError("No pages discovered. Check URL and authentication settings.")

        # ── Phase 2: UI Exploration ──────────────────────────────
        _progress("Phase 2", "Exploring dynamic UI elements...", 0.3)
        explorations = {}
        for i, page in enumerate(pages):
            if not page.success:
                continue
            _progress("Phase 2", f"Exploring page {i+1}/{len(pages)}: {page.url}",
                      0.3 + (0.3 * i / max(len(pages), 1)))
            try:
                exploration = await explore_page_ui(page.url, config, i)
                explorations[page.url] = exploration
            except Exception as e:
                logger.warning(f"UI exploration failed for {page.url}: {e}")

        _progress("Phase 2", f"UI exploration complete for {len(explorations)} pages", 0.6)

        # ── Analyze UI Structure ─────────────────────────────────
        page_analyses = []
        page_markdowns = {}
        dynamic_states_map = {}

        for page in pages:
            if not page.success:
                continue
            # Use exploration HTML if available (has more states), else use crawl HTML
            html = page.raw_html
            if page.url in explorations:
                html = explorations[page.url].initial_html or html

            analysis = analyze_page_ui(html, url=page.url, title=page.title)
            page_analyses.append(analysis)
            page_markdowns[page.url] = page.markdown

            # Collect dynamic states
            if page.url in explorations:
                exp = explorations[page.url]
                dynamic_states_map[page.url] = [
                    {
                        "trigger_label": s.trigger_label,
                        "trigger_type": s.trigger_type,
                        "trigger_action": s.trigger_action,
                    }
                    for s in exp.ui_states
                ]

        # ── Parse supplementary documents ────────────────────────
        doc_text = ""
        if config.doc_paths:
            _progress("Phase 2.5", "Parsing supplementary documents...", 0.62)
            doc_text = parse_documents(config.doc_paths)

        # ── Phase 3: LLM Synthesis ───────────────────────────────
        _progress("Phase 3", "Generating context documentation with LLM...", 0.65)
        synthesis = await synthesize_portal_context(
            config=config,
            llm_provider=llm,
            page_analyses=page_analyses,
            dynamic_states=dynamic_states_map,
            page_markdowns=page_markdowns,
            doc_text=doc_text,
        )

        # ── Write Output ─────────────────────────────────────────
        _progress("Output", "Writing documentation files...", 0.95)
        output_path = write_output(config, synthesis)

        _progress("Done", f"Complete! Output at: {output_path}", 1.0)
        return output_path

    finally:
        await llm.close()
