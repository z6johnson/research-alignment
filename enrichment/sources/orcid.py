"""ORCID public API client.

Queries the public ORCID API to find researcher profiles and extract
works, employment, and funding data. No authentication required for
public records.

API docs: https://info.orcid.org/documentation/api-tutorials/
"""

import logging

from .base import BaseSource

logger = logging.getLogger(__name__)

SEARCH_URL = "https://pub.orcid.org/v3.0/search/"
RECORD_URL = "https://pub.orcid.org/v3.0/{orcid_id}"


class ORCIDSource(BaseSource):
    source_name = "orcid"
    min_request_interval = 1.0
    confidence = 0.9  # self-reported by researcher

    def __init__(self):
        super().__init__()
        self._session.headers.update({
            "Accept": "application/json",
        })

    def fields_provided(self):
        return ["orcid", "recent_publications", "funded_grants", "email"]

    def fetch(self, faculty_dict):
        """Search ORCID for this faculty member and extract their record."""
        first = faculty_dict.get("first_name", "")
        last = faculty_dict.get("last_name", "")

        # If we already have their ORCID ID, go directly to the record
        existing_orcid = faculty_dict.get("orcid")
        if existing_orcid:
            return self._fetch_record(existing_orcid, first, last)

        # Otherwise, search by name + affiliation
        orcid_id = self._search_orcid(first, last)
        if not orcid_id:
            return None

        return self._fetch_record(orcid_id, first, last)

    def _search_orcid(self, first_name, last_name):
        """Search ORCID for a researcher by name and UCSD affiliation."""
        query = (
            f'given-names:{first_name} AND family-name:{last_name} '
            f'AND affiliation-org-name:"University of California San Diego"'
        )

        resp = self._get(SEARCH_URL, params={"q": query, "rows": 5})
        if not resp:
            return None

        try:
            data = resp.json()
        except ValueError:
            return None

        results = data.get("result") or []
        if not results:
            # Try broader search without affiliation
            query_broad = f"given-names:{first_name} AND family-name:{last_name}"
            resp = self._get(SEARCH_URL, params={"q": query_broad, "rows": 3})
            if not resp:
                return None
            try:
                data = resp.json()
            except ValueError:
                return None
            results = data.get("result") or []

        if not results:
            return None

        # Return the first match's ORCID ID
        orcid_id = results[0].get("orcid-identifier", {}).get("path")
        return orcid_id

    def _fetch_record(self, orcid_id, first_name, last_name):
        """Fetch the full ORCID record and extract relevant data."""
        url = RECORD_URL.format(orcid_id=orcid_id)
        resp = self._get(url)
        if not resp:
            return None

        try:
            record = resp.json()
        except ValueError:
            return None

        result = {
            "orcid": orcid_id,
            "_source_url": f"https://orcid.org/{orcid_id}",
        }

        # Extract email from ORCID person record
        email = self._extract_email(record, first_name, last_name)
        if email:
            result["email"] = email

        # Extract works (publications)
        works = self._extract_works(record)
        if works:
            result["recent_publications"] = works

        # Extract fundings (grants)
        fundings = self._extract_fundings(record)
        if fundings:
            result["funded_grants"] = fundings

        # Provide works_count for the normalizer
        works_section = (
            record.get("activities-summary", {})
            .get("works", {})
            .get("group", [])
        )
        result["works_count"] = len(works_section)

        # Extract recent work titles for normalizer
        recent_works = []
        for group in works_section[:10]:
            summaries = group.get("work-summary", [])
            if summaries:
                title_obj = summaries[0].get("title", {})
                title_val = title_obj.get("title", {}).get("value", "")
                if title_val:
                    recent_works.append(title_val)
        if recent_works:
            result["recent_works"] = recent_works

        return result if len(result) > 2 else None  # More than just orcid + _source_url

    @staticmethod
    def _extract_email(record, first_name, last_name):
        """Extract a ucsd.edu email from the ORCID person record.

        ORCID profiles may list one or more email addresses under
        person -> emails -> email.  We prefer @ucsd.edu addresses but
        accept @eng.ucsd.edu and other sub-domains.
        """
        emails_section = (
            record.get("person", {})
            .get("emails", {})
            .get("email", [])
        )
        ucsd_emails = []
        for entry in emails_section:
            addr = entry.get("email", "").strip().lower()
            if addr and "ucsd.edu" in addr:
                ucsd_emails.append(addr)

        if not ucsd_emails:
            return None

        # If multiple, prefer one that contains part of the person's name
        first = first_name.lower()
        last = last_name.lower()
        for addr in ucsd_emails:
            local = addr.split("@")[0]
            if (last and last[:3] in local) or (first and first[:3] in local):
                return addr

        # Fall back to first ucsd.edu address found
        return ucsd_emails[0]

    def _extract_works(self, record):
        """Extract recent publications from ORCID record."""
        works_groups = (
            record.get("activities-summary", {})
            .get("works", {})
            .get("group", [])
        )

        publications = []
        for group in works_groups[:20]:  # Most recent 20
            summaries = group.get("work-summary", [])
            if not summaries:
                continue
            summary = summaries[0]

            pub = {}
            title_obj = summary.get("title", {})
            title_val = title_obj.get("title", {}).get("value", "")
            if title_val:
                pub["title"] = title_val

            # Year
            pub_date = summary.get("publication-date") or {}
            year_val = pub_date.get("year", {})
            if isinstance(year_val, dict) and year_val.get("value"):
                try:
                    pub["year"] = int(year_val["value"])
                except (ValueError, TypeError):
                    pass

            # Journal
            journal = summary.get("journal-title")
            if journal and isinstance(journal, dict):
                pub["journal"] = journal.get("value", "")
            elif isinstance(journal, str):
                pub["journal"] = journal

            if pub.get("title"):
                publications.append(pub)

        return publications or None

    def _extract_fundings(self, record):
        """Extract funding/grants from ORCID record."""
        funding_groups = (
            record.get("activities-summary", {})
            .get("fundings", {})
            .get("group", [])
        )

        grants = []
        for group in funding_groups[:15]:
            summaries = group.get("funding-summary", [])
            if not summaries:
                continue
            summary = summaries[0]

            grant = {}
            title_obj = summary.get("title", {})
            title_val = title_obj.get("title", {}).get("value", "")
            if title_val:
                grant["title"] = title_val

            org = summary.get("organization", {})
            if org.get("name"):
                grant["agency"] = org["name"]

            # Dates
            start = summary.get("start-date") or {}
            if start.get("year", {}).get("value"):
                grant["start_date"] = start["year"]["value"]

            end = summary.get("end-date") or {}
            if end and end.get("year", {}).get("value"):
                grant["end_date"] = end["year"]["value"]

            if grant.get("title"):
                grants.append(grant)

        return grants or None
