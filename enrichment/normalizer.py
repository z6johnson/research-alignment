"""LLM-based data normalizer for enrichment data.

Takes raw data from multiple sources and produces structured,
normalized faculty profile fields using LiteLLM.
"""

import json
import logging

from utils.grant_matcher import _call_llm, _parse_json_response

logger = logging.getLogger(__name__)

NORMALIZE_SYSTEM_PROMPT = """\
You are an academic profile analyst. You will receive raw data about a \
faculty member collected from multiple public sources (university profile, \
NIH grants, PubMed publications). Your task is to produce a clean, \
structured summary of their research expertise.

Rules:
1. Merge and deduplicate information from all sources.
2. Preserve factual accuracy — do not invent expertise not supported by the data.
3. When sources conflict, prefer the university profile over other sources.
4. Be concise but comprehensive.

Return ONLY valid JSON with this structure:
{
  "research_interests_enriched": "A 2-4 sentence narrative summary of their \
research focus areas, suitable for matching against funding opportunities.",
  "expertise_keywords": ["list", "of", "specific", "expertise", "keywords"],
  "methodologies": ["research methods they use, e.g., RCT, cohort study, ..."],
  "disease_areas": ["specific diseases or health conditions they study"],
  "populations": ["populations they study, e.g., adolescents, refugees, ..."]
}

If there is insufficient data for a field, use an empty list or null."""


def normalize_faculty_data(faculty_dict, raw_enrichment_data):
    """Use LLM to produce structured profile fields from raw enrichment data.

    Args:
        faculty_dict: Current faculty record dict.
        raw_enrichment_data: Dict mapping source_name -> raw data dict.

    Returns:
        Dict with normalized fields, or None if normalization fails.
    """
    # Build the context for the LLM
    parts = []

    name = f"{faculty_dict.get('first_name', '')} {faculty_dict.get('last_name', '')}"
    title = faculty_dict.get("title", "")
    parts.append(f"Faculty: {name}, {title}")

    if faculty_dict.get("research_interests"):
        parts.append(
            f"Original research interests (from university directory): "
            f"{faculty_dict['research_interests']}"
        )

    for source_name, data in raw_enrichment_data.items():
        if not data:
            continue

        if source_name == "ucsd_profile" and data.get("research_interests_enriched"):
            parts.append(
                f"UCSD Profile description: {data['research_interests_enriched']}"
            )

        if source_name == "nih_reporter" and data.get("funded_grants"):
            grants_text = []
            for g in data["funded_grants"][:10]:
                grants_text.append(
                    f"- {g.get('title', 'Untitled')} "
                    f"({g.get('agency', 'NIH')})"
                )
                if g.get("abstract"):
                    grants_text.append(f"  Abstract excerpt: {g['abstract'][:200]}")
            parts.append("NIH-funded grants:\n" + "\n".join(grants_text))

        if source_name == "pubmed" and data.get("recent_publications"):
            pubs_text = []
            for p in data["recent_publications"][:10]:
                line = f"- {p.get('title', 'Untitled')}"
                if p.get("journal"):
                    line += f" ({p['journal']}"
                    if p.get("year"):
                        line += f", {p['year']}"
                    line += ")"
                pubs_text.append(line)
                if p.get("mesh_terms"):
                    pubs_text.append(f"  MeSH: {', '.join(p['mesh_terms'][:5])}")
            parts.append("Recent PubMed publications:\n" + "\n".join(pubs_text))

        if source_name == "orcid" and data.get("works_count"):
            parts.append(f"ORCID: {data['works_count']} total works")
            if data.get("recent_works"):
                parts.append(
                    "Recent ORCID works:\n" +
                    "\n".join(f"- {w}" for w in data["recent_works"][:5])
                )

    if len(parts) <= 1:
        # Only have the name — not enough data to normalize
        return None

    user_prompt = "\n\n".join(parts)

    try:
        raw = _call_llm(NORMALIZE_SYSTEM_PROMPT, user_prompt, max_tokens=1000, temperature=0.1)
        result = _parse_json_response(raw)
        return result
    except Exception:
        logger.exception("LLM normalization failed for %s", name)
        return None
