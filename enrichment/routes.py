"""Flask Blueprint for enrichment API endpoints."""

import logging
import os
from functools import wraps

from flask import Blueprint, jsonify, request

from enrichment.jobs import get_job_status, start_enrichment_job
from enrichment.pipeline import enrich_faculty, get_enrichment_status
from models import EnrichmentLog

logger = logging.getLogger(__name__)

enrichment_bp = Blueprint("enrichment", __name__, url_prefix="/api/enrichment")


def require_api_key(f):
    """Decorator that checks the X-API-Key header against ENRICHMENT_API_KEY."""
    @wraps(f)
    def decorated(*args, **kwargs):
        expected_key = os.getenv("ENRICHMENT_API_KEY", "")
        if not expected_key:
            return jsonify({"error": "ENRICHMENT_API_KEY not configured on server"}), 500

        provided_key = request.headers.get("X-API-Key", "")
        if provided_key != expected_key:
            return jsonify({"error": "Invalid or missing API key"}), 401

        return f(*args, **kwargs)
    return decorated


@enrichment_bp.route("/status", methods=["GET"])
def status():
    """Get enrichment coverage statistics and current job status."""
    result = get_enrichment_status()
    job = get_job_status()
    if job:
        result["job"] = job
    return jsonify(result)


@enrichment_bp.route("/run", methods=["POST"])
@require_api_key
def run_batch():
    """Trigger batch enrichment as a background job.

    Request body (JSON, all fields optional):
        sources: list of source names (default: all)
        faculty_ids: list of faculty IDs (default: all)
        dry_run: boolean (default: false)
    """
    from flask import current_app

    data = request.get_json(silent=True) or {}
    sources = data.get("sources")
    faculty_ids = data.get("faculty_ids")
    dry_run = data.get("dry_run", False)

    job = start_enrichment_job(
        app=current_app._get_current_object(),
        sources=sources,
        faculty_ids=faculty_ids,
        dry_run=dry_run,
    )

    if job is None:
        return jsonify({
            "error": "An enrichment job is already running",
            "job": get_job_status(),
        }), 409

    return jsonify(job), 202


@enrichment_bp.route("/run/<int:faculty_id>", methods=["POST"])
@require_api_key
def run_single(faculty_id):
    """Enrich a single faculty member synchronously."""
    data = request.get_json(silent=True) or {}
    sources = data.get("sources")
    dry_run = data.get("dry_run", False)

    result = enrich_faculty(
        faculty_id=faculty_id,
        sources=sources,
        dry_run=dry_run,
    )

    if "error" in result:
        return jsonify(result), 404

    return jsonify(result)


@enrichment_bp.route("/log/<int:faculty_id>", methods=["GET"])
def enrichment_log(faculty_id):
    """Get the enrichment provenance log for a faculty member."""
    logs = EnrichmentLog.query.filter_by(faculty_id=faculty_id).order_by(
        EnrichmentLog.retrieved_at.desc()
    ).all()

    return jsonify([
        {
            "id": log.id,
            "source_name": log.source_name,
            "source_url": log.source_url,
            "field_updated": log.field_updated,
            "old_value": log.old_value,
            "new_value": log.new_value[:200] if log.new_value else None,
            "confidence": log.confidence,
            "method": log.method,
            "retrieved_at": log.retrieved_at.isoformat() if log.retrieved_at else None,
        }
        for log in logs
    ])
