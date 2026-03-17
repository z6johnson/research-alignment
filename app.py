import json
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

from utils.document_parser import extract_text
from utils.grant_matcher import process_grant

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


@app.route("/")
def index():
    """Serve the frontend."""
    return send_from_directory(".", "index.html")


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

    try:
        faculty = get_faculty_data()["faculty"]
        results = process_grant(text, faculty)
    except Exception as e:
        logger.exception("Grant processing failed")
        detail = str(e)
        if "api_key" in detail.lower() or "auth" in detail.lower():
            msg = "LLM API credentials are not configured. Check LITELLM_API_KEY and LITELLM_API_BASE."
        elif "connect" in detail.lower() or "timeout" in detail.lower():
            msg = "Could not reach the LLM API. Please try again shortly."
        elif "parse" in detail.lower() or "json" in detail.lower():
            msg = "The model returned an unparseable response. Please try again."
        else:
            msg = f"Failed to analyze the grant document: {detail}"
        return jsonify({"error": msg}), 500

    return jsonify(results)


@app.errorhandler(413)
def file_too_large(e):
    return jsonify({"error": "File is too large. Maximum size is 10 MB."}), 413
