# Portal Context Generator — Implementation Walkthrough

> **Date**: 2026-05-07  
> **Status**: Core implementation complete, ready for end-to-end testing

---

## What Was Built

A self-contained Python utility that generates structured portal context documentation from any internal portal URL. The tool crawls portal pages, interacts with dynamic UI elements, and uses an LLM to synthesize human- and machine-readable documentation.

### Project Structure

```
Portal-Context/
├── cli.py                          # Command-line interface
├── app.py                          # Streamlit web UI
├── portal_context/                 # Core library
│   ├── __init__.py                 # Package init (v0.1.0)
│   ├── config.py                   # Configuration dataclass
│   ├── llm_provider.py             # LLM abstraction layer
│   ├── crawler.py                  # Phase 1: Page Discovery
│   ├── ui_explorer.py              # Phase 2: Dynamic UI Exploration
│   ├── ui_analyzer.py              # Phase 3 pre-processing: HTML parsing
│   ├── synthesizer.py              # Phase 3: LLM Context Generation
│   ├── doc_parser.py               # Supplementary document parsing
│   ├── writer.py                   # Markdown output writer
│   └── pipeline.py                 # Pipeline orchestrator
├── docs/                           # Documentation
│   ├── implementation_plan.md      # Technical design (v3.2)
│   ├── llm_integration_guide.md    # Custom LLM setup guide
│   └── walkthrough.md              # This file
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Architecture: Three-Phase Pipeline

```
Portal URL ──► Phase 1: Discover ──► Phase 2: Explore ──► Phase 3: Synthesize ──► Markdown Output
                 (Crawl4AI BFS)      (Playwright/JS)         (LLM)
```

### Phase 1 — Page Discovery (`crawler.py`)

**What it does**: Uses Crawl4AI's BFS deep crawl to find all pages within the portal domain.

**Key implementation details**:
- `BFSDeepCrawlStrategy` with `include_external=False` keeps crawl within the portal
- `LXMLWebScrapingStrategy` for fast HTML parsing
- `PruningContentFilter` removes boilerplate content from markdown output
- Screenshots captured via `screenshot=True` and saved as base64-decoded PNGs
- Browser profile copy for authentication: copies essential Chrome profile files (Cookies, Login Data) to a temp directory to avoid the Chrome profile lock conflict

**Input**: Portal URL + config  
**Output**: `list[DiscoveredPage]` — URL, title, raw HTML, clean markdown, screenshot path

### Phase 2 — Dynamic UI Exploration (`ui_explorer.py`)

**What it does**: For each discovered page, interacts with dynamic UI elements and captures what appears/disappears.

**Key implementation details**:
- Injects JavaScript (`DISCOVER_INTERACTIVES_JS`) to find all interactive elements:
  - `<select>` dropdowns and custom dropdown triggers
  - Tab elements (`[role="tab"]`, `.nav-tab`)
  - Accordions (`[data-toggle="collapse"]`, `details > summary`, `[aria-expanded]`)
  - Modal triggers (`[data-toggle="modal"]`, `[aria-haspopup="dialog"]`)
  - Radio/checkbox toggles
- Uses Crawl4AI session management (`session_id`) to keep the browser alive across interactions
- `js_only=True` re-captures DOM without re-navigating after each interaction
- Page state is reset by reloading between interactions
- Limits: max 20 interactions per page, 5-second timeout per interaction

**Input**: Page URL + config  
**Output**: `PageExploration` — initial HTML, interactive elements list, captured UI states

### Phase 2.5 — UI Analysis (`ui_analyzer.py`)

**What it does**: Parses raw HTML into structured data — forms, buttons, navigation, tables.

**Key implementation details**:
- Uses BeautifulSoup4 for HTML parsing
- Extracts:
  - **Navigation**: `<nav>` elements, sidebars, breadcrumbs
  - **Forms**: All `<form>` tags plus orphan inputs (fields outside forms)
  - **Form fields**: Label, type, required flag, options (for dropdowns)
  - **Action buttons**: Identified by keywords (create, edit, delete, save, submit, etc.)
  - **Table headers**: Column names only — reveals entity structure without extracting data
  - **Sections**: Heading hierarchy (h1–h4)
  - **Tabs**: `[role="tab"]` and tablist children
- Label resolution chain: `<label for="...">` → parent `<label>` → `aria-label` → `placeholder` → `name`
- Explicitly does NOT extract data values

**Input**: Raw HTML string  
**Output**: `PageUIAnalysis` — navigation, breadcrumbs, forms, buttons, table headers, sections, tabs

### Phase 3 — LLM Synthesis (`synthesizer.py`)

**What it does**: Uses the LLM to generate documentation from all the structured UI data.

**Key implementation details**:
- Four-pass approach:
  1. **Page Understanding**: Per-page analysis — purpose, operations, entities, forms, dynamic behavior
  2. **Portal Overview**: High-level summary from all page analyses + user notes + docs
  3. **Process Discovery**: Identifies end-to-end workflows with steps, conditions, alternative flows
  4. **Manifest Generation**: Machine-readable page index (generated without LLM)
- System prompt enforces critical rules:
  - Never expand abbreviations unless the portal shows the expansion
  - Focus on operations, not data
  - Preserve all internal terminology
- Prompt templates include all structured UI data: forms, buttons, dynamic states, markdown content

**Input**: Page analyses + dynamic states + markdowns + user docs  
**Output**: `PortalSynthesis` — overview, page analyses, processes, manifest

---

## LLM Provider Layer (`llm_provider.py`)

Three provider implementations behind a common `LLMProvider` interface:

| Provider | Class | How It Calls the LLM |
|----------|-------|---------------------|
| **Gemini** | `GeminiProvider` | `google-genai` SDK — supports multimodal (text + images) |
| **OpenAI-compatible** | `OpenAICompatibleProvider` | Plain `httpx` POST to `/v1/chat/completions` |
| **Custom** | `CustomAPIProvider` | Plain `httpx` POST with configurable request/response field names |

**Key design decisions**:
- No `openai` SDK dependency — OpenAI-compatible calls use raw `httpx`
- Custom provider supports dot-notation response fields (e.g., `data.result.text`)
- Custom provider falls back to text-only if `generate_with_image` is called
- `create_provider(config)` factory function handles instantiation
- All providers use lazy initialization and have `close()` for cleanup

---

## Output Layer (`writer.py`)

Generates the complete folder structure:

```
output/{portal-name}/
├── portal_overview.md      # Human-readable: what the portal is and does
├── portal_manifest.md      # Machine-readable: page index with form/button counts
├── pages/                  # One file per page with LLM-generated analysis
│   ├── dashboard.md
│   ├── create_stream.md
│   └── ...
├── processes/              # Workflow documentation (split by process if possible)
│   ├── curate_vod_stream.md
│   └── ...
├── portal_context.md       # Consolidated single file (everything)
└── screenshots/            # PNG screenshots from Phase 1 and Phase 2
```

**Process splitting**: The writer attempts to split the LLM's process output into separate files by detecting `## Process:` headers. Falls back to a single `all_processes.md` if the output doesn't have clear boundaries.

---

## Interfaces

### CLI (`cli.py`)

- Full `argparse` with grouped arguments (LLM, Portal, Auth, Tuning, Input)
- Progress bar with phase/message/percentage
- `test-llm` sub-command to verify LLM connectivity
- Loads defaults from `.env` via `PortalConfig.from_env()`

### Streamlit UI (`app.py`)

- Sidebar: provider config, crawl tuning, auth settings
- Main: URL input, file upload for supplementary docs, notes text area
- Progress bar with live log streaming
- File preview of all generated markdown
- ZIP download of complete output

---

## Configuration (`config.py`)

`PortalConfig` dataclass with:
- Auto-derived portal name from URL (strips `www.`, `portal.`, `app.` prefixes)
- `from_env()` classmethod for `.env`-based initialization
- `validate()` method returning a list of errors
- Three auth methods: `none`, `profile` (Chrome profile copy), `cdp` (DevTools Protocol)

---

## Supporting Modules

### Document Parser (`doc_parser.py`)

Parses supplementary files users can provide for richer context:
- **PDF**: `PyPDF2.PdfReader` — extracts text from all pages
- **DOCX**: `python-docx.Document` — extracts paragraph text
- **PPTX**: `python-pptx.Presentation` — extracts text from all shapes per slide
- **MD/TXT**: Direct file read

### Pipeline (`pipeline.py`)

Orchestrates all three phases with:
- Config validation
- LLM provider lifecycle management (`create_provider` → use → `close`)
- Progress callback for UI integration
- Error handling that continues through partial failures

---

## Verification Status

| Check | Status |
|-------|--------|
| All module imports | ✅ Passed |
| CLI `--help` | ✅ Passed |
| Dependencies installed in venv | ✅ Passed |
| End-to-end pipeline test | ⏳ Pending (needs LLM key or local LLM) |

---

## How to Test

```bash
# Activate venv
.\venv\Scripts\Activate.ps1

# Test LLM connection first
python cli.py test-llm --provider gemini --api-key YOUR_KEY

# Run on a public site
python cli.py --url https://example.com --provider gemini --api-key YOUR_KEY --max-depth 1 --max-pages 5

# Run Streamlit UI
streamlit run app.py
```
