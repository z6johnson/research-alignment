"""Enrichment pipeline orchestrator.

Coordinates fetching data from multiple sources, normalizing it with LLM,
and writing enriched data back to the database.
"""

import json
import logging

from models import EnrichmentLog, Faculty, db
from .normalizer import normalize_faculty_data
from .sources.nih_reporter import NIHReporterSource
from .sources.orcid import ORCIDSource
from .sources.pubmed import PubMedSource
from .sources.ucsd_profile import UCSDProfileSource

logger = logging.getLogger(__name__)

# Registry of available sources
SOURCE_CLASSES = {
    "ucsd_profile": UCSDProfileSource,
    "nih_reporter": NIHReporterSource,
    "pubmed": PubMedSource,
    "orcid": ORCIDSource,
}

# Fields that can be directly written to the Faculty model (non-JSON)
DIRECT_FIELDS = {"profile_url", "orcid", "google_scholar_id", "h_index"}

# Fields that are JSON arrays and should be replaced wholesale
JSON_FIELDS = {"funded_grants", "recent_publications", "expertise_keywords"}

# Fields produced by the LLM normalizer
NORMALIZED_FIELDS = {
    "research_interests_enriched",
    "expertise_keywords",
}


def enrich_faculty(faculty_id, sources=None, dry_run=False):
    """Enrich a single faculty member from specified sources.

    Args:
        faculty_id: ID of the faculty member.
        sources: List of source names to use, or None for all.
        dry_run: If True, fetch data but don't write to DB.

    Returns:
        Dict summarizing what was enriched.
    """
    faculty = Faculty.query.get(faculty_id)
    if not faculty:
        logger.error("Faculty ID %d not found.", faculty_id)
        return {"error": f"Faculty ID {faculty_id} not found"}

    faculty_dict = faculty.to_dict()
    name = f"{faculty.first_name} {faculty.last_name}"
    logger.info("Enriching: %s (ID: %d)", name, faculty_id)

    source_names = sources or list(SOURCE_CLASSES.keys())
    raw_data = {}
    summary = {"faculty_id": faculty_id, "name": name, "sources": {}}

    # Phase 1: Fetch from all sources
    for source_name in source_names:
        if source_name not in SOURCE_CLASSES:
            logger.warning("Unknown source: %s", source_name)
            continue

        source = SOURCE_CLASSES[source_name]()
        try:
            result = source.fetch(faculty_dict)
        except Exception:
            logger.exception("Source %s failed for %s", source_name, name)
            result = None

        if result:
            raw_data[source_name] = result
            summary["sources"][source_name] = {
                "status": "data_found",
                "fields": [k for k in result if not k.startswith("_")],
            }
        else:
            summary["sources"][source_name] = {"status": "no_data"}

    if not raw_data:
        logger.info("No enrichment data found for %s", name)
        return summary

    if dry_run:
        summary["dry_run"] = True
        summary["raw_data"] = {
            k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")}
            for k, v in raw_data.items()
        }
        return summary

    # Phase 2: Write direct fields to DB
    for source_name, data in raw_data.items():
        source_cls = SOURCE_CLASSES[source_name]
        for field, value in data.items():
            if field.startswith("_"):
                continue

            if field in DIRECT_FIELDS or field in JSON_FIELDS:
                old_value = getattr(faculty, field, None)
                if old_value is not None and field not in JSON_FIELDS:
                    continue  # Don't overwrite existing direct fields

                old_str = json.dumps(old_value) if isinstance(old_value, (list, dict)) else str(old_value)
                new_str = json.dumps(value) if isinstance(value, (list, dict)) else str(value)

                setattr(faculty, field, value)

                log = EnrichmentLog(
                    faculty_id=faculty_id,
                    source_name=source_name,
                    source_url=data.get("_source_url"),
                    field_updated=field,
                    old_value=old_str,
                    new_value=new_str,
                    confidence=source_cls.confidence if hasattr(source_cls, 'confidence') else 0.5,
                    method="api" if source_name != "ucsd_profile" else "scrape",
                    raw_response=json.dumps(data)[:5000],
                )
                db.session.add(log)

    # Phase 3: LLM normalization
    normalized = normalize_faculty_data(faculty_dict, raw_data)
    if normalized:
        for field in ("research_interests_enriched", "expertise_keywords"):
            value = normalized.get(field)
            if value:
                old_value = getattr(faculty, field, None)
                old_str = json.dumps(old_value) if isinstance(old_value, (list, dict)) else str(old_value)
                new_str = json.dumps(value) if isinstance(value, (list, dict)) else str(value)

                setattr(faculty, field, value)

                log = EnrichmentLog(
                    faculty_id=faculty_id,
                    source_name="llm_normalizer",
                    field_updated=field,
                    old_value=old_str,
                    new_value=new_str,
                    confidence=0.85,
                    method="llm_extraction",
                )
                db.session.add(log)

        summary["normalization"] = "success"
    else:
        summary["normalization"] = "skipped_or_failed"

    db.session.commit()
    logger.info("Enrichment complete for %s", name)
    return summary


def enrich_all(sources=None, faculty_ids=None, dry_run=False, progress_callback=None):
    """Enrich all (or specified) faculty members.

    Args:
        sources: List of source names to use, or None for all.
        faculty_ids: List of specific faculty IDs, or None for all.
        dry_run: If True, fetch but don't write.
        progress_callback: Optional callable(completed, total) for progress tracking.

    Returns:
        List of per-faculty summary dicts.
    """
    if faculty_ids:
        faculty_list = Faculty.query.filter(Faculty.id.in_(faculty_ids)).all()
    else:
        faculty_list = Faculty.query.all()

    logger.info("Starting enrichment for %d faculty members.", len(faculty_list))
    results = []

    for i, faculty in enumerate(faculty_list):
        result = enrich_faculty(faculty.id, sources=sources, dry_run=dry_run)
        results.append(result)
        if progress_callback:
            progress_callback(i + 1, len(faculty_list))

    # Summary stats
    enriched_count = sum(
        1 for r in results
        if any(s.get("status") == "data_found" for s in r.get("sources", {}).values())
    )
    logger.info(
        "Enrichment complete. %d/%d faculty had data found.",
        enriched_count, len(results),
    )

    return results


def get_enrichment_status():
    """Return a summary of enrichment coverage."""
    total = Faculty.query.count()
    with_original = Faculty.query.filter(Faculty.research_interests.isnot(None)).count()
    with_enriched = Faculty.query.filter(Faculty.research_interests_enriched.isnot(None)).count()
    with_grants = Faculty.query.filter(Faculty.funded_grants.isnot(None)).count()
    with_pubs = Faculty.query.filter(Faculty.recent_publications.isnot(None)).count()

    return {
        "total_faculty": total,
        "with_original_interests": with_original,
        "with_enriched_interests": with_enriched,
        "with_funded_grants": with_grants,
        "with_publications": with_pubs,
        "coverage_original": round(with_original / total * 100, 1) if total else 0,
        "coverage_enriched": round(with_enriched / total * 100, 1) if total else 0,
    }
