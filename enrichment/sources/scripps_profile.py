"""Scripps Institution of Oceanography profile scraper.

Scrapes the UCSD catalog faculty listing and profiles.ucsd.edu
to discover and extract SIO faculty data.
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseSource

logger = logging.getLogger(__name__)


class ScrippsProfileSource(BaseSource):
    source_name = "scripps_profile"
    min_request_interval = 2.0  # respect servers
    confidence = 1.0  # institutional source

    PROFILES_BASE = "https://profiles.ucsd.edu"
    CATALOG_URL = "https://catalog.ucsd.edu/faculty/SIO.html"
    SCRIPPS_PEOPLE_URL = "https://scripps.ucsd.edu/people"

    def fields_provided(self):
        return ["research_interests_enriched", "profile_url"]

    def fetch(self, faculty_dict):
        """Try multiple Scripps/UCSD sources to find profile data."""
        first = faculty_dict.get("first_name", "")
        last = faculty_dict.get("last_name", "")

        # Strategy 1: profiles.ucsd.edu (most reliable, richest data)
        profile_data = self._search_profiles_ucsd(first, last)
        if profile_data:
            return profile_data

        # Strategy 2: scripps.ucsd.edu individual profile pages
        scripps_data = self._search_scripps_website(first, last)
        if scripps_data:
            return scripps_data

        return None

    def _search_profiles_ucsd(self, first_name, last_name):
        """Search profiles.ucsd.edu for the faculty member."""
        search_url = f"{self.PROFILES_BASE}/search"
        resp = self._get(search_url, params={
            "from": "0",
            "searchtype": "people",
            "searchfor": f"{first_name} {last_name}",
        })
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")

        profile_link = None
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            link_text = link.get_text(strip=True).lower()
            full_name = f"{first_name} {last_name}".lower()
            if full_name in link_text and "/profile/" in href:
                profile_link = href if href.startswith("http") else f"{self.PROFILES_BASE}{href}"
                break

        if not profile_link:
            return None

        resp = self._get(profile_link)
        if not resp:
            return None

        return self._parse_profile_page(resp.text, profile_link)

    def _search_scripps_website(self, first_name, last_name):
        """Try to find a profile on scripps.ucsd.edu."""
        # Common URL patterns for Scripps faculty pages
        slug_patterns = [
            f"{first_name.lower()}-{last_name.lower()}",
            f"{first_name[0].lower()}{last_name.lower()}",
            last_name.lower(),
        ]

        for slug in slug_patterns:
            url = f"https://scripps.ucsd.edu/profiles/{slug}"
            resp = self._get(url)
            if resp and resp.status_code == 200:
                return self._parse_profile_page(resp.text, url)

        return None

    def _parse_profile_page(self, html, profile_url):
        """Extract research description from a profile page."""
        soup = BeautifulSoup(html, "html.parser")
        data = {"profile_url": profile_url}

        research_text_parts = []

        for heading in soup.find_all(["h2", "h3", "h4"]):
            heading_text = heading.get_text(strip=True).lower()
            if any(kw in heading_text for kw in [
                "research", "overview", "biography", "interests",
                "about", "expertise", "focus",
            ]):
                for sibling in heading.find_next_siblings():
                    if sibling.name in ("h2", "h3", "h4"):
                        break
                    text = sibling.get_text(strip=True)
                    if text:
                        research_text_parts.append(text)

        # Also check meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            research_text_parts.append(meta_desc["content"])

        if research_text_parts:
            combined = " ".join(research_text_parts)
            combined = re.sub(r"\s+", " ", combined).strip()
            if len(combined) > 2000:
                combined = combined[:2000]
            data["research_interests_enriched"] = combined

        return data if "research_interests_enriched" in data else None


def discover_sio_faculty_from_catalog():
    """Scrape the UCSD catalog SIO faculty listing page.

    Returns a list of dicts with {first_name, last_name, title} for each
    faculty member found.

    This is a standalone discovery function, not part of the enrichment
    pipeline. Use it to build the initial seed data.
    """
    import requests

    url = "https://catalog.ucsd.edu/faculty/SIO.html"
    headers = {
        "User-Agent": "UCSD-GrantMatch/1.0 (academic research tool; "
                       "contact: hwsph-grants@ucsd.edu)",
    }

    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    faculty = []

    # The catalog page typically lists faculty as paragraphs or list items
    # with format: "Last, First, Title" or "Last, First M., Title"
    # Try multiple parsing strategies

    # Strategy 1: Look for <p> or <li> elements with faculty entries
    for el in soup.find_all(["p", "li", "div"]):
        text = el.get_text(strip=True)
        entry = _parse_faculty_entry(text)
        if entry:
            faculty.append(entry)

    # Deduplicate by (first_name, last_name)
    seen = set()
    unique = []
    for f in faculty:
        key = (f["first_name"].lower(), f["last_name"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(f)

    return unique


def discover_sio_faculty_from_profiles():
    """Discover SIO faculty via profiles.ucsd.edu department search.

    Returns a list of dicts with {first_name, last_name, title, profile_url}.
    """
    import requests

    session = requests.Session()
    session.headers.update({
        "User-Agent": "UCSD-GrantMatch/1.0 (academic research tool; "
                       "contact: hwsph-grants@ucsd.edu)",
    })

    faculty = []
    offset = 0
    page_size = 25

    while True:
        url = "https://profiles.ucsd.edu/search"
        resp = session.get(url, params={
            "from": str(offset),
            "searchtype": "people",
            "searchfor": "",
            "searchdept": "Scripps Institution of Oceanography",
        }, timeout=30)

        if not resp or resp.status_code != 200:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        page_entries = []

        for card in soup.find_all(["div", "li", "article"], class_=True):
            name_el = card.find(["a", "h3", "h4"], href=True)
            if not name_el:
                continue

            href = name_el.get("href", "")
            if "/profile/" not in href:
                continue

            name_text = name_el.get_text(strip=True)
            title_el = card.find(["span", "p"], class_=lambda c: c and "title" in c.lower()) if card else None
            title = title_el.get_text(strip=True) if title_el else ""

            parts = name_text.split(",", 1)
            if len(parts) == 2:
                last_name = parts[0].strip()
                first_name = parts[1].strip().split()[0] if parts[1].strip() else ""
            else:
                name_parts = name_text.strip().split()
                if len(name_parts) >= 2:
                    first_name = name_parts[0]
                    last_name = name_parts[-1]
                else:
                    continue

            profile_url = href if href.startswith("http") else f"https://profiles.ucsd.edu{href}"

            page_entries.append({
                "first_name": first_name,
                "last_name": last_name,
                "title": title,
                "profile_url": profile_url,
            })

        faculty.extend(page_entries)

        # If we got fewer results than page size, we're done
        if len(page_entries) < page_size:
            break

        offset += page_size

        # Safety limit
        if offset > 500:
            break

    return faculty


# Title patterns for parsing catalog entries
_TITLE_PATTERNS = [
    "Professor", "Associate Professor", "Assistant Professor",
    "Adjunct Professor", "Professor Emeritus", "Professor Emerita",
    "Research Scientist", "Senior Lecturer", "Lecturer",
    "Distinguished Professor",
]


def _parse_faculty_entry(text):
    """Try to parse a catalog-style faculty entry.

    Common formats:
    - "Adams, Peter B., B.S., Ph.D., Professor"
    - "Baker, Jane, Ph.D., Associate Professor of ..."
    """
    if not text or len(text) < 5 or len(text) > 500:
        return None

    # Must contain a comma (Last, First format)
    if "," not in text:
        return None

    # Must contain a recognized title
    title = ""
    for t in _TITLE_PATTERNS:
        if t.lower() in text.lower():
            title = t
            break
    if not title:
        return None

    # Parse: "Last, First [Middle] [Degrees], Title [of ...]"
    parts = text.split(",")
    if len(parts) < 2:
        return None

    last_name = parts[0].strip()
    # First name is typically the first word after the first comma
    first_part = parts[1].strip()
    first_name = first_part.split()[0] if first_part else ""

    # Extract degrees (common academic degree patterns)
    degree_pattern = r'\b(Ph\.?D\.?|M\.?D\.?|M\.?S\.?|B\.?S\.?|B\.?A\.?|M\.?A\.?|M\.?P\.?H\.?|Dr\.?P\.?H\.?|Sc\.?D\.?|J\.?D\.?|M\.?B\.?A\.?)\b'
    degrees = re.findall(degree_pattern, text, re.IGNORECASE)
    # Normalize degree formatting
    degrees = [d.replace(".", "").upper() for d in degrees]
    # Deduplicate while preserving order
    seen = set()
    degrees = [d for d in degrees if not (d in seen or seen.add(d))]

    if not first_name or not last_name:
        return None

    # Filter out obviously wrong entries
    if any(c.isdigit() for c in last_name):
        return None

    return {
        "first_name": first_name,
        "last_name": last_name,
        "title": title,
        "degrees": degrees if degrees else [],
    }
