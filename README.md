# Research Alignment

AI-powered faculty expertise discovery tool for UC San Diego's Herbert Wertheim School of Public Health. Identify faculty whose research expertise aligns with funding opportunity requirements through three interaction modes.

## How It Works

Three ways to discover aligned faculty:

1. **Upload a funding opportunity** (PDF or TXT) — AI extracts requirements and ranks faculty by alignment
2. **Enter expertise requirements** manually — paste or describe the expertise you need and get ranked matches
3. **Browse the expert directory** — search and filter faculty by expertise, methods, disease areas, and populations

Two sequential LLM calls power the matching analysis via [LiteLLM](https://github.com/BerriAI/litellm):
- **Call 1:** Extract structured requirements from the opportunity text
- **Call 2:** Rank faculty by alignment with those requirements

For large faculty sets (300+), a keyword pre-filter narrows candidates before the LLM stage to control token costs without sacrificing accuracy.

## Architecture

| Component | Platform | What it does |
|-----------|----------|--------------|
| **Frontend** | Vercel | Serves `index.html`, CSS, and JS as static files via CDN |
| **API** | Vercel / Render | Runs the Flask app — `/api/match`, `/api/match-text`, `/api/faculty` |
| **Enrichment** | GitHub Actions | Weekly automated data enrichment from NIH, PubMed, ORCID, UCSD Profiles |

## Project Structure

```
research-alignment/
├── app.py                    # Flask API
├── requirements.txt          # Python dependencies
├── vercel.json               # Vercel deployment config
├── index.html                # Single-page frontend (three-tab interface)
├── .env.example              # Environment variable template
├── data/
│   ├── faculty.json          # Faculty directory (source of truth)
│   └── enrichment_log.json   # Append-only audit log
├── static/
│   ├── css/style.css         # UCSD-branded styles (Seed Style Guide)
│   └── js/app.js             # Frontend logic
├── utils/
│   ├── document_parser.py    # PDF/TXT text extraction
│   └── grant_matcher.py      # LLM matching engine + keyword pre-filter
├── enrichment/
│   ├── pipeline.py           # Enrichment orchestrator
│   ├── normalizer.py         # LLM-based data normalization
│   ├── run.py                # GitHub Actions runner
│   └── sources/              # Data source adapters (NIH, PubMed, ORCID, UCSD)
└── docs/
    ├── responsible-ai-seed-principles.md
    └── seed-style-guide.md
```

## Faculty Schema

Each faculty record includes:

| Field | Type | Description |
|-------|------|-------------|
| `first_name`, `last_name` | string | Name |
| `degrees` | string[] | Academic degrees |
| `title` | string | Position title |
| `email` | string | Contact email |
| `research_interests` | string | Original directory text (never overwritten) |
| `research_interests_enriched` | string | LLM-synthesized summary from all sources |
| `expertise_keywords` | string[] | Extracted domain keywords |
| `methodologies` | string[] | Research methods used |
| `disease_areas` | string[] | Health conditions studied |
| `populations` | string[] | Target populations |
| `committee_service` | string[] | Academic Senate committee participation |
| `integrity_flags` | string[] | Research integrity flags (future feature) |
| `h_index` | int | Hirsch index |
| `funded_grants` | object[] | Funded project history |
| `recent_publications` | object[] | Recent publication history |

## API

### `POST /api/match`

Upload a funding opportunity document for faculty matching.

**Request:** `multipart/form-data` with a `file` field (PDF or TXT, max 10 MB)

### `POST /api/match-text`

Match manually entered expertise text against faculty.

**Request:** `application/json` with `{"text": "expertise requirements..."}`

### `GET /api/faculty`

Return the faculty directory for browsing and filtering.

**Response (200):** Array of faculty objects with profile fields.

### Response Format (match endpoints)

```json
{
  "grant_summary": {
    "grant_title": "...",
    "funding_agency": "...",
    "grant_summary": "...",
    "investigator_requirements": [...],
    "overall_research_themes": [...]
  },
  "matches": [
    {
      "rank": 1,
      "first_name": "...",
      "last_name": "...",
      "match_score": 85,
      "expertise_alignment": 90,
      "methodological_fit": 80,
      "track_record": 75,
      "match_reasoning": "..."
    }
  ],
  "total_faculty_considered": 109,
  "faculty_without_interests_count": 21
}
```

## Deployment

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `LITELLM_API_KEY` | Yes | LLM API key |
| `LITELLM_API_BASE` | Yes | LLM API endpoint URL |
| `LITELLM_MODEL` | No | Model identifier (default: `api-gpt-oss-120b`) |
| `NCBI_API_KEY` | No | PubMed API key (increases rate limit) |
