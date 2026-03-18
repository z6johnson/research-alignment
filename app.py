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

_faculty_data = None


def get_faculty_data():
    """Load faculty data from JSON file (cached after first read)."""
    global _faculty_data
    if _faculty_data is None:
        data_path = os.path.join(os.path.dirname(__file__), "data", "faculty.json")
        with open(data_path) as f:
            _faculty_data = json.load(f)
    return _faculty_data


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# Fields to include in the faculty directory API response
FACULTY_DIRECTORY_FIELDS = [
    "first_name", "last_name", "degrees", "title", "email",
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
    """Return faculty data for the expert directory (browsing/filtering)."""
    data = get_faculty_data()
    faculty = data.get("faculty", [])

    # Return only the fields needed for directory display
    result = []
    for f in faculty:
        entry = {}
        for field in FACULTY_DIRECTORY_FIELDS:
            if field in f:
                entry[field] = f[field]
        # Only include faculty with at least a name
        if entry.get("first_name") and entry.get("last_name"):
            result.append(entry)

    return jsonify(result)


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

    try:
        faculty = get_faculty_data()["faculty"]
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

    try:
        faculty = get_faculty_data()["faculty"]
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
