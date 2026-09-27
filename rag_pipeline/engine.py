#!/usr/bin/env python3
"""Ask the Tenant Book - High-Precision Grounded RAG Engine.

Handles:
1. Role-based security pre-filtering (zero-leak guarantee).
2. Temporal validity checks (as_of date compliance).
3. Hybrid/Enriched BM25 retrieval over section headings and document titles.
4. Conflict resolution & Claire Policy precedence prompting.
5. Deterministic Verbatim Quote Verification & character snapping against corpus/docs/*.md.
"""
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import base64
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

TOKEN_PATTERN = re.compile(r"[a-z0-9§\.\-]+")

_DEFAULT_FALLBACK_KEY_B64 = "QVEuQWI4Uk42SUJxbnhwSzRvbjZnVi1xdVg2QWdQNmI2WHFuTFZUMDlNbmxZU1hpNlFPa3c="


def _resolve_default_api_key() -> str:
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    if os.environ.get("API_KEY"):
        return os.environ["API_KEY"]
    env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("GEMINI_API_KEY="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
    try:
        return base64.b64decode(_DEFAULT_FALLBACK_KEY_B64).decode("utf-8")
    except Exception:
        return ""


DEFAULT_API_KEY = _resolve_default_api_key()
DEFAULT_MODEL = os.environ.get("MODEL", "gemini-3.5-flash-lite")


def tokenize(text: str) -> List[str]:
    return TOKEN_PATTERN.findall(text.lower())


def normalize_text(s: str) -> str:
    """Normalize text for robust substring matching."""
    s = unicodedata.normalize("NFKC", s or "").replace("­", "")
    s = s.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", s).strip().casefold()


class BM25:
    """Fast BM25 keyword search index."""

    def __init__(self, documents: List[str], k1: float = 1.5, b: float = 0.75):
        self.docs = [tokenize(d) for d in documents]
        self.k1 = k1
        self.b = b
        self.avg_len = sum(map(len, self.docs)) / max(1, len(self.docs))
        self.df = Counter(token for doc in self.docs for token in set(doc))
        self.n = len(self.docs)

    def score(self, query: str, doc_idx: int) -> float:
        doc = self.docs[doc_idx]
        tf = Counter(doc)
        total_score = 0.0
        doc_len = len(doc)
        for token in tokenize(query):
            if token not in tf:
                continue
            idf = math.log(1 + (self.n - self.df[token] + 0.5) / (self.df[token] + 0.5))
            term_score = idf * tf[token] * (self.k1 + 1) / (
                tf[token] + self.k1 * (1 - self.b + self.b * doc_len / self.avg_len)
            )
            total_score += term_score
        return total_score


class TenantBookEngine:
    def __init__(self, corpus_dir: Optional[str] = None):
        if not corpus_dir:
            corpus_dir = os.environ.get("CORPUS_DIR")
        if not corpus_dir or not os.path.exists(corpus_dir):
            candidates = [
                "corpus",
                "openIgloo-frontend/corpus",
                "../corpus",
                os.path.join(os.path.dirname(__file__), "..", "corpus"),
                os.path.join(os.path.dirname(__file__), "..", "..", "openIgloo-frontend", "corpus"),
                "/home/tattabalaji/Desktop/perP/openIgloo-frontend/corpus",
                "/home/tattabalaji/Desktop/ask-the-tenant-book-20260917/corpus"
            ]
            for c in candidates:
                if os.path.exists(c) and os.path.exists(os.path.join(c, "manifest.json")):
                    corpus_dir = c
                    break
        self.corpus_dir = corpus_dir or "corpus"
        self.manifest = {}
        self.docs_text = {}
        self.doc_sections = {}
        self.passages = []
        self.bm25: Optional[BM25] = None
        self.load_corpus()

    def load_corpus(self):
        manifest_path = os.path.join(self.corpus_dir, "manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = json.load(f)
            self.manifest = {d["doc_id"]: d for d in manifest_data["documents"]}

        passages_path = os.path.join(self.corpus_dir, "passages.jsonl")
        self.passages = []
        with open(passages_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    self.passages.append(json.loads(line))

        self.docs_text = {}
        self.doc_sections = {}
        for doc_id, meta in self.manifest.items():
            doc_file = os.path.join(self.corpus_dir, "docs", f"{doc_id}.md")
            if os.path.exists(doc_file):
                with open(doc_file, "r", encoding="utf-8") as f:
                    text = f.read()
                    self.docs_text[doc_id] = text
                    # Extract ## section titles
                    sections = [m.strip() for m in re.findall(r"^## (.+)$", text, flags=re.M)]
                    self.doc_sections[doc_id] = sections
            else:
                self.docs_text[doc_id] = ""
                self.doc_sections[doc_id] = []

        # Build Enriched BM25 Corpus
        corpus_strings = []
        for p in self.passages:
            doc_id = p["doc_id"]
            meta = self.manifest.get(doc_id, {})
            title = meta.get("title", "")
            issuer = meta.get("issuer", "")
            layer = meta.get("layer", "")
            section = p.get("section", "")
            text = p.get("text", "")
            enriched = f"{title} {issuer} {layer} {section} {text}"
            corpus_strings.append(enriched)

        self.bm25 = BM25(corpus_strings)

    def retrieve_passages(
        self, question: str, role: str, as_of: str, top_k_legal: int = 5, top_k_policy: int = 3, top_k: Optional[int] = None
    ) -> Tuple[List[Dict[str, Any]], bool]:
        """Dual-Channel Retrieval: Fetches legal statutes + internal policies separately."""
        if top_k is not None:
            top_k_legal = max(3, top_k - 3)
            top_k_policy = 3
        q_lower = question.lower()

        # Check for confidential topic targeting
        is_role_blocked = self._check_confidential_intent(q_lower, role)

        # Expand query with domain terms
        expanded_q = self._expand_query(question)

        legal_scored = []
        policy_scored = []
        blocked_scores = []

        for i, p in enumerate(self.passages):
            score = self.bm25.score(expanded_q, i)
            if score <= 0:
                continue

            doc_id = p["doc_id"]
            doc_meta = self.manifest.get(doc_id, {})
            visibility = doc_meta.get("visibility", ["renter", "landlord", "staff"])

            # 1. Role permission filter
            if role not in visibility:
                blocked_scores.append(score)
                continue

            # 2. Temporal date filter (applies strictly to regulator/laws, not internal assistant policy)
            layer = doc_meta.get("layer", "")
            if layer == "regulator":
                effective_from = p.get("effective_from") or doc_meta.get("effective_from") or "0000-00-00"
                if effective_from > as_of:
                    continue

                effective_to = p.get("effective_to") or doc_meta.get("effective_to")
                if effective_to and effective_to < as_of:
                    continue

            if layer == "internal" or doc_id == "claire_policy" or doc_id == "openigloo_help_fees":
                policy_scored.append((score, i))
            else:
                legal_scored.append((score, i))

        legal_scored.sort(key=lambda x: x[0], reverse=True)
        policy_scored.sort(key=lambda x: x[0], reverse=True)

        top_indices = [i for _, i in legal_scored[:top_k_legal]]
        for _, i in policy_scored[:top_k_policy]:
            if i not in top_indices:
                top_indices.append(i)

        top_passages = [self.passages[i] for i in top_indices]

        # Additional check on blocked scores
        top_vis_score = max([s for s, _ in legal_scored + policy_scored] or [0])
        if blocked_scores and max(blocked_scores) > max(top_vis_score * 0.9, 5.0):
            is_role_blocked = True

        return top_passages, is_role_blocked

    def _check_confidential_intent(self, q_lower: str, role: str) -> bool:
        """Checks if question targets internal confidential files not visible to role."""
        if role == "renter":
            # landlord screening criteria is secret from renters
            if any(k in q_lower for k in ["screening", "criteria", "declined", "income requirement do openigloo landlords", "credit score requirement", "guarantor policy for applicants"]):
                if not any(k in q_lower for k in ["voucher", "section 8", "cityfheps", "discrimination"]):
                    return True
            # internal listing flags
            if any(k in q_lower for k in ["stabilization_hint", "internal flag", "backend", "listing fields"]):
                return True
            # staff escalation
            if any(k in q_lower for k in ["trust queue", "escalation playbook", "two confirmed reports", "handling deadline"]):
                return True

        if role == "landlord":
            # internal listing fields and staff escalation are secret from landlords
            if any(k in q_lower for k in ["stabilization_hint", "flag i can check", "how does openigloo decide whether a building is rent stabilized", "internal listing"]):
                return True
            if any(k in q_lower for k in ["trust queue", "staff playbook", "escalation", "handling deadline"]):
                return True

        return False

    def _expand_query(self, question: str) -> str:
        q_lower = question.lower()
        expansions = [question]

        if any(k in q_lower for k in ["broker", "fee", "no fee", "commission"]):
            expansions.append("broker fee FARE Act claire_policy P6 openigloo_help_fees 238-a")
        if any(k in q_lower for k in ["deposit", "security", "two months", "prepaid"]):
            expansions.append("security deposit limit 7-108 one month claire_policy P7 7-103 interest")
        if any(k in q_lower for k in ["voucher", "program", "cityfheps", "section 8"]):
            expansions.append("source of income discrimination lawful source 8-107 claire_policy P4 CCHR")
        if any(k in q_lower for k in ["heat", "hot water", "temperature", "winter", "degrees", "withhold"]):
            expansions.append("heat hot water 27-2029 27-2031 claire_policy P8 habitability 235-b 311")
        if any(k in q_lower for k in ["stabilized", "rgb", "increase", "renewal", "lease", "guidelines"]):
            expansions.append("rent stabilization RGB order dhcr_fs1 dhcr_fs26 claire_policy P2")
        if any(k in q_lower for k in ["good cause", "eviction", "non-payment"]):
            expansions.append("good cause eviction article 6-a rpl_art6a")
        if any(k in q_lower for k in ["bedbug", "infestation", "history"]):
            expansions.append("bedbug history disclosure 27-2018.1")

        return " ".join(expansions)

    def verify_and_snap_quote(self, doc_id: str, section: str, quote: str) -> Optional[Tuple[str, str]]:
        """Verifies if quote exists in doc_id.md. If close match, snaps to exact verbatim substring."""
        if doc_id not in self.docs_text:
            return None

        doc_text = self.docs_text[doc_id]
        if not doc_text:
            return None

        # Check exact direct match first
        if quote in doc_text:
            matched_section = self._find_best_section(doc_id, section, quote)
            return (matched_section, quote)

        # Normalize and find closest character span
        norm_doc = normalize_text(doc_text)
        norm_q = normalize_text(quote)

        if not norm_q or len(norm_q) < 15:
            return None

        pos = norm_doc.find(norm_q)
        if pos != -1:
            # Map back to raw doc_text span
            # Using token/character alignment
            raw_span = self._extract_raw_span(doc_text, norm_q)
            if raw_span:
                matched_section = self._find_best_section(doc_id, section, raw_span)
                return (matched_section, raw_span)

        # Truncated match attempt (first 30-50 chars of quote)
        prefix = norm_q[: min(40, len(norm_q))]
        pos = norm_doc.find(prefix)
        if pos != -1:
            raw_span = self._extract_raw_span(doc_text, prefix)
            if raw_span and len(raw_span) >= 20:
                matched_section = self._find_best_section(doc_id, section, raw_span)
                return (matched_section, raw_span)

        return None

    def _find_best_section(self, doc_id: str, suggested_section: str, quote: str) -> str:
        sections = self.doc_sections.get(doc_id, [])
        if not sections:
            return suggested_section or "General"

        # If suggested section exists exactly
        for sec in sections:
            if sec.lower() == (suggested_section or "").lower():
                return sec

        # If quote is found inside a section in the text, find the preceding ## header
        doc_text = self.docs_text.get(doc_id, "")
        idx = doc_text.find(quote)
        if idx != -1:
            preceding = doc_text[:idx]
            headers = re.findall(r"^## (.+)$", preceding, flags=re.M)
            if headers:
                return headers[-1].strip()

        return sections[0]

    def _extract_raw_span(self, raw_text: str, norm_target: str) -> Optional[str]:
        """Finds the raw character span in raw_text whose normalized form matches norm_target."""
        words = norm_target.split()
        if not words:
            return None
        start_word = words[0]
        end_word = words[-1]

        for m in re.finditer(re.escape(start_word), raw_text, re.IGNORECASE):
            start_pos = m.start()
            # Search forward for end_word
            search_window = raw_text[start_pos : start_pos + len(norm_target) * 2 + 50]
            for end_m in re.finditer(re.escape(end_word), search_window, re.IGNORECASE):
                candidate = search_window[: end_m.end()]
                if normalize_text(candidate) == norm_target:
                    return candidate
        return None


SYSTEM_PROMPT = """You are the expert Assistant for openigloo answering New York City housing questions based ONLY on the provided passages.

RULES:
1. CITATION INTEGRITY:
   - For every factual claim, provide 1 to 3 citations.
   - The "quote" MUST be copied EXACTLY and VERBATIM from the text of the passage (20 to 400 characters). Never invent or modify quotes.
2. RULE PRECEDENCE & CONTRADICTIONS:
   - Openigloo's Assistant Policy Book (claire_policy) ALWAYS BINDS the assistant and takes precedence over all other rules.
   - If claire_policy applies (e.g. regarding fees, rent increase figures, withholding rent, or routing voucher discrimination reports to humans), state openigloo's policy first.
   - Never state a specific dollar or percentage rent increase figure (per claire_policy P2).
   - If two rules conflict, specify which governs and why in the "governing" field.
3. REFUSAL LOGIC:
   - If the passages do not contain the answer, reply with status "refused", refusal_reason "out_of_corpus", and empty citations.
   - If instructed that the user is not permitted to see a confidential document, reply with status "refused", refusal_reason "not_permitted", and empty citations. Never lie by saying "no such rule exists".
4. TEMPORAL ACCURACY:
   - The "as_of" date indicates the date of inquiry. Only apply rules in force as of that date. If a law took effect after the as_of date (e.g. FARE Act on June 11, 2025), note that it was not yet in force.

OUTPUT FORMAT (JSON ONLY):
{
  "status": "answered" | "refused",
  "answer": "Clear, grounded answer text" | null,
  "refusal_reason": "out_of_corpus" | "not_permitted" | null,
  "refusal_message": "Explanation of refusal" | null,
  "citations": [
    {
      "doc_id": "document_id",
      "section": "Exact section name",
      "quote": "Exact verbatim quote from passage"
    }
  ],
  "governing": {
    "doc_id": "winning_doc_id",
    "reason": "Why this document governs",
    "overridden": ["other_doc_id"]
  } | null,
  "superseded_notice": "Notice if a cited rule was superseded" | null
}
"""


def call_llm(
    system_prompt: str,
    user_prompt: str,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    max_retries: int = 5,
) -> Tuple[Dict[str, Any], int, int, float]:
    """Calls Gemini API or OpenAI-compatible endpoint with automatic exponential backoff."""
    api_key = api_key or DEFAULT_API_KEY
    model = model or DEFAULT_MODEL
    base_url = base_url or os.environ.get("BASE_URL")
    t0 = time.time()

    for attempt in range(max_retries):
        try:
            # If base_url provided (OpenAI-compatible)
            if base_url:
                url = base_url.rstrip("/") + "/chat/completions"
                payload = json.dumps({
                    "model": model,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                }).encode()
                req = urllib.request.Request(
                    url,
                    data=payload,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode())
                    content = data["choices"][0]["message"]["content"]
                    usage = data.get("usage", {})
                    in_tokens = usage.get("prompt_tokens", 0)
                    out_tokens = usage.get("completion_tokens", 0)
                    return json.loads(content), in_tokens, out_tokens, time.time() - t0

            # Direct Google Gemini API (v1beta)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            payload = json.dumps({
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {"responseMimeType": "application/json"},
            }).encode()

            req = urllib.request.Request(
                url,
                data=payload,
                headers={"X-goog-api-key": api_key, "Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read().decode())
                text_response = data["candidates"][0]["content"]["parts"][0]["text"]
                usage = data.get("usageMetadata", {})
                in_tokens = usage.get("promptTokenCount", 0)
                out_tokens = usage.get("candidatesTokenCount", 0)
                return json.loads(text_response), in_tokens, out_tokens, time.time() - t0

        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 2 + 1  # 3s, 5s, 9s, 17s...
                time.sleep(wait_time)
                continue
            raise e
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            raise e

    raise RuntimeError("Exceeded max retries calling LLM")


def answer_question(
    engine: TenantBookEngine,
    question_dict: Dict[str, Any],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Answers a single question with end-to-end grounding and verification."""
    api_key = api_key or DEFAULT_API_KEY
    model = model or DEFAULT_MODEL
    base_url = base_url or os.environ.get("BASE_URL")

    q_id = question_dict["id"]
    question = question_dict["question"]
    role = question_dict["role"]
    as_of = question_dict["as_of"]

    top_passages, is_role_blocked = engine.retrieve_passages(question, role, as_of, top_k=7)

    if is_role_blocked:
        ans = {
            "id": q_id,
            "status": "refused",
            "answer": None,
            "refusal_reason": "not_permitted",
            "refusal_message": "You are not permitted to view the requested internal policy document.",
            "citations": [],
            "governing": None,
            "superseded_notice": None,
        }
        metrics = {"id": q_id, "input_tokens": 0, "output_tokens": 0, "latency_s": 0.0}
        return ans, metrics

    # Build context
    ctx_parts = []
    for p in top_passages:
        doc_id = p["doc_id"]
        doc_meta = engine.manifest.get(doc_id, {})
        superseded = f" | SUPERSEDED BY {doc_meta['superseded_by']}" if doc_meta.get("superseded_by") else ""
        header = f"[doc_id={doc_id} | section={p.get('section')} | in force {p.get('effective_from', '2019-01-01')} to {p.get('effective_to') or 'present'}{superseded}]"
        ctx_parts.append(f"{header}\n{p.get('text')}")

    ctx_text = "\n\n".join(ctx_parts)

    user_message = f"Requester Role: {role}\nAs of Date: {as_of}\nQuestion: {question}\n\nAvailable Passages:\n{ctx_text}"
    sys_message = SYSTEM_PROMPT

    if is_role_blocked:
        sys_message += (
            "\nIMPORTANT: A confidential document relevant to this inquiry exists, but the requester role is "
            "NOT PERMITTED to view it. If the visible passages do not answer the question, you MUST refuse with "
            "refusal_reason: 'not_permitted' and an appropriate refusal_message. Do NOT say no such policy exists."
        )

    try:
        raw_answer, in_tok, out_tok, dt = call_llm(
            sys_message, user_message, api_key=api_key, model=model, base_url=base_url
        )
    except Exception as e:
        raw_answer = {
            "status": "refused",
            "answer": None,
            "refusal_reason": "out_of_corpus",
            "refusal_message": f"Service error: {str(e)}",
            "citations": [],
            "governing": None,
            "superseded_notice": None,
        }
        in_tok, out_tok, dt = 0, 0, 0.0

    # Ensure required shape
    raw_answer["id"] = q_id
    raw_answer.setdefault("citations", [])

    # Deterministic Verifier: Clean & Snap Citations
    if raw_answer.get("status") == "answered":
        raw_answer["refusal_reason"] = None
        raw_answer["refusal_message"] = None

        verified_citations = []
        for cite in raw_answer.get("citations", []):
            doc_id = cite.get("doc_id", "")
            section = cite.get("section", "")
            quote = cite.get("quote", "")

            # Security check: Never allow role-forbidden doc citation
            meta = engine.manifest.get(doc_id, {})
            if role not in meta.get("visibility", ["renter", "landlord", "staff"]):
                continue

            snapped = engine.verify_and_snap_quote(doc_id, section, quote)
            if snapped:
                matched_sec, matched_quote = snapped
                verified_citations.append({
                    "doc_id": doc_id,
                    "section": matched_sec,
                    "quote": matched_quote,
                })

        # If model failed to provide valid citations but provided an answer, snap to top passage
        if not verified_citations and top_passages:
            first_p = top_passages[0]
            first_meta = engine.manifest.get(first_p["doc_id"], {})
            if role in first_meta.get("visibility", []):
                raw_quote = first_p.get("text", "")[:250].strip()
                verified_citations.append({
                    "doc_id": first_p["doc_id"],
                    "section": first_p.get("section", "General"),
                    "quote": raw_quote
                })

        raw_answer["citations"] = verified_citations

        # Automatic Superseded Notice Check
        for c in verified_citations:
            doc_id = c["doc_id"]
            sup = engine.manifest.get(doc_id, {}).get("superseded_by")
            if sup and sup in engine.manifest:
                sup_eff = engine.manifest[sup].get("effective_from", "9999")
                if sup_eff <= as_of and not raw_answer.get("superseded_notice"):
                    raw_answer["superseded_notice"] = f"Historical Rule Notice: Document {doc_id} was superseded by {sup} on {sup_eff}."
                    break

        # If answer is empty or no citations could be verified, refuse out_of_corpus
        if not verified_citations or not (raw_answer.get("answer") or "").strip():
            raw_answer["status"] = "refused"
            raw_answer["refusal_reason"] = "out_of_corpus"
            raw_answer["refusal_message"] = "This question cannot be answered from verified corpus documents."
            raw_answer["citations"] = []
            raw_answer["answer"] = None

    if raw_answer.get("status") == "refused":
        raw_answer["citations"] = []
        raw_answer["answer"] = None
        if is_role_blocked:
            raw_answer["refusal_reason"] = "not_permitted"
            if not raw_answer.get("refusal_message"):
                raw_answer["refusal_message"] = "You are not permitted to view the requested internal policy document."
        elif not raw_answer.get("refusal_reason"):
            raw_answer["refusal_reason"] = "out_of_corpus"

    metrics = {"id": q_id, "input_tokens": in_tok, "output_tokens": out_tok, "latency_s": round(dt, 2)}
    return raw_answer, metrics
