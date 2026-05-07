# Portal Context Generator — Project Documentation

## Table of Contents

- [1. What Is This Project?](#1-what-is-this-project)
  - [The Problem](#the-problem)
  - [The Solution](#the-solution)
- [2. Architecture](#2-architecture)
  - [High-Level Flow](#high-level-flow)
  - [Pipeline Orchestration](#pipeline-orchestration)
- [3. Module-by-Module Breakdown](#3-module-by-module-breakdown)
  - [3.1 config.py — Configuration](#31-configpy--configuration)
  - [3.2 llm_provider.py — LLM Abstraction](#32-llm_providerpy--llm-abstraction)
  - [3.3 crawler.py — Phase 1: Page Discovery](#33-crawlerpy--phase-1-page-discovery)
  - [3.4 ui_explorer.py — Phase 2: Dynamic UI Exploration](#34-ui_explorerpy--phase-2-dynamic-ui-exploration)
  - [3.5 ui_analyzer.py — HTML to Structured Data](#35-ui_analyzerpy--html-to-structured-data)
  - [3.6 synthesizer.py — Phase 3: LLM Synthesis](#36-synthesizerpy--phase-3-llm-synthesis)
  - [3.7 doc_parser.py — Supplementary Documents](#37-doc_parserpy--supplementary-documents)
  - [3.8 writer.py — Output Generation](#38-writerpy--output-generation)
- [4. Interfaces](#4-interfaces)
  - [4.1 CLI](#41-cli-clipy)
  - [4.2 Streamlit UI](#42-streamlit-ui-apppy)
- [5. Authentication Guide](#5-authentication-guide)
  - [Option A: Profile Copy](#option-a-profile-copy---auth-profile)
  - [Option B: CDP](#option-b-cdp---auth-cdp)
- [6. LLM Provider Guide](#6-llm-provider-guide)
  - [Gemini](#gemini-free-tier--recommended)
  - [OpenAI-Compatible](#openai-compatible-local-llms)
  - [Custom API](#custom-api)
- [7. Project File Map](#7-project-file-map)
- [8. Dependencies](#8-dependencies)
- [9. Design Principles](#9-design-principles)

---

## 1. What Is This Project?

Portal Context Generator is a self-contained Python utility that automatically generates structured documentation for any internal web portal. It tells an autonomous bot (or a human) **what the portal does**, **what operations are available**, and **how to complete tasks step-by-step**.

### The Problem

Organizations run dozens of internal portals for various operations — content management, order processing, user administration, etc. Each portal has its own UI, its own terminology, and its own workflows. When building a bot that needs to operate across these portals, someone has to manually document every page, every form, every button, every process. This is slow, error-prone, and doesn't scale.

### The Solution

Point this tool at a portal URL → it crawls every page, interacts with dynamic UI elements (dropdowns, tabs, modals), and uses an LLM to synthesize the raw UI data into clean, structured documentation.

**What it extracts**: UI structure, operations, workflows, navigation, forms, terminology.  
**What it does NOT extract**: Actual data content (no user records, no transaction data, no PII).

---

## 2. Architecture

### High-Level Flow

```
Portal URL
    │
    ▼
┌─────────────────────────────────────────────────┐
│  Phase 1: PAGE DISCOVERY (crawler.py)           │
│  Crawl4AI BFS deep crawl                        │
│  Output: URLs, HTML, markdown, screenshots       │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│  Phase 2: UI EXPLORATION (ui_explorer.py)       │
│  Click dropdowns, tabs, accordions              │
│  Capture DOM changes after each interaction     │
│  Output: Interactive elements + UI states        │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│  UI ANALYSIS (ui_analyzer.py)                   │
│  Parse HTML → structured data (no LLM)          │
│  Output: Forms, buttons, nav, tables, tabs       │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│  Phase 3: LLM SYNTHESIS (synthesizer.py)        │
│  Pass 1: Page understanding (per page)          │
│  Pass 2: Portal overview (1 call)               │
│  Pass 3: Process discovery (1 call)             │
│  Output: Structured context documentation        │
└──────────────────┬──────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────┐
│  OUTPUT WRITER (writer.py)                      │
│  Generates markdown files + folder structure     │
└─────────────────────────────────────────────────┘
```

### Pipeline Orchestration

`pipeline.py` ties everything together. It runs the phases sequentially, passes data between them, handles errors gracefully (a failed page doesn't stop the whole run), and reports progress via a callback.

---

## 3. Module-by-Module Breakdown

### 3.1 `config.py` — Configuration

A single `PortalConfig` dataclass holds every setting:

| Group | Settings |
|-------|----------|
| **Portal** | `portal_url`, `portal_name` (auto-derived from URL) |
| **LLM** | `llm_provider`, `llm_model`, `llm_api_key`, `llm_base_url`, `llm_request_field`, `llm_response_field` |
| **Crawl** | `max_depth`, `max_pages`, `max_interactions_per_page`, `interaction_timeout` |
| **Auth** | `auth_method` (none/profile/cdp), `chrome_profile_dir`, `cdp_url` |
| **Output** | `output_dir`, `capture_screenshots` |
| **Supplementary** | `doc_paths`, `user_notes` |

**Key methods**:
- `PortalConfig.from_env(url)` — Creates config from `.env` file
- `config.validate()` — Returns list of configuration errors

### 3.2 `llm_provider.py` — LLM Abstraction

Three providers behind a single `LLMProvider` interface:

```
LLMProvider (abstract)
├── GeminiProvider        — google-genai SDK, free tier, multimodal
├── OpenAICompatibleProvider — httpx POST to /v1/chat/completions
└── CustomAPIProvider     — httpx POST with configurable field mapping
```

**Why no OpenAI SDK?** We use raw `httpx` for OpenAI-compatible and Custom providers to avoid unnecessary dependencies and to give full control over the HTTP call.

**Factory function**: `create_provider(config)` returns the right provider based on `config.llm_provider`.

**Interface**:
```python
async def generate(prompt: str, system_prompt: str = "") -> str
async def generate_with_image(prompt: str, image_path: str, system_prompt: str = "") -> str
async def close()
```

### 3.3 `crawler.py` — Phase 1: Page Discovery

**Technology**: Crawl4AI with `BFSDeepCrawlStrategy`

**What it does**:
1. Launches a browser (with auth if configured)
2. BFS-crawls from the root URL, staying within the portal domain
3. For each page: captures URL, title, raw HTML, filtered markdown, screenshot

**Authentication support**:

| Method | How it works |
|--------|-------------|
| `none` | Fresh anonymous browser |
| `profile` | Copies Chrome profile (cookies, login data) to a temp directory. Detects whether user provided `User Data` root or a specific profile dir (e.g., `Profile 5`) |
| `cdp` | Connects to a running Chrome via WebSocket. Auto-fetches the WS URL from Chrome's `/json/version` HTTP endpoint |

**Profile detection logic**:
- If `Local State` exists at the given path → it's the `User Data` root → copies `Default`
- If `Local State` exists in the parent → user gave a specific profile (e.g., `Profile 5`) → copies that profile

### 3.4 `ui_explorer.py` — Phase 2: Dynamic UI Exploration

**What it does**: For each discovered page, injects JavaScript to find interactive elements, then clicks each one and captures the resulting DOM state.

**Interactive elements detected**:
- `<select>` dropdowns and custom dropdown triggers
- Tabs (`[role="tab"]`, `.nav-tab`, `.nav-link`)
- Accordions (`[data-toggle="collapse"]`, `details > summary`, `[aria-expanded]`)
- Modal triggers (`[data-toggle="modal"]`, `[aria-haspopup="dialog"]`)
- Radio/checkbox toggles that affect UI state

**How interaction works**:
1. Load page and run `DISCOVER_INTERACTIVES_JS` — returns JSON array of interactive elements
2. For each element (up to `max_interactions_per_page`):
   - Inject JS to click/select the element
   - Wait 1.5s for DOM to settle
   - Capture HTML snapshot + screenshot
   - Reload page to reset state
3. Return all captured UI states

**Reuses crawler auth**: Calls `_build_browser_config(config)` from `crawler.py` so CDP/profile auth is respected.

### 3.5 `ui_analyzer.py` — HTML to Structured Data

**Technology**: BeautifulSoup4 (no LLM)

**What it extracts from raw HTML**:

| Data | How |
|------|-----|
| **Navigation** | `<nav>` elements, `[role="navigation"]`, `.sidebar` |
| **Breadcrumbs** | `.breadcrumb`, `[aria-label*="breadcrumb"]` |
| **Forms** | All `<form>` tags + orphan `<input>/<select>/<textarea>` outside forms |
| **Form fields** | Label (via `<label for>`, parent `<label>`, `aria-label`, `placeholder`), type, required flag, dropdown options |
| **Action buttons** | `<button>` elements + `<a>` tags with action keywords (create, edit, delete, save, submit, etc.) |
| **Table headers** | `<thead>` column names — reveals entity structure without extracting data |
| **Sections** | Heading hierarchy (h1–h4) |
| **Tabs** | `[role="tab"]`, `[role="tablist"]` children |

### 3.6 `synthesizer.py` — Phase 3: LLM Synthesis

**This is the only module that uses the LLM.** Three passes:

#### Pass 1: Page Understanding (1 LLM call per page)
- **Input**: Structured UI data (forms, buttons, tables, dynamic states, markdown excerpt)
- **Output**: What the page is for, what operations are available, what entities it manages
- **Why LLM**: Raw data is just element lists. Only an LLM can infer that a form with "Title, Category, Publish Date" + "Submit for Review" = content creation page

#### Pass 2: Portal Overview (1 LLM call total)
- **Input**: All page analyses + user notes + supplementary doc text
- **Output**: "What this portal is", capabilities list, key entities, sections, terminology table
- **Why LLM**: Synthesizing multiple page analyses into a coherent overview

#### Pass 3: Process Discovery (1 LLM call total)
- **Input**: All page analyses with operations
- **Output**: Named processes with sequential steps (which page → what action → expected result)
- **Why LLM**: Connecting operations across pages into end-to-end workflows

**Critical LLM rules** (enforced via system prompt):
- NEVER expand abbreviations unless the portal itself shows the expansion
- Preserve all internal terminology exactly as shown
- Focus on operations, not data content

#### Manifest (no LLM)
- Machine-readable page index table with form/button/table counts

### 3.7 `doc_parser.py` — Supplementary Documents

Parses user-provided files to enrich context:

| Format | Library |
|--------|---------|
| PDF | PyPDF2 |
| DOCX | python-docx |
| PPTX | python-pptx |
| MD/TXT | Plain file read |

### 3.8 `writer.py` — Output Generation

Creates the output folder structure:

```
output/{portal-name}/
├── portal_overview.md      # Human-readable overview
├── portal_manifest.md      # Machine-readable page index
├── portal_context.md       # Everything in one file
├── pages/                  # Per-page detailed analysis
│   ├── dashboard.md
│   └── ...
├── processes/              # Process/workflow documentation
│   ├── create_stream.md
│   └── ...
└── screenshots/            # PNG screenshots
```

The writer attempts to split the LLM's process output into separate files by detecting `## Process:` headers. Falls back to `all_processes.md` if it can't split.

---

## 4. Interfaces

### 4.1 CLI (`cli.py`)

```bash
# Basic usage
python cli.py --url https://portal.example.com --provider gemini --api-key KEY

# With profile auth
python cli.py --url URL --auth profile \
  --chrome-profile "C:/Users/.../User Data/Profile 5"

# With CDP (connect to running browser)
python cli.py --url URL --auth cdp --cdp-url http://localhost:9222

# With supplementary docs
python cli.py --url URL --docs ./sop.pdf ./guide.docx --notes "Content ops portal"

# Test LLM connection
python cli.py test-llm --provider gemini --api-key KEY
```

Features:
- Grouped argument sections (LLM, Portal, Auth, Crawl Tuning, Input)
- Progress bar with phase/message/percentage
- `.env` auto-loading for API keys
- `test-llm` sub-command

### 4.2 Streamlit UI (`app.py`)

```bash
streamlit run app.py
```

Features:
- Sidebar: LLM provider config, crawl tuning, auth settings
- Main area: URL input, portal name, output directory
- Supplementary input: file upload (PDF/DOCX/PPTX/MD/TXT) + text notes
- Progress bar with live log streaming
- File preview of all generated markdown
- Screenshot gallery (Grid view + Slideshow view)
- Screenshot browser for past output folders
- ZIP download of complete output

---

## 5. Authentication Guide

### Option A: Profile Copy (`--auth profile`)

**How it works**: Copies your Chrome profile's cookies and session data to a temp directory, then launches Playwright with that profile.

**Setup**:
1. Find your profile path: Open Chrome → `chrome://version/` → look for "Profile Path"
2. Close Chrome completely (profile is locked while Chrome runs)
3. Provide the path (either the `User Data` root or specific profile like `Profile 5`)

**Limitations**: 
- Chrome must be closed during the run
- Session cookies may expire if the portal uses short-lived tokens

### Option B: CDP (`--auth cdp`)

**How it works**: Connects directly to your running Chrome browser via the Chrome DevTools Protocol.

**Setup**:
1. Close Chrome
2. Relaunch with debug port:
   ```
   "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\Users\you\AppData\Local\Google\Chrome\User Data" --profile-directory="Profile 5"
   ```
3. Use Chrome normally (it's the same browser, just with the debug port open)
4. Set `--auth cdp --cdp-url http://localhost:9222`

**Advantages**: 
- No need to close Chrome during runs
- Uses the live session — never stale
- Works with SSO/MFA portals (you've already authenticated)

---

## 6. LLM Provider Guide

### Gemini (Free Tier) — Recommended

```bash
python cli.py --url URL --provider gemini --api-key YOUR_GEMINI_KEY
```

Free tier limits: 15 RPM for `gemini-2.0-flash`. Sufficient for portals with up to ~15 pages per run.

### OpenAI-Compatible (Local LLMs)

Works with vLLM, Ollama, LM Studio, text-generation-webui, or any server exposing `/v1/chat/completions`.

```bash
python cli.py --url URL --provider openai --llm-url http://localhost:8080/v1 --model llama-3
```

### Custom API

For non-standard LLM endpoints. Configure which JSON fields carry the request and response:

```bash
python cli.py --url URL --provider custom \
  --llm-url http://your-llm:5000/generate \
  --request-field input \
  --response-field output
```

Supports dot-notation for nested response fields (e.g., `data.result.text`).

See [LLM Integration Guide](llm_integration_guide.md) for detailed adapter patterns.

---

## 7. Project File Map

```
Portal-Context/
├── cli.py                              # CLI entry point
├── app.py                              # Streamlit UI entry point
├── requirements.txt                    # Python dependencies
├── .env.example                        # Configuration template
├── .gitignore
├── README.md                           # Quick-start guide
│
├── portal_context/                     # Core library
│   ├── __init__.py                     # Package init, version
│   ├── config.py                       # PortalConfig dataclass
│   ├── llm_provider.py                 # LLM abstraction (3 providers)
│   ├── crawler.py                      # Phase 1: BFS page discovery
│   ├── ui_explorer.py                  # Phase 2: Dynamic UI interaction
│   ├── ui_analyzer.py                  # HTML → structured UI data
│   ├── synthesizer.py                  # Phase 3: LLM synthesis
│   ├── doc_parser.py                   # PDF/DOCX/PPTX/MD parser
│   ├── writer.py                       # Markdown output generator
│   └── pipeline.py                     # Pipeline orchestrator
│
├── docs/                               # Documentation
│   ├── project_documentation.md        # This file
│   ├── implementation_plan.md          # Technical design (v3.2)
│   ├── llm_integration_guide.md        # Custom LLM setup
│   └── walkthrough.md                  # Implementation walkthrough
│
└── output/                             # Generated output (gitignored)
    └── {portal-name}/
        ├── portal_overview.md
        ├── portal_manifest.md
        ├── portal_context.md
        ├── pages/*.md
        ├── processes/*.md
        └── screenshots/*.png
```

---

## 8. Dependencies

| Package | Purpose |
|---------|---------|
| `crawl4ai` | Web crawling with BFS deep crawl, Playwright browser automation |
| `beautifulsoup4` + `lxml` | HTML parsing for UI analysis |
| `httpx` | HTTP client for OpenAI-compatible and Custom LLM calls |
| `google-genai` | Google Gemini API SDK |
| `python-dotenv` | `.env` file loading |
| `streamlit` | Web UI |
| `PyPDF2` | PDF document parsing |
| `python-docx` | DOCX document parsing |
| `python-pptx` | PPTX document parsing |

---

## 9. Design Principles

1. **No data extraction** — Only UI structure and operations. Never scrape portal data.
2. **Abbreviation integrity** — Never expand abbreviations unless the portal explicitly defines them.
3. **Self-contained** — Runs entirely within the office network. The only external call is to the LLM API (which can also be local).
4. **Provider-agnostic** — Swap LLM backends without changing any pipeline code.
5. **Graceful degradation** — If one page fails to crawl or one LLM call fails, the pipeline continues with what it has.
6. **Virtual environment** — Always runs in a Python venv.
