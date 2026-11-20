import React, { useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './styles.css';

const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const fingers = ['L1 - Thumb','L2 - Index','L3 - Middle','L4 - Ring','L5 - Little','R1 - Thumb','R2 - Index','R3 - Middle','R4 - Ring','R5 - Little'];

function icon(type, size = 20) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinecap: 'round', strokeLinejoin: 'round' };
  if (type === 'finger') return <svg {...common}><path d="M7 14V8a5 5 0 0 1 10 0v6"/><path d="M5 15V9a7 7 0 0 1 14 0v6"/><path d="M3 14V10a9 9 0 0 1 18 0v5"/><path d="M9 16v-6a3 3 0 0 1 6 0v6"/><path d="M7 17c1.2 2.2 3.1 3 5 3s3.8-.8 5-3"/></svg>;
  if (type === 'upload') return <svg {...common}><path d="M12 16V4"/><path d="m7 9 5-5 5 5"/><path d="M5 20h14"/></svg>;
  if (type === 'check') return <svg {...common}><path d="m5 12 4 4L19 6"/></svg>;
  if (type === 'download') return <svg {...common}><path d="M12 4v11"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/></svg>;
  if (type === 'refresh') return <svg {...common}><path d="M20 11a8 8 0 0 0-14.9-3"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.9 3"/><path d="M20 20v-4h-4"/></svg>;
  return null;
}

function fakeFingerprint(seed, coreX = 50, coreY = 46) {
  const paths = [];
  for (let i = 0; i < 15; i++) {
    const rx = 8 + i * 3.5 + ((seed * 7 + i * 3) % 4);
    const ry = 7 + i * 3.2;
    const wobble = ((seed + i) % 5) - 2;
    paths.push(`<ellipse cx="${coreX + wobble}" cy="${coreY}" rx="${rx}" ry="${ry}" fill="none" stroke="#111" stroke-width="1.8"/>`);
  }
  for (let i = 0; i < 12; i++) {
    const y = 8 + i * 7;
    paths.push(`<path d="M5 ${y} C 25 ${y - 8 + seed % 5}, 75 ${y + 8}, 95 ${y - 2}" fill="none" stroke="#111" stroke-width="1.3"/>`);
  }
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="240" height="180" viewBox="0 0 100 75"><rect width="100" height="75" fill="#f4f4f2"/>${paths.join('')}</svg>`)}`;
}

function DemoCard({ finger, i }) {
  const patterns = ['Loop','Arch','Whorl','Loop','Accidental','Loop','Whorl','Loop','Arch','Loop'];
  const rc = [14,0,16,12,11,15,17,13,0,14][i];
  const core = {x: 49, y: 35};
  const delta = {x: 72, y: 59};
  return <ResultCard finger={finger} result={{pattern:patterns[i],ridge_count:rc,confidence:92+i%7,status:'success',core,delta,retry_attempted:false}} src={fakeFingerprint(i+1)} />;
}

function ResultCard({ finger, result, src }) {
  const w = result?.width || 100;
  const h = result?.height || 75;
  const cX = result?.core ? (result.core.x / w) * 100 : null;
  const cY = result?.core ? (result.core.y / h) * 100 : null;
  const dX = result?.delta ? (result.delta.x / w) * 100 : null;
  const dY = result?.delta ? (result.delta.y / h) * 100 : null;

  return (
    <article className="result-card">
      <div className="finger-image-wrap">
        {src ? <img src={src} alt={finger} className="finger-image"/> : <div className="no-image">No preview</div>}

        {/* SVG overlay line connecting C and D exactly */}
        {cX != null && dX != null && (
          <svg viewBox="0 0 100 100" preserveAspectRatio="none" style={{position:'absolute',top:0,left:0,width:'100%',height:'100%',pointerEvents:'none',zIndex:2}}>
            <line x1={`${cX}%`} y1={`${cY}%`} x2={`${dX}%`} y2={`${dY}%`} stroke="#f2c900" strokeWidth="2.5" strokeDasharray="3 2"/>
          </svg>
        )}

        {cX != null && <span className="marker core" style={{left:`${cX}%`, top:`${cY}%`, zIndex:3}}>C</span>}
        {dX != null && <span className="marker delta" style={{left:`${dX}%`, top:`${dY}%`, zIndex:3}}>D</span>}
      </div>
      <div className="card-body">
        <div className="finger-name">{finger}</div>
        <div className="chips"><span>RC: {result?.ridge_count ?? '—'}</span></div>
        <div className="confidence">
          {result?.status === 'success'
            ? <><span className="dot success-dot"/> {result.pattern} – {result.confidence}% confidence</>
            : <><span className="dot warn-dot"/> Detection needs review</>
          }
        </div>
      </div>
    </article>
  );
}

function LearnerReport({ results, demo }) {
  const selected = results?.finger_results || [];

  let whorlCount = 0;
  let ulnarCount = 0;
  let radialCount = 0;
  let archCount = 0;
  let compositeCount = 0;

  if (demo) {
    whorlCount = 3;
    ulnarCount = 3;
    radialCount = 4;
    archCount = 0;
    compositeCount = 0;
  } else if (selected.length > 0) {
    selected.forEach(r => {
      const p = (r.pattern || '').toLowerCase();
      const fn = (r.filename || '').toLowerCase();
      if (p.includes('whorl') || p.includes('target') || p.includes('spiral')) {
        if (p.includes('composite') || p.includes('s-family')) compositeCount++;
        else whorlCount++;
      } else if (p.includes('loop')) {
        if (fn.includes('radial') || fn.includes('rad') || p.includes('radial')) radialCount++;
        else ulnarCount++;
      } else if (p.includes('arch')) {
        archCount++;
      } else {
        ulnarCount++;
      }
    });
  }

  const total = Math.max(1, (demo ? 10 : selected.length));
  const whorlPct = Math.round((whorlCount / total) * 100);
  const ulnarPct = Math.round((ulnarCount / total) * 100);
  const radialPct = Math.round((radialCount / total) * 100);
  const archPct = Math.round((archCount / total) * 100);
  const compositePct = Math.round((compositeCount / total) * 100);

  const styles = [
    {
      title: "COGNITIVE LEARNER",
      type: "WHORL TYPE",
      pct: whorlPct,
      color: "#1e3a8a",
      points: [
        "They like self-discovery in the pursuit of knowledge.",
        "Will take own initiative to seek knowledge and find answers.",
        "Somewhat self-centered; strong believer in own beliefs & knowledge.",
        "Self-motivated in achievements; demand space & respect in communication.",
        "High ego and very proud of oneself."
      ],
      guidance: [
        "Avoid excessive demands on learning quick.",
        "Allow self-discovery of mistakes and motivate with a reason to learn.",
        "Do not spoon-feed answers; give space and respect in decision making.",
        "Discourage harsh punishment; encourage learning from reflection."
      ]
    },
    {
      title: "AFFECTIVE LEARNER",
      type: "ULNAR LOOP",
      pct: ulnarPct,
      color: "#0284c7",
      points: [
        "Easily influenced by environment; learn by example.",
        "Learn by imitation with high degree of acceptance in learning.",
        "Sociable, easy-going, avoids conflicts; tends to listen to other opinions.",
        "Quiet achiever who thrives on encouragement and emotional connection."
      ],
      guidance: [
        "Organized and planned with guided examples.",
        "Give regular encouragement to instill feel-good factors and motivation.",
        "Create an emotionally supportive, positive study environment."
      ]
    },
    {
      title: "CRITICAL LEARNER",
      type: "RADIAL LOOP",
      pct: radialPct,
      color: "#0d9488",
      points: [
        "Creative, loves challenges, thinks out of the box, rebellious.",
        "Searches for differences; unique independent personality style.",
        "Tends to do things without concern for convention; self-centered.",
        "Thrives on setting new standards, breaking moulds, and debating."
      ],
      guidance: [
        "Coached by reverse reasoning and using reverse psychology.",
        "Use stages, goals, and points accumulation to achieve milestones.",
        "Motivated by big challenges; use self-planning and self-management."
      ]
    },
    {
      title: "REFLECTIVE LEARNER",
      type: "ARCH TYPE",
      pct: archPct,
      color: "#ea580c",
      points: [
        "Open-minded, able to absorb a lot like a sponge.",
        "High retention capacity once grasped, but cautious to internalize.",
        "Learns better when there is a trusted mentor to guide step-by-step."
      ],
      guidance: [
        "Clear reward & recognition to drive goal achievement.",
        "Motivated by philosophical concepts, steady routines, and pragmatic logic.",
        "Best if given 1-on-1 focus and structured daily practice."
      ]
    },
    {
      title: "INTEGRATED LEARNER",
      type: "COMPOSITE WHORL",
      pct: compositePct,
      color: "#7c3aed",
      points: [
        "Compound learning style with strong analytical & multi-source integration.",
        "Wide range of curiosity for diverse subjects with high learning agility.",
        "Sets clear targets and strives to achieve; autonomous and independent.",
        "Can experience split concentration due to multiple concurrent interests."
      ],
      guidance: [
        "Participate in setting structured priorities and clear time management.",
        "Cultivate analytical thinking with diverse cross-disciplinary knowledge.",
        "Increase focus and sustained consistency through mindfulness & goal checkpoints."
      ]
    }
  ];

  return (
    <div className="report-container">
      <div className="report-header">
        <div>
          <h2>DMIT Learning Styles &amp; Personality Profile</h2>
          <p>Cognitive, Affective, Critical, Reflective &amp; Integrated distribution based on dermatoglyphic ridge analysis</p>
        </div>
      </div>

      <div className="report-cards-grid">
        {styles.map((s, idx) => (
          <div key={idx} className="learner-card">
            <div className="learner-header" style={{backgroundColor: s.color}}>
              {s.title}
            </div>
            <div className="learner-body">
              <div className="learner-info">
                <h4>Characteristics:</h4>
                <ul>
                  {s.points.map((p, i) => <li key={i}>{p}</li>)}
                </ul>
                <h4>Proposed Guiding Methods:</h4>
                <ul className="guidance-list">
                  {s.guidance.map((g, i) => <li key={i}>{g}</li>)}
                </ul>
              </div>
              <div className="learner-badge-col">
                <div className="badge-box">
                  <div className="badge-type">{s.type}</div>
                  <div className="badge-pct" style={{backgroundColor: s.color}}>{s.pct}%</div>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function App() {
  const inputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [demo, setDemo] = useState(false);
  const [isDragging, setIsDragging] = useState(false);

  const urls = useMemo(() => files.map(f => URL.createObjectURL(f)), [files]);

  const handleFileList = (incomingList) => {
    const validImages = incomingList.filter(f => {
      const type = (f.type || '').toLowerCase();
      const name = (f.name || '').toLowerCase();
      return type.includes('image') || name.endsWith('.jpg') || name.endsWith('.jpeg') || name.endsWith('.png') || name.endsWith('.bmp');
    });
    if (!validImages.length && incomingList.length > 0) {
      setError('Please upload JPG, PNG, or BMP image files.');
      return;
    }
    const selected = validImages.slice(0, 30);
    setFiles(selected);
    setDemo(false);
    setResults(null);
    setError(validImages.length > 30 ? 'Only the first 30 images were selected.' : '');
  };

  const onFiles = (event) => {
    const incoming = Array.from(event.target.files || []);
    handleFileList(incoming);
  };

  const onDragOver = (e) => { e.preventDefault(); e.stopPropagation(); setIsDragging(true); };
  const onDragLeave = (e) => { e.preventDefault(); e.stopPropagation(); setIsDragging(false); };
  const onDrop = (e) => {
    e.preventDefault(); e.stopPropagation(); setIsDragging(false);
    if (e.dataTransfer?.files && e.dataTransfer.files.length > 0) {
      handleFileList(Array.from(e.dataTransfer.files));
    }
  };

  async function analyze() {
    if (!files.length) return;
    setLoading(true); setError('');
    try {
      const form = new FormData();
      files.forEach(file => form.append('files', file));
      const res = await fetch(`${API}/api/analyze`, { method:'POST', body:form });
      if (!res.ok) throw new Error(await res.text());
      setResults(await res.json());
    } catch (e) {
      setError('Backend is not reachable. Start the Python API on port 8000.');
    } finally { setLoading(false); }
  }

  function loadDemo() {
    setDemo(true); setError(''); setResults({trc:125, finger_results:[]});
  }

  function resetAll() {
    setFiles([]); setResults(null); setDemo(false); setError('');
    if (inputRef.current) inputRef.current.value = '';
  }

  const selected = results?.finger_results || [];
  const selectedByFinger = Object.fromEntries(selected.map(r => [r.finger, r]));

  function exportExcel() {
    const list = demo
      ? [
          { finger: 'L1 - Thumb', pattern: 'Loop', ridge_count: 14, confidence: 92 },
          { finger: 'L2 - Index', pattern: 'Arch', ridge_count: 0, confidence: 93 },
          { finger: 'L3 - Middle', pattern: 'Whorl', ridge_count: 16, confidence: 94 },
          { finger: 'L4 - Ring', pattern: 'Loop', ridge_count: 12, confidence: 95 },
          { finger: 'L5 - Little', pattern: 'Accidental', ridge_count: 11, confidence: 96 },
          { finger: 'R1 - Thumb', pattern: 'Loop', ridge_count: 15, confidence: 97 },
          { finger: 'R2 - Index', pattern: 'Whorl', ridge_count: 17, confidence: 98 },
          { finger: 'R3 - Middle', pattern: 'Loop', ridge_count: 13, confidence: 92 },
          { finger: 'R4 - Ring', pattern: 'Arch', ridge_count: 0, confidence: 93 },
          { finger: 'R5 - Little', pattern: 'Loop', ridge_count: 14, confidence: 94 }
        ]
      : selected;

    const trcValue = demo ? 125 : (results?.trc ?? 0);

    let csvContent = '\uFEFF';
    csvContent += 'FINGERPRINT ANALYSIS & DMIT REPORT\n';
    csvContent += `Generated On,${new Date().toLocaleString()}\n`;
    csvContent += `Total Ridge Count (TRC),${trcValue}\n\n`;
    csvContent += 'Finger,Pattern Type,Ridge Count (RC),Confidence (%),Status,Filename\n';

    list.forEach(item => {
      const f = `"${item.finger || ''}"`;
      const p = `"${item.pattern || ''}"`;
      const rc = item.ridge_count != null ? item.ridge_count : '—';
      const c = item.confidence != null ? `${item.confidence}%` : '—';
      const st = `"${item.status || 'success'}"`;
      const fn = `"${item.filename || ''}"`;
      csvContent += `${f},${p},${rc},${c},${st},${fn}\n`;
    });

    csvContent += '\nLEARNING STYLE PROFILE & DISTRIBUTION\n';
    csvContent += 'Learning Style,Pattern Family,Target Potential (%)\n';
    csvContent += 'Cognitive Learner,Whorl Type,30%\n';
    csvContent += 'Affective Learner,Ulnar Loop,30%\n';
    csvContent += 'Critical Learner,Radial Loop,40%\n';
    csvContent += 'Reflective Learner,Arch Type,0%\n';
    csvContent += 'Integrated Learner,Composite Whorl,0%\n';

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `Fingerprint_DMIT_Report_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">{icon('finger', 42)}<div><h1>Fingerprint Analyzer</h1><p>Core, delta &amp; ridge count prototype</p></div></div>
        <div className="prototype"><span/> Prototype</div>
      </header>

      <main>
        <section className="upload-section">
          <div
            className={`upload-box ${isDragging ? 'dragover' : ''}`}
            onClick={() => inputRef.current?.click()}
            onDragOver={onDragOver}
            onDragEnter={onDragOver}
            onDragLeave={onDragLeave}
            onDrop={onDrop}
          >
            <div className="upload-icon">{icon('upload', 30)}</div>
            <h2>{isDragging ? 'Drop images here' : 'Upload or Drag & Drop fingerprint images'}</h2>
            <p>JPG, PNG or BMP · Drag and drop or browse · up to 30 images</p>
            <input ref={inputRef} type="file" accept="image/png,image/jpeg,image/bmp,.bmp" multiple onChange={onFiles} hidden/>
            {files.length > 0 && <div className="file-count">{files.length} image{files.length !== 1 ? 's' : ''} ready</div>}
          </div>
          <div className="actions">
            <button className="secondary" onClick={loadDemo}>Load demo</button>
            <button className="secondary" onClick={resetAll} disabled={!files.length && !results && !demo}>Reset</button>
            <button className="primary" disabled={!files.length || loading} onClick={analyze}>{loading ? 'Analyzing…' : 'Analyze images'}</button>
          </div>
          {error && <div className="error">{error}</div>}
        </section>

        {(files.length || demo || results) ? (
          <section className="results-section">
            <div className="section-head">
              <div><h2>Ten-finger results</h2><p>{demo ? 'Demo data · replace with real uploads' : `${files.length} uploaded images · best result selected for each finger`}</p></div>
              <button className="icon-button" onClick={exportExcel}>{icon('download',18)} Export Excel</button>
            </div>

            <div className="grid">
              {fingers.map((finger,i) => {
                const r = selectedByFinger[finger];
                if (demo) return <DemoCard key={finger} finger={finger} i={i}/>;
                const sourceIndex = r?.index;
                return <ResultCard key={finger} finger={finger} result={r} src={sourceIndex != null ? urls[sourceIndex] : null}/>;
              })}
            </div>

            <div className="trc-bar">
              <div><div className="trc-label">Total Ridge Count (TRC)</div><div className="trc-note">Sum of the ten selected ridge counts</div></div>
              <div className="trc-value">{demo ? 125 : (results?.trc ?? '—')}</div>
              <button className="primary" onClick={exportExcel}>{icon('download',17)} Export Excel (.csv)</button>
            </div>

            <LearnerReport results={results} demo={demo} />
          </section>
        ) : (
          <section className="empty">
            <div>{icon('finger',38)}</div>
            <h2>Ready for fingerprints</h2>
            <p>Upload up to 30 images to analyze core, delta and ridge count.</p>
          </section>
        )}

        <footer>Prototype only · Detection is heuristic and must be validated against labeled fingerprint examples before production use.</footer>
      </main>
    </div>
  );
}

createRoot(document.getElementById('root')).render(<App />);
