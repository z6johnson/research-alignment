import json
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from utils.document_parser import extract_text
from utils.grant_matcher import process_grant, process_text

load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

# CORS only needed for local development (same-origin on Vercel)
CORS(app, origins=["http://localhost:*", "http://127.0.0.1:*"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"pdf", "txt"}

_faculty_cache = {}

# Map department keys to filenames and display labels
_DEPT_CONFIG = {
    "hwsph": {"filename": "faculty.json", "label": "Herbert Wertheim School of Public Health"},
    "sio":   {"filename": "sio_faculty.json", "label": "Scripps Institution of Oceanography"},
}


def get_faculty_data(department=None):
    """Load faculty data from JSON file (cached after first read).

    Args:
        department: "sio" for Scripps, "all" for both, None for HWSPH (default).
    """
    cache_key = department or "hwsph"
    if cache_key not in _faculty_cache:
        if department == "all":
            # Merge all departments, tagging each faculty with their dept
            merged = []
            for dept_key, cfg in _DEPT_CONFIG.items():
                data_path = os.path.join(os.path.dirname(__file__), "data", cfg["filename"])
                with open(data_path) as f:
                    dept_data = json.load(f)
                for fac in dept_data.get("faculty", []):
                    fac["department"] = dept_key
                    fac["department_label"] = cfg["label"]
                    merged.append(fac)
            _faculty_cache[cache_key] = {"faculty": merged}
        else:
            if department == "sio":
                filename = "sio_faculty.json"
                dept_key = "sio"
            else:
                filename = "faculty.json"
                dept_key = "hwsph"
            data_path = os.path.join(os.path.dirname(__file__), "data", filename)
            with open(data_path) as f:
                data = json.load(f)
            # Tag faculty with department
            for fac in data.get("faculty", []):
                fac["department"] = dept_key
                fac["department_label"] = _DEPT_CONFIG[dept_key]["label"]
            _faculty_cache[cache_key] = data
    return _faculty_cache[cache_key]


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# Fields to include in the faculty directory API response
FACULTY_DIRECTORY_FIELDS = [
    "first_name", "last_name", "degrees", "title", "email",
    "department", "department_label",
    "research_interests", "research_interests_enriched",
    "expertise_keywords", "disease_areas", "methodologies", "populations",
    "h_index", "profile_url", "orcid",
    "funded_grants", "recent_publications",
    "committee_service", "integrity_flags",
]


@app.route("/")
def index():
    """Serve the frontend."""
    return send_from_directory(".", "index.html")


@app.route("/api/faculty")
def faculty_directory():
    """Return faculty data for the expert directory (browsing/filtering).

    Query params:
        dept: "sio" for Scripps, omit or "hwsph" for Public Health (default).
    """
    dept = request.args.get("dept", "").strip().lower() or "all"
    if dept not in ("sio", "hwsph", "all"):
        return jsonify({"error": f"Unknown department: {dept}. Use 'sio', 'hwsph', or 'all'."}), 400
    if dept == "hwsph":
        dept = None

    data = get_faculty_data(dept)
    faculty = data.get("faculty", [])

    query = request.args.get("q", "").strip().lower()
    limit = min(int(request.args.get("limit", 20)), 50)
    offset = int(request.args.get("offset", 0))

    # Build filtered list with only the directory fields
    result = []
    for f in faculty:
        if not (f.get("first_name") and f.get("last_name")):
            continue

        # If there's a query, check if all terms match
        if query:
            searchable = _get_searchable_text(f)
            terms = query.split()
            if not all(t in searchable for t in terms):
                continue

        entry = {}
        for field in FACULTY_DIRECTORY_FIELDS:
            if field in f:
                entry[field] = f[field]
        result.append(entry)

    total = len(result)
    page = result[offset:offset + limit]

    return jsonify({"results": page, "total": total, "offset": offset, "limit": limit})


def _get_searchable_text(f):
    """Build a single lowercase string of all searchable fields for a faculty member."""
    parts = [
        f.get("first_name") or "", f.get("last_name") or "",
        f.get("title") or "",
        f.get("research_interests") or "",
        f.get("research_interests_enriched") or "",
        *(f.get("expertise_keywords") or []),
        *(f.get("disease_areas") or []),
        *(f.get("methodologies") or []),
        *(f.get("populations") or []),
        *(f.get("committee_service") or []),
    ]
    return " ".join(str(p) for p in parts).lower()


@app.route("/api/match", methods=["POST"])
def match():
    """Match a file-uploaded funding opportunity against faculty."""
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

    dept = request.form.get("dept", "").strip().lower() or "all"
    if dept == "hwsph":
        dept = None

    try:
        faculty = get_faculty_data(dept)["faculty"]
        results = process_grant(text, faculty)
    except Exception as e:
        logger.exception("Document processing failed")
        return jsonify({"error": _friendly_error(e)}), 500

    return jsonify(results)


@app.route("/api/match-text", methods=["POST"])
def match_text():
    """Match manually entered expertise text against faculty."""
    data = request.get_json(silent=True)
    if not data or not data.get("text"):
        return jsonify({"error": "No text provided"}), 400

    text = data["text"].strip()
    if len(text) < 20:
        return jsonify({"error": "Please provide at least 20 characters of text"}), 400

    if len(text) > 60000:
        return jsonify({"error": "Text is too long. Maximum 60,000 characters."}), 400

    dept = data.get("dept", "").strip().lower() or "all"
    if dept == "hwsph":
        dept = None

    try:
        faculty = get_faculty_data(dept)["faculty"]
        results = process_text(text, faculty)
    except Exception as e:
        logger.exception("Text processing failed")
        return jsonify({"error": _friendly_error(e)}), 500

    return jsonify(results)


def _friendly_error(e):
    """Convert exception to user-friendly error message."""
    detail = str(e)
    if "api_key" in detail.lower() or "auth" in detail.lower():
        return "LLM API credentials are not configured. Check LITELLM_API_KEY and LITELLM_API_BASE."
    elif "connect" in detail.lower() or "timeout" in detail.lower():
        return "Could not reach the LLM API. Please try again shortly."
    elif "parse" in detail.lower() or "json" in detail.lower():
        return "The model returned an unparseable response. Please try again."
    else:
        return f"Failed to analyze the document: {detail}"


@app.errorhandler(413)
def file_too_large(e):
    return jsonify({"error": "File is too large. Maximum size is 10 MB."}), 413
