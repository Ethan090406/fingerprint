import React, { useEffect, useState } from 'react';
import { FINGER_ORDER, PATTERN_CODES, ARCH_CODES, suggestCode, sendToSoftInput } from './excelBridge';

// Optional client details. Leave a field blank and the sheet keeps whatever it already has.
const FIELDS = [
  ['analysisNo', 'Analysis no.', 'text'], ['clientCode', 'Client code', 'text'],
  ['name', 'Name', 'text'], ['fatherName', "Father's / husband's name", 'text'],
  ['motherName', "Mother's name", 'text'], ['dob', 'Date of birth', 'date'],
  ['mobile', 'Mobile', 'text'], ['email', 'Email', 'text'],
  ['address', 'Address', 'text'], ['address2', 'Address (line 2)', 'text'],
  ['reportDate', 'Report date', 'date'], ['atdLeft', 'ATD (left)', 'number'],
  ['atdRight', 'ATD (right)', 'number'], ['gender', 'Gender', 'text'],
];

/** rows = the ten effective finger results, in FINGER_ORDER (App's effectiveFor(f, i)). */
export default function ExcelPanel({ rows }) {
  const [codes, setCodes] = useState({});
  const [details, setDetails] = useState({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  // A new analysis gives fresh suggested codes (the analyst then confirms them).
  const sig = rows.map(r => r?.pattern || '').join('|');
  useEffect(() => {
    const next = {};
    FINGER_ORDER.forEach((f, i) => { next[f] = suggestCode(rows[i]?.pattern); });
    setCodes(next);
    setMsg(null);
  }, [sig]);

  const rcOf = (i) => {
    const code = codes[FINGER_ORDER[i]];
    if (ARCH_CODES.includes(code)) return 0;
    const v = rows[i]?.ridge_count;
    return Number.isInteger(v) ? v : null;
  };
  const missing = FINGER_ORDER.filter((f, i) => !codes[f] || rcOf(i) === null);
  const ready = missing.length === 0;

  async function send() {
    setBusy(true); setMsg(null);
    try {
      const fingers = {};
      FINGER_ORDER.forEach((f, i) => { fingers[f] = { code: codes[f], rc: rcOf(i) }; });
      const r = await sendToSoftInput(fingers, details);
      setMsg(r.saved
        ? { ok: true, text: `Saved to ${r.name}. Now open it in Excel, press Ctrl+S, then open the report workbook and choose "Update links".` }
        : { ok: false, text: `Could not write to the file (${r.reason}). A copy was downloaded as ${r.name}. Close the file in Excel and try again.` });
    } catch (e) {
      if (e && e.name === 'AbortError') setMsg(null);
      else setMsg({ ok: false, text: String(e.message || e) });
    } finally { setBusy(false); }
  }

  return (
    <section className="xl-panel">
      <div className="xl-head">
        <div>
          <h2>Send to Excel (SoftInput.xlsx)</h2>
          <p>Confirm each finger's pattern code, then pick the SoftInput file. Only the pattern and ridge-count cells (and any details you fill in) are changed.</p>
        </div>
        <button className="primary" disabled={!ready || busy} onClick={send}>
          {busy ? 'Saving…' : 'Send to Excel'}
        </button>
      </div>

      <div className="xl-grid">
        {FINGER_ORDER.map((f, i) => (
          <div key={f} className={`xl-cell ${codes[f] ? '' : 'xl-need'}`}>
            <div className="xl-finger">{f}</div>
            <select value={codes[f] || ''} onChange={e => setCodes(c => ({ ...c, [f]: e.target.value }))}>
              <option value="">Choose code…</option>
              {PATTERN_CODES.map(([c, label]) => <option key={c} value={c}>{c} – {label}</option>)}
            </select>
            <div className="xl-rc">RC: {rcOf(i) ?? '—'}</div>
          </div>
        ))}
      </div>
      {!ready && <div className="xl-note">Still needed: {missing.join(', ')} (pick a code, and make sure the ridge count is set for non-arch fingers).</div>}
      <div className="xl-note">Check L vs R (ulnar vs radial) and the whorl type yourself — the detector can only suggest.</div>

      <details className="xl-details">
        <summary>Client details &amp; ATD (optional)</summary>
        <div className="xl-fields">
          {FIELDS.map(([key, label, type]) => (
            <label key={key}>{label}
              <input type={type} value={details[key] || ''} onChange={e => setDetails(d => ({ ...d, [key]: e.target.value }))} />
            </label>
          ))}
        </div>
      </details>

      {msg && <div className={msg.ok ? 'xl-ok' : 'error'}>{msg.text}</div>}
    </section>
  );
}
