# Tri9T AI Engineering Internship Assignment — CT-200 API

A beginner-friendly FastAPI backend for parsing a CT-200 PDF manual into a versioned section tree, pinning selections to exact source versions, generating structured QA test-case ideas, and detecting stale generations after re-ingestion.

> **Included inputs:** `data/ct200_manual.pdf` and `data/ct200_manual_v2.pdf` are the actual supplied manuals. The parser has been tested against both, and real-manual regression tests are included. The parser remains heuristic; review the extracted tree and limitations before submission.

## Features

- PDF text extraction using PyMuPDF, with an OCR fallback for image-only pages through Tesseract (Tesseract and English language data must be installed on the machine).
- Heading/section tree reconstruction with parent IDs, content hashes, logical keys, and duplicate-heading handling.
- Multiple immutable document versions per `document_key`.
- Browse top-level sections, fetch a node, and search headings/body text.
- Version-pinned named selections preserve the exact text/hash used at selection time.
- LLM generation via an OpenAI-compatible API, with JSON/Pydantic validation and one retry.
- Offline deterministic fallback when no API key is configured; responses label the provider as `offline_fallback`.
- JSON-file storage for generated output, including source snapshots and hashes.
- Retrieval-time staleness checks and lightweight text diff summaries.
- Unit and integration tests for duplicate headings, nested hierarchy, numbered clinical-list preservation, the irregular 2.1.1.1 heading, v2-only E6/Data Export content, whitespace-normalized hashes, text changes, and end-to-end staleness.

## 1. Install and run

Python 3.10+ recommended. For scanned/image-only PDFs, install Tesseract OCR and its English language data; selectable-text PDFs do not require OCR.

```bash
python -m venv .venv
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # optional; edit the file to configure an LLM provider
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for interactive Swagger documentation. Health check: `GET /health`.

Without `LLM_API_KEY`, generation uses an explicitly labelled deterministic fallback. To use a provider, set `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL` in your environment or `.env` file. This starter does not automatically load `.env`; export those variables in your shell or install `python-dotenv` and add `load_dotenv()` before importing config.

## 2. Ingest version 1 and version 2

The supplied manuals are already included in `data/`. Example using curl:

```bash
curl -X POST 'http://127.0.0.1:8000/documents/ingest?document_key=ct200&version_label=v1' \
  -F 'file=@data/ct200_manual.pdf;type=application/pdf'

curl -X POST 'http://127.0.0.1:8000/documents/ingest?document_key=ct200&version_label=v2' \
  -F 'file=@data/ct200_manual_v2.pdf;type=application/pdf'
```

Each version is stored separately. Re-ingesting the same `document_key` + `version_label` returns HTTP 409 rather than overwriting history. The parser uses numbering and short all-caps text heuristics. A CT-200-specific rule keeps the numbered classification entries under Section 3.3 instead of incorrectly promoting them to headings. The irregular `2.1.1.1` heading is retained at level 4 and attached to the nearest detected parent, `2.1 General Specifications`, because `2.1.1` is absent.

## 3. Browse and search

```bash
curl 'http://127.0.0.1:8000/documents/ct200/versions'
curl 'http://127.0.0.1:8000/documents/ct200/sections'
curl 'http://127.0.0.1:8000/documents/ct200/sections?version=v1'
curl 'http://127.0.0.1:8000/nodes/1'
curl 'http://127.0.0.1:8000/search?q=pressure&document_key=ct200&version=v1'
curl 'http://127.0.0.1:8000/nodes/1/changes'
```

Replace node IDs with IDs returned by your own API; IDs are database-generated and must not be assumed.

## 4. Create a pinned selection and generate QA test cases

```bash
curl -X POST 'http://127.0.0.1:8000/selections' \
  -H 'Content-Type: application/json' \
  -d '{"name":"Pressure behavior review","node_ids":[1,2]}'

curl -X POST 'http://127.0.0.1:8000/generations' \
  -H 'Content-Type: application/json' \
  -d '{"selection_id":1}'

curl 'http://127.0.0.1:8000/generations?selection_id=1'
curl 'http://127.0.0.1:8000/generations?node_id=1'
```

Use the real selection ID and node IDs from API responses. Repeating generation for the same selection and source fingerprint returns the existing record. Pass `{"selection_id":1,"regenerate":true}` to deliberately generate a new run.

## 5. Run tests

```bash
pytest -q
```

Tests do not need an API key. The suite includes synthetic parser/versioning tests plus regression tests and an end-to-end v1 → v2 staleness test using the actual CT-200 PDFs. Generation uses the labelled offline fallback unless a real LLM provider is configured.

## API summary

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Health check |
| POST | `/documents/ingest` | Ingest a PDF as a named version |
| GET | `/documents/{document_key}/versions` | List versions |
| GET | `/documents/{document_key}/sections?version=v1` | List top-level sections; default latest |
| GET | `/nodes/{node_id}` | Node text and direct children |
| GET | `/search?q=...` | Search headings/body |
| GET | `/nodes/{node_id}/changes` | Compare logical node across versions |
| POST | `/selections` | Create version-pinned selection |
| GET | `/selections/{selection_id}` | Retrieve selection and source snapshots |
| POST | `/generations` | Generate 3–5 structured QA cases |
| GET | `/generations?selection_id=...` | Retrieve generated cases and staleness |
| GET | `/generations?node_id=...` | Retrieve generations that used a node |
| GET | `/generations/{generation_id}` | Retrieve generation records for its selection |

## Important design limits to explain honestly

1. **Parsing is heuristic even when OCR succeeds.** PyMuPDF extracts selectable text and attempts Tesseract OCR for pages with very little text. OCR can misread characters and needs Tesseract installed. Table-like lines are retained as body text, not guaranteed to become structured tables.
2. **Logical-node matching is approximate.** Section ancestry/title keys handle stable headings; a unique-title fallback helps simple moves/renames only when titles remain unique. Ambiguous duplicate headings and large restructuring require manual review.
3. **Hash-based staleness is conservative.** Any body text change marks the test generation stale, including wording-only changes. It does not judge clinical significance.
4. **LLM output is schema-validated.** One retry is attempted. If the provider still returns invalid output, the API returns HTTP 502 and does not store it as a successful generation.
5. **JSON output store is a simple local implementation.** It is suitable for the assignment demo but not concurrent production writes; use a transactional document database for multi-worker production use.
6. **Fallback generation is for development/demo only.** Clearly disclose whether actual LLM-backed output was used during your final demonstration.

## Git commit history

Do not make one giant final commit. Suggested incremental sequence:

```bash
git init
git add requirements.txt .gitignore .env.example
git commit -m "chore: initialize FastAPI project"
git add app/database.py app/models.py app/schemas.py
git commit -m "feat: add document and selection data models"
git add app/parser.py tests/test_parser.py
git commit -m "feat: parse PDF text into section hierarchy"
git add app/versioning.py tests/test_versioning.py
git commit -m "feat: add content hashing and version comparison"
git add app/llm.py
git commit -m "feat: validate structured QA generation output"
git add app/main.py
git commit -m "feat: expose ingestion browse selection and retrieval APIs"
git add README.md APPROACH.md
 git commit -m "docs: explain setup tradeoffs and validation"
```

Make commits as you actually implement and test each stage; never fabricate a commit history. Push to your own GitHub repository before submitting.
