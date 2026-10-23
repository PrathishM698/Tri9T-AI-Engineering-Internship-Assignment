# Approach Document — Tri9T AI CT-200 API

## 1. Scope and input status

The implementation follows the assignment's requested backend workflow: PDF ingestion, a hierarchical and versioned document representation, browse/search endpoints, pinned selections, LLM-based QA case generation, generation retrieval, and staleness/impact visibility.

**Input validation:** Both supplied CT-200 PDFs and the assignment update were reviewed. The parser was exercised against both manuals, and regression tests were added for the observed numbered classification list, the irregular `2.1.1.1` heading, the v2-only E6 code, the new Data Export section, and the v1 → v2 stale-generation workflow. This does not prove every visual/layout irregularity is solved; table cells are still retained as text rather than fully structured cells, and a human should inspect the extracted hierarchy before submission.

## 2. Data model

- `DocumentVersion`: document key, version label, source filename, timestamp. The `(document_key, version_label)` pair is unique, and an existing version is never silently overwritten.
- `DocumentNode`: version-specific node ID, logical key, heading, level, body text, parent ID, order, type, and SHA-256 content hash. The database node ID identifies one version's node; the logical key is a best-effort cross-version identity.
- `Selection` and `SelectionItem`: a named selection stores the exact node ID, version ID, heading, text snapshot, and hash. A later re-ingest cannot rewrite the selected source text.
- `GenerationRecord`: relational index for a generation stored in JSON. Generated JSON also includes a source snapshot and fingerprint so results remain traceable after re-ingestion.

## 3. Parsing strategy

PyMuPDF extracts selectable text in page order and attempts Tesseract OCR on pages with very little selectable text (Tesseract and English language data must be installed). A small CT-200-focused heuristic detects numbered headings and short all-caps headings. Number depth determines section level; a stack creates parent-child relationships. Unrecognized lines—including bullet and table-like rows—remain in the current section's body rather than being discarded. The actual manual exposed a false-positive: the numbered classification lines under Section 3.3 (for example, `1. Normal: ...`) were initially promoted to top-level headings. A rule now treats single-digit numbered entries containing a colon as list content. Repeated headings are separate nodes, and a logical key includes ancestry and an occurrence suffix.

This intentionally avoids pretending to understand uncertain structure. The OCR fallback depends on local Tesseract installation and may misrecognize text; OCR confidence is not yet recorded. The parser does not guarantee true table-cell extraction. The supplied manual also contains `2.1.1.1 Battery Life Under Typical Use` without an intermediate `2.1.1` heading. The parser preserves level 4 and attaches it to the nearest detected parent (`2.1 General Specifications`) instead of inventing a missing section. Visual tables are preserved as extracted text rows, not a guaranteed structured table object; image/caption association and OCR confidence remain limitations.

## 4. Unit-test coverage

`tests/test_parser.py` covers duplicate heading identity, nested hierarchy, numbered classification list preservation, the irregular heading-number gap, v2 E6 retention, the new Data Export section, and whitespace-normalized hashes. `tests/test_versioning.py` covers changed/unchanged text and unique-title matching. `tests/test_api_integration.py` ingests both actual PDFs, creates a v1 selection, generates cases, and verifies that retrieval flags it stale against v2.

## 5. Version matching

The primary matching key is ancestry + heading + occurrence index. A unique-title fallback is used only when a title occurs once in both versions. Body hashes then reveal content changes. This favors precision for duplicate headings over aggressive fuzzy matching. It can fail when headings are renamed, reordered under different parents, duplicated differently, or when the parser reconstructs a different ancestry. Those cases should be exposed for review instead of silently merging nodes. A production-grade extension could use normalized paths, numbering, title similarity, neighboring section context, and human-reviewed match overrides.

## 6. Staleness and impact detection

The selection stores the exact source text and hash. Generation records store that same source snapshot and a fingerprint. At retrieval, the API finds the latest node associated with the same logical key and compares hashes. Any changed hash marks the generation stale and includes a lightweight text comparison summary.

This is conservative: a punctuation or wording edit and a changed clinical threshold both mark stale. That is preferable to silently treating a possibly safety-relevant change as harmless, but it creates false positives and does not assess semantic or clinical impact. The current system is a traceability aid, not a medical-device safety determination. A future version could classify changed numeric values, units, negations, thresholds, warning terms, and error codes as high-impact while still requiring human review.

## 7. LLM prompt, validation, retry, and duplicate policy

The prompt requires 3–5 test-case ideas grounded only in selected source text and asks the model not to invent thresholds, error codes, or timing. The output is parsed as JSON and validated against Pydantic fields with length constraints. One retry asks for corrected JSON. If it still fails, the API returns HTTP 502 and does not save invalid output as a successful generation.

When no API key is configured, the application returns deterministic fallback cases clearly labelled `offline_fallback`; this makes local setup and tests possible, but it is not a substitute for demonstrating actual LLM output. Configure an OpenAI-compatible endpoint and key for the live demo.

Duplicate policy: submitting the same selection with the same source fingerprint returns the previous generation unless `regenerate=true` is supplied. This avoids accidental repeated calls/cost and provides predictable retrieval while allowing explicit regeneration.

## 8. Decision log

1. **Most likely silent wrong result:** Heading classification may mistake a numbered list item for a section heading or miss a visually formatted heading. Catch this with page-by-page visual comparison, node-count/parent checks, heading inventories, and tests built from every real irregularity in the supplied manual.
2. **Simplicity chosen over full correctness:** Text-based heuristics and exact hash staleness were chosen over layout/OCR/table understanding and semantic risk classification. In production, complex layouts, heading renumbering, or ambiguous duplicate sections would break matching first and could lead to incorrect traceability.
3. **Unsupported input:** A scanned PDF page that has no meaningful selectable text is sent through Tesseract OCR. If OCR is unavailable or still returns too little text, ingestion returns a clear error rather than creating a misleading hierarchy. OCR confidence tracking is not implemented yet.

## 9. What I would improve with more time

- Improve visual comparison and enumerate any remaining structural irregularities in the supplied CT-200 manuals.
- Add visual page render comparisons, table extraction, figure/caption associations, page references, OCR confidence tracking, and improved handling for mixed scanned/text pages.
- Add transactional tests for the complete v1 → v2 → stale generation API flow, plus tests for malformed LLM output and duplicate generation behavior.
- Use an atomic/transactional store for generation documents under concurrent requests and add schema migrations.
- Improve cross-version matching with parent context, section numbers, normalized title similarity, explicit unmatched/ambiguous states, and manual overrides.
- Add risk-aware change classification without allowing it to suppress conservative staleness flags automatically.
