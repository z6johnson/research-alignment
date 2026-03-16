# Grant Match — Deployment & Migration Guide

Complete guide for deploying grant-match on Railway with PostgreSQL and the faculty enrichment service.

## Architecture

Everything runs on **Railway** as a single service:

```
Railway Project
├── Web Service (Flask — serves frontend + API)
└── PostgreSQL (addon — auto-provisioned)
```

The Flask app serves both the frontend (`index.html`, `/static/*`) and all API endpoints at the same origin. No CORS configuration needed in production.

---

## 1. Railway Setup

### Create the project

1. Sign up at [railway.app](https://railway.app) (GitHub login recommended)
2. Click **New Project** → **Deploy from GitHub repo**
3. Select the `grant-match` repository
4. Railway auto-detects the Python app via `Procfile` and `requirements.txt`

### Add PostgreSQL

1. In your Railway project, click **+ New** → **Database** → **Add PostgreSQL**
2. Railway automatically sets the `DATABASE_URL` environment variable on your web service
3. No manual connection string needed — it just works

### Set environment variables

In the Railway dashboard, go to your web service → **Variables** and add:

| Variable | Required | Value |
|----------|----------|-------|
| `LITELLM_API_KEY` | Yes | Your LLM provider API key |
| `LITELLM_API_BASE` | Yes | Your LLM API base URL |
| `LITELLM_MODEL` | No | Default: `openai/api-gpt-oss-120b` |
| `ENRICHMENT_API_KEY` | Yes | Any strong random string (for enrichment API auth) |
| `NCBI_API_KEY` | No | PubMed API key for higher rate limits. Free at [ncbi.nlm.nih.gov/account](https://www.ncbi.nlm.nih.gov/account/) |

**Note:** `DATABASE_URL` is auto-set by the PostgreSQL addon — do not set it manually.

### Deploy

Railway auto-deploys when you push to the connected branch. The first deploy will:
1. Install dependencies from `requirements.txt`
2. Start gunicorn via the `Procfile`
3. Auto-create all database tables
4. Seed 130 faculty records from `data/faculty.json`

Verify: visit `https://your-app.up.railway.app/` — you should see the Grant Match UI.

---

## 2. Local Development

### Quick start

```bash
git clone https://github.com/your-org/grant-match.git
cd grant-match
pip install -r requirements.txt

# Create .env with your LLM credentials
cp .env.example .env  # or create manually

# Run (uses local SQLite — no DATABASE_URL needed)
python -m flask run
```

### Local `.env` file

```env
LITELLM_API_KEY=your-llm-api-key
LITELLM_API_BASE=https://your-llm-endpoint.com/v1
ENRICHMENT_API_KEY=dev-secret
```

Without `DATABASE_URL`, the app automatically uses SQLite at `data/grant_match.db`.

---

## 3. Running Enrichment

Enrichment populates faculty records with data from public academic sources. All write endpoints require an `X-API-Key` header matching `ENRICHMENT_API_KEY`.

### Check current coverage

```bash
curl https://your-app.up.railway.app/api/enrichment/status
```

```json
{
  "total_faculty": 130,
  "with_original_interests": 77,
  "with_enriched_interests": 0,
  "coverage_original": 59.2,
  "coverage_enriched": 0.0,
  "with_funded_grants": 0,
  "with_publications": 0
}
```

### Enrich all faculty (background job)

```bash
curl -X POST https://your-app.up.railway.app/api/enrichment/run \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Returns immediately with a job ID. Poll `/api/enrichment/status` to track progress — the `job` field shows `"progress": "42/130"`.

### Enrich with specific sources

```bash
curl -X POST https://your-app.up.railway.app/api/enrichment/run \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"sources": ["ucsd_profile", "nih_reporter"]}'
```

### Enrich specific faculty

```bash
curl -X POST https://your-app.up.railway.app/api/enrichment/run \
  -H "X-API-Key: your-secret-key" \
  -H "Content-Type: application/json" \
  -d '{"faculty_ids": [1, 2, 3]}'
```

### Enrich one person (synchronous)

```bash
curl -X POST https://your-app.up.railway.app/api/enrichment/run/1 \
  -H "X-API-Key: your-secret-key"
```

### View enrichment provenance

```bash
curl https://your-app.up.railway.app/api/enrichment/log/1
```

### Recommended enrichment order

1. **UCSD Profiles first** — fills the critical gap (53 faculty with null research interests)
2. **NIH RePORTER + PubMed** — adds grant history and publications
3. **ORCID** — supplemental coverage for works and fundings

### Expected timings

| Source | Per faculty | All 130 faculty | Rate limit |
|--------|-----------|-----------------|------------|
| UCSD Profiles | ~4s | ~9 min | 1 req/2s |
| NIH RePORTER | ~1s | ~2.5 min | 1 req/s |
| PubMed | ~1s | ~1.5 min | 3 req/s (10 with NCBI key) |
| ORCID | ~2s | ~4.5 min | 1 req/s |
| **All sources** | ~8s | **~18 min** | — |

---

## 4. Data Model Reference

### faculty table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment ID |
| `first_name` | TEXT | Faculty first name |
| `last_name` | TEXT | Faculty last name |
| `degrees` | JSON | `["MD", "PhD"]` |
| `title` | TEXT | Academic title |
| `email` | TEXT | Email address |
| `department` | TEXT | Department (future multi-dept support) |
| `school` | TEXT | School name |
| `research_interests` | TEXT | **Original** from directory — never overwritten |
| `research_interests_enriched` | TEXT | LLM-normalized summary from enrichment |
| `expertise_keywords` | JSON | `["epidemiology", "HIV", ...]` |
| `profile_url` | TEXT | UCSD profiles page URL |
| `orcid` | TEXT | ORCID identifier |
| `google_scholar_id` | TEXT | Google Scholar profile ID |
| `h_index` | INTEGER | h-index |
| `recent_publications` | JSON | `[{title, year, journal, mesh_terms}, ...]` |
| `funded_grants` | JSON | `[{title, agency, amount, start_date, co_pis}, ...]` |
| `source_url` | TEXT | URL of original data source |
| `created_at` | TIMESTAMP | Record creation time |
| `updated_at` | TIMESTAMP | Last modification time |

### enrichment_log table

| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER PK | Auto-increment ID |
| `faculty_id` | INTEGER FK | References faculty.id |
| `source_name` | TEXT | `ucsd_profile`, `nih_reporter`, `pubmed`, `orcid` |
| `source_url` | TEXT | Exact URL or API endpoint fetched |
| `field_updated` | TEXT | Which faculty field was changed |
| `old_value` | TEXT | Previous value |
| `new_value` | TEXT | New value written |
| `confidence` | FLOAT | 0.0–1.0 confidence score |
| `method` | TEXT | `api`, `scrape`, or `llm_extraction` |
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

### Source confidence levels

| Source | Confidence | Rationale |
|--------|-----------|-----------|
| UCSD Profiles | 1.0 | Institutional source |
| ORCID | 0.9 | Self-reported by researcher |
| LLM Normalizer | 0.85 | Synthesized from all sources |
| NIH RePORTER | 0.8 | Verified federal records |
| PubMed | 0.7 | Name disambiguation can be imperfect |
| Google Scholar | 0.5 | Name matching unreliable (future/optional) |

---

## 5. Adding New Enrichment Sources

### Step 1: Create the source class

```python
# enrichment/sources/my_source.py
from .base import BaseSource

class MySource(BaseSource):
    source_name = "my_source"
    min_request_interval = 1.0
    confidence = 0.8

    def fields_provided(self):
        return ["field_name_1", "field_name_2"]

    def fetch(self, faculty_dict):
        # Your API/scraping logic here
        return {
            "field_name_1": "value",
            "_source_url": "https://api.example.com/...",
        }
```

### Step 2: Register in `enrichment/pipeline.py`

```python
from .sources.my_source import MySource

SOURCE_CLASSES = {
    ...,
    "my_source": MySource,
}
```

### Step 3: Handle in `enrichment/normalizer.py` (if applicable)

Add a section in `normalize_faculty_data()` to include the source's data in the LLM prompt.

### Step 4: Add model fields (if needed)

If the source provides data that doesn't fit existing columns, add to `models.py` and `Faculty.to_dict()`.

---

## 6. API Reference

### Frontend
| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Grant Match web application |

### Grant Matching
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/match` | — | Upload grant PDF/TXT, get faculty matches |

### Faculty
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/faculty` | — | List all faculty. `?q=term` for search |
| GET | `/api/faculty/<id>` | — | Single faculty record |

### Enrichment
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/enrichment/status` | — | Coverage stats + job progress |
| POST | `/api/enrichment/run` | X-API-Key | Start batch enrichment (background) |
| POST | `/api/enrichment/run/<id>` | X-API-Key | Enrich one faculty (synchronous) |
| GET | `/api/enrichment/log/<id>` | — | Provenance log for a faculty member |

---

## 7. Roadmap

| Phase | Status | What |
|-------|--------|------|
| 1 | Done | PostgreSQL data model, SQLAlchemy ORM, UCSD profile scraper |
| 2 | Done | NIH RePORTER + PubMed clients, enriched grant matcher |
| 3 | Done | ORCID client, backend enrichment API, Railway deployment |
| Future | Planned | Google Scholar (optional), admin dashboard, scheduled re-enrichment, multi-school |
