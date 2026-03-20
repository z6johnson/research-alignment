"""PubMed / NCBI E-utilities client.

Queries PubMed for publications by a faculty member.
API docs: https://www.ncbi.nlm.nih.gov/books/NBK25500/

Free API key available at https://www.ncbi.nlm.nih.gov/account/ (optional,
increases rate limit from 3/sec to 10/sec).
"""

import logging
import os
import re
import xml.etree.ElementTree as ET

from .base import BaseSource

logger = logging.getLogger(__name__)

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class PubMedSource(BaseSource):
    source_name = "pubmed"
    min_request_interval = 0.35  # ~3 req/sec without API key
    confidence = 0.7

    def __init__(self):
        super().__init__()
        self._api_key = os.getenv("NCBI_API_KEY", "")
        if self._api_key:
            self.min_request_interval = 0.1  # 10 req/sec with key

    _EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]*ucsd\.edu")

    def fields_provided(self):
        return ["recent_publications", "email"]

    def fetch(self, faculty_dict):
        """Search PubMed for recent publications by this faculty member."""
        first = faculty_dict.get("first_name", "")
        last = faculty_dict.get("last_name", "")

        # Build search query with affiliation filter
        query = f'{last} {first[0]}[Author] AND "University of California San Diego"[Affiliation]'

        # Step 1: Search for PMIDs
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": 20,
            "sort": "date",
            "retmode": "json",
        }
        if self._api_key:
            params["api_key"] = self._api_key

        resp = self._get(ESEARCH_URL, params=params)
        if not resp:
            return None

        try:
            search_data = resp.json()
        except ValueError:
            return None

        id_list = search_data.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return None

        # Step 2: Fetch article details
        fetch_params = {
            "db": "pubmed",
            "id": ",".join(id_list),
            "retmode": "xml",
        }
        if self._api_key:
            fetch_params["api_key"] = self._api_key

        resp = self._get(EFETCH_URL, params=fetch_params)
        if not resp:
            return None

        publications, author_email = self._parse_pubmed_xml(resp.text, last)
        if not publications:
            return None

        result = {
            "recent_publications": publications,
            "_source_url": f"{ESEARCH_URL}?term={query}",
        }
        if author_email:
            result["email"] = author_email
        return result

    def _parse_pubmed_xml(self, xml_text, last_name=""):
        """Parse PubMed XML response into publication dicts.

        Also extracts corresponding author @ucsd.edu email from
        AffiliationInfo elements, which often embed email addresses.

        Returns:
            Tuple of (publications_list, author_email_or_None).
        """
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            logger.warning("Failed to parse PubMed XML response")
            return [], None

        publications = []
        author_email = None

        for article in root.findall(".//PubmedArticle"):
            pub = {}

            # Title
            title_el = article.find(".//ArticleTitle")
            if title_el is not None and title_el.text:
                pub["title"] = title_el.text.strip()

            # Year
            year_el = article.find(".//PubDate/Year")
            if year_el is not None and year_el.text:
                pub["year"] = int(year_el.text)

            # Journal
            journal_el = article.find(".//Journal/Title")
            if journal_el is not None and journal_el.text:
                pub["journal"] = journal_el.text.strip()

            # MeSH terms
            mesh_terms = []
            for mesh in article.findall(".//MeshHeading/DescriptorName"):
                if mesh.text:
                    mesh_terms.append(mesh.text)
            if mesh_terms:
                pub["mesh_terms"] = mesh_terms

            # Abstract (truncated)
            abstract_parts = []
            for abs_text in article.findall(".//AbstractText"):
                if abs_text.text:
                    abstract_parts.append(abs_text.text.strip())
            if abstract_parts:
                abstract = " ".join(abstract_parts)
                pub["abstract"] = abstract[:500]

            if pub.get("title"):
                publications.append(pub)

            # Extract ucsd.edu email from affiliation or author info
            if not author_email:
                for aff in article.findall(".//AffiliationInfo/Affiliation"):
                    if aff.text:
                        match = self._EMAIL_RE.search(aff.text)
                        if match:
                            author_email = match.group(0).lower()
                            break
                # Also check AuthorList for email attributes
                if not author_email:
                    for author_el in article.findall(".//Author"):
                        # Some PubMed records store email in Identifier
                        for ident in author_el.findall("Identifier"):
                            src = (ident.get("Source") or "").lower()
                            if src == "email" and ident.text:
                                addr = ident.text.strip().lower()
                                if "ucsd.edu" in addr:
                                    author_email = addr
                                    break
                        if author_email:
                            break

        return publications, author_email
