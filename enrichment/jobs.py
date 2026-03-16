"""Background job manager for enrichment pipeline.

Uses a simple threading approach — sufficient for a pilot with a single
background job at a time. No Celery/Redis dependency needed.
"""

import logging
import threading
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Module-level job state (single job at a time)
_job_lock = threading.Lock()
_current_job = None


def get_job_status():
    """Return the current job state, or None if no job is running/completed."""
    return _current_job


def start_enrichment_job(app, sources=None, faculty_ids=None, dry_run=False):
    """Start a background enrichment job.

    Args:
        app: Flask app instance (needed for app context in thread).
        sources: List of source names, or None for all.
        faculty_ids: List of faculty IDs, or None for all.
        dry_run: If True, fetch but don't write.

    Returns:
        Job status dict, or None if a job is already running.
    """
    global _current_job

    with _job_lock:
        if _current_job and _current_job.get("status") == "running":
            return None  # Already running

        job_id = str(uuid.uuid4())[:8]
        _current_job = {
            "job_id": job_id,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "progress": "0/?",
            "total_faculty": 0,
            "enriched_count": 0,
            "sources": sources,
            "dry_run": dry_run,
            "error": None,
        }

    thread = threading.Thread(
        target=_run_enrichment,
        args=(app, job_id, sources, faculty_ids, dry_run),
        daemon=True,
    )
    thread.start()
    return _current_job.copy()


def _run_enrichment(app, job_id, sources, faculty_ids, dry_run):
    """Thread target that runs the enrichment pipeline."""
    global _current_job

    with app.app_context():
        try:
            from enrichment.pipeline import enrich_all

            def on_progress(completed, total):
                if _current_job and _current_job["job_id"] == job_id:
                    _current_job["progress"] = f"{completed}/{total}"
                    _current_job["total_faculty"] = total

            results = enrich_all(
                sources=sources,
                faculty_ids=faculty_ids,
                dry_run=dry_run,
                progress_callback=on_progress,
            )

            enriched_count = sum(
                1 for r in results
                if any(
                    s.get("status") == "data_found"
                    for s in r.get("sources", {}).values()
                )
            )

            with _job_lock:
                if _current_job and _current_job["job_id"] == job_id:
                    _current_job["status"] = "completed"
                    _current_job["completed_at"] = datetime.now(timezone.utc).isoformat()
                    _current_job["enriched_count"] = enriched_count

        except Exception as e:
            logger.exception("Enrichment job %s failed", job_id)
            with _job_lock:
                if _current_job and _current_job["job_id"] == job_id:
                    _current_job["status"] = "failed"
                    _current_job["completed_at"] = datetime.now(timezone.utc).isoformat()
                    _current_job["error"] = str(e)
