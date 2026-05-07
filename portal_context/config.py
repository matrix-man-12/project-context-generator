"""
Configuration module for Portal Context Generator.

Defines the PortalConfig dataclass with all configurable parameters
for crawling, LLM, authentication, and output settings.
"""

import os
from dataclasses import dataclass, field
from typing import Literal, Optional
from urllib.parse import urlparse

from dotenv import load_dotenv


@dataclass
class PortalConfig:
    """Configuration for a portal context generation run."""

    # Portal settings
    portal_url: str
    portal_name: str = ""

    # LLM settings
    llm_provider: Literal["gemini", "openai", "custom"] = "gemini"
    llm_model: str = "gemini-2.0-flash"
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_request_field: str = "input"       # For custom provider
    llm_response_field: str = "output"     # For custom provider

    # Crawl settings
    max_depth: int = 3
    max_pages: int = 100
    max_interactions_per_page: int = 20
    interaction_timeout: int = 5

    # Output settings
    capture_screenshots: bool = True
    output_dir: str = "./output"

    # Authentication
    auth_method: Literal["none", "profile", "cdp"] = "none"
    chrome_profile_dir: str = ""
    cdp_url: str = ""

    # Supplementary input
    doc_paths: list[str] = field(default_factory=list)
    user_notes: str = ""

    def __post_init__(self):
        """Auto-derive portal_name from URL if not provided."""
        if not self.portal_name:
            parsed = urlparse(self.portal_url)
            # Use hostname without common prefixes
            hostname = parsed.hostname or "unknown-portal"
            for prefix in ["www.", "portal.", "app."]:
                if hostname.startswith(prefix):
                    hostname = hostname[len(prefix):]
            # Take first part of hostname as name
            self.portal_name = hostname.split(".")[0]

    @classmethod
    def from_env(cls, portal_url: str, **overrides) -> "PortalConfig":
        """Create config from environment variables with optional overrides."""
        load_dotenv()

        config = cls(
            portal_url=portal_url,
            llm_provider=os.getenv("LLM_PROVIDER", "gemini"),
            llm_model=os.getenv("LLM_MODEL", os.getenv("GEMINI_MODEL", "gemini-2.0-flash")),
            llm_api_key=os.getenv("LLM_API_KEY", os.getenv("GEMINI_API_KEY", "")),
            llm_base_url=os.getenv("LLM_BASE_URL", ""),
            llm_request_field=os.getenv("LLM_REQUEST_FIELD", "input"),
            llm_response_field=os.getenv("LLM_RESPONSE_FIELD", "output"),
            auth_method=os.getenv("AUTH_METHOD", "none"),
            chrome_profile_dir=os.getenv("CHROME_PROFILE_DIR", ""),
            cdp_url=os.getenv("CDP_URL", ""),
        )

        # Apply explicit overrides
        for key, value in overrides.items():
            if hasattr(config, key) and value is not None:
                setattr(config, key, value)

        return config

    def validate(self) -> list[str]:
        """Validate configuration and return list of errors."""
        errors = []

        if not self.portal_url:
            errors.append("portal_url is required")

        if self.llm_provider == "gemini" and not self.llm_api_key:
            errors.append("GEMINI_API_KEY is required when using gemini provider")

        if self.llm_provider == "openai" and not self.llm_base_url:
            errors.append("LLM_BASE_URL is required when using openai provider")

        if self.llm_provider == "custom" and not self.llm_base_url:
            errors.append("LLM_BASE_URL is required when using custom provider")

        if self.auth_method == "profile" and not self.chrome_profile_dir:
            errors.append("CHROME_PROFILE_DIR is required when using profile auth")

        if self.auth_method == "cdp" and not self.cdp_url:
            errors.append("CDP_URL is required when using cdp auth")

        return errors
