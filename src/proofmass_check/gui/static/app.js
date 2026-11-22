// SPDX-FileCopyrightText: 2026 Paweł Kikta
// SPDX-License-Identifier: Apache-2.0
'use strict';
/* The GUI's page: the open folders, the matrix of a folder, one run, and comparisons
   (docs/gui.md, section 6). Every value comes from the server's API. The page builds its elements
   with h() and never from HTML text, so text in a results file cannot run as code. */

const TOKEN = new URLSearchParams(location.search).get('token') || '';
// A margin above this is "close": it passes, but a small change can make it fail. It is a display
// setting of the GUI, not a rule of the spec, and it never changes a verdict (docs/gui.md, 6.4).
const CLOSE = 0.8;
const ORDER = ['LOAD', 'DROP', 'HOLD', 'TRACK', 'LIMIT', 'STABLE', 'SPEED', 'PASSIVE', 'GRIP', 'SHAKE',
  'STAND', 'DRIVE', 'TURN', 'STEER'];
const WHEELED = ['STAND', 'DRIVE', 'TURN', 'STEER'];
const SIGN = {PASS: '✓', FAIL: '✕', 'N/A': '·'};
const NEWTON_NOTE = 'Newton is experimental: its results can differ from run to run (spec.md, section 5).';
const SETTINGS_NOTE = 'The settings of this run differ from the spec. Its notes say which.';

const main = document.getElementById('main');
const selected = new Set(JSON.parse(sessionStorage.getItem('selected') || '[]'));
const view = {onlyFailed: false, text: '', wheeledOpen: false, onlyDiffers: false, fullPaths: false};
let state = null;

// --- elements

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (name.startsWith('on')) el.addEventListener(name.slice(2), value);
    else if (name === 'class') el.className = value;
    else if (name === 'checked' || name === 'value') el[name] = value;
    else el.setAttribute(name, value === true ? '' : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false || child === '') continue;
    el.append(child instanceof Node ? child : String(child));
  }
  return el;
}

function fill(el, ...children) {
  // replaceChildren() writes null as the text "null" and does not open arrays, so they go first.
  el.replaceChildren(...children.flat(Infinity).filter(c => c !== null && c !== undefined && c !== false && c !== ''));
}

const key = (folderId, runId) => `${folderId}\n${runId}`;
const refOf = k => k.split('\n');
const saveSelection = () => sessionStorage.setItem('selected', JSON.stringify([...selected]));
const cls = v => ({PASS: 'pass', FAIL: 'fail', 'N/A': 'na'})[v] || 'na';
const runHref = (folderId, runId) => `#/f/${encodeURIComponent(folderId)}/r/${encodeURIComponent(runId)}`;
const compareHref = refs => `#/compare/${encodeURIComponent(JSON.stringify(refs))}`;

function verdict(v, big) {
  return h('span', {class: `v ${cls(v)}${big ? ' big' : ''}`}, `${SIGN[v] ?? '?'} ${v}`);
}

function sign(v, title) {
  return v ? h('span', {class: `v ${cls(v)}`, title}, SIGN[v] ?? '?') : h('span', {class: 'v na'}, '');
}

function result(run, big) {
  if (run.error) return h('span', {class: `v err${big ? ' big' : ''}`, title: run.error}, 'ERROR');
  if (run.passed) return h('span', {class: `v pass${big ? ' big' : ''}`}, '✓ PASSED');
  return h('span', {class: `v fail${big ? ' big' : ''}`}, `✕ FAILED (${run.failed})`);
}

function order(ids) {
  const found = new Set(ids);
  return [...ORDER.filter(i => found.has(i)), ...[...found].filter(i => !ORDER.includes(i))];
}

function crumbs(...items) {
  document.getElementById('crumbs').replaceChildren(...items.flatMap(([label, href]) => [
    h('span', {class: 'sep'}, '/'), href ? h('a', {href}, label) : h('span', {}, label)]));
}

function counts(runs) {
  const errors = runs.filter(r => r.error).length;
  const passed = runs.filter(r => r.passed).length;
  return {total: runs.length, passed, errors, failed: runs.length - passed - errors};
}

function seconds(s) {
  if (typeof s !== 'number') return '';
  return s < 120 ? `${s.toFixed(1)} s` : `${(s / 60).toFixed(1)} min`;
}

function marginText(m) {
  if (m === null || m === undefined) return '';
  return m < 10 ? `${Math.round(m * 100)}%` : `${m >= 100 ? '>99' : m.toFixed(0)}×`;
}

function marginBar(m) {
  if (m === null || m === undefined) return h('span', {class: 'muted'}, 'no ratio');
  const kind = m > 1 ? 'over' : m >= CLOSE ? 'close' : 'ok';
  const fill = h('i');
  fill.style.width = `${Math.max(Math.min(m, 1), 0.02) * 100}%`;
  const what = m > 1 ? 'past its limit' : m >= CLOSE ? 'passes, close to its limit' : 'passes';
  return h('div', {class: `margin ${kind}`, title: `uses ${marginText(m)} of its limit: ${what}`},
    h('div', {class: 'track'}, fill), h('span', {}, marginText(m)));
}

function settingsText(s) {
  const parts = [];
  if (typeof s.settle_s === 'number') parts.push(`settle ${s.settle_s} s`);
  if (typeof s.linear_tol === 'number') parts.push(`linear tolerance ${+(s.linear_tol * 1000).toFixed(3)} mm`);
  if (typeof s.angular_tol === 'number') parts.push(`angular tolerance ${+(s.angular_tol * 180 / Math.PI).toFixed(3)} deg`);
  if (typeof s.random_poses === 'number') parts.push(`${s.random_poses} random poses`);
  if ('floor' in s) parts.push(typeof s.floor === 'number' ? `floor at ${(s.floor * 1000).toFixed(1)} mm` : 'no floor');
  return parts.join(' · ') || 'not recorded';
}

function detailLines(detail) {
  // The detail text as written, one part per line. A part that failed is marked. Numbers are
  // never read from it (docs/gui.md, section 5.1).
  return detail.split('; ').map(part => h('div', {class: part.endsWith(' FAIL') ? 'fail' : null}, part));
}

function banner(text, info) {
  return h('p', {class: `banner${info ? ' info' : ''}`}, text);
}

function subject(name) {
  // An empty subject is the whole asset (docs/spec.md, section 6).
  return name || h('span', {class: 'muted'}, 'asset');
}

function status() {
  const el = h('p', {class: 'status', role: 'status'});
  el.say = (text, error) => { el.textContent = text; el.className = `status${error ? ' err' : ''}`; };
  return el;
}

// --- the server

async function api(path, body) {
  const options = {headers: {'X-Token': TOKEN}};
  if (body !== undefined) {
    options.method = 'POST';
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  const res = await fetch(path, options);
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`;
    try { message = (await res.json()).error || message; } catch { /* the answer was not JSON */ }
    throw new Error(message);
  }
  return res;
}

const apiJson = async (path, body) => (await api(path, body)).json();

async function download(refs, format, title, say) {
  say(`Making the ${format.toUpperCase()} report…`);
  try {
    const res = await api('/api/report', {runs: refs, format, title, full_paths: view.fullPaths});
    const url = URL.createObjectURL(await res.blob());
    const link = h('a', {href: url, download: `${title.replace(/[^\w.-]+/g, '_')}.${format}`});
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    say(`Report of ${refs.length} runs saved by the browser.`);
  } catch (e) {
    say(e.message, true);
  }
}

// --- the views

async function route() {
  if (!TOKEN) {
    crumbs();
    fill(main, h('h1', {}, 'No token'), h('p', {}, 'Open the address that ',
      h('code', {}, 'proofmass-check gui'), ' printed in its terminal. It holds the token this page needs.'));
    return;
  }
  const parts = location.hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent);
  try {
    state = await apiJson('/api/state');
    document.getElementById('version').textContent = `${state.version} · spec ${state.spec_version}`;
    if (parts[0] === 'f' && parts[2] === 'r') await runView(parts[1], parts[3]);
    else if (parts[0] === 'f') folderView(parts[1]);
    else if (parts[0] === 'compare') await compareView(JSON.parse(parts[1]));
    else if (parts[0] === 'pair') await pairView(parts[1], parts[2]);
    else homeView();
  } catch (e) {
    crumbs();
    fill(main, h('h1', {}, 'Something went wrong'), h('p', {class: 'status err'}, e.message),
      h('p', {}, h('a', {href: '#/'}, 'Back to the folders')));
  }
}

function homeView() {
  crumbs();
  const say = status();
  const input = h('input', {type: 'text', size: 70, placeholder: 'C:\\results\\lightwheel',
    'aria-label': 'The folder to open'});
  const form = h('form', {class: 'toolbar', onsubmit: async event => {
    event.preventDefault();
    say.say('Reading the folder…');
    try {
      const folder = await apiJson('/api/open', {path: input.value});
      location.hash = `#/f/${folder.id}`;
    } catch (e) {
      say.say(e.message, true);
    }
  }}, input, h('button', {class: 'primary', type: 'submit'}, 'Open folder'));
  const list = state.folders.length
    ? h('div', {class: 'folders'}, state.folders.map(folderRow))
    : h('p', {class: 'empty'}, 'Open a folder that holds results files. The page reads every results file ',
      'of proofmass-check below it, whatever the file is called.');
  fill(main, h('h1', {}, 'Results'),
    h('p', {class: 'sub'}, 'Folders with results files of proofmass-check. The page only shows them: ',
      'it never changes a file and never runs a check.'),
    form, say, list);
  input.focus();
}

function folderRow(folder) {
  const c = counts(folder.runs);
  const engines = [...new Set(folder.runs.map(r => r.engine))].join(', ');
  const tools = [...new Set(folder.runs.map(r => r.tool_version))].join(', ');
  return h('div', {class: 'folder'},
    h('a', {class: 'name', href: `#/f/${folder.id}`}, folder.name),
    h('div', {class: 'path'}, folder.path),
    h('div', {class: 'counts'},
      h('span', {}, `${c.total} runs`),
      h('span', {class: 'pass-text'}, `${c.passed} passed`),
      h('span', {class: 'fail-text'}, `${c.failed} failed`),
      c.errors ? h('span', {class: 'fail-text'}, `${c.errors} stopped with an error`) : null,
      engines ? h('span', {class: 'muted'}, engines) : null,
      tools ? h('span', {class: 'muted mono'}, `proofmass-check ${tools}`) : null,
      folder.problems.length ? h('span', {class: 'muted'}, `${folder.problems.length} files not read`) : null),
    h('div', {class: 'actions'},
      h('button', {onclick: async () => { await apiJson('/api/reload', {folder: folder.id}); route(); }}, 'Read again'),
      h('button', {onclick: async () => { await apiJson('/api/close', {folder: folder.id}); route(); }}, 'Close')));
}

function folderView(folderId) {
  const folder = state.folders.find(f => f.id === folderId);
  if (!folder) throw new Error(`No open folder ${folderId}. Open it again from the list of folders.`);
  crumbs([folder.name, null]);
  const runs = [...folder.runs].sort((a, b) =>
    a.asset.localeCompare(b.asset) || a.engine.localeCompare(b.engine) || a.id.localeCompare(b.id));
  const ids = order(runs.flatMap(r => Object.keys(r.verdicts)));
  const c = counts(runs);
  const say = status();
  const box = h('div', {class: 'scroll'});
  const compareButton = h('button', {onclick: () => {
    if (selected.size < 2) return say.say('Tick two runs or more to compare them. Runs ticked in other folders count too.', true);
    location.hash = compareHref([...selected].map(refOf));
  }});
  const exportRefs = () => {
    const mine = runs.filter(r => selected.has(key(folderId, r.id)));
    return (mine.length ? mine : runs).map(r => [folderId, r.id]);
  };
  const updateSelection = () => { compareButton.textContent = `Compare ticked runs (${selected.size})`; };

  const visible = () => runs.filter(r => (!view.onlyFailed || !r.passed)
    && (!view.text || `${r.asset} ${r.id}`.toLowerCase().includes(view.text.toLowerCase())));

  const measured = runs.some(r => r.measured);  // runs without measurements have no margin to show

  function draw() {
    const shown = visible();
    const hasWheeled = ids.some(i => WHEELED.includes(i));
    const cols = view.wheeledOpen || !hasWheeled ? ids : [...ids.filter(i => !WHEELED.includes(i)), 'WHEELED'];
    const toggleWheeled = () => { view.wheeledOpen = !view.wheeledOpen; draw(); };
    const all = h('input', {type: 'checkbox', 'aria-label': 'Tick every run shown',
      checked: shown.length > 0 && shown.every(r => selected.has(key(folderId, r.id))),
      onchange: e => {
        for (const r of shown) e.target.checked ? selected.add(key(folderId, r.id)) : selected.delete(key(folderId, r.id));
        saveSelection(); draw(); updateSelection();
      }});
    const head = h('tr', {}, h('th', {class: 'c'}, all), h('th', {}, 'Asset'), h('th', {}, 'Engine'),
      cols.map(id => h('th', {class: 'c'}, id === 'WHEELED' || (view.wheeledOpen && WHEELED.includes(id))
        ? h('button', {onclick: toggleWheeled, title: 'Show or hide STAND, DRIVE, TURN and STEER'}, id)
        : id)),
      h('th', {}, 'Result'),
      measured ? h('th', {class: 'num', title: 'The highest margin of the run: how much of its limit its closest measurement uses'}, 'Margin') : null,
      h('th', {class: 'num'}, 'Time'));
    const rows = shown.map(r => {
      const k = key(folderId, r.id);
      const tick = h('input', {type: 'checkbox', checked: selected.has(k), 'aria-label': `Tick ${r.asset} ${r.engine}`,
        onchange: e => { e.target.checked ? selected.add(k) : selected.delete(k); saveSelection(); updateSelection(); }});
      const cells = cols.map(id => {
        if (id === 'WHEELED') {
          const found = WHEELED.map(w => r.verdicts[w]).filter(Boolean);
          const worst = found.includes('FAIL') ? 'FAIL' : found.includes('PASS') ? 'PASS' : found.length ? 'N/A' : null;
          return h('td', {class: 'c'}, sign(worst, WHEELED.map(w => `${w} ${r.verdicts[w] ?? ''}`).join('\n')));
        }
        const v = r.verdicts[id];
        return h('td', {class: 'c'}, sign(v, v ? `${id} ${v}\n${r.details[id]}` : ''));
      });
      return h('tr', {},
        h('td', {class: 'c'}, tick),
        h('td', {}, h('a', {href: runHref(folderId, r.id)}, r.asset), h('div', {class: 'mono muted'}, r.id)),
        h('td', {}, r.engine, ' ',
          r.engine === 'newton' ? h('span', {class: 'badge', title: NEWTON_NOTE}, 'experimental') : null, ' ',
          r.settings_differ ? h('span', {class: 'badge', title: SETTINGS_NOTE}, 'settings') : null),
        cells,
        h('td', {}, result(r)),
        measured ? h('td', {class: 'num'}, marginText(r.worst_margin)) : null,
        h('td', {class: 'num'}, seconds(r.seconds)));
    });
    const failing = id => shown.filter(r => id === 'WHEELED'
      ? WHEELED.some(w => r.verdicts[w] === 'FAIL') : r.verdicts[id] === 'FAIL').length;
    const foot = h('tr', {}, h('td'), h('td', {colspan: 2}, `${shown.length} of ${runs.length} runs shown`),
      cols.map(id => { const n = failing(id); return h('td', {class: 'c fail-text', title: `${n} shown runs fail ${id}`}, n ? `✕ ${n}` : ''); }),
      h('td', {colspan: measured ? 3 : 2}));
    fill(box, shown.length
      ? h('table', {}, h('thead', {}, head), h('tbody', {}, rows), h('tfoot', {}, foot))
      : h('p', {class: 'empty'}, runs.length ? 'No run matches the filter.' : 'This folder has no results files.'));
  }

  const others = state.folders.filter(f => f.id !== folderId);
  const pick = others.length ? h('select', {'aria-label': 'The folder to compare with'},
    others.map(f => h('option', {value: f.id}, f.name))) : null;
  updateSelection();
  const versions = [...new Set(runs.map(r => `${r.tool_version} (spec ${r.spec_version})`))].join(', ');
  fill(main,
    h('h1', {}, folder.name),
    h('p', {class: 'sub'}, h('span', {class: 'mono'}, folder.path), versions ? ` · proofmass-check ${versions}` : ''),
    h('p', {class: 'toolbar'},
      h('span', {}, `${c.total} runs`), h('span', {class: 'pass-text'}, `${c.passed} passed`),
      h('span', {class: 'fail-text'}, `${c.failed} failed`),
      c.errors ? h('span', {class: 'fail-text'}, `${c.errors} stopped with an error`) : null,
      h('span', {class: 'muted'}, `${seconds(runs.reduce((t, r) => t + (typeof r.seconds === 'number' ? r.seconds : 0), 0))} in all`)),
    runs.some(r => r.settings_differ) ? banner('Some runs have settings that differ from the spec. They carry the mark "settings".') : null,
    runs.some(r => r.engine === 'newton') ? banner(NEWTON_NOTE, true) : null,
    folder.truncated ? banner('This folder has more JSON files than the page reads. Open a folder further down.') : null,
    h('div', {class: 'toolbar'},
      h('label', {}, h('input', {type: 'checkbox', checked: view.onlyFailed,
        onchange: e => { view.onlyFailed = e.target.checked; draw(); }}), 'Only runs that did not pass'),
      h('input', {type: 'text', placeholder: 'Filter by asset or file', value: view.text,
        'aria-label': 'Filter by asset or file', oninput: e => { view.text = e.target.value; draw(); }}),
      h('span', {class: 'grow'}),
      compareButton,
      pick, pick ? h('button', {onclick: () => { location.hash = `#/pair/${folderId}/${pick.value}`; }}, 'Compare folders') : null),
    h('div', {class: 'toolbar'},
      h('span', {class: 'muted'}, 'Report of the ticked runs, or of all runs when none is ticked:'),
      h('button', {onclick: () => download(exportRefs(), 'html', folder.name, say.say)}, 'Save HTML'),
      h('button', {onclick: () => download(exportRefs(), 'csv', folder.name, say.say)}, 'Save CSV'),
      h('label', {title: 'Results files hold the full path of the asset, which can hold your user name'},
        h('input', {type: 'checkbox', checked: view.fullPaths, onchange: e => { view.fullPaths = e.target.checked; }}),
        'Full paths'),
      h('span', {class: 'grow'}),
      h('button', {onclick: async () => { await apiJson('/api/reload', {folder: folderId}); route(); }}, 'Read again')),
    say, box,
    folder.problems.length ? h('details', {},
      h('summary', {}, `${folder.problems.length} files look like results but could not be read`),
      h('ul', {class: 'notes'}, folder.problems.map(p => h('li', {}, h('code', {}, p.file), `: ${p.why}`)))) : null);
  draw();
}

async function runView(folderId, runId) {
  const folder = state.folders.find(f => f.id === folderId);
  if (!folder) throw new Error(`No open folder ${folderId}. Open it again from the list of folders.`);
  const d = await apiJson(`/api/run?folder=${encodeURIComponent(folderId)}&run=${encodeURIComponent(runId)}`);
  crumbs([folder.name, `#/f/${encodeURIComponent(folderId)}`], [`${d.asset} · ${d.engine}`, null]);
  const k = key(folderId, runId);
  const say = status();
  const tick = h('button', {onclick: () => {
    selected.has(k) ? selected.delete(k) : selected.add(k);
    saveSelection();
    tick.textContent = selected.has(k) ? 'Untick for compare' : 'Tick for compare';
    say.say(`${selected.size} runs ticked. Compare them from a folder's page.`);
  }}, selected.has(k) ? 'Untick for compare' : 'Tick for compare');
  const copy = h('button', {onclick: async () => {
    try { await navigator.clipboard.writeText(d.sha256); say.say('SHA-256 copied.'); } catch (e) { say.say(e.message, true); }
  }}, 'Copy');
  const facts = [
    ['File', d.file],
    ['SHA-256', h('span', {}, d.sha256, ' ', copy)],
    ['Variants', Object.entries(d.variants).map(([n, v]) => `${n}=${v}`).join(', ') || 'none'],
    ['Engine', [d.engine, ...Object.entries(d.engine_versions).map(([n, v]) => `${n} ${v}`)].join(' · ')],
    ['proofmass-check', h('span', {}, `${d.tool_version}, spec ${d.spec_version} `,
      h('a', {href: d.spec_url, target: '_blank', rel: 'noreferrer noopener'}, 'the spec of this version'))],
    ['Settings', settingsText(d.settings)],
    ['Time', seconds(d.seconds) || 'not recorded'],
    ['Results file', `${d.id} in ${folder.path}`],
  ];
  const checks = [...d.checks.filter(c => c.verdict !== 'N/A'), ...d.checks.filter(c => c.verdict === 'N/A')];
  const measured = d.measurements.length
    ? [h('h2', {}, 'Joints', h('span', {class: 'muted'}, 'every measurement, the ones that failed first, then by margin')),
      h('div', {class: 'scroll'}, h('table', {},
        h('thead', {}, h('tr', {}, ['Subject', 'Check', 'Case', 'Quantity'].map(t => h('th', {}, t)),
          h('th', {class: 'num'}, 'Value'), h('th', {class: 'num'}, 'Limit'), h('th', {}, 'Margin'), h('th', {class: 'c'}, ''))),
        h('tbody', {}, d.measurements.map(m => h('tr', {},
          h('td', {class: 'mono'}, subject(m.subject)), h('td', {class: 'mono'}, m.check), h('td', {}, m.case), h('td', {}, m.quantity),
          h('td', {class: 'num'}, `${m.shown_value} ${m.shown_unit}`),
          h('td', {class: 'num'}, m.shown_limit === '' ? '' : `${m.bound === 'min' ? '≥' : '≤'} ${m.shown_limit} ${m.shown_unit}`),
          h('td', {}, marginBar(m.margin)),
          h('td', {class: 'c'}, sign(m.ok ? 'PASS' : 'FAIL'))))))),
    ]
    : [banner('This results file has no measurements, so the page shows the detail text of each check only. '
      + 'The numbers for margins come with the measurements field (docs/gui.md, section 5.1).', true)];
  fill(main,
    h('h1', {}, d.asset, result(d, true), h('span', {class: 'sub'}, d.engine)),
    h('div', {class: 'toolbar'}, tick,
      h('button', {onclick: () => download([[folderId, runId]], 'html', `${d.asset}-${d.engine}`, say.say)}, 'Save HTML'),
      h('button', {onclick: () => download([[folderId, runId]], 'csv', `${d.asset}-${d.engine}`, say.say)}, 'Save CSV')),
    say,
    d.engine === 'newton' ? banner(NEWTON_NOTE, true) : null,
    d.settings_differ ? banner(SETTINGS_NOTE) : null,
    d.notes.length ? h('ul', {class: 'notes banner'}, d.notes.map(n => h('li', {}, n))) : null,
    h('dl', {class: 'facts'}, facts.flatMap(([name, value]) => [h('dt', {}, name), h('dd', {}, value)])),
    d.error ? [h('h2', {}, 'The run stopped with an error'), h('pre', {class: 'error'}, d.error)] : null,
    measured,
    checks.length ? h('h2', {}, 'Checks', h('span', {class: 'muted'}, 'the ones that ran first, then N/A with the reason')) : null,
    h('div', {}, checks.map(c => h('div', {class: `check ${cls(c.verdict)}`},
      h('div', {class: 'id'}, c.id), h('div', {}, sign(c.verdict), ' '),
      h('div', {class: 'title'}, c.title),
      h('div', {class: 'detail'}, c.verdict === 'N/A' ? c.detail : detailLines(c.detail))))));
}

async function compareView(refs) {
  const c = await apiJson('/api/compare', {runs: refs});
  crumbs(['Compare', null]);
  const without = i => {
    const rest = refs.filter((_, j) => j !== i);
    location.hash = rest.length >= 2 ? compareHref(rest) : '#/';
  };
  const runsTable = h('div', {class: 'scroll'}, h('table', {},
    h('thead', {}, h('tr', {}, ['', 'Asset', 'Engine', 'proofmass-check', 'Results file', 'Result', ''].map(t => h('th', {}, t)))),
    h('tbody', {}, c.runs.map((r, i) => h('tr', {},
      h('td', {class: 'mono'}, `${i + 1}`),
      h('td', {}, h('a', {href: runHref(refs[i][0], refs[i][1])}, r.asset), h('div', {class: 'mono muted'}, r.sha256.slice(0, 16))),
      h('td', {}, r.engine, ' ', r.engine === 'newton' ? h('span', {class: 'badge', title: NEWTON_NOTE}, 'experimental') : null),
      h('td', {class: 'mono'}, `${r.tool_version} · spec ${r.spec_version}`),
      h('td', {class: 'mono'}, r.id),
      h('td', {}, result(r)),
      h('td', {}, h('button', {onclick: () => without(i), title: 'Take this run out of the comparison'}, 'Remove')))))));
  const tableBox = h('div');
  function draw() {
    const rows = c.checks.filter(row => !view.onlyDiffers || row.differs);
    const mrows = c.measurements.filter(row => !view.onlyDiffers || row.differs);
    fill(tableBox,
      h('h2', {}, 'Checks', h('span', {class: 'muted'}, c.same_spec ? 'a row with a different verdict is marked' : 'no differences marked')),
      h('div', {class: 'scroll'}, h('table', {},
        h('thead', {}, h('tr', {}, h('th', {}, 'Check'), c.runs.map((_, i) => h('th', {class: 'c'}, `${i + 1}`)), h('th', {}, 'Verdicts'))),
        h('tbody', {}, rows.map(row => h('tr', {class: row.differs ? 'differs' : null},
          h('td', {}, h('b', {class: 'mono'}, row.id), ' ', h('span', {class: 'muted'}, row.title)),
          row.cells.map(cell => h('td', {class: 'c'}, sign(cell?.verdict, cell ? cell.detail : 'no result'))),
          h('td', {class: 'mono'}, Object.entries(row.counts).map(([v, n]) => `${v} ${n} of ${c.runs.length}`).join(' · '))))))),
      c.measurements.length ? [
        h('h2', {}, 'Measurements', h('span', {class: 'muted'}, 'lowest and highest value of each, over the runs')),
        h('div', {class: 'scroll'}, h('table', {},
          h('thead', {}, h('tr', {}, ['Subject', 'Check', 'Case', 'Quantity'].map(t => h('th', {}, t)),
            c.runs.map((_, i) => h('th', {class: 'num'}, `${i + 1}`)), h('th', {class: 'num'}, 'Lowest'), h('th', {class: 'num'}, 'Highest'))),
          h('tbody', {}, mrows.map(row => h('tr', {class: row.differs ? 'differs' : null},
            h('td', {class: 'mono'}, subject(row.subject)), h('td', {class: 'mono'}, row.check), h('td', {}, row.case), h('td', {}, row.quantity),
            row.cells.map(m => h('td', {class: `num ${m && !m.ok ? 'fail-text' : ''}`}, m ? `${m.shown_value} ${m.shown_unit}` : '')),
            h('td', {class: 'num'}, `${row.lowest} ${row.shown_unit}`), h('td', {class: 'num'}, `${row.highest} ${row.shown_unit}`))))))] : null);
  }
  fill(main,
    h('h1', {}, `Compare ${c.runs.length} runs`),
    c.same_asset
      ? banner('All runs are of the same root file (SHA-256). The hash does not cover the layers the root file references.', true)
      : banner('The runs are of different files: their root files have different SHA-256 values.'),
    c.same_spec ? null
      : banner('The runs follow different spec versions. spec.md says that their results are not compared, so the page marks no differences.'),
    c.runs.some(r => r.engine === 'newton') ? banner(NEWTON_NOTE, true) : null,
    runsTable,
    h('div', {class: 'toolbar'}, h('label', {}, h('input', {type: 'checkbox', checked: view.onlyDiffers,
      onchange: e => { view.onlyDiffers = e.target.checked; draw(); }}), 'Only rows that differ')),
    tableBox);
  draw();
}

async function pairView(a, b) {
  const folderA = state.folders.find(f => f.id === a);
  const folderB = state.folders.find(f => f.id === b);
  if (!folderA || !folderB) throw new Error('One of the two folders is not open any more.');
  const p = await apiJson('/api/pair', {a, b});
  crumbs([folderA.name, `#/f/${a}`], [`compared with ${folderB.name}`, null]);
  const ids = order(p.pairs.flatMap(pair => pair.comparison.checks.map(row => row.id)));
  const rows = p.pairs.map(pair => {
    const [ra, rb] = pair.comparison.runs;
    const byId = Object.fromEntries(pair.comparison.checks.map(row => [row.id, row]));
    const changed = pair.comparison.checks.some(row => row.differs);
    return h('tr', {class: changed ? 'differs' : null},
      h('td', {}, h('a', {href: compareHref([[a, pair.a], [b, pair.b]])}, ra.asset)),
      h('td', {class: 'mono'}, `${ra.engine} ${ra.tool_version}`, h('br'), `${rb.engine} ${rb.tool_version}`),
      ids.map(id => {
        const row = byId[id];
        return h('td', {class: 'c'}, sign(row?.cells[0]?.verdict, row?.cells[0]?.detail), h('br'),
          sign(row?.cells[1]?.verdict, row?.cells[1]?.detail));
      }),
      h('td', {}, pair.comparison.same_spec ? (changed ? 'verdicts differ' : 'same verdicts') : 'different spec versions: not compared'));
  });
  const alone = (folder, list) => list.length ? h('p', {class: 'sub'}, `Only in ${folder.name}: `, list.join(', ')) : null;
  fill(main,
    h('h1', {}, `${folderA.name} and ${folderB.name}`),
    h('p', {class: 'sub'}, 'Runs are paired by the SHA-256 of the asset\'s root file, with the same engine first. ',
      'In each cell, the upper sign is ', h('b', {}, folderA.name), ' and the lower one ', h('b', {}, folderB.name), '.'),
    p.pairs.length ? h('div', {class: 'scroll'}, h('table', {},
      h('thead', {}, h('tr', {}, h('th', {}, 'Asset'), h('th', {}, 'Engine and version'), ids.map(id => h('th', {class: 'c'}, id)), h('th', {}, ''))),
      h('tbody', {}, rows))) : h('p', {class: 'empty'}, 'No asset is in both folders.'),
    alone(folderA, p.only_a), alone(folderB, p.only_b));
}

window.addEventListener('hashchange', () => { route(); window.scrollTo(0, 0); });
route();
