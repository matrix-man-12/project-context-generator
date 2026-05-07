"""
Writer — Generates the output folder structure with markdown files.

Creates portal_overview.md, portal_manifest.md, pages/*.md,
processes/*.md, and portal_context.md (consolidated).
"""

import logging
import re
from datetime import datetime
from pathlib import Path

from portal_context.synthesizer import PortalSynthesis

logger = logging.getLogger(__name__)


def write_output(config, synthesis: PortalSynthesis) -> str:
    """
    Write all output files to the configured output directory.
    
    Returns:
        Path to the output directory
    """
    output_dir = Path(config.output_dir) / config.portal_name
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(f"Writing output to: {output_dir}")

    # Write portal_overview.md
    _write_overview(output_dir, config, synthesis)

    # Write portal_manifest.md
    _write_manifest(output_dir, synthesis)

    # Write pages/*.md
    _write_pages(output_dir, synthesis)

    # Write processes/*.md
    _write_processes(output_dir, synthesis)

    # Write portal_context.md (consolidated)
    _write_consolidated(output_dir, config, synthesis)

    logger.info(f"Output complete: {output_dir}")
    return str(output_dir)


def _write_overview(output_dir: Path, config, synthesis: PortalSynthesis):
    """Write portal_overview.md — human-readable overview."""
    content = f"""# Portal: {config.portal_name}

> **URL**: {config.portal_url}  
> **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}  
> **Pages Analyzed**: {len(synthesis.page_analyses)}

{synthesis.overview}
"""
    (output_dir / "portal_overview.md").write_text(content, encoding="utf-8")
    logger.info("  ✓ portal_overview.md")


def _write_manifest(output_dir: Path, synthesis: PortalSynthesis):
    """Write portal_manifest.md — machine-readable page index."""
    (output_dir / "portal_manifest.md").write_text(synthesis.manifest, encoding="utf-8")
    logger.info("  ✓ portal_manifest.md")


def _write_pages(output_dir: Path, synthesis: PortalSynthesis):
    """Write individual page analysis files."""
    pages_dir = output_dir / "pages"
    pages_dir.mkdir(exist_ok=True)

    for i, page in enumerate(synthesis.page_analyses):
        filename = _make_filename(page.title or page.url, i)
        content = f"""# Page: {page.title or page.url}

- **URL**: {page.url}

{page.llm_analysis}
"""
        (pages_dir / filename).write_text(content, encoding="utf-8")

    logger.info(f"  ✓ pages/ ({len(synthesis.page_analyses)} files)")


def _write_processes(output_dir: Path, synthesis: PortalSynthesis):
    """Write process documentation."""
    processes_dir = output_dir / "processes"
    processes_dir.mkdir(exist_ok=True)

    if synthesis.processes:
        # Split processes into separate files if there are clear process headers
        process_sections = _split_processes(synthesis.processes)
        
        if len(process_sections) > 1:
            for i, (name, content) in enumerate(process_sections):
                filename = _make_filename(name, i)
                full_content = f"""# Process: {name}

> **Portal**: {synthesis.portal_name}

{content}
"""
                (processes_dir / filename).write_text(full_content, encoding="utf-8")
        else:
            # Write as a single file
            content = f"""# Portal Processes: {synthesis.portal_name}

{synthesis.processes}
"""
            (processes_dir / "all_processes.md").write_text(content, encoding="utf-8")

    logger.info(f"  ✓ processes/")


def _write_consolidated(output_dir: Path, config, synthesis: PortalSynthesis):
    """Write portal_context.md — everything in one file."""
    sections = [
        f"# Portal Context: {config.portal_name}",
        f"",
        f"> **URL**: {config.portal_url}  ",
        f"> **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"> **Pages Analyzed**: {len(synthesis.page_analyses)}",
        f"",
        f"---",
        f"",
        f"## Overview",
        f"",
        synthesis.overview,
        f"",
        f"---",
        f"",
        f"## Pages",
        f"",
    ]

    for page in synthesis.page_analyses:
        sections.append(f"### {page.title or page.url}")
        sections.append(f"**URL**: {page.url}")
        sections.append("")
        sections.append(page.llm_analysis)
        sections.append("")
        sections.append("---")
        sections.append("")

    sections.extend([
        "## Processes",
        "",
        synthesis.processes,
        "",
        "---",
        "",
        "## Manifest",
        "",
        synthesis.manifest,
    ])

    content = "\n".join(sections)
    (output_dir / "portal_context.md").write_text(content, encoding="utf-8")
    logger.info("  ✓ portal_context.md")


def _split_processes(text: str) -> list[tuple[str, str]]:
    """Split process text into named sections."""
    # Look for markdown headers that indicate process boundaries
    pattern = r"(?:^|\n)##\s+(?:Process:?\s*)?(.+?)(?:\n)"
    matches = list(re.finditer(pattern, text))

    if len(matches) < 2:
        return [("All Processes", text)]

    sections = []
    for i, match in enumerate(matches):
        name = match.group(1).strip()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((name, text[start:end].strip()))

    return sections


def _make_filename(text: str, index: int) -> str:
    """Create a safe markdown filename from text."""
    # Clean the text
    slug = text.lower().strip()
    slug = re.sub(r'https?://[^\s]+', '', slug)  # Remove URLs
    slug = re.sub(r'[^\w\s-]', '', slug)           # Remove special chars
    slug = re.sub(r'\s+', '_', slug)                # Spaces to underscores
    slug = slug.strip('_')[:60]                     # Limit length
    
    if not slug:
        slug = f"page_{index:03d}"
    
    return f"{slug}.md"
