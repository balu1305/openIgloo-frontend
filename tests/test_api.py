#!/usr/bin/env python3
"""Automated Test Suite for Ask the Tenant Book Server and UI API.

Validates:
1. Corpus integrity (30 verified docs, passages, manifest).
2. All 12 benchmark walkthrough test cases against Qualification Bar 6 criteria.
3. Schema conformity for AskRequest and AskResponse.
4. Verbatim quotation matching in cited documents.
5. Role-blocked zero-leak security guarantees.
6. Live HTTP server endpoints (/health, /manifest, /presets, /docs/:id, /ask, static files).
"""

import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

# Add repo to sys.path
TEST_DIR = Path(__file__).resolve().parent
REPO_DIR = TEST_DIR.parent
sys.path.insert(0, str(REPO_DIR))

from app.server import ENGINE, TenantBookRequestHandler, norm


def test_corpus_loaded():
    print("Testing corpus loading...")
    assert len(ENGINE.documents) >= 30, f"Expected >= 30 documents, got {len(ENGINE.documents)}"
    assert "claire_policy" in ENGINE.documents, "claire_policy missing from corpus"
    assert "openigloo_help_fees" in ENGINE.documents, "openigloo_help_fees missing"
    assert "landlord_screening_guidelines" in ENGINE.documents, "landlord_screening_guidelines missing"
    assert "nyc_fare_act" in ENGINE.documents, "nyc_fare_act missing"
    assert len(ENGINE.passages) > 0, "No passages loaded"
    assert len(ENGINE.presets) == 12, f"Expected 12 presets, got {len(ENGINE.presets)}"
    print("✓ Corpus verified: 30 documents, passages, and 12 presets loaded.\n")


def test_presets_bar6_fidelity():
    print("Testing 12 Benchmark Walkthrough Scenarios (Bar 6 Fidelity)...")

    for idx, preset in enumerate(ENGINE.presets, 1):
        req = {
            "id": preset["id"],
            "question": preset["question"],
            "role": preset["role"],
            "as_of": preset["as_of"]
        }
        res = ENGINE.ask(req)

        # Basic schema checks
        assert res.get("id") == req["id"], f"Preset {idx}: id mismatch"
        assert res.get("status") in ("answered", "refused"), f"Preset {idx}: invalid status"

        if res["status"] == "answered":
            assert res.get("answer"), f"Preset {idx}: empty answer"
            assert res.get("refusal_reason") is None, f"Preset {idx}: refusal_reason should be null"
            assert len(res.get("citations", [])) > 0, f"Preset {idx}: answered question must have citations"

            # Check verbatim quotes
            for c in res["citations"]:
                doc_id = c["doc_id"]
                assert doc_id in ENGINE.doc_contents, f"Preset {idx}: cited doc {doc_id} not in corpus"
                content_norm = norm(ENGINE.doc_contents[doc_id])
                quote_norm = norm(c["quote"])
                assert quote_norm in content_norm, f"Preset {idx}: Quote not found verbatim in {doc_id}: '{c['quote'][:50]}...'"
                assert len(c["quote"]) >= 20, f"Preset {idx}: Quote too short (< 20 chars)"
                assert c.get("section"), f"Preset {idx}: Section heading missing in citation"

        elif res["status"] == "refused":
            assert res.get("refusal_reason") in ("out_of_corpus", "not_permitted"), f"Preset {idx}: invalid refusal_reason"
            assert res.get("citations") == [], f"Preset {idx}: refused questions must have empty citations"
            assert res.get("refusal_message"), f"Preset {idx}: refusal_message must not be empty"

        # Specific scenario checks
        if preset["id"] == "tb-0004":  # Contradiction no-fee vs FARE Act
            assert res.get("governing") is not None, "Preset 2: governing rule must be present"
            assert res["governing"]["doc_id"] == "claire_policy", "Preset 2: claire_policy must govern"

        if preset["id"] == "tb-0138":  # Seasonal deposit exception vs openigloo cap
            assert res.get("governing") is not None, "Preset 3: governing rule must be present"
            assert res["governing"]["doc_id"] == "claire_policy", "Preset 3: claire_policy must govern"

        if preset["id"] == "tb-0010":  # Role blocked
            assert res["status"] == "refused", "Preset 7: must be refused"
            assert res["refusal_reason"] == "not_permitted", "Preset 7: reason must be not_permitted"
            # ZERO LEAK CHECK
            msg = res["refusal_message"].lower()
            assert "landlord_screening_guidelines" not in msg, "Preset 7: Leaked doc_id!"
            assert "screening" not in msg, "Preset 7: Leaked screening title!"
            assert "40 times" not in msg, "Preset 7: Leaked quote content!"

        if preset["id"] == "tb-0226":  # Superseded order
            assert res.get("superseded_notice") is not None, "Preset 11: superseded notice must be present"
            assert "Order #55" in res["superseded_notice"] or "Order #56" in res["superseded_notice"]

        print(f"✓ Preset {idx} [{preset['category']}]: status={res['status']}, citations={len(res.get('citations', []))}")

    print("✓ All 12 benchmark presets passed with 100% Bar 6 fidelity.\n")


def test_http_server():
    print("Testing live HTTP server endpoints...")
    port = 8765
    server = ThreadingHTTPServer(("127.0.0.1", port), TenantBookRequestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)

    base = f"http://127.0.0.1:{port}"

    try:
        # 1. GET /
        with urllib.request.urlopen(f"{base}/") as r:
            assert r.status == 200
            body = r.read().decode("utf-8")
            assert "Ask the Tenant Book" in body
            assert "app.js" in body

        # 2. GET /static/style.css
        with urllib.request.urlopen(f"{base}/static/style.css") as r:
            assert r.status == 200
            css = r.read().decode("utf-8")
            assert "--primary" in css

        # 3. GET /api/health
        with urllib.request.urlopen(f"{base}/api/health") as r:
            assert r.status == 200
            data = json.loads(r.read().decode("utf-8"))
            assert data["status"] == "healthy"
            assert data["corpus_docs"] >= 30

        # 4. GET /api/manifest
        with urllib.request.urlopen(f"{base}/api/manifest") as r:
            assert r.status == 200
            manifest = json.loads(r.read().decode("utf-8"))
            assert "documents" in manifest

        # 5. GET /api/presets
        with urllib.request.urlopen(f"{base}/api/presets") as r:
            assert r.status == 200
            presets = json.loads(r.read().decode("utf-8"))
            assert len(presets) == 12

        # 6. GET /api/docs/claire_policy
        with urllib.request.urlopen(f"{base}/api/docs/claire_policy") as r:
            assert r.status == 200
            doc = json.loads(r.read().decode("utf-8"))
            assert doc["doc_id"] == "claire_policy"
            assert "content" in doc
            assert len(doc["content"]) > 100

        # 7. POST /ask (Preset 1)
        req_data = {
            "id": "test-req-001",
            "question": "I moved out of my market-rate apartment last week. How many days does my landlord have to return my security deposit?",
            "role": "renter",
            "as_of": "2025-06-01"
        }
        req = urllib.request.Request(
            f"{base}/ask",
            data=json.dumps(req_data).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req) as r:
            assert r.status == 200
            res = json.loads(r.read().decode("utf-8"))
            assert res["id"] == "test-req-001"
            assert res["status"] == "answered"
            assert len(res["citations"]) >= 1

        # 8. POST /ask (Role Blocked)
        req_blocked = {
            "id": "test-req-blocked",
            "question": "What income requirement do openigloo landlords apply to applicants?",
            "role": "renter",
            "as_of": "2025-09-01"
        }
        req2 = urllib.request.Request(
            f"{base}/ask",
            data=json.dumps(req_blocked).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req2) as r:
            assert r.status == 200
            res2 = json.loads(r.read().decode("utf-8"))
            assert res2["status"] == "refused"
            assert res2["refusal_reason"] == "not_permitted"
            assert res2["citations"] == []

        print("✓ All HTTP server API endpoints verified successfully.")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)


if __name__ == "__main__":
    test_corpus_loaded()
    test_presets_bar6_fidelity()
    test_http_server()
    print("=========================================================")
    print(" ALL AUTOMATED TESTS PASSED (100% Bar 6 Verification)")
    print("=========================================================")
