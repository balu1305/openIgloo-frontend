/**
 * Ask the Tenant Book — Production Client Application Logic
 * Implements Qualification Bar 6 ("Frontend Fidelity"):
 * - Distinct out-of-corpus vs role-blocked refusal views.
 * - In-place verbatim citation highlighting with glowing pulse and smooth scroll.
 * - Conflict resolution and governing rule surfacing.
 * - Temporal and superseded notices.
 * - 12 preset benchmark test runner.
 */

// --------------------------------------------------------------------------
// 1. Application State
// --------------------------------------------------------------------------
const state = {
  role: 'renter',
  asOf: '2025-08-15',
  currentQuestion: '',
  response: null,
  activeDocId: null,
  activeCitationIndex: 0,
  manifest: null,
  presets: [],
  theme: localStorage.getItem('tenant_book_theme') || 'dark',
};

// --------------------------------------------------------------------------
// 2. DOM Elements Cache
// --------------------------------------------------------------------------
const DOM = {
  themeToggle: document.getElementById('theme-toggle'),
  roleClearanceBadge: document.getElementById('role-clearance-badge'),
  roleSegments: document.querySelectorAll('#role-segmented-control .segment-btn'),
  asOfDateInput: document.getElementById('as-of-date'),
  datePresetsBtn: document.getElementById('date-presets-btn'),
  datePresetsMenu: document.getElementById('date-presets-menu'),
  walkthroughSelect: document.getElementById('walkthrough-select'),
  askForm: document.getElementById('ask-form'),
  questionInput: document.getElementById('question-input'),
  submitBtn: document.getElementById('submit-btn'),
  clearBtn: document.getElementById('clear-btn'),
  
  // Views
  stateEmpty: document.getElementById('state-empty'),
  stateLoading: document.getElementById('state-loading'),
  loadingMessage: document.getElementById('loading-message'),
  stateAnswered: document.getElementById('state-answered'),
  stateOutOfCorpus: document.getElementById('state-out-of-corpus'),
  stateRoleBlocked: document.getElementById('state-role-blocked'),

  // Answer View Components
  answeredAsofBadge: document.getElementById('answered-asof-badge'),
  supersededNoticeBox: document.getElementById('superseded-notice-box'),
  supersededNoticeText: document.getElementById('superseded-notice-text'),
  governingBox: document.getElementById('governing-box'),
  govWinnerDoc: document.getElementById('gov-winner-doc'),
  govReason: document.getElementById('gov-reason'),
  govOverriddenContainer: document.getElementById('gov-overridden-container'),
  govOverriddenList: document.getElementById('gov-overridden-list'),
  answerText: document.getElementById('answer-text'),
  citationsList: document.getElementById('citations-list'),
  legalDisclaimerBox: document.getElementById('legal-disclaimer-box'),

  // Refusal View Components
  outOfCorpusMessage: document.getElementById('out-of-corpus-message'),
  roleBlockedMessage: document.getElementById('role-blocked-message'),

  // Evidence Viewer Components
  docSelector: document.getElementById('doc-selector'),
  docTitle: document.getElementById('doc-title'),
  docIdBadge: document.getElementById('doc-id-badge'),
  docIssuer: document.getElementById('doc-issuer'),
  docEffectiveDates: document.getElementById('doc-effective-dates'),
  docVisibilityPills: document.getElementById('doc-visibility-pills'),
  docSupersededBanner: document.getElementById('doc-superseded-banner'),
  docSupersededText: document.getElementById('doc-superseded-text'),
  docSourceLink: document.getElementById('doc-source-link'),
  docBodyContainer: document.getElementById('doc-body-container'),
  toastContainer: document.getElementById('toast-container'),
};

// --------------------------------------------------------------------------
// 3. String Normalization & Exact Substring Finder (Matching grader.py)
// --------------------------------------------------------------------------
function norm(s) {
  if (!s) return '';
  let str = s.normalize('NFKC').replace(/\xad/g, '');
  str = str.replace(/[’‘]/g, "'").replace(/[“”]/g, '"');
  str = str.replace(/[–—]/g, '-');
  return str.replace(/\s+/g, ' ').trim().toLowerCase();
}

/**
 * Searches for a verbatim quote inside raw markdown content with normalization tolerance,
 * and wraps it in a glowing <mark class="citation-highlight"> tag.
 */
function highlightVerbatimQuote(markdownText, quote, citationNumber = 1) {
  if (!markdownText || !quote) return markdownText;

  // 1. Direct exact match check
  const exactIdx = markdownText.indexOf(quote);
  if (exactIdx !== -1) {
    const before = markdownText.slice(0, exactIdx);
    const matched = markdownText.slice(exactIdx, exactIdx + quote.length);
    const after = markdownText.slice(exactIdx + quote.length);
    const badge = `<span class="highlight-badge-pill">Quoted in Answer (#${citationNumber})</span>`;
    return `${before}<mark class="citation-highlight active-pulse" id="active-citation-mark">${badge}${matched}</mark>${after}`;
  }

  // 2. Normalized sliding window search
  const normQuote = norm(quote);
  if (normQuote.length < 15) return markdownText;

  // Quick heuristic: search by first 25 normalized chars
  const anchorLength = Math.min(30, normQuote.length);
  const anchor = normQuote.slice(0, anchorLength);

  // Walk through lines of markdown
  const lines = markdownText.split('\n');
  let matchFound = false;

  for (let i = 0; i < lines.length; i++) {
    const lineNorm = norm(lines[i]);
    if (lineNorm.includes(anchor)) {
      // Highlight this paragraph / line
      const badge = `<span class="highlight-badge-pill">Quoted in Answer (#${citationNumber})</span>`;
      lines[i] = `<mark class="citation-highlight active-pulse" id="active-citation-mark">${badge}${lines[i]}</mark>`;
      matchFound = true;
      break;
    }
  }

  if (matchFound) {
    return lines.join('\n');
  }

  return markdownText;
}

// --------------------------------------------------------------------------
// 4. API Client Service
// --------------------------------------------------------------------------
const API = {
  async health() {
    const r = await fetch('/api/health');
    return r.json();
  },

  async manifest() {
    const r = await fetch('/api/manifest');
    return r.json();
  },

  async presets() {
    const r = await fetch('/api/presets');
    return r.json();
  },

  async doc(docId) {
    const r = await fetch(`/api/docs/${encodeURIComponent(docId)}`);
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${r.status}`);
    }
    return r.json();
  },

  async ask(req) {
    const r = await fetch('/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.error || `Server Error ${r.status}`);
    }
    return r.json();
  }
};

// --------------------------------------------------------------------------
// 5. Toast Notifications
// --------------------------------------------------------------------------
function showToast(message, icon = 'ℹ️', durationMs = 3200) {
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `<span class="toast-icon">${icon}</span><span class="toast-msg">${message}</span>`;
  DOM.toastContainer.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, durationMs);
}

// --------------------------------------------------------------------------
// 6. Theme & Clearance Badge Updates
// --------------------------------------------------------------------------
function applyTheme(theme) {
  state.theme = theme;
  document.documentElement.setAttribute('data-theme', theme);
  DOM.themeToggle.querySelector('.theme-icon').textContent = theme === 'dark' ? '🌙' : '☀️';
  localStorage.setItem('tenant_book_theme', theme);
}

function updateRoleClearanceUI(role) {
  state.role = role;
  DOM.roleSegments.forEach((btn) => {
    const isActive = btn.dataset.role === role;
    btn.classList.toggle('active', isActive);
    btn.setAttribute('aria-checked', isActive);
  });

  const badge = DOM.roleClearanceBadge;
  badge.className = `clearance-pill pill-${role}`;
  if (role === 'renter') {
    badge.textContent = 'Public Renter';
  } else if (role === 'landlord') {
    badge.textContent = 'Landlord Access';
  } else if (role === 'staff') {
    badge.textContent = 'Staff Internal';
  }
}

// --------------------------------------------------------------------------
// 7. View State Router
// --------------------------------------------------------------------------
function showState(viewName) {
  const views = [DOM.stateEmpty, DOM.stateLoading, DOM.stateAnswered, DOM.stateOutOfCorpus, DOM.stateRoleBlocked];
  views.forEach((v) => v.classList.remove('active'));

  if (viewName === 'empty') DOM.stateEmpty.classList.add('active');
  else if (viewName === 'loading') DOM.stateLoading.classList.add('active');
  else if (viewName === 'answered') DOM.stateAnswered.classList.add('active');
  else if (viewName === 'out_of_corpus') DOM.stateOutOfCorpus.classList.add('active');
  else if (viewName === 'role_blocked') DOM.stateRoleBlocked.classList.add('active');
}

// --------------------------------------------------------------------------
// 8. Render Answer / Refusal Response
// --------------------------------------------------------------------------
function renderResponse(res, req) {
  state.response = res;

  if (res.status === 'answered') {
    showState('answered');

    // As-of date badge
    DOM.answeredAsofBadge.textContent = `As of: ${req.as_of || state.asOf}`;

    // Superseded Notice Banner
    if (res.superseded_notice) {
      DOM.supersededNoticeBox.classList.remove('hidden');
      DOM.supersededNoticeText.textContent = res.superseded_notice;
    } else {
      DOM.supersededNoticeBox.classList.add('hidden');
    }

    // Conflict / Governing Rule Box
    if (res.governing) {
      DOM.governingBox.classList.remove('hidden');
      DOM.govWinnerDoc.textContent = res.governing.doc_id;
      DOM.govReason.textContent = res.governing.reason;

      const overridden = res.governing.overridden || [];
      if (overridden.length > 0) {
        DOM.govOverriddenContainer.classList.remove('hidden');
        DOM.govOverriddenList.innerHTML = overridden
          .map((docId) => `<span class="overridden-tag">${docId}</span>`)
          .join('');
      } else {
        DOM.govOverriddenContainer.classList.add('hidden');
      }
    } else {
      DOM.governingBox.classList.add('hidden');
    }

    // Plain Answer text rendered via marked
    DOM.answerText.innerHTML = marked.parse(res.answer || '');

    // Citations list
    const citations = res.citations || [];
    DOM.citationsList.innerHTML = '';

    if (citations.length === 0) {
      DOM.citationsList.innerHTML = '<p class="subtle-hint">No citations attached.</p>';
    } else {
      citations.forEach((c, idx) => {
        const pill = document.createElement('button');
        pill.type = 'button';
        pill.className = `citation-pill-btn ${idx === 0 ? 'active' : ''}`;
        pill.innerHTML = `
          <span class="cit-num">[${idx + 1}]</span>
          <div class="cit-details">
            <span class="cit-doc-id">${c.doc_id}</span>
            <span class="cit-section">${c.section || 'General'}</span>
          </div>
          <span class="cit-jump-arrow">Jump to quote ↗</span>
        `;
        pill.addEventListener('click', () => {
          DOM.citationsList.querySelectorAll('.citation-pill-btn').forEach((p) => p.classList.remove('active'));
          pill.classList.add('active');
          loadAndHighlightCitation(c.doc_id, c.quote, idx + 1);
        });
        DOM.citationsList.appendChild(pill);
      });

      // Automatically load and highlight the first citation in the right pane!
      loadAndHighlightCitation(citations[0].doc_id, citations[0].quote, 1);
    }

    // Check for legal tactical advice boundary (Policy P8/P9)
    const qLower = (req.question || '').toLowerCase();
    const isLegalAdviceQuestion =
      qLower.includes('withhold') ||
      qLower.includes('stop paying') ||
      qLower.includes('sue') ||
      qLower.includes('countersue') ||
      qLower.includes('court papers');

    DOM.legalDisclaimerBox.classList.toggle('hidden', !isLegalAdviceQuestion);
  } else if (res.status === 'refused') {
    if (res.refusal_reason === 'not_permitted') {
      showState('role_blocked');
      DOM.roleBlockedMessage.textContent =
        res.refusal_message ||
        "The requested document or policy is restricted to authorized roles. Your current role is not permitted to view this information.";
      // Ensure right pane does NOT leak anything
      resetEvidenceViewer();
    } else {
      // Out of corpus or other
      showState('out_of_corpus');
      DOM.outOfCorpusMessage.textContent =
        res.refusal_message ||
        "This question is outside the scope of the verified NYC Tenant Book. The assistant only answers from verified corpus documents.";
      resetEvidenceViewer();
    }
  }
}

// --------------------------------------------------------------------------
// 9. Load and Highlight Evidence in Right Pane
// --------------------------------------------------------------------------
async function loadAndHighlightCitation(docId, quote, citationNumber = 1) {
  try {
    state.activeDocId = docId;
    state.activeCitationIndex = citationNumber;

    // Update document dropdown selector
    if (DOM.docSelector.value !== docId) {
      DOM.docSelector.value = docId;
    }

    // Fetch full document
    const doc = await API.doc(docId);

    // Update Document Header
    DOM.docTitle.textContent = doc.title || docId;
    DOM.docIdBadge.textContent = doc.doc_id;
    DOM.docIssuer.textContent = doc.issuer || 'openigloo / NYC';
    DOM.docEffectiveDates.textContent = `${doc.effective_from || 'Always'} to ${doc.effective_to || 'Present'}`;

    // Visibility Pills
    const vis = doc.visibility || ['renter', 'landlord', 'staff'];
    DOM.docVisibilityPills.innerHTML = vis
      .map((r) => `<span class="role-tag ${r}">${r}</span>`)
      .join('');

    // Source Link
    if (doc.source_url && doc.source_url !== 'internal') {
      DOM.docSourceLink.href = doc.source_url;
      DOM.docSourceLink.classList.remove('hidden');
    } else {
      DOM.docSourceLink.classList.add('hidden');
    }

    // Superseded Notice
    if (doc.superseded_by) {
      DOM.docSupersededBanner.classList.remove('hidden');
      DOM.docSupersededText.textContent = `This document has been superseded by ${doc.superseded_by}.`;
    } else {
      DOM.docSupersededBanner.classList.add('hidden');
    }

    // Highlight verbatim quote in markdown text
    const rawContent = doc.content || '';
    const contentWithHighlight = highlightVerbatimQuote(rawContent, quote, citationNumber);

    // Render into Markdown DOM
    DOM.docBodyContainer.innerHTML = marked.parse(contentWithHighlight);

    // Smooth scroll directly to the highlighted mark
    setTimeout(() => {
      const mark = document.getElementById('active-citation-mark');
      if (mark) {
        mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }
    }, 80);

    showToast(`Loaded evidence: ${docId}`, '📄', 2000);
  } catch (err) {
    console.error('Error loading citation document:', err);
    showToast(`Failed to load evidence: ${err.message}`, '⚠️');
  }
}

function resetEvidenceViewer() {
  DOM.docTitle.textContent = 'Evidence Restricted or Unavailable';
  DOM.docIdBadge.textContent = 'no document loaded';
  DOM.docIssuer.textContent = '—';
  DOM.docEffectiveDates.textContent = '—';
  DOM.docVisibilityPills.innerHTML = '';
  DOM.docSupersededBanner.classList.add('hidden');
  DOM.docSourceLink.classList.add('hidden');
  DOM.docBodyContainer.innerHTML = `
    <div class="doc-placeholder">
      <div class="placeholder-icon">🔒</div>
      <h4>Zero-Leak Protection Active</h4>
      <p>No document, section, or quote information is exposed for refused or unauthorized queries.</p>
    </div>
  `;
}

// --------------------------------------------------------------------------
// 10. Form Submission & Query Pipeline
// --------------------------------------------------------------------------
async function handleAskSubmit(e) {
  if (e) e.preventDefault();
  const q = DOM.questionInput.value.trim();
  if (!q) {
    showToast('Please enter a question to ask', '⚠️');
    return;
  }

  state.currentQuestion = q;
  showState('loading');
  DOM.submitBtn.disabled = true;

  const req = {
    id: `req-${Date.now()}`,
    question: q,
    role: state.role,
    as_of: state.asOf,
  };

  try {
    const res = await API.ask(req);
    renderResponse(res, req);
  } catch (err) {
    console.error('API Query Error:', err);
    showToast(`Query Failed: ${err.message}`, '❌');
    showState('empty');
  } finally {
    DOM.submitBtn.disabled = false;
  }
}

// --------------------------------------------------------------------------
// 11. 12 Benchmark Walkthrough Presets
// --------------------------------------------------------------------------
function loadPreset(presetIdx) {
  const preset = state.presets[presetIdx];
  if (!preset) return;

  // Set inputs
  updateRoleClearanceUI(preset.role);
  state.asOf = preset.as_of;
  DOM.asOfDateInput.value = preset.as_of;
  DOM.questionInput.value = preset.question;
  DOM.walkthroughSelect.value = presetIdx.toString();

  showToast(`Loaded Walkthrough #${presetIdx + 1}: ${preset.category}`, '🎯', 2800);

  // Auto submit query
  handleAskSubmit();
}

// --------------------------------------------------------------------------
// 12. Initialization & Event Listeners
// --------------------------------------------------------------------------
async function initApp() {
  applyTheme(state.theme);
  updateRoleClearanceUI(state.role);

  // Fetch manifest and presets in parallel
  try {
    const [manifest, presets] = await Promise.all([
      API.manifest().catch(() => ({ documents: [] })),
      API.presets().catch(() => []),
    ]);

    state.manifest = manifest;
    state.presets = presets;

    // Populate Corpus Document Selector
    const docs = manifest.documents || [];
    DOM.docSelector.innerHTML = '<option value="" disabled selected>Browse 30 Corpus Documents...</option>';
    docs.forEach((d) => {
      const opt = document.createElement('option');
      opt.value = d.doc_id;
      opt.textContent = `${d.title} (${d.doc_id})`;
      DOM.docSelector.appendChild(opt);
    });
  } catch (err) {
    console.warn('Initialization metadata fetch notice:', err);
  }

  // Role Segmented Switch
  DOM.roleSegments.forEach((btn) => {
    btn.addEventListener('click', () => {
      const newRole = btn.dataset.role;
      updateRoleClearanceUI(newRole);
      showToast(`Switched role to ${newRole.toUpperCase()}`, '👤', 2000);
      if (DOM.questionInput.value.trim()) {
        handleAskSubmit();
      }
    });
  });

  // Date input change
  DOM.asOfDateInput.addEventListener('change', (e) => {
    state.asOf = e.target.value;
    showToast(`As-of date set to ${state.asOf}`, '📅', 2000);
    if (DOM.questionInput.value.trim()) {
      handleAskSubmit();
    }
  });

  // Date Presets Menu Toggle
  DOM.datePresetsBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    DOM.datePresetsMenu.classList.toggle('show');
  });

  document.addEventListener('click', () => {
    DOM.datePresetsMenu.classList.remove('show');
  });

  DOM.datePresetsMenu.querySelectorAll('.menu-item').forEach((item) => {
    item.addEventListener('click', (e) => {
      e.stopPropagation();
      const date = item.dataset.date;
      state.asOf = date;
      DOM.asOfDateInput.value = date;
      DOM.datePresetsMenu.classList.remove('show');
      showToast(`Date set to ${date}`, '⚡', 2000);
      if (DOM.questionInput.value.trim()) {
        handleAskSubmit();
      }
    });
  });

  // Walkthrough Dropdown
  DOM.walkthroughSelect.addEventListener('change', (e) => {
    const idx = parseInt(e.target.value, 10);
    if (!isNaN(idx)) {
      loadPreset(idx);
    }
  });

  // Sample Chips
  document.querySelectorAll('.chip-btn').forEach((chip) => {
    chip.addEventListener('click', () => {
      const idx = parseInt(chip.dataset.presetIdx, 10);
      if (!isNaN(idx)) {
        loadPreset(idx);
      }
    });
  });

  // Form Submit & Keyboard Shortcuts
  DOM.askForm.addEventListener('submit', handleAskSubmit);

  DOM.questionInput.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleAskSubmit();
    }
  });

  // Clear Button
  DOM.clearBtn.addEventListener('click', () => {
    DOM.questionInput.value = '';
    DOM.walkthroughSelect.value = '';
    showState('empty');
    resetEvidenceViewer();
    showToast('Workspace cleared', '🧹', 1800);
  });

  // Document Selector
  DOM.docSelector.addEventListener('change', (e) => {
    const docId = e.target.value;
    if (docId) {
      loadAndHighlightCitation(docId, null, 1);
    }
  });

  // Theme Toggle
  DOM.themeToggle.addEventListener('click', () => {
    const newTheme = state.theme === 'dark' ? 'light' : 'dark';
    applyTheme(newTheme);
  });
}

// Boot on DOM ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}
