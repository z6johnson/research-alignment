# Grant Match — Migration & Deployment Guide

Complete guide for deploying grant-match with the PostgreSQL data model and faculty enrichment service.

---

## 1. Database Setup

### Production: Neon Postgres (free tier)

1. Create a free account at [neon.tech](https://neon.tech)
2. Create a new project (any region — `us-east-1` recommended for Render)
3. Copy the connection string from the dashboard. It looks like:
   ```
   postgresql://user:password@ep-xxxxx.us-east-1.aws.neon.tech/neondb?sslmode=require
   ```
4. Set this as your `DATABASE_URL` environment variable (see Section 2)

**Neon free tier includes:** 0.5 GB storage, auto-suspend after 5 min idle, no expiration.

### Local development: SQLite (automatic)

If `DATABASE_URL` is not set, the app automatically uses a local SQLite database at `data/grant_match.db`. No setup needed.

### Auto-seeding

On first run, if the `faculty` table is empty, the app automatically imports all records from `data/faculty.json`. This is idempotent — it only runs once per database.

---

## 2. Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | Yes (prod) | PostgreSQL connection string. Omit for local SQLite. |
| `LITELLM_API_KEY` | Yes | API key for the LLM provider |
| `LITELLM_API_BASE` | Yes | Base URL for the LLM API endpoint |
| `LITELLM_MODEL` | No | Model identifier (default: `openai/api-gpt-oss-120b`) |
| `ENRICHMENT_API_KEY` | Yes (prod) | Shared secret for enrichment API auth. Set to any strong random string. |
| `NCBI_API_KEY` | No | PubMed API key for higher rate limits (10 req/s vs 3). Free at [ncbi.nlm.nih.gov/account](https://www.ncbi.nlm.nih.gov/account/) |

### Local `.env` file example

```env
DATABASE_URL=postgresql://user:password@ep-xxxxx.us-east-1.aws.neon.tech/neondb?sslmode=require
LITELLM_API_KEY=your-llm-api-key
LITELLM_API_BASE=https://your-llm-endpoint.com/v1
LITELLM_MODEL=openai/api-gpt-oss-120b
ENRICHMENT_API_KEY=your-secret-key-here
NCBI_API_KEY=your-ncbi-key-here
```

---

## 3. Deployment to Render

### Prerequisites
- A Render account with the grant-match repo connected
- Environment variables configured in the Render dashboard

### render.yaml

The `render.yaml` in the repo defines the web service. All env vars are marked `sync: false` — set them manually in the Render dashboard under **Environment**.

### Steps

1. Push your code to the connected branch
2. Render auto-deploys on push
3. In the Render dashboard, go to **Environment** and set all variables from Section 2
4. The first deploy will auto-create tables and seed faculty data from `faculty.json`
5. Verify the app is running: `curl https://your-app.onrender.com/api/faculty`

### gunicorn configuration

Already configured in `render.yaml`:
```
gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120
```

The 120s timeout accommodates LLM calls during grant matching (~10-15s each, two calls per match).

---

## 4. Running Enrichment

Enrichment is triggered via API endpoints, not CLI. All write endpoints require an `X-API-Key` header.

### Endpoints

#### Check enrichment coverage
```bash
curl https://your-app.onrender.com/api/enrichment/status
```

Response:
```json
{
  "total_faculty": 130,
  "with_original_interests": 77,
  "with_enriched_interests": 0,
  "with_funded_grants": 0,
  "with_publications": 0,
  "coverage_original": 59.2,
  "coverage_enriched": 0.0
}
```

#### Enrich all faculty (background job)
```bash
curl -X POST https://your-app.onrender.com/api/enrichment/run \
  -H "X-API-Key: your-secret-key-here" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Returns immediately with a job ID. Poll `/api/enrichment/status` to track progress.

#### Enrich with specific sources only
```bash
curl -X POST https://your-app.onrender.com/api/enrichment/run \
  -H "X-API-Key: your-secret-key-here" \
  -H "Content-Type: application/json" \
  -d '{"sources": ["ucsd_profile", "nih_reporter"]}'
```

#### Enrich specific faculty members
```bash
curl -X POST https://your-app.onrender.com/api/enrichment/run \
  -H "X-API-Key: your-secret-key-here" \
  -H "Content-Type: application/json" \
  -d '{"faculty_ids": [1, 2, 3]}'
```

#### Enrich a single faculty member (synchronous)
```bash
curl -X POST https://your-app.onrender.com/api/enrichment/run/1 \
  -H "X-API-Key: your-secret-key-here"
```

#### View enrichment history for a faculty member
```bash
curl https://your-app.onrender.com/api/enrichment/log/1
```

### Expected timings

| Source | Per faculty | All 130 faculty | Rate limit |
|--------|-----------|-----------------|------------|
| UCSD Profiles | ~4s (2 requests) | ~9 min | 1 req/2s |
| NIH RePORTER | ~1s | ~2.5 min | 1 req/s |
| PubMed | ~1s (2 requests) | ~1.5 min | 3 req/s (10 with key) |
| ORCID | ~2s (2 requests) | ~4.5 min | 1 req/s |
| **All sources** | ~8s | **~18 min** | — |

### Recommended enrichment order

1. Start with UCSD Profiles only — fills the most critical gap (null research interests):
   ```bash
   curl -X POST .../api/enrichment/run \
     -H "X-API-Key: ..." \
     -d '{"sources": ["ucsd_profile"]}'
   ```
2. Then add NIH RePORTER + PubMed for grant/publication data
3. Finally add ORCID for supplemental coverage

---

## 5. Data Model Reference

### faculty table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment ID |
| `first_name` | TEXT | Faculty first name |
| `last_name` | TEXT | Faculty last name |
| `degrees` | JSON | Array of degree strings, e.g. `["MD", "PhD"]` |
| `title` | TEXT | Academic title |
| `email` | TEXT | Email address |
| `department` | TEXT | Department (for future multi-dept support) |
| `school` | TEXT | School name |
| `research_interests` | TEXT | **Original** from directory scrape — never overwritten |
| `research_interests_enriched` | TEXT | LLM-normalized summary from enrichment |
| `expertise_keywords` | JSON | Array of keyword strings from LLM normalization |
| `profile_url` | TEXT | UCSD profiles page URL |
| `orcid` | TEXT | ORCID identifier |
| `google_scholar_id` | TEXT | Google Scholar profile ID |
| `h_index` | INTEGER | h-index from Google Scholar |
| `recent_publications` | JSON | Array of {title, year, journal, mesh_terms} |
| `funded_grants` | JSON | Array of {title, agency, amount, start_date, co_pis} |
| `source_url` | TEXT | URL of original data source |
| `created_at` | TIMESTAMP | Record creation time |
| `updated_at` | TIMESTAMP | Last modification time |

### enrichment_log table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment ID |
| `faculty_id` | INTEGER FK | References faculty.id |
| `source_name` | TEXT | Source identifier (ucsd_profile, nih_reporter, pubmed, orcid) |
| `source_url` | TEXT | Exact URL or API endpoint fetched |
| `field_updated` | TEXT | Which faculty field was changed |
| `old_value` | TEXT | Previous value (for audit) |
| `new_value` | TEXT | New value written |
| `confidence` | FLOAT | 0.0–1.0 confidence score |
| `method` | TEXT | How data was obtained (api, scrape, llm_extraction) |
| `raw_response` | TEXT | Raw API/scrape response (truncated to 5KB) |
| `retrieved_at` | TIMESTAMP | When this enrichment occurred |

### match_audit table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment ID |
| `run_date` | TIMESTAMP | When the match was run |
| `grant_filename` | TEXT | Uploaded file name |
| `grant_title` | TEXT | Extracted grant title |
| `funding_agency` | TEXT | Extracted funding agency |
| `grant_requirements` | JSON | Full extracted requirements |
| `results` | JSON | Full match results array |
| `faculty_count` | INTEGER | Faculty considered in matching |
| `model_used` | TEXT | LLM model identifier |
| `processing_seconds` | FLOAT | Total processing time |

### Enrichment source confidence levels

| Source | Confidence | Rationale |
|--------|-----------|-----------|
| UCSD Profiles | 1.0 | Institutional source, closest to faculty's own description |
| ORCID | 0.9 | Self-reported by the researcher |
| NIH RePORTER | 0.8 | Verified federal grant records |
| PubMed | 0.7 | Strong signal, but name disambiguation can be imperfect |
| LLM Normalizer | 0.85 | Synthesized from all sources by LLM |
| Google Scholar | 0.5 | Name matching unreliable (future/optional) |

---

## 6. Adding New Enrichment Sources

To add a new data source:

### Step 1: Create the source class

Create `enrichment/sources/my_source.py`:

```python
from .base import BaseSource

class MySource(BaseSource):
    source_name = "my_source"
    min_request_interval = 1.0  # seconds between requests
    confidence = 0.8

    def fields_provided(self):
        return ["field_name_1", "field_name_2"]

    def fetch(self, faculty_dict):
        """Fetch data for a faculty member.

        Args:
            faculty_dict: Dict with first_name, last_name, email, etc.

        Returns:
            Dict of {field_name: value}, or None if no data found.
            Use _source_url key for provenance tracking.
        """
        # Your API/scraping logic here
        return {
            "field_name_1": "value",
            "_source_url": "https://api.example.com/...",
        }
```

### Step 2: Register in pipeline.py

In `enrichment/pipeline.py`, add the import and registry entry:

```python
from .sources.my_source import MySource

SOURCE_CLASSES = {
    ...
    "my_source": MySource,
}
```

### Step 3: Handle in normalizer.py (if needed)

If your source provides data the LLM normalizer should consider, add a section in `enrichment/normalizer.py`'s `normalize_faculty_data()` function.

### Step 4: Add model fields (if needed)

If your source provides data that doesn't fit existing Faculty columns, add new columns to `models.py` and include them in `Faculty.to_dict()`.

---

## 7. Phase Roadmap

| Phase | Status | What |
|-------|--------|------|
| Phase 1 | Done | PostgreSQL data model, SQLAlchemy ORM, faculty repository, match audit logging, UCSD profile scraper |
| Phase 2 | Done | NIH RePORTER API client, PubMed E-utilities client, enriched grant matcher prompt |
| Phase 3 | Done | ORCID API client, backend enrichment service (API endpoints), API key auth, migration documentation |
| Future | Planned | Google Scholar source (optional, fragile), admin dashboard, scheduled re-enrichment, multi-school support |

---

## 8. API Reference (Complete)

### Grant Matching
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/match` | None | Upload grant PDF/TXT, get faculty matches |

### Faculty
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/faculty` | None | List all faculty. `?q=search` for text search |
| GET | `/api/faculty/<id>` | None | Get single faculty record |

### Enrichment
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/api/enrichment/status` | None | Coverage stats + job progress |
| POST | `/api/enrichment/run` | X-API-Key | Start batch enrichment (background) |
| POST | `/api/enrichment/run/<id>` | X-API-Key | Enrich one faculty (synchronous) |
| GET | `/api/enrichment/log/<id>` | None | Provenance log for a faculty member |
