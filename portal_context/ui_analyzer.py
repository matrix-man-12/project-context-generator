"""
UI Analyzer — Extracts structured UI data from raw HTML.

Parses HTML to identify forms, buttons, navigation, tables,
and other interactive elements. Does NOT extract data values.
"""

import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)


@dataclass
class FormField:
    label: str = ""
    name: str = ""
    field_type: str = ""  # text, select, textarea, checkbox, radio, date, file, etc.
    required: bool = False
    options: list[str] = field(default_factory=list)
    placeholder: str = ""


@dataclass
class FormInfo:
    form_id: str = ""
    form_name: str = ""
    action: str = ""
    method: str = ""
    fields: list[FormField] = field(default_factory=list)


@dataclass
class ActionButton:
    text: str = ""
    button_type: str = ""  # submit, button, link
    css_class: str = ""
    is_primary: bool = False


@dataclass
class NavItem:
    text: str = ""
    href: str = ""
    is_active: bool = False
    children: list = field(default_factory=list)


@dataclass
class PageUIAnalysis:
    """Structured UI analysis of a single page."""
    url: str = ""
    title: str = ""
    navigation: list[NavItem] = field(default_factory=list)
    breadcrumbs: list[str] = field(default_factory=list)
    forms: list[FormInfo] = field(default_factory=list)
    action_buttons: list[ActionButton] = field(default_factory=list)
    table_headers: list[list[str]] = field(default_factory=list)
    sections: list[str] = field(default_factory=list)
    tabs: list[str] = field(default_factory=list)


def analyze_page_ui(html: str, url: str = "", title: str = "") -> PageUIAnalysis:
    """
    Analyze a page's HTML and extract structured UI information.
    
    Extracts forms, buttons, navigation, tables (headers only),
    sections, and tabs — ignoring actual data content.
    """
    if not html:
        return PageUIAnalysis(url=url, title=title)

    soup = BeautifulSoup(html, "html.parser")
    analysis = PageUIAnalysis(url=url, title=title or _get_title(soup))

    analysis.navigation = _extract_navigation(soup)
    analysis.breadcrumbs = _extract_breadcrumbs(soup)
    analysis.forms = _extract_forms(soup)
    analysis.action_buttons = _extract_buttons(soup)
    analysis.table_headers = _extract_table_headers(soup)
    analysis.sections = _extract_sections(soup)
    analysis.tabs = _extract_tabs(soup)

    return analysis


def _get_title(soup: BeautifulSoup) -> str:
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return ""


def _extract_navigation(soup: BeautifulSoup) -> list[NavItem]:
    """Extract navigation items from nav elements, sidebars."""
    nav_items = []
    nav_elements = soup.find_all("nav")
    
    # Also look for common sidebar patterns
    for selector in [".sidebar", "#sidebar", '[role="navigation"]']:
        found = soup.select(selector)
        nav_elements.extend(found)

    for nav in nav_elements:
        for link in nav.find_all("a", recursive=True):
            text = link.get_text(strip=True)
            if text and len(text) < 100:
                item = NavItem(
                    text=text,
                    href=link.get("href", ""),
                    is_active="active" in link.get("class", []),
                )
                nav_items.append(item)

    return nav_items


def _extract_breadcrumbs(soup: BeautifulSoup) -> list[str]:
    """Extract breadcrumb trail."""
    bc = soup.find(class_=re.compile(r"breadcrumb", re.I))
    if not bc:
        bc = soup.find(attrs={"aria-label": re.compile(r"breadcrumb", re.I)})
    if bc:
        items = bc.find_all("li") or bc.find_all("a")
        return [item.get_text(strip=True) for item in items if item.get_text(strip=True)]
    return []


def _extract_forms(soup: BeautifulSoup) -> list[FormInfo]:
    """Extract all forms with their fields."""
    forms = []
    for form_tag in soup.find_all("form"):
        form = FormInfo(
            form_id=form_tag.get("id", ""),
            form_name=form_tag.get("name", ""),
            action=form_tag.get("action", ""),
            method=form_tag.get("method", ""),
        )
        form.fields = _extract_form_fields(form_tag)
        forms.append(form)

    # Also look for form-like structures (fieldsets, labeled inputs outside forms)
    orphan_inputs = soup.find_all(["input", "select", "textarea"], recursive=True)
    orphan_fields = []
    for inp in orphan_inputs:
        if not inp.find_parent("form"):
            field = _parse_field(inp)
            if field.label or field.name:
                orphan_fields.append(field)

    if orphan_fields:
        forms.append(FormInfo(form_name="(inline fields)", fields=orphan_fields))

    return forms


def _extract_form_fields(form_tag: Tag) -> list[FormField]:
    """Extract fields from a form element."""
    fields = []
    for el in form_tag.find_all(["input", "select", "textarea"]):
        field = _parse_field(el)
        if field.field_type != "hidden":  # Skip hidden fields
            fields.append(field)
    return fields


def _parse_field(el: Tag) -> FormField:
    """Parse a single form field element."""
    field = FormField(name=el.get("name", ""), placeholder=el.get("placeholder", ""))

    # Determine type
    if el.name == "select":
        field.field_type = "dropdown"
        field.options = [opt.get_text(strip=True) for opt in el.find_all("option") if opt.get_text(strip=True)]
    elif el.name == "textarea":
        field.field_type = "textarea"
    else:
        field.field_type = el.get("type", "text")

    # Check required
    field.required = el.has_attr("required") or el.get("aria-required") == "true"

    # Find label
    field.label = _find_label(el)

    return field


def _find_label(el: Tag) -> str:
    """Find the label text for a form element."""
    el_id = el.get("id", "")
    if el_id:
        label = el.find_parent().find("label", attrs={"for": el_id}) if el.find_parent() else None
        if not label:
            soup_root = el.find_parent(["html", "[document]"]) or el.find_parent()
            if soup_root:
                label = soup_root.find("label", attrs={"for": el_id})
        if label:
            return label.get_text(strip=True)
    
    # Check parent label
    parent_label = el.find_parent("label")
    if parent_label:
        text = parent_label.get_text(strip=True)
        return text

    # aria-label
    aria = el.get("aria-label", "")
    if aria:
        return aria

    return el.get("placeholder", el.get("name", ""))


def _extract_buttons(soup: BeautifulSoup) -> list[ActionButton]:
    """Extract action buttons (not inside forms as submit)."""
    buttons = []
    
    for btn in soup.find_all(["button", "a"]):
        text = btn.get_text(strip=True)
        if not text or len(text) > 80:
            continue

        classes = " ".join(btn.get("class", []))
        
        # Skip navigation links (already captured)
        if btn.name == "a" and btn.find_parent("nav"):
            continue

        # Check if it's an action-like element
        action_keywords = ["create", "add", "new", "edit", "delete", "remove", "save",
                          "submit", "cancel", "update", "publish", "export", "import",
                          "upload", "download", "approve", "reject", "send", "confirm"]
        
        is_action = (
            btn.name == "button" or
            any(kw in text.lower() for kw in action_keywords) or
            "btn" in classes
        )

        if is_action:
            buttons.append(ActionButton(
                text=text,
                button_type=btn.get("type", "button") if btn.name == "button" else "link",
                css_class=classes,
                is_primary="primary" in classes or "btn-primary" in classes,
            ))

    return buttons


def _extract_table_headers(soup: BeautifulSoup) -> list[list[str]]:
    """Extract table column headers (reveals entity structure)."""
    headers_list = []
    for table in soup.find_all("table"):
        thead = table.find("thead")
        if thead:
            for row in thead.find_all("tr"):
                headers = [th.get_text(strip=True) for th in row.find_all(["th", "td"])]
                if headers:
                    headers_list.append(headers)
        else:
            first_row = table.find("tr")
            if first_row:
                ths = first_row.find_all("th")
                if ths:
                    headers_list.append([th.get_text(strip=True) for th in ths])
    return headers_list


def _extract_sections(soup: BeautifulSoup) -> list[str]:
    """Extract page section headings."""
    sections = []
    for heading in soup.find_all(["h1", "h2", "h3", "h4"]):
        text = heading.get_text(strip=True)
        if text and len(text) < 150:
            sections.append(f"{heading.name}: {text}")
    return sections


def _extract_tabs(soup: BeautifulSoup) -> list[str]:
    """Extract tab labels."""
    tabs = []
    for tab in soup.find_all(attrs={"role": "tab"}):
        text = tab.get_text(strip=True)
        if text:
            tabs.append(text)
    # Also check for tab-like nav patterns
    for tablist in soup.find_all(attrs={"role": "tablist"}):
        for child in tablist.find_all(["a", "button", "li"]):
            text = child.get_text(strip=True)
            if text and text not in tabs:
                tabs.append(text)
    return tabs
