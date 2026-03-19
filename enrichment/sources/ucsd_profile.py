"""UCSD faculty profile scraper.

Fetches public faculty profile pages from profiles.ucsd.edu to extract
research descriptions, bio text, lab affiliations, and email addresses.
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseSource

logger = logging.getLogger(__name__)


class UCSDProfileSource(BaseSource):
    source_name = "ucsd_profile"
    min_request_interval = 2.0  # respect the server: 1 req per 2 seconds
    confidence = 1.0  # institutional source — highest confidence

    PROFILES_BASE = "https://profiles.ucsd.edu"

    # Generic/shared emails that should never be assigned to individual faculty
    BLOCKED_EMAILS = frozenset({
        "ctri-support@ucsd.edu",
        "support@ucsd.edu",
        "info@ucsd.edu",
        "webmaster@ucsd.edu",
        "jacobsschool@ucsd.edu",
    })

    def fields_provided(self):
        return ["research_interests_enriched", "profile_url", "email"]

    def fetch(self, faculty_dict):
        """Scrape the UCSD profiles page for this faculty member."""
        first = faculty_dict.get("first_name", "")
        last = faculty_dict.get("last_name", "")

        # Try the profiles.ucsd.edu search (primary — has email + research)
        profile_data = self._search_profiles_ucsd(first, last)

        # If we got research data but no email, try supplementary sources
        if profile_data and not profile_data.get("email"):
            email = self._search_ucsd_directory(first, last)
            if email:
                profile_data["email"] = email
        if profile_data and not profile_data.get("email"):
            email = self._search_jacobsschool_profile(first, last)
            if email:
                profile_data["email"] = email

        if profile_data:
            return profile_data

        # No profile found — still try to get just an email
        data = {}
        email = self._search_ucsd_directory(first, last)
        if email:
            data["email"] = email
        if not data.get("email"):
            email = self._search_jacobsschool_profile(first, last)
            if email:
                data["email"] = email

        # Fallback: try hwsph directory page scrape (for HWSPH faculty)
        if not data:
            return self._search_hwsph_directory(first, last)

        return data if data else None

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

        # Find the profile link that matches this person
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

        # Fetch the individual profile page
        resp = self._get(profile_link)
        if not resp:
            return None

        return self._parse_profile_page(resp.text, profile_link)

    def _parse_profile_page(self, html, profile_url):
        """Extract research description and email from a profiles.ucsd.edu page."""
        soup = BeautifulSoup(html, "html.parser")
        data = {"profile_url": profile_url}

        # --- Email extraction ---
        email = self._extract_email_from_page(soup)
        if email:
            data["email"] = email

        # Look for research/overview section — common patterns in UCSD profiles
        research_text_parts = []

        for heading in soup.find_all(["h2", "h3", "h4"]):
            heading_text = heading.get_text(strip=True).lower()
            if any(kw in heading_text for kw in ["research", "overview", "biography", "interests"]):
                # Grab sibling elements until the next heading
                for sibling in heading.find_next_siblings():
                    if sibling.name in ("h2", "h3", "h4"):
                        break
                    text = sibling.get_text(strip=True)
                    if text:
                        research_text_parts.append(text)

        # Also check for meta description
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            research_text_parts.append(meta_desc["content"])

        if research_text_parts:
            combined = " ".join(research_text_parts)
            # Clean up whitespace
            combined = re.sub(r"\s+", " ", combined).strip()
            # Truncate to reasonable length
            if len(combined) > 2000:
                combined = combined[:2000]
            data["research_interests_enriched"] = combined

        # Return data if we found email or research interests
        if "research_interests_enriched" in data or "email" in data:
            return data
        return None

    @classmethod
    def _extract_email_from_page(cls, soup):
        """Extract a ucsd.edu email address from a profile page.

        Tries multiple strategies:
        1. mailto: links
        2. Structured contact info sections
        3. Regex scan of page text for ucsd.edu addresses

        Filters out known generic/support addresses (BLOCKED_EMAILS).
        """
        # Strategy 1: mailto: links (most reliable)
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if href.startswith("mailto:"):
                addr = href.replace("mailto:", "").split("?")[0].strip().lower()
                if addr and "ucsd.edu" in addr and addr not in cls.BLOCKED_EMAILS:
                    return addr

        # Strategy 2: Look for email in contact/info sections
        email_pattern = re.compile(
            r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]*ucsd\.edu",
        )
        for el in soup.find_all(["span", "p", "div", "a", "li"]):
            el_text = el.get_text(strip=True)
            match = email_pattern.search(el_text)
            if match:
                addr = match.group(0).lower()
                if addr not in cls.BLOCKED_EMAILS:
                    return addr

        # Strategy 3: Full-page regex (last resort)
        full_text = soup.get_text()
        match = email_pattern.search(full_text)
        if match:
            addr = match.group(0).lower()
            if addr not in cls.BLOCKED_EMAILS:
                return addr

        return None

    def _search_ucsd_directory(self, first_name, last_name):
        """Search the UCSD online directory for a faculty email.

        Uses the public directory search at directory.ucsd.edu which returns
        contact information for UCSD employees.
        """
        search_url = "https://directory.ucsd.edu/search"
        resp = self._get(search_url, params={
            "query": f"{first_name} {last_name}",
        })
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        full_name_lower = f"{first_name} {last_name}".lower()

        email_pattern = re.compile(
            r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]*ucsd\.edu",
        )

        # Look for result rows/cards containing this person's name
        for container in soup.find_all(["tr", "div", "li", "article"]):
            text = container.get_text(strip=True).lower()
            if first_name.lower() in text and last_name.lower() in text:
                # Found a matching entry — look for email
                for link in container.find_all("a", href=True):
                    href = link["href"]
                    if href.startswith("mailto:"):
                        addr = href.replace("mailto:", "").split("?")[0].strip().lower()
                        if "ucsd.edu" in addr:
                            return addr
                match = email_pattern.search(container.get_text())
                if match:
                    return match.group(0).lower()

        # Broader scan: any ucsd.edu email near the person's name on the page
        full_text = soup.get_text()
        # Find all email addresses on the page
        all_emails = email_pattern.findall(full_text)
        if len(all_emails) == 1:
            # If there's exactly one result, it's likely our person
            return all_emails[0].lower()

        return None

    def _search_jacobsschool_profile(self, first_name, last_name):
        """Try to find email from a Jacobs School individual profile page.

        Jacobs School profile URLs follow patterns like:
        jacobsschool.ucsd.edu/people/profile/first-last
        """
        slug = f"{first_name.lower()}-{last_name.lower()}"
        url = f"https://jacobsschool.ucsd.edu/people/profile/{slug}"
        resp = self._get(url)
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        return self._extract_email_from_page(soup)

    def _search_hwsph_directory(self, first_name, last_name):
        """Fallback: search the HWSPH faculty directory for a bio link."""
        url = "https://hwsph.ucsd.edu/people/faculty/faculty-directory.html"
        resp = self._get(url)
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        full_name = f"{first_name} {last_name}".lower()

        for link in soup.find_all("a", href=True):
            if full_name in link.get_text(strip=True).lower():
                href = link["href"]
                if not href.startswith("http"):
                    href = f"https://hwsph.ucsd.edu{href}"

                detail_resp = self._get(href)
                if detail_resp:
                    return self._parse_profile_page(detail_resp.text, href)

        return None
