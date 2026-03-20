"""UCSD faculty profile scraper.

Fetches public faculty profile pages from profiles.ucsd.edu to extract
research descriptions, bio text, lab affiliations, and email addresses.
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseSource

logger = logging.getLogger(__name__)

# Regex for @ucsd.edu addresses, reused across methods
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]*ucsd\.edu")


class UCSDProfileSource(BaseSource):
    source_name = "ucsd_profile"
    min_request_interval = 2.0  # respect the server: 1 req per 2 seconds
    confidence = 1.0  # institutional source — highest confidence

    PROFILES_BASE = "https://profiles.ucsd.edu"

    # Jacobs department websites — each has faculty pages with contact info
    DEPT_FACULTY_URLS = {
        "Bioengineering": "https://be.ucsd.edu/faculty",
        "Chemical and Nano Engineering": "https://ceng.ucsd.edu/faculty",
        "Computer Science & Engineering": "https://cse.ucsd.edu/people/faculty",
        "Electrical and Computer Engineering": "https://ece.ucsd.edu/people",
        "Mechanical & Aerospace Engineering": "https://mae.ucsd.edu/people/faculty",
        "Structural Engineering": "https://se.ucsd.edu/people/faculty",
        "NanoEngineering": "https://nanoengineering.ucsd.edu/faculty",
    }

    # Generic/shared emails that should never be assigned to individual faculty
    BLOCKED_EMAILS = frozenset({
        "ctri-support@ucsd.edu",
        "support@ucsd.edu",
        "info@ucsd.edu",
        "webmaster@ucsd.edu",
        "jacobsschool@ucsd.edu",
        "hwsph-grants@ucsd.edu",
        "admissions@ucsd.edu",
        "registrar@ucsd.edu",
    })

    # Common generic local-part prefixes that are never personal
    _GENERIC_PREFIXES = frozenset({
        "info", "support", "admin", "admissions", "help", "contact",
        "office", "dept", "department", "registrar", "webmaster",
        "grants", "ctri-support", "communications", "events",
    })

    def fields_provided(self):
        return ["research_interests_enriched", "profile_url", "email"]

    @classmethod
    def _is_plausible_faculty_email(cls, email, first_name, last_name):
        """Check whether *email* plausibly belongs to this faculty member.

        Heuristic: the local part (before @) should contain at least a
        3-character prefix of the first or last name, **or** the first initial.
        This catches patterns like ``jsmith@``, ``j3smith@``, ``smithj@``,
        ``john.smith@``, and the common UCSD ``abc123@`` (initials + digits)
        format.

        Generic prefixes (``info``, ``support``, etc.) are always rejected,
        even if they happen to overlap with a name fragment.
        """
        local = email.split("@")[0].lower().replace(".", "").replace("-", "")
        first = first_name.lower()
        last = last_name.lower()

        # Reject known generic prefixes
        raw_local = email.split("@")[0].lower()
        if raw_local in cls._GENERIC_PREFIXES:
            return False

        # Accept if first initial is present AND any part of last name (≥3 chars)
        has_first_initial = first and first[0] in local
        has_last_fragment = last and len(last) >= 3 and last[:3] in local

        # Accept if a ≥3-char prefix of first or last name appears
        has_first_fragment = first and len(first) >= 3 and first[:3] in local
        has_name_signal = has_last_fragment or has_first_fragment or (has_first_initial and has_last_fragment)

        if has_name_signal:
            return True

        # Accept single-initial + digits pattern (e.g. j4smith, abc012) if
        # at least the first initial matches
        if has_first_initial and re.match(r"[a-z]{1,3}\d+", local):
            return True

        return False

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
        if profile_data and not profile_data.get("email"):
            dept = faculty_dict.get("subdepartment", "")
            email = self._search_dept_website(first, last, dept)
            if email:
                profile_data["email"] = email

        # Validate any email we found against the faculty name
        if profile_data and profile_data.get("email"):
            if not self._is_plausible_faculty_email(profile_data["email"], first, last):
                logger.warning(
                    "Dropping implausible email %s for %s %s",
                    profile_data["email"], first, last,
                )
                del profile_data["email"]

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
        if not data.get("email"):
            dept = faculty_dict.get("subdepartment", "")
            email = self._search_dept_website(first, last, dept)
            if email:
                data["email"] = email

        # Validate fallback email too
        if data.get("email") and not self._is_plausible_faculty_email(data["email"], first, last):
            logger.warning(
                "Dropping implausible fallback email %s for %s %s",
                data["email"], first, last,
            )
            del data["email"]

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

        Tries multiple strategies in order of reliability:
        1. mailto: links within the main content area
        2. mailto: links anywhere on the page
        3. Regex scan within contact/info sections only

        Filters out known generic/support addresses (BLOCKED_EMAILS).
        Does NOT do a full-page regex scan — that is the source of most
        false positives (footer links, sidebar widgets, etc.).
        """
        # Identify the main content area to prefer over page chrome
        content_area = (
            soup.find("main")
            or soup.find(id=re.compile(r"content|main|profile", re.I))
            or soup.find(class_=re.compile(r"content|main|profile", re.I))
            or soup  # fall back to whole page for Strategy 1–2
        )

        # Strategy 1: mailto: links in main content area (most reliable)
        for link in content_area.find_all("a", href=True):
            href = link["href"]
            if href.startswith("mailto:"):
                addr = href.replace("mailto:", "").split("?")[0].strip().lower()
                if addr and "ucsd.edu" in addr and addr not in cls.BLOCKED_EMAILS:
                    return addr

        # Strategy 2: mailto: links anywhere on page (catches nav/sidebar contact)
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if href.startswith("mailto:"):
                addr = href.replace("mailto:", "").split("?")[0].strip().lower()
                if addr and "ucsd.edu" in addr and addr not in cls.BLOCKED_EMAILS:
                    return addr

        # Strategy 3: Regex scan scoped to contact/info sections only
        contact_sections = content_area.find_all(
            ["span", "p", "div", "li"],
            string=re.compile(r"email|contact|e-mail", re.I),
        )
        # Also check elements near headings that mention "contact"
        for heading in content_area.find_all(["h2", "h3", "h4", "dt", "label"]):
            if re.search(r"contact|email", heading.get_text(strip=True), re.I):
                for sib in heading.find_next_siblings():
                    if sib.name in ("h2", "h3", "h4"):
                        break
                    contact_sections.append(sib)

        for el in contact_sections:
            match = _EMAIL_RE.search(el.get_text())
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

        # Look for result rows/cards containing this person's name
        for container in soup.find_all(["tr", "div", "li", "article"]):
            text = container.get_text(strip=True).lower()
            if first_name.lower() in text and last_name.lower() in text:
                # Found a matching entry — prefer mailto: links
                for link in container.find_all("a", href=True):
                    href = link["href"]
                    if href.startswith("mailto:"):
                        addr = href.replace("mailto:", "").split("?")[0].strip().lower()
                        if "ucsd.edu" in addr and addr not in self.BLOCKED_EMAILS:
                            return addr
                # Fall back to regex within this name-matched container only
                match = _EMAIL_RE.search(container.get_text())
                if match:
                    addr = match.group(0).lower()
                    if addr not in self.BLOCKED_EMAILS:
                        return addr

        # Do NOT fall back to a broad page scan — that is how generic
        # emails (ctri-support, etc.) leak into faculty records.
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

    def _search_dept_website(self, first_name, last_name, subdepartment):
        """Search the faculty member's department website for their email.

        Many Jacobs School departments (CSE, ECE, MAE, etc.) maintain their
        own faculty pages that include contact info not found on the central
        profiles.ucsd.edu site.
        """
        if not subdepartment:
            return None

        # Find the department URL — try exact match first, then substring
        dept_url = self.DEPT_FACULTY_URLS.get(subdepartment)
        if not dept_url:
            subdept_lower = subdepartment.lower()
            for dept_name, url in self.DEPT_FACULTY_URLS.items():
                if dept_name.lower() in subdept_lower or subdept_lower in dept_name.lower():
                    dept_url = url
                    break
        if not dept_url:
            return None

        resp = self._get(dept_url)
        if not resp:
            return None

        soup = BeautifulSoup(resp.text, "html.parser")
        full_name = f"{first_name} {last_name}".lower()

        # Strategy: find a container that mentions this person's name,
        # then look for mailto links or email patterns within it
        for container in soup.find_all(["tr", "div", "li", "article", "td", "section"]):
            text = container.get_text(strip=True).lower()
            if first_name.lower() not in text or last_name.lower() not in text:
                continue

            # Check for mailto links
            for link in container.find_all("a", href=True):
                href = link["href"]
                if href.startswith("mailto:"):
                    addr = href.replace("mailto:", "").split("?")[0].strip().lower()
                    if addr and "ucsd.edu" in addr and addr not in self.BLOCKED_EMAILS:
                        return addr

            # Check for email pattern in text
            match = _EMAIL_RE.search(container.get_text())
            if match:
                addr = match.group(0).lower()
                if addr not in self.BLOCKED_EMAILS:
                    return addr

            # If the container has a link to an individual profile page, follow it
            for link in container.find_all("a", href=True):
                href = link["href"]
                link_text = link.get_text(strip=True).lower()
                if full_name in link_text or last_name.lower() in link_text:
                    if not href.startswith("http"):
                        # Reconstruct absolute URL from dept_url base
                        from urllib.parse import urljoin
                        href = urljoin(dept_url, href)
                    if "ucsd.edu" in href and href != dept_url:
                        detail_resp = self._get(href)
                        if detail_resp:
                            detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
                            email = self._extract_email_from_page(detail_soup)
                            if email:
                                return email
                        break  # Only follow one link per person

        return None

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
