# Ask the Tenant Book — openigloo Assistant UI & Production Server

A production-grade, authoritative web user interface and zero-dependency backend server for **"Ask the Tenant Book"**, built strictly in compliance with **Qualification Bar 6 ("Frontend Fidelity")**.

---

## Features

- **Qualification Bar 6 ("Frontend Fidelity") Compliance**:
  - **Refusal Fidelity**: Refusals *never* look like answers. Neutral gray dashed cards for `out_of_corpus` ("Not in the Tenant Book") vs. high-contrast security lockout cards for `not_permitted` ("Access Restricted — Information Not Available for Your Role").
  - **Zero Leaks**: Blocked documents never leak titles, sections, or quotes to unauthorized roles.
  - **In-Place Verbatim Citation Highlighting**: Clicking any citation pill smoothly scrolls to the exact section in the right pane and wraps the verbatim quoted passage in a glowing, pulsing highlight (`<mark class="citation-highlight">`) with a `"Quoted in Answer (#N)"` badge.
  - **Conflict Resolution & Governing Rule Box**: Automatically renders a dedicated container displaying which rule controls (e.g., openigloo listing standards P6 / P7) and tags overridden laws with strikethroughs.
  - **Temporal & Superseded Document Notices**: Clear alerts when laws were not yet in effect or when orders (such as RGB Order #55 vs #56) were superseded.
  - **Reviewer Walkthrough 12 Presets**: Built-in dropdown selector preloaded with all 12 benchmark evaluation scenarios for single-click verification.
- **Zero External Dependencies**:
  - Backend runs on standard Python 3 (`http.server.ThreadingHTTPServer`) with zero pip dependencies.
  - Frontend runs pure HTML5, modern CSS Grid/Flexbox, and vanilla ES6+ modules with bundled offline Markdown rendering (`marked.min.js`).

---

## Directory Structure

```
openIgloo-frontend/
├── app/
│   ├── server.py              # Zero-dependency HTTP server & Ask API engine
│   └── static/
│       ├── index.html         # Responsive semantic dual-pane SPA
│       ├── style.css          # Design system, dark/light themes, refusal styles
│       ├── app.js             # State management, API client, highlighting
│       └── vendor/
│           └── marked.min.js  # Bundled offline markdown renderer
├── corpus/                    # 30 verified NYC housing docs & manifest.json
│   ├── docs/                  # Full markdown documents with ## section headers
│   ├── manifest.json          # Document metadata, effective dates & visibility
│   └── passages.jsonl         # Chunked passages
├── schemas/                   # JSON schemas for requests, responses & questions
│   ├── request.schema.json
│   └── response.schema.json
├── scripts/
│   └── serve.sh               # Quick launcher script
└── tests/
    └── test_api.py            # Automated test suite (12 benchmarks & endpoints)
```

---

## Quick Start

### 1. Launch the Server

Run the launcher script from either the repository root or parent:

```bash
./scripts/serve.sh
```

Or run directly with Python:

```bash
python3 app/server.py --port 8080
```

Open your browser to:
👉 **[http://localhost:8080](http://localhost:8080)**

---

## 12 Benchmark Walkthrough Scenarios

Use the **"Benchmark Walkthrough"** dropdown in the top navigation bar to test any of the 12 evaluation test cases:

1. **Plain In-Corpus Answer**: Security deposit 14-day return timeline (`renter`, `2025-06-01`).
2. **Contradiction**: Platform no-fee listing vs FARE Act broker fee (`renter`, `2025-08-15`).
3. **Contradiction**: Summer rental seasonal deposit exception vs openigloo cap (`renter`, `2025-07-15`).
4. **Policy Override**: Rent renewal % calculation ban under Claire Policy P2 (`renter`, `2024-07-01`).
5. **Refusal (Out of Corpus)**: New Jersey jurisdiction inquiry (`renter`, `2025-08-01`).
6. **Refusal (Out of Corpus)**: SCRIE senior rent increase exemption (`renter`, `2026-01-15`).
7. **Refusal (Role Blocked)**: Renter asking for landlord screening criteria (`renter`, `2025-09-01`).
8. **Role Clearance Counterpart**: Landlord asking voucher income criteria (`landlord`, `2025-09-01`).
9. **Temporal (Pre-FARE Act)**: Broker fee inquiry prior to enactment date (`renter`, `2025-05-01`).
10. **Temporal (Post-FARE Act)**: Broker fee inquiry after June 11, 2025 (`renter`, `2025-08-15`).
11. **Superseded Document**: Rent Guidelines Board Order #55 vs #56 (`staff`, `2024-07-15`).
12. **Staff Escalation**: Discrimination report handling and threshold rules (`staff`, `2025-09-01`).

---

## Running Automated Tests

Run the full automated verification suite:

```bash
python3 tests/test_api.py
```

This verifies:
- All 30 corpus documents and passages.
- All 12 benchmark test cases against `schemas/response.schema.json`.
- Exact verbatim quote matches in source markdown files.
- Zero-leak role security.
- Live HTTP endpoints (`GET /`, `GET /static/*`, `GET /api/manifest`, `GET /api/docs/:id`, `POST /ask`).
