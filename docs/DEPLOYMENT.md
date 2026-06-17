# Deployment Guide

This project can run three ways:

1. **Local, no Docker** - `uvicorn` + `streamlit run`, SQLite (see main README).
2. **Local, Docker Compose** - full stack with PostgreSQL (this doc, section 1).
3. **Cloud demo** - backend + dashboard deployed separately (this doc, section 2).

---

## 1. Local stack with Docker Compose

This brings up PostgreSQL, the FastAPI backend, and the Streamlit dashboard
together.

```bash
docker compose up --build
```

- Dashboard: http://localhost:8501
- API docs (Swagger): http://localhost:8000/docs
- Health check: http://localhost:8000/health

By default `DEMO_MODE=true`, so the stack works immediately with **no
credentials** - sample documents, mock text extraction, and a mock
classifier/extractor are used.

### Running against real OCR / AI

Tesseract OCR is already installed inside the backend Docker image (see
`Dockerfile`), so unlike Project 1's Gmail integration, there's no
interactive login step blocking real usage here. Create a `.env` file in
the project root (docker compose loads it automatically):

```env
DEMO_MODE=false
ANTHROPIC_API_KEY=sk-ant-...
```

With `DEMO_MODE=false`:
- PDF uploads are parsed with `pdfplumber` (requires a digital text layer -
  scanned PDFs with no embedded text will report "extraction_failed"; upload
  as an image instead to use OCR).
- PNG/JPG/JPEG uploads are processed with real Tesseract OCR.
- Classification and field extraction call the Anthropic API with forced
  structured output.

---

## 2. Cloud demo deployment

The cloud demo deploys the backend and dashboard as **separate services**.
Because there's no OAuth/login flow in this project (unlike Project 1's
Gmail integration), the cloud demo *can* run with `DEMO_MODE=false` if you
want to showcase real OCR/AI - but running in `DEMO_MODE=true` is simpler,
faster, and avoids any AI API costs for visitors, so that's the recommended
default.

### 2.1 Database

Use any managed PostgreSQL provider (Render, Railway, Supabase, Neon, etc.).
Copy the connection string - it will look like:

```text
postgresql://user:password@host:5432/dbname
```

### 2.2 Backend (FastAPI)

Deploy the root `Dockerfile` to a container platform (Render, Railway, Fly.io,
etc.) with these environment variables:

| Variable | Value |
| --- | --- |
| `ENV` | `production` |
| `DEMO_MODE` | `true` (recommended) or `false` |
| `DATABASE_URL` | your managed Postgres connection string |
| `UPLOAD_DIR` | `/app/uploads` (or a mounted persistent volume path) |
| `EXPORT_DIR` | `/app/exports` (or a mounted persistent volume path) |
| `ANTHROPIC_API_KEY` | only needed if `DEMO_MODE=false` |

The container listens on port `8000` and exposes:
- `GET /health` - use this as the platform's health check
- `GET /docs` - interactive API documentation
- `POST /demo/seed` - seeds the 6 demo documents on first call

**Important:** uploaded files are stored on the container's local disk
(`UPLOAD_DIR`/`EXPORT_DIR`). Most container platforms have ephemeral
filesystems, so files may be lost on redeploy/restart unless you attach a
persistent volume. For the public demo, this is acceptable since the seeded
demo documents have no real file on disk anyway (`file_path="(demo:<key>)"`)
- only user-uploaded files are affected.

### 2.3 Dashboard (Streamlit)

Deploy `dashboard/Dockerfile` (build context = project root) to the same or
a different platform, with:

| Variable | Value |
| --- | --- |
| `API_BASE_URL` | the public URL of the backend deployed in 2.2 |

The container listens on port `8501`.

### 2.4 Seeding the demo

After both services are live, open the dashboard's **Demo Mode** page and
click **Load Sample Documents** (or call `POST /demo/seed` on the backend
directly). This loads the 6 sample documents covering every scenario, so a
visitor can immediately classify, extract, validate, review, and export.

### 2.5 Add the links to the README

Once deployed, add both URLs to the **Live demo** section of the main
`README.md`:

```markdown
## Live demo
- Dashboard: https://your-dashboard-url
- API docs: https://your-backend-url/docs
```

---

## Summary of safety guarantees in any deployment

- Sensitive real invoices/contracts should never be uploaded to the public
  cloud demo - it's intended for sample data only.
- No document can be exported unless explicitly approved by a human
  reviewer (enforced in `app/services/export.py`, not just the UI).
- Validation errors block approval until corrected (enforced in
  `app/services/review.py`).
- The AI never approves or exports documents on its own - it only proposes
  classifications and field extractions.
