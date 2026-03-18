"""NSF Award Search API client.

Queries the public NSF Award Search API to find grants associated with
a faculty member at UCSD. No API key required.
Docs: https://www.research.gov/common/webapi/awardapisearch-v1.htm
"""

import logging

from .base import BaseSource

logger = logging.getLogger(__name__)

API_BASE = "https://api.nsf.gov/services/v1/awards.json"

# Fields we request from the NSF API
PRINT_FIELDS = ",".join([
    "id", "title", "piFirstName", "piLastName",
    "startDate", "expDate", "abstractText",
    "fundsObligatedAmt", "agency", "fundProgramName",
    "coPDPI",
])


class NSFAwardSource(BaseSource):
    source_name = "nsf_awards"
    min_request_interval = 1.0  # be polite
    confidence = 0.8  # verified federal records

    def fields_provided(self):
        return ["funded_grants"]

    def fetch(self, faculty_dict):
        """Search NSF Award Search for grants where this person is PI."""
        first = faculty_dict.get("first_name", "")
        last = faculty_dict.get("last_name", "")

        params = {
            "piFirstName": first,
            "piLastName": last,
            "awardeeName": "University of California San Diego",
            "printFields": PRINT_FIELDS,
            "offset": "0",
            "rpp": "25",  # results per page
        }

        resp = self._get(API_BASE, params=params)
        if not resp:
            return None

        try:
            data = resp.json()
        except ValueError:
            logger.warning("Invalid JSON from NSF API for %s %s", first, last)
            return None

        response_obj = data.get("response", {})
        awards = response_obj.get("award") or []
        if not awards:
            return None

        grants = []
        for award in awards:
            grant = {
                "title": (award.get("title") or "").strip(),
                "agency": "NSF",
                "nsf_program": award.get("fundProgramName", ""),
                "amount": award.get("fundsObligatedAmt"),
                "start_date": award.get("startDate"),
                "end_date": award.get("expDate"),
                "nsf_award_id": award.get("id", ""),
            }

            # Abstract (truncated to 500 chars like NIH source)
            abstract = award.get("abstractText", "")
            if abstract:
                grant["abstract"] = abstract[:500]

            # Extract co-PIs
            co_pis_raw = award.get("coPDPI") or []
            if isinstance(co_pis_raw, str):
                co_pis_raw = [co_pis_raw]
            co_pis = [
                name.strip() for name in co_pis_raw
                if name.strip() and last.lower() not in name.lower()
            ]
            if co_pis:
                grant["co_pis"] = co_pis

            grants.append(grant)

        return {
            "funded_grants": grants,
            "_source_url": f"{API_BASE} (PI: {first} {last}, UCSD)",
        }
