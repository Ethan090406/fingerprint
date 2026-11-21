// excelBridge.js
// Writes the finger patterns / ridge counts (and optional client details) into the
// company's SoftInput.xlsx *without* touching anything else in the file
// (hidden sheets, external links and formulas all stay exactly as they are).
//
// Needs:  npm i jszip
import JSZip from 'jszip';

// Order matches TextInput rows 19..38 (pattern row, RC row on the next row).
export const FINGER_ORDER = [
  'L1 - Thumb', 'L2 - Index', 'L3 - Middle', 'L4 - Ring', 'L5 - Little',
  'R1 - Thumb', 'R2 - Index', 'R3 - Middle', 'R4 - Ring', 'R5 - Little',
];

// Company pattern codes (from the legend on the TextInput sheet).
export const PATTERN_CODES = [
  ['W1', 'Target Centric'], ['W2', 'Spiral'], ['W3', 'Elongated Target Centric'],
  ['W4', 'Elongated Spiral'], ['W5', 'Double Loop'], ['W6', 'Imploding'],
  ['W7', 'Composite'], ['W8', "Target Centric Ulnar Peacock's Eye"],
  ['W9', "Spiral Ulnar Peacock's Eye"], ['W10', "Target Centric Radial Peacock's Eye"],
  ['W11', "Spiral Radial Peacock's Eye"], ['L', 'Ulnar Loop'], ['R', 'Radial Loop'],
  ['L1', 'Ulnar Falling Loop'], ['R1', 'Radial Falling Loop'], ['X1', 'Simple Arch'],
  ['X2', 'Tented Arch'], ['X3', 'Tented Arch with Ulnar Loop'],
  ['X4', 'Tented Arch with Radial Loop'], ['W', 'Accidental Whorl'],
];
export const ARCH_CODES = ['X1', 'X2'];            // arches always have RC = 0

// What the detector says -> a starting code. The analyst must confirm it:
// the detector cannot tell ulnar from radial, or the whorl sub-type.
export function suggestCode(pattern) {
  if (pattern === 'Loop') return 'L';
  if (pattern === 'Arch') return 'X1';
  if (pattern === 'Tented Arch') return 'X2';
  return '';                                        // Whorl / unknown: analyst must choose
}

// Optional client fields -> TextInput cell (blank fields are left untouched, so the
// sheet's existing links keep working). kind: s = text, n = number, d = date
export const DETAIL_CELLS = {
  analysisNo: ['E1', 's'], clientCode: ['E2', 's'], name: ['E3', 's'],
  fatherName: ['E4', 's'], motherName: ['E5', 's'], dob: ['E6', 'd'],
  mobile: ['E7', 's'], email: ['E8', 's'], address: ['E9', 's'],
  address2: ['E10', 's'], reportDate: ['E11', 'd'],
  atdLeft: ['E12', 'n'], atdRight: ['E13', 'n'], gender: ['I13', 's'],
};

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function excelSerial(isoDate) {                      // 'YYYY-MM-DD' -> Excel date number
  const [y, m, d] = isoDate.split('-').map(Number);
  return Math.round((Date.UTC(y, m - 1, d) - Date.UTC(1899, 11, 30)) / 86400000);
}

// Replace one cell with a constant, keeping its style. Drops any formula/link in it.
function setCell(xml, ref, kind, value) {
  const re = new RegExp(`<c r="${ref}"([^>]*?)(?:/>|>[\\s\\S]*?</c>)`);
  const m = xml.match(re);
  if (!m) throw new Error(`Cell ${ref} not found in TextInput. Is this the right SoftInput file?`);
  const style = (m[1].match(/\ss="(\d+)"/) || [])[1];
  const s = style ? ` s="${style}"` : '';
  const cell = kind === 's'
    ? `<c r="${ref}"${s} t="inlineStr"><is><t xml:space="preserve">${esc(value)}</t></is></c>`
    : `<c r="${ref}"${s}><v>${value}</v></c>`;
  return xml.replace(re, cell);
}

async function textInputPath(zip) {
  const wb = await zip.file('xl/workbook.xml').async('string');
  const rels = await zip.file('xl/_rels/workbook.xml.rels').async('string');
  const sheet = wb.match(/<sheet [^>]*name="TextInput"[^>]*r:id="([^"]+)"/);
  if (!sheet) throw new Error('No sheet named "TextInput" in this file.');
  const rel = rels.match(new RegExp(`<Relationship [^>]*Id="${sheet[1]}"[^>]*>`))[0];
  const target = rel.match(/Target="([^"]+)"/)[1];
  return 'xl/' + target.replace(/^\/?(xl\/)?/, '');
}

/**
 * @param {ArrayBuffer|Blob} xlsx   the SoftInput.xlsx bytes
 * @param {Object} fingers          { 'L1 - Thumb': { code:'L', rc:8 }, ... } (all 10)
 * @param {Object} details          optional, keys of DETAIL_CELLS
 * @returns {Promise<Blob>}         patched workbook
 */
export async function patchSoftInput(xlsx, fingers, details = {}) {
  const zip = await JSZip.loadAsync(xlsx);
  const path = await textInputPath(zip);
  let xml = await zip.file(path).async('string');

  FINGER_ORDER.forEach((name, i) => {
    const f = fingers[name];
    if (!f || !f.code) throw new Error(`${name}: choose a pattern code first.`);
    const rc = ARCH_CODES.includes(f.code) ? 0 : Number(f.rc);
    if (!Number.isInteger(rc) || rc < 0 || rc > 60) throw new Error(`${name}: ridge count must be a whole number.`);
    xml = setCell(xml, `D${19 + i * 2}`, 's', f.code);
    xml = setCell(xml, `D${20 + i * 2}`, 'n', rc);
  });

  for (const [key, [ref, kind]] of Object.entries(DETAIL_CELLS)) {
    const v = details[key];
    if (v === undefined || v === null || String(v).trim() === '') continue;
    if (kind === 'd') xml = setCell(xml, ref, 'n', excelSerial(v));
    else if (kind === 'n') xml = setCell(xml, ref, 'n', Number(v));
    else xml = setCell(xml, ref, 's', v);
  }
  zip.file(path, xml);

  // Make Excel recalculate everything the moment the file is opened.
  let wb = await zip.file('xl/workbook.xml').async('string');
  wb = /<calcPr[^>]*fullCalcOnLoad/.test(wb) ? wb
    : wb.replace(/<calcPr([^>]*?)\/>/, '<calcPr$1 fullCalcOnLoad="1"/>');
  zip.file('xl/workbook.xml', wb);

  // Cells that used to hold formulas/links are now plain values, so Excel's saved
  // calculation list (calcChain) would be out of date and trigger a "repair" message.
  // Removing it is safe: Excel rebuilds it by itself.
  if (zip.file('xl/calcChain.xml')) {
    zip.remove('xl/calcChain.xml');
    let rels = await zip.file('xl/_rels/workbook.xml.rels').async('string');
    rels = rels.replace(/<Relationship [^>]*calcChain[^>]*\/>/g, '');
    zip.file('xl/_rels/workbook.xml.rels', rels);
    let ct = await zip.file('[Content_Types].xml').async('string');
    ct = ct.replace(/<Override [^>]*calcChain[^>]*\/>/g, '');
    zip.file('[Content_Types].xml', ct);
  }

  return zip.generateAsync({
    type: 'blob',
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    compression: 'DEFLATE',
  });
}

/**
 * Ask the user to pick SoftInput.xlsx, patch it, and save it back to the same file.
 * Chrome / Edge only. If the browser can't write back (or Excel has the file open),
 * it falls back to downloading a patched copy.
 */
export async function sendToSoftInput(fingers, details) {
  if (!window.showOpenFilePicker) {
    throw new Error('Please use Chrome or Edge for "Send to Excel".');
  }
  const [handle] = await window.showOpenFilePicker({
    multiple: false,
    types: [{ description: 'SoftInput workbook', accept: { 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'] } }],
  });
  const file = await handle.getFile();
  const out = await patchSoftInput(await file.arrayBuffer(), fingers, details);
  try {
    const w = await handle.createWritable();   // asks the user for permission
    await w.write(out);
    await w.close();
    return { saved: true, name: file.name };
  } catch (e) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(out);
    a.download = file.name.replace(/\.xlsx$/i, '') + '_updated.xlsx';
    a.click();
    return { saved: false, name: a.download, reason: String(e.message || e) };
  }
}
