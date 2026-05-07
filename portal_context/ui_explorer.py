"""
Phase 2: Dynamic UI Exploration.

Interacts with portal pages to discover dynamic UI states —
clicks dropdowns, tabs, accordions, and captures what appears/disappears.
"""

import asyncio
import base64
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


# JavaScript to discover interactive elements on a page
DISCOVER_INTERACTIVES_JS = """
(() => {
    function uniqueSelector(el) {
        if (el.id) return '#' + el.id;
        if (el.name) return `[name="${el.name}"]`;
        const tag = el.tagName.toLowerCase();
        const parent = el.parentElement;
        if (!parent) return tag;
        const siblings = [...parent.children].filter(c => c.tagName === el.tagName);
        if (siblings.length === 1) return uniqueSelector(parent) + ' > ' + tag;
        const idx = siblings.indexOf(el) + 1;
        return uniqueSelector(parent) + ` > ${tag}:nth-of-type(${idx})`;
    }

    function getLabel(el) {
        if (el.labels && el.labels.length > 0) return el.labels[0].textContent.trim();
        const ariaLabel = el.getAttribute('aria-label');
        if (ariaLabel) return ariaLabel;
        const prev = el.previousElementSibling;
        if (prev && prev.tagName === 'LABEL') return prev.textContent.trim();
        const placeholder = el.getAttribute('placeholder');
        if (placeholder) return placeholder;
        return el.textContent?.trim().substring(0, 50) || '';
    }

    const interactives = [];

    // Dropdowns (<select> and custom)
    document.querySelectorAll('select, [role="listbox"], [data-toggle="dropdown"], .dropdown-toggle')
        .forEach(el => {
            const options = el.tagName === 'SELECT'
                ? [...el.options].map(o => ({value: o.value, text: o.text}))
                : [];
            interactives.push({
                type: 'dropdown', selector: uniqueSelector(el),
                label: getLabel(el), options: options
            });
        });

    // Tabs
    document.querySelectorAll('[role="tab"], .nav-tab, .tab-item, .nav-link[data-toggle="tab"]')
        .forEach(el => interactives.push({
            type: 'tab', selector: uniqueSelector(el),
            label: el.textContent.trim().substring(0, 80),
            active: el.classList.contains('active') || el.getAttribute('aria-selected') === 'true'
        }));

    // Accordions / Expandables
    document.querySelectorAll('[data-toggle="collapse"], .accordion-header, .accordion-button, details > summary, [aria-expanded]')
        .forEach(el => {
            if (el.getAttribute('role') === 'tab') return; // Already captured as tab
            interactives.push({
                type: 'accordion', selector: uniqueSelector(el),
                label: el.textContent.trim().substring(0, 80),
                expanded: el.getAttribute('aria-expanded') === 'true'
            });
        });

    // Modal triggers
    document.querySelectorAll('[data-toggle="modal"], [data-bs-toggle="modal"], [aria-haspopup="dialog"]')
        .forEach(el => interactives.push({
            type: 'modal_trigger', selector: uniqueSelector(el),
            label: el.textContent.trim().substring(0, 80)
        }));

    // Radio/checkbox groups that might toggle UI
    document.querySelectorAll('input[type="radio"], input[type="checkbox"]')
        .forEach(el => {
            if (el.hasAttribute('data-toggle') || el.closest('[data-toggle]')) {
                interactives.push({
                    type: 'toggle', selector: uniqueSelector(el),
                    label: getLabel(el), checked: el.checked
                });
            }
        });

    return JSON.stringify(interactives);
})();
"""


@dataclass
class UIState:
    """A captured UI state after interacting with an element."""
    trigger_element: str = ""
    trigger_type: str = ""
    trigger_label: str = ""
    trigger_action: str = ""
    html_snapshot: str = ""
    screenshot_path: str = ""
    revealed_elements: list[str] = field(default_factory=list)


@dataclass
class PageExploration:
    """Complete UI exploration result for a single page."""
    url: str
    initial_html: str = ""
    initial_screenshot: str = ""
    interactive_elements: list[dict] = field(default_factory=list)
    ui_states: list[UIState] = field(default_factory=list)


async def explore_page_ui(page_url: str, config, page_index: int = 0) -> PageExploration:
    """
    Phase 2: Explore dynamic UI states on a single portal page.

    Uses Crawl4AI sessions to interact with dropdowns, tabs, accordions
    and capture the resulting DOM changes.
    """
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    logger.info(f"Phase 2: Exploring UI on {page_url}")
    exploration = PageExploration(url=page_url)

    browser_config = BrowserConfig(headless=True, verbose=False)
    session_id = f"explore_{page_index}"

    screenshots_dir = Path(config.output_dir) / config.portal_name / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        # Step 1: Load page and capture initial state
        initial_config = CrawlerRunConfig(
            session_id=session_id,
            screenshot=True,
            scan_full_page=True,
            page_timeout=30000,
            js_code=[DISCOVER_INTERACTIVES_JS],
        )

        result = await crawler.arun(page_url, config=initial_config)
        if not getattr(result, 'success', False):
            logger.warning(f"Failed to load {page_url}: {getattr(result, 'error_message', 'unknown')}")
            return exploration

        exploration.initial_html = getattr(result, 'html', '')

        # Save initial screenshot
        if hasattr(result, 'screenshot') and result.screenshot:
            ss_path = screenshots_dir / f"explore_{page_index:03d}_initial.png"
            ss_path.write_bytes(base64.b64decode(result.screenshot))
            exploration.initial_screenshot = str(ss_path)

        # Parse discovered interactive elements
        try:
            js_result = getattr(result, 'script_result', None) or getattr(result, 'js_result', None)
            if js_result:
                exploration.interactive_elements = json.loads(js_result)
            else:
                # Fallback: try to extract from extracted_content
                extracted = getattr(result, 'extracted_content', '')
                if extracted and extracted.startswith('['):
                    exploration.interactive_elements = json.loads(extracted)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Could not parse interactive elements for {page_url}")

        if not exploration.interactive_elements:
            logger.info(f"  No interactive elements found on {page_url}")
            return exploration

        logger.info(f"  Found {len(exploration.interactive_elements)} interactive elements")

        # Step 2: Interact with each element (limited)
        max_interactions = min(len(exploration.interactive_elements), config.max_interactions_per_page)

        for idx, element in enumerate(exploration.interactive_elements[:max_interactions]):
            try:
                state = await _interact_with_element(
                    crawler, session_id, page_url, element, idx, page_index,
                    screenshots_dir, config.interaction_timeout,
                )
                if state:
                    exploration.ui_states.append(state)
            except Exception as e:
                logger.warning(f"  Interaction {idx} failed: {e}")

            # Reset page state by reloading
            try:
                reset_config = CrawlerRunConfig(
                    session_id=session_id, page_timeout=15000,
                )
                await crawler.arun(page_url, config=reset_config)
            except Exception:
                pass

    logger.info(f"  UI exploration complete: {len(exploration.ui_states)} states captured")
    return exploration


async def _interact_with_element(
    crawler, session_id, page_url, element, idx, page_index,
    screenshots_dir, timeout
) -> UIState | None:
    """Interact with a single UI element and capture the resulting state."""
    from crawl4ai import CrawlerRunConfig

    el_type = element.get("type", "")
    selector = element.get("selector", "")
    label = element.get("label", "")

    if not selector:
        return None

    logger.info(f"    Interacting with {el_type}: {label}")

    # Build JS to click/interact with the element
    if el_type == "dropdown" and element.get("options"):
        # For <select>, we select the first non-empty option
        js_code = f"""
        (() => {{
            const el = document.querySelector('{selector}');
            if (el && el.tagName === 'SELECT') {{
                el.selectedIndex = Math.min(1, el.options.length - 1);
                el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            }} else if (el) {{
                el.click();
            }}
        }})();
        """
    else:
        js_code = f"""
        (() => {{
            const el = document.querySelector('{selector}');
            if (el) el.click();
        }})();
        """

    interact_config = CrawlerRunConfig(
        session_id=session_id,
        js_only=True,
        js_code=[js_code],
        delay_before_return_html=1.5,
        screenshot=True,
        page_timeout=timeout * 1000,
    )

    result = await crawler.arun(page_url, config=interact_config)

    state = UIState(
        trigger_element=selector,
        trigger_type=el_type,
        trigger_label=label,
        trigger_action="click" if el_type != "dropdown" else "select",
        html_snapshot=getattr(result, 'html', ''),
    )

    # Save screenshot
    if hasattr(result, 'screenshot') and result.screenshot:
        ss_name = f"explore_{page_index:03d}_interact_{idx:02d}_{el_type}.png"
        ss_path = screenshots_dir / ss_name
        ss_path.write_bytes(base64.b64decode(result.screenshot))
        state.screenshot_path = str(ss_path)

    return state
