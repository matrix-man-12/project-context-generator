"""
Phase 1: Page Discovery — Crawl4AI-based portal crawler.

Uses BFS deep crawl to discover all pages within a portal domain.
For each page, captures URL, title, raw HTML, clean markdown, and screenshot.
"""

import asyncio
import base64
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class DiscoveredPage:
    """Represents a single discovered portal page."""
    url: str
    title: str = ""
    raw_html: str = ""
    markdown: str = ""
    screenshot_path: str = ""
    depth: int = 0
    success: bool = True
    error: str = ""


def _slugify(url: str) -> str:
    """Convert URL to a filesystem-safe slug."""
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "_") or "home"
    slug = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in path)
    return slug[:80]


def _extract_title(result) -> str:
    """Extract page title from crawl result."""
    if hasattr(result, 'metadata') and result.metadata:
        title = result.metadata.get("title", "")
        if title:
            return title
    if hasattr(result, 'html') and result.html:
        match = re.search(r"<title[^>]*>(.*?)</title>", result.html, re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()
    return ""


def _extract_markdown(result) -> str:
    """Extract clean markdown from crawl result."""
    if hasattr(result, 'markdown'):
        md = result.markdown
        if hasattr(md, 'fit_markdown') and md.fit_markdown:
            return md.fit_markdown
        if hasattr(md, 'raw_markdown') and md.raw_markdown:
            return md.raw_markdown
        if isinstance(md, str):
            return md
    return ""


def _build_browser_config(config):
    """Build Crawl4AI BrowserConfig based on auth settings."""
    from crawl4ai import BrowserConfig

    kwargs = {"headless": True, "verbose": True}

    if config.auth_method == "cdp" and config.cdp_url:
        # Connect to an already-running Chrome with --remote-debugging-port
        cdp = config.cdp_url
        # Crawl4AI expects a WebSocket URL for CDP
        if cdp.startswith("http://"):
            # Convert http://localhost:9222 → ws://localhost:9222/devtools/browser/
            # We need to fetch the actual WS endpoint from the /json/version API
            cdp_ws = _get_cdp_websocket_url(cdp)
            if cdp_ws:
                cdp = cdp_ws
            else:
                # Fallback: construct ws URL directly
                cdp = cdp.replace("http://", "ws://") + "/devtools/browser/"

        logger.info(f"Connecting to browser via CDP: {cdp}")
        kwargs["use_managed_browser"] = True
        kwargs["cdp_url"] = cdp
        kwargs["headless"] = False  # We're connecting to a visible browser

    elif config.auth_method == "profile" and config.chrome_profile_dir:
        if os.path.exists(config.chrome_profile_dir):
            temp_profile = tempfile.mkdtemp(prefix="portal_ctx_")
            profile_dir = config.chrome_profile_dir

            # Detect if user gave a specific profile dir (e.g. "Profile 5")
            # or the User Data root dir.
            # If "Local State" exists at the given path, it's the User Data root.
            # If "Local State" exists in the PARENT, user gave a specific profile.
            local_state_here = os.path.join(profile_dir, "Local State")
            local_state_parent = os.path.join(os.path.dirname(profile_dir), "Local State")

            if os.path.exists(local_state_here):
                # User gave User Data root — copy "Default" profile
                user_data_dir = profile_dir
                src_profile = os.path.join(profile_dir, "Default")
                dst_profile = os.path.join(temp_profile, "Default")
            elif os.path.exists(local_state_parent):
                # User gave a specific profile dir like "Profile 5"
                user_data_dir = os.path.dirname(profile_dir)
                profile_name = os.path.basename(profile_dir)
                src_profile = profile_dir
                dst_profile = os.path.join(temp_profile, profile_name)
                # Chromium needs to know which profile to use
                kwargs["chrome_channel"] = profile_name
            else:
                # Fallback: treat whatever they gave as the profile source
                user_data_dir = os.path.dirname(profile_dir)
                src_profile = profile_dir
                dst_profile = os.path.join(temp_profile, os.path.basename(profile_dir))

            logger.info(f"Copying profile from: {src_profile}")
            logger.info(f"Temp user data dir: {temp_profile}")

            if os.path.exists(src_profile):
                shutil.copytree(src_profile, dst_profile, dirs_exist_ok=True,
                                ignore=shutil.ignore_patterns(
                                    "Cache", "Code Cache", "GPUCache",
                                    "Service Worker", "CacheStorage",
                                    "blob_storage", "IndexedDB"))

            # Copy Local State (required by Chromium)
            ls_src = os.path.join(user_data_dir, "Local State")
            ls_dst = os.path.join(temp_profile, "Local State")
            if os.path.exists(ls_src):
                shutil.copy2(ls_src, ls_dst)

            kwargs["user_data_dir"] = temp_profile
            kwargs["use_persistent_context"] = True
        else:
            logger.warning(f"Chrome profile not found: {config.chrome_profile_dir}")

    return BrowserConfig(**kwargs)


def _get_cdp_websocket_url(http_url: str) -> str | None:
    """Fetch the actual WebSocket debugger URL from Chrome's /json/version endpoint."""
    import urllib.request
    import json
    try:
        version_url = http_url.rstrip("/") + "/json/version"
        with urllib.request.urlopen(version_url, timeout=5) as resp:
            data = json.loads(resp.read())
            ws_url = data.get("webSocketDebuggerUrl", "")
            if ws_url:
                logger.info(f"Got CDP WebSocket URL: {ws_url}")
                return ws_url
    except Exception as e:
        logger.warning(f"Could not fetch CDP WebSocket URL from {http_url}: {e}")
    return None


async def discover_pages(config) -> list[DiscoveredPage]:
    """
    Phase 1: Discover all pages within the portal using BFS deep crawl.
    """
    from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
    from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
    from crawl4ai.content_scraping_strategy import LXMLWebScrapingStrategy
    from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
    from crawl4ai.content_filter_strategy import PruningContentFilter

    logger.info(f"Phase 1: Discovering pages at {config.portal_url}")

    browser_config = _build_browser_config(config)
    crawl_strategy = BFSDeepCrawlStrategy(
        max_depth=config.max_depth, include_external=False, max_pages=config.max_pages,
    )
    md_generator = DefaultMarkdownGenerator(
        content_filter=PruningContentFilter(threshold=0.4),
        options={"ignore_links": False},
    )
    run_config = CrawlerRunConfig(
        deep_crawl_strategy=crawl_strategy,
        scraping_strategy=LXMLWebScrapingStrategy(),
        markdown_generator=md_generator,
        screenshot=config.capture_screenshots,
        scan_full_page=True, remove_overlay_elements=True,
        simulate_user=True, verbose=True, page_timeout=30000,
    )

    screenshots_dir = Path(config.output_dir) / config.portal_name / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    pages: list[DiscoveredPage] = []

    async with AsyncWebCrawler(config=browser_config) as crawler:
        results = await crawler.arun(config.portal_url, config=run_config)
        if not isinstance(results, list):
            results = [results]

        for i, r in enumerate(results):
            page = DiscoveredPage(
                url=r.url,
                title=_extract_title(r),
                raw_html=getattr(r, 'html', ''),
                markdown=_extract_markdown(r),
                depth=r.metadata.get("depth", 0) if hasattr(r, 'metadata') and r.metadata else 0,
                success=getattr(r, 'success', True),
                error=getattr(r, 'error_message', ''),
            )
            if config.capture_screenshots and hasattr(r, 'screenshot') and r.screenshot:
                ss_path = screenshots_dir / f"page_{i:03d}_{_slugify(page.url)}.png"
                try:
                    ss_path.write_bytes(base64.b64decode(r.screenshot))
                    page.screenshot_path = str(ss_path)
                except Exception as e:
                    logger.warning(f"Screenshot save failed for {page.url}: {e}")
            pages.append(page)
            logger.info(f"  Found: {page.url} (depth={page.depth})")

    logger.info(f"Phase 1 complete: {len(pages)} pages discovered")
    return pages
