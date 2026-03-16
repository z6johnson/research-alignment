import json
import logging
import os
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from db import init_db
from enrichment.routes import enrichment_bp
from models import MatchAudit, db
from utils.document_parser import extract_text
from utils.faculty_repository import get_faculty_for_matching
from utils.grant_matcher import extract_grant_requirements, match_faculty

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

# CORS only needed for local development (frontend and API are same-origin in production)
CORS(app, origins=["http://localhost:*", "http://127.0.0.1:*"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"pdf", "txt"}

# Initialize database (creates tables and seeds from JSON on first run)
init_db(app)

# Register enrichment API endpoints
app.register_blueprint(enrichment_bp)


@app.route("/")
def index():
    """Serve the frontend single-page application."""
    return send_from_directory(".", "index.html")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route("/api/match", methods=["POST"])
def match():
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Only PDF and TXT files are supported"}), 400

    try:
        text = extract_text(file)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    start_time = time.time()

    try:
        faculty_with_interests, faculty_without = get_faculty_for_matching()
        requirements = extract_grant_requirements(text)
        matches = match_faculty(requirements, faculty_with_interests)
    except Exception:
        logger.exception("Grant processing failed")
        return jsonify({"error": "Failed to analyze the grant document. Please try again."}), 500

    elapsed = time.time() - start_time

    # Log the match to the audit trail
    try:
        audit = MatchAudit(
            grant_filename=file.filename,
            grant_title=requirements.get("grant_title"),
            funding_agency=requirements.get("funding_agency"),
            grant_requirements=requirements,
            results=matches,
            faculty_count=len(faculty_with_interests),
            model_used=os.getenv("LITELLM_MODEL", "api-gpt-oss-120b"),
            processing_seconds=round(elapsed, 2),
        )
        db.session.add(audit)
        db.session.commit()
    except Exception:
        logger.exception("Failed to log match audit")
        db.session.rollback()

    return jsonify({
        "grant_summary": requirements,
        "matches": matches,
        "faculty_without_interests_count": len(faculty_without),
        "total_faculty_considered": len(faculty_with_interests),
    })


@app.route("/api/faculty", methods=["GET"])
def list_faculty():
    """List all faculty with optional search."""
    from utils.faculty_repository import get_all_faculty, search_faculty

    q = request.args.get("q")
    if q:
        return jsonify(search_faculty(q))
    return jsonify(get_all_faculty())


@app.route("/api/faculty/<int:faculty_id>", methods=["GET"])
def get_faculty(faculty_id):
    """Get a single faculty member."""
    from utils.faculty_repository import get_faculty_by_id

    result = get_faculty_by_id(faculty_id)
    if not result:
        return jsonify({"error": "Faculty not found"}), 404
    return jsonify(result)


@app.errorhandler(413)
def file_too_large(e):
    return jsonify({"error": "File is too large. Maximum size is 10 MB."}), 413
