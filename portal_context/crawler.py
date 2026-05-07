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

    if config.auth_method == "profile" and config.chrome_profile_dir:
        if os.path.exists(config.chrome_profile_dir):
            temp_profile = tempfile.mkdtemp(prefix="portal_ctx_")
            logger.info(f"Copying Chrome profile to: {temp_profile}")
            essential = ["Cookies", "Login Data", "Web Data", "Local State"]
            default_dir = os.path.join(config.chrome_profile_dir, "Default")
            temp_default = os.path.join(temp_profile, "Default")
            os.makedirs(temp_default, exist_ok=True)
            local_state = os.path.join(config.chrome_profile_dir, "Local State")
            if os.path.exists(local_state):
                shutil.copy2(local_state, os.path.join(temp_profile, "Local State"))
            if os.path.exists(default_dir):
                for fn in os.listdir(default_dir):
                    if any(fn.startswith(e) for e in essential):
                        src = os.path.join(default_dir, fn)
                        dst = os.path.join(temp_default, fn)
                        if os.path.isfile(src):
                            shutil.copy2(src, dst)
            kwargs["user_data_dir"] = temp_profile
        else:
            logger.warning(f"Chrome profile not found: {config.chrome_profile_dir}")

    return BrowserConfig(**kwargs)


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
