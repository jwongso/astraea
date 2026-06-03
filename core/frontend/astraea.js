'use strict';
/**
 * Astraea shared frontend utilities.
 * Served by all Astraea apps at /static/astraea/astraea.js
 * Load BEFORE the jurisdiction-specific app.js.
 */
(function (global) {

  // ---- HTML escaping ----
  function escapeHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ---- Answer rendering ----
  function renderAnswer(text) {
    const idx = text.lastIndexOf('\n\nSources:');
    if (idx !== -1) text = text.substring(0, idx);
    text = escapeHtml(text.trim());

    const html = text.split(/\n{2,}/).map(para => {
      if (/^---+$/.test(para.trim())) return '<hr>';
      const lines = para.split('\n');

      const h = lines[0].match(/^(#{1,4}) (.+)/);
      if (h) {
        const level = Math.min(h[1].length + 2, 6);
        return `<h${level}>${h[2]}</h${level}>`;
      }

      if (lines.some(l => /^[-*] /.test(l.trim()))) {
        const items = []; let cur = null;
        for (const line of lines) {
          if (/^[-*] /.test(line.trim())) {
            if (cur !== null) items.push(cur);
            cur = line.trim().replace(/^[-*] /, '').replace(/  $/, '');
          } else if (cur !== null && line.trim()) {
            cur += ' ' + line.trim();
          }
        }
        if (cur !== null) items.push(cur);
        return `<ul>${items.map(t => `<li>${t}</li>`).join('')}</ul>`;
      }

      if (lines.some(l => /^\d+\. /.test(l.trim()))) {
        const items = []; let cur = null;
        for (const line of lines) {
          const m = line.trim().match(/^(\d+)\. (.*)/);
          if (m) { if (cur) items.push(cur); cur = { num: m[1], text: m[2].replace(/  $/, '') }; }
          else if (cur && line.trim()) cur.text += ' ' + line.trim();
        }
        if (cur) items.push(cur);
        return `<ol>${items.map(it => `<li value="${it.num}">${it.text}</li>`).join('')}</ol>`;
      }

      const tableLines = lines.filter(l => /^\|/.test(l.trim()));
      if (tableLines.length >= 2) {
        const sepIdx = tableLines.findIndex(l => /^\|[\s\-|:]+\|/.test(l.trim()) && !/[a-zA-Z0-9]/.test(l));
        if (sepIdx === 1) {
          const parseRow = row => row.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
          const headers = parseRow(tableLines[0]);
          const dataRows = tableLines.slice(sepIdx + 1);
          const thead = `<thead><tr>${headers.map(hh => `<th>${hh}</th>`).join('')}</tr></thead>`;
          const tbody = `<tbody>${dataRows.map(r => `<tr>${parseRow(r).map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody>`;
          return `<table class="answer-table">${thead}${tbody}</table>`;
        }
      }

      return `<p>${lines.map(l => l.replace(/  $/, '')).join('<br>')}</p>`;
    }).join('');

    return html
      .replace(/\[S(\d+)\]/g, '<a href="#ctx-S$1" class="citation-link" data-source="S$1">[S$1]</a>')
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      .replace(/\b(https?:\/\/[^\s<>"]+)/g, url => `<a href="${url}" target="_blank" rel="noopener">${url}</a>`);
  }

  // ---- Citation link click - delegated, auto-registered ----
  // Scopes to .compare-col if present so compare mode works correctly.
  document.addEventListener('click', e => {
    const link = e.target.closest('.citation-link');
    if (!link) return;
    e.preventDefault();
    const src = link.dataset.source;
    const scope = link.closest('.compare-col') || document;
    const card = scope.querySelector(`#ctx-${CSS.escape(src)}`);
    if (!card) return;
    const det = card.closest('details');
    if (det && !det.open) det.open = true;
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
    card.classList.remove('citation-highlight');
    void card.offsetWidth;
    card.classList.add('citation-highlight');
    setTimeout(() => card.classList.remove('citation-highlight'), 2500);
  });

  // ---- Source cards ----
  // opts: {
  //   legislationGroupLabel: string,  default 'Relevant legislation'
  //   decisionGroupLabel: string,     default 'Decisions'
  //   decisionLabel: string,          default 'Decision'
  //   showLegToggle: bool,            default false - adds leg-sec-toggle + data-section
  // }
  function renderSources(sources, legislation, opts) {
    opts = opts || {};
    const sourcesList = document.getElementById('sources-list');
    const sourcesSection = document.getElementById('sources-section');
    if (!sourcesList || !sourcesSection) return;

    const hasLeg = legislation && legislation.length > 0;
    const hasDec = sources && sources.length > 0;
    if (!hasLeg && !hasDec) { sourcesSection.classList.remove('visible'); return; }

    const legGroupLabel = opts.legislationGroupLabel || 'Relevant legislation';
    const decGroupLabel = opts.decisionGroupLabel || 'Decisions';
    const decLabel = opts.decisionLabel || 'Decision';

    let html = '';
    if (hasLeg) {
      if (hasDec) html += `<div class="sources-group-label">${legGroupLabel}</div>`;
      html += legislation.map(s => {
        const url = (s.url || '').startsWith('https://') ? s.url : '#';
        const secMatch = (s.case_id || '').match(/\/s(\d+[A-Z]?)$/i);
        const secNum = secMatch ? secMatch[1] : '';
        const dataAttr = (secNum && opts.showLegToggle) ? ` data-section="${escapeHtml(secNum)}"` : '';
        const spanClass = opts.showLegToggle
          ? 'source-num source-num--leg leg-sec-toggle'
          : 'source-num source-num--leg';
        return `<div class="source-card source-card--leg"><span class="${spanClass}"${dataAttr} title="Show decisions citing this section">&sect;</span><div class="source-info"><a class="source-title" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.title || s.case_id)}</a></div></div>`;
      }).join('');
    }
    if (hasDec) {
      if (hasLeg) html += `<div class="sources-group-label">${decGroupLabel}</div>`;
      html += sources.map((s, i) => {
        const label = s.date
          ? `${s.court_name || decLabel} - ${s.date}`
          : (s.court_name || decLabel);
        const url = (s.url || '').startsWith('https://') ? s.url : '#';
        return `<div class="source-card"><span class="source-num">S${i + 1}</span><div class="source-info"><a class="source-title" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a></div></div>`;
      }).join('');
    }
    sourcesList.innerHTML = html;
    sourcesSection.classList.add('visible');
  }

  // ---- Confidence badge ----
  function renderConfidence(ev, resultCard) {
    const existing = document.getElementById('confidence-badge');
    if (existing) existing.remove();
    if (!ev || !ev.level) return;
    const badge = document.createElement('div');
    badge.id = 'confidence-badge';
    badge.className = `confidence-badge confidence-${ev.level}`;
    const icons = { high: '●', medium: '◑', low: '○' };
    badge.innerHTML = `<span class="confidence-icon">${icons[ev.level] || '●'}</span> <span class="confidence-msg">${escapeHtml(ev.message)}</span>`;
    const container = resultCard || document.getElementById('result-card');
    if (!container) return;
    const aiWarning = container.querySelector('.ai-warning');
    if (aiWarning) container.insertBefore(badge, aiWarning);
    else container.prepend(badge);
  }

  // ---- SSE stream reader ----
  // Reads an SSE response and calls onEvent(parsedEvent) for each data frame.
  // Throws on connection loss so callers can catch and show an error.
  async function streamEvents(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const raw = buffer.slice(0, boundary).trim();
        buffer = buffer.slice(boundary + 2);
        if (!raw.startsWith('data: ')) continue;
        let ev;
        try { ev = JSON.parse(raw.slice(6)); } catch (_) { continue; }
        onEvent(ev);
      }
    }
  }

  // ---- Token loader ----
  async function loadToken() {
    try {
      const r = await fetch('/token');
      return (await r.json()).token || '';
    } catch (_) { return ''; }
  }

  // ---- Queue status ----
  async function pollQueue(queueNoticeEl) {
    try {
      const r = await fetch('/health');
      if (!r.ok) return;
      const d = await r.json();
      if (!queueNoticeEl) return;
      const waiting = d.waiting || 0;
      if (waiting > 0) {
        queueNoticeEl.textContent = `${waiting} ${waiting === 1 ? 'person' : 'people'} waiting - estimated wait ~${d.estimated_wait_seconds || 0}s`;
        queueNoticeEl.classList.add('visible');
      } else {
        queueNoticeEl.classList.remove('visible');
      }
    } catch (_) {}
  }

  // ---- Full feedback save ----
  async function saveFullFeedback(payload, rating, comment, isDebug, apiToken) {
    try {
      await fetch('/feedback/full', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-API-Key': apiToken },
        body: JSON.stringify({ ...payload, rating, comment: comment || '', is_debug: isDebug || false }),
      });
    } catch (_) {}
  }

  // ---- Disclaimer modal ----
  function initDisclaimer(storageKey) {
    if (localStorage.getItem(storageKey)) return;
    const modal = document.getElementById('disclaimer-modal');
    const checkbox = document.getElementById('disclaimer-checkbox');
    const agreeBtn = document.getElementById('disclaimer-agree');
    if (!modal || !checkbox || !agreeBtn) return;
    modal.classList.add('visible');
    document.body.classList.add('modal-open');
    checkbox.addEventListener('change', () => { agreeBtn.disabled = !checkbox.checked; });
    agreeBtn.addEventListener('click', () => {
      localStorage.setItem(storageKey, '1');
      modal.classList.remove('visible');
      document.body.classList.remove('modal-open');
    });
  }

  global.Astraea = {
    escapeHtml,
    renderAnswer,
    renderSources,
    renderConfidence,
    streamEvents,
    loadToken,
    pollQueue,
    saveFullFeedback,
    initDisclaimer,
  };

})(window);
