"""
CLI — Command-line interface for Portal Context Generator.

Usage:
    python cli.py --url https://portal.internal.com --provider gemini --api-key KEY
    python cli.py --help
"""

import argparse
import asyncio
import logging
import sys
import time

from portal_context.config import PortalConfig
from portal_context.pipeline import run_pipeline


def main():
    parser = argparse.ArgumentParser(
        prog="portal-context",
        description="Generate comprehensive portal context documentation from any portal URL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Gemini provider (free tier)
  python cli.py --url https://portal.internal.com --provider gemini --api-key YOUR_KEY

  # With browser profile auth
  python cli.py --url https://portal.internal.com --provider gemini --api-key KEY \\
    --auth profile --chrome-profile "C:/Users/you/.../User Data"

  # Local LLM (OpenAI-compatible)
  python cli.py --url https://portal.internal.com --provider openai \\
    --llm-url http://localhost:8080/v1 --model llama-3

  # Custom LLM API
  python cli.py --url https://portal.internal.com --provider custom \\
    --llm-url http://localhost:5000/generate --request-field input --response-field output

  # With supplementary docs
  python cli.py --url https://portal.internal.com --provider gemini --api-key KEY \\
    --docs ./sop.pdf ./guide.docx --notes "Used by content ops team"
        """,
    )

    # Required
    parser.add_argument("--url", required=True, help="Portal URL to analyze")

    # LLM settings
    llm_group = parser.add_argument_group("LLM Configuration")
    llm_group.add_argument("--provider", choices=["gemini", "openai", "custom"],
                           default="gemini", help="LLM provider (default: gemini)")
    llm_group.add_argument("--api-key", default="", help="LLM API key")
    llm_group.add_argument("--model", default="", help="LLM model name")
    llm_group.add_argument("--llm-url", default="", help="LLM base URL (for openai/custom)")
    llm_group.add_argument("--request-field", default="input",
                           help="Request field name for custom provider")
    llm_group.add_argument("--response-field", default="output",
                           help="Response field name for custom provider")

    # Portal settings
    portal_group = parser.add_argument_group("Portal Settings")
    portal_group.add_argument("--name", default="", help="Portal name (auto-derived if not given)")
    portal_group.add_argument("--output", default="./output", help="Output directory (default: ./output)")

    # Auth settings
    auth_group = parser.add_argument_group("Authentication")
    auth_group.add_argument("--auth", choices=["none", "profile", "cdp"],
                            default="none", help="Auth method (default: none)")
    auth_group.add_argument("--chrome-profile", default="",
                            help="Chrome profile directory (for --auth profile)")
    auth_group.add_argument("--cdp-url", default="",
                            help="CDP URL (for --auth cdp)")

    # Crawl tuning
    tuning_group = parser.add_argument_group("Crawl Tuning")
    tuning_group.add_argument("--max-depth", type=int, default=3,
                              help="Max BFS crawl depth (default: 3)")
    tuning_group.add_argument("--max-pages", type=int, default=100,
                              help="Max pages to discover (default: 100)")
    tuning_group.add_argument("--max-interactions", type=int, default=20,
                              help="Max interactions per page (default: 20)")
    tuning_group.add_argument("--no-screenshots", action="store_true",
                              help="Disable screenshot capture")

    # Supplementary input
    input_group = parser.add_argument_group("Supplementary Input")
    input_group.add_argument("--docs", nargs="*", default=[],
                             help="Supplementary document files (PDF, DOCX, PPTX, MD, TXT)")
    input_group.add_argument("--notes", default="",
                             help="Free-text notes about the portal")

    # Misc
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    # Sub-command: test-llm
    subparsers = parser.add_subparsers(dest="command")
    test_parser = subparsers.add_parser("test-llm", help="Test LLM connection")
    test_parser.add_argument("--provider", choices=["gemini", "openai", "custom"], required=True)
    test_parser.add_argument("--api-key", default="")
    test_parser.add_argument("--model", default="")
    test_parser.add_argument("--llm-url", default="")
    test_parser.add_argument("--request-field", default="input")
    test_parser.add_argument("--response-field", default="output")

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Handle test-llm sub-command
    if args.command == "test-llm":
        asyncio.run(_test_llm(args))
        return

    # Build config
    config = PortalConfig(
        portal_url=args.url,
        portal_name=args.name,
        llm_provider=args.provider,
        llm_model=args.model or _default_model(args.provider),
        llm_api_key=args.api_key,
        llm_base_url=args.llm_url,
        llm_request_field=args.request_field,
        llm_response_field=args.response_field,
        max_depth=args.max_depth,
        max_pages=args.max_pages,
        max_interactions_per_page=args.max_interactions,
        capture_screenshots=not args.no_screenshots,
        output_dir=args.output,
        auth_method=args.auth,
        chrome_profile_dir=args.chrome_profile,
        cdp_url=args.cdp_url,
        doc_paths=args.docs,
        user_notes=args.notes,
    )

    # Validate
    errors = config.validate()
    if errors:
        print("Configuration errors:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    # Progress callback for CLI
    def on_progress(phase, msg, pct):
        bar_len = 30
        filled = int(bar_len * pct)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"\r[{bar}] {pct*100:5.1f}% | {phase}: {msg}", end="", flush=True)
        if pct >= 1.0:
            print()

    # Run pipeline
    print(f"\n🔍 Portal Context Generator")
    print(f"   URL: {config.portal_url}")
    print(f"   LLM: {config.llm_provider} ({config.llm_model})")
    print(f"   Output: {config.output_dir}/{config.portal_name}")
    print()

    start = time.time()
    try:
        output_path = asyncio.run(run_pipeline(config, progress_callback=on_progress))
        elapsed = time.time() - start
        print(f"\n✅ Done in {elapsed:.1f}s")
        print(f"📁 Output: {output_path}")
    except KeyboardInterrupt:
        print("\n\n⚠ Cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


def _default_model(provider: str) -> str:
    """Return default model name for a provider."""
    defaults = {
        "gemini": "gemini-2.0-flash",
        "openai": "default",
        "custom": "default",
    }
    return defaults.get(provider, "default")


async def _test_llm(args):
    """Test LLM connection with a simple prompt."""
    from portal_context.llm_provider import create_provider
    from portal_context.config import PortalConfig

    print("🧪 Testing LLM connection...")

    config = PortalConfig(
        portal_url="https://test.example.com",
        llm_provider=args.provider,
        llm_model=args.model or _default_model(args.provider),
        llm_api_key=args.api_key,
        llm_base_url=args.llm_url,
        llm_request_field=args.request_field,
        llm_response_field=args.response_field,
    )

    llm = create_provider(config)
    try:
        response = await llm.generate(
            "Respond with exactly: 'Connection successful'. Nothing else."
        )
        print(f"✅ LLM responded: {response.strip()}")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)
    finally:
        await llm.close()


if __name__ == "__main__":
    main()
