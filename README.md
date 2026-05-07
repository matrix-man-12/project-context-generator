# 🔍 Portal Context Generator

Generate comprehensive portal context documentation from any internal portal URL. The output serves as knowledge input for autonomous bots, telling them what a portal does, how it works, and what steps to take for any operation.

## What It Does

- **Crawls** all pages within a portal (Phase 1 — BFS Discovery)
- **Explores** dynamic UI states — clicks dropdowns, tabs, accordions and captures what appears (Phase 2 — UI Exploration)
- **Generates** structured documentation using LLM — overview, page details, process workflows (Phase 3 — Synthesis)

> **Important**: This tool extracts UI structure and operations — NOT data. It documents what the portal can do, not what data it contains.

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/matrix-man-12/project-context-generator.git
cd project-context-generator

# 2. Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1          # Windows PowerShell
# source venv/bin/activate            # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Install browser (required by Crawl4AI)
playwright install chromium

# 5. Copy and configure environment
copy .env.example .env
# Edit .env with your API keys

# 6. Run
python cli.py --url https://portal.example.com --provider gemini --api-key YOUR_KEY
```

## Usage

### CLI

```bash
# Gemini provider (free tier)
python cli.py --url https://portal.internal.com --provider gemini --api-key KEY

# With browser profile auth
python cli.py --url https://portal.internal.com --provider gemini --api-key KEY \
  --auth profile --chrome-profile "C:/Users/you/AppData/Local/Google/Chrome/User Data"

# Local LLM (OpenAI-compatible)
python cli.py --url https://portal.internal.com --provider openai \
  --llm-url http://localhost:8080/v1 --model llama-3

# Custom LLM API
python cli.py --url https://portal.internal.com --provider custom \
  --llm-url http://localhost:5000/generate --request-field input --response-field output

# With supplementary docs
python cli.py --url https://portal.internal.com --provider gemini --api-key KEY \
  --docs ./sop.pdf ./guide.docx --notes "Used by content ops team"

# Test LLM connection
python cli.py test-llm --provider gemini --api-key KEY
```

### Streamlit UI

```bash
streamlit run app.py
```

## Output

```
output/
└── portal-name/
    ├── portal_overview.md      # Human-readable overview
    ├── portal_manifest.md      # Machine-readable page index
    ├── pages/                  # Per-page UI analysis
    ├── processes/              # Task → Process → Steps
    ├── portal_context.md       # Consolidated single file
    └── screenshots/            # Page screenshots
```

## LLM Providers

| Provider | Config | Use Case |
|----------|--------|----------|
| **Gemini** | `--provider gemini --api-key KEY` | Free tier, supports vision |
| **OpenAI-compatible** | `--provider openai --llm-url URL` | vLLM, Ollama, LM Studio |
| **Custom API** | `--provider custom --llm-url URL` | Any simple POST endpoint |

For non-standard LLM APIs, see [LLM Integration Guide](docs/llm_integration_guide.md).

## Authentication

| Method | Flag | Description |
|--------|------|-------------|
| None | `--auth none` | Default, no authentication |
| Profile Copy | `--auth profile` | Copies Chrome profile to inherit login session |
| CDP | `--auth cdp` | Connects to running Chrome via DevTools Protocol |

## Configuration Reference

All settings can be set via CLI flags, `.env` file, or Streamlit UI.

| Setting | CLI Flag | Env Variable | Default |
|---------|----------|-------------|---------|
| Portal URL | `--url` | — | Required |
| LLM Provider | `--provider` | `LLM_PROVIDER` | `gemini` |
| API Key | `--api-key` | `GEMINI_API_KEY` / `LLM_API_KEY` | — |
| LLM Model | `--model` | `LLM_MODEL` | `gemini-2.0-flash` |
| LLM URL | `--llm-url` | `LLM_BASE_URL` | — |
| Max Depth | `--max-depth` | — | `3` |
| Max Pages | `--max-pages` | — | `100` |
| Max Interactions | `--max-interactions` | — | `20` |
| Auth Method | `--auth` | `AUTH_METHOD` | `none` |

## Project Structure

```
├── cli.py                      # Command-line interface
├── app.py                      # Streamlit UI
├── portal_context/             # Core library
│   ├── config.py               # Configuration
│   ├── llm_provider.py         # LLM abstraction
│   ├── crawler.py              # Phase 1: Page Discovery
│   ├── ui_explorer.py          # Phase 2: UI Exploration
│   ├── ui_analyzer.py          # HTML → Structured UI Data
│   ├── synthesizer.py          # Phase 3: LLM Synthesis
│   ├── doc_parser.py           # Document parsing
│   ├── writer.py               # Output writer
│   └── pipeline.py             # Pipeline orchestrator
├── docs/
│   ├── implementation_plan.md  # Technical design document
│   └── llm_integration_guide.md # Custom LLM setup guide
├── requirements.txt
├── .env.example
└── .gitignore
```

## License

Internal use only.
