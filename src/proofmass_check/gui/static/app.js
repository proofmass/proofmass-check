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
let poller = null;  // the timer that follows a running batch

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
  const size = big ? ' big' : '';
  const main = run.error ? h('span', {class: `v err${size}`, title: run.error}, 'ERROR')
    : run.passed ? h('span', {class: `v pass${size}`}, '✓ PASSED')
    : h('span', {class: `v fail${size}`}, `✕ FAILED (${run.failed})`);
  // A pass does not cover what did not run: say so next to the verdict, not only in the notes.
  const gaps = run.engine_cannot_run || [];
  const wheels = run.wheels_without_mobile || [];
  const marks = [
    gaps.length ? h('span', {class: 'badge',
      title: `The ${run.engine} engine cannot run ${gaps.join(', ')} on this asset yet, so this result does not cover them.`},
    `${gaps.length} not run`) : null,
    wheels.length ? h('span', {class: 'badge',
      title: `${wheels.join(', ')} look like wheels, but the asset has no SimReady_Metadata.mobile, `
        + 'so STAND, DRIVE, TURN and STEER did not run (docs/wheeled-robots.md).'},
    'wheels not checked') : null,
  ].filter(Boolean);
  if (!marks.length) return main;
  return h('span', {}, main, marks.map(m => [' ', m]));
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
  if (poller) { clearInterval(poller); poller = null; }
  const parts = location.hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent);
  try {
    state = await apiJson('/api/state');
    document.getElementById('version').textContent = `${state.version} · spec ${state.spec_version}`;
    if (parts[0] === 'f' && parts[2] === 'r') await runView(parts[1], parts[3]);
    else if (parts[0] === 'f') folderView(parts[1]);
    else if (parts[0] === 'b') await batchView(parts[1]);
    else if (parts[0] === 'settings') await settingsView();
    else if (parts[0] === 'new') await newBatchView();
    else if (parts[0] === 'inspect') await inspectView(JSON.parse(parts[1]));
    else if (parts[0] === 'compare') await compareView(JSON.parse(parts[1]));
    else if (parts[0] === 'pair') await pairView(parts[1], parts[2]);
    else await homeView();
  } catch (e) {
    crumbs();
    fill(main, h('h1', {}, 'Something went wrong'), h('p', {class: 'status err'}, e.message),
      h('p', {}, h('a', {href: '#/'}, 'Back to the folders')));
  }
}

async function homeView() {
  crumbs();
  const batches = await apiJson('/api/batches');
  state = await apiJson('/api/state');  // /api/batches read again the folders of batches whose assets ended
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
  fill(main,
    h('h1', {}, 'Batches', h('a', {class: 'button primary', href: '#/new'}, 'New batch')),
    h('p', {class: 'sub'}, 'Runs of proofmass-check that this page started, in the workspace. ',
      h('a', {href: '#/settings'}, 'Settings'), ' give the Python of each engine and the workspace.'),
    batches.length ? h('div', {class: 'folders'}, batches.slice(0, 30).map(batchRow))
      : h('p', {class: 'empty'}, 'No batch yet. Start one with New batch.'),
    h('h2', {}, 'Folders', h('span', {class: 'muted'}, 'results files from anywhere, read only')),
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

function folderView(folderId, batch) {
  // batch, for the folder of a batch: {name, panel}. The panel shows the batch's runs above the matrix.
  const folder = state.folders.find(f => f.id === folderId);
  if (!folder) throw new Error(`No open folder ${folderId}. Open it again from the list of folders.`);
  crumbs(batch ? [batch.name, null] : [folder.name, null]);
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
    // A header says what its check does, as the spec's titles say it (/api/state gives them).
    const what = id => `${id}: ${(state && state.checks && state.checks[id]) || ''}`;
    const wheeledHelp = `${WHEELED.map(what).join('\n')}\n\nClick to show or hide the four wheeled checks.`;
    const head = h('tr', {}, h('th', {class: 'c'}, all), h('th', {}, 'Asset'), h('th', {}, 'Engine'),
      cols.map(id => h('th', {class: 'c', title: id === 'WHEELED' ? wheeledHelp : what(id)},
        id === 'WHEELED' || (view.wheeledOpen && WHEELED.includes(id))
          ? h('button', {onclick: toggleWheeled, title: id === 'WHEELED' ? wheeledHelp : `${what(id)}\n\nClick to fold the wheeled checks.`}, id)
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
    h('h1', {}, batch ? batch.name : folder.name),
    h('p', {class: 'sub'}, h('span', {class: 'mono'}, folder.path), versions ? ` · proofmass-check ${versions}` : ''),
    batch ? batch.panel : null,
    batch ? h('h2', {}, 'Results', h('span', {class: 'muted'}, 'the runs that have ended')) : null,
    h('p', {class: 'toolbar'},
      h('span', {}, `${c.total} runs`), h('span', {class: 'pass-text'}, `${c.passed} passed`),
      h('span', {class: 'fail-text'}, `${c.failed} failed`),
      c.errors ? h('span', {class: 'fail-text'}, `${c.errors} stopped with an error`) : null,
      h('span', {class: 'muted'}, `${seconds(runs.reduce((t, r) => t + (typeof r.seconds === 'number' ? r.seconds : 0), 0))} in all`)),
    runs.some(r => r.settings_differ) ? banner('Some runs have settings that differ from the spec. They carry the mark "settings".') : null,
    runs.some(r => (r.engine_cannot_run || []).length)
      ? banner('Some runs did not run every check their asset needs: their engine cannot run it yet. They carry the mark '
        + '"not run", and a pass does not cover those checks. Run them in an engine that can.') : null,
    runs.some(r => (r.wheels_without_mobile || []).length)
      ? banner('Some assets have joints that look like wheels but no SimReady_Metadata.mobile, so their wheeled checks '
        + 'did not run. They carry the mark "wheels not checked" (docs/wheeled-robots.md).') : null,
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
      h('a', {class: 'button', href: inspectHref({file: d.file, engine: ['physx', 'newton'].includes(d.engine) ? d.engine : 'physx',
        variants: Object.entries(d.variants).map(([k, v]) => `${k}=${v}`), floor: d.settings.floor !== null, run: [folderId, runId]})},
        'Inspect the asset'),
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

// --- batches: runs that the page starts (docs/gui.md, sections 6.2, 6.3 and 6.9)

const RUN_STATES = {running: 'running', queued: 'waiting to start', done: 'done', stopped: 'stopped',
  cancelled: 'cancelled', error: 'the engine did not start', 'not started': 'not started'};
const LICENCE_NOTE = 'Isaac Sim asks you to accept the NVIDIA Omniverse License Agreement the first time it '
  + 'starts. This page never accepts it for you: start Isaac Sim once in a terminal and accept it there, '
  + 'before the first PhysX batch.';
let viewNumber = 0;  // a view that loads in the background draws only while it is still the current view

function batchCounts(b) {
  const all = b.runs.flatMap(r => r.assets);
  const n = (...names) => all.filter(a => names.includes(a.state)).length;
  return {passed: n('passed'), failed: n('failed'), errors: n('error', 'stopped'), open: n('running', 'waiting')};
}

function batchRow(b) {
  const c = batchCounts(b);
  return h('div', {class: 'folder'},
    h('a', {class: 'name', href: `#/b/${encodeURIComponent(b.id)}`}, b.name),
    h('div', {class: 'path'}, `${b.created} · ${b.engines.join(', ')} · ${b.assets.length} assets · ${b.path}`),
    h('div', {class: 'counts'},
      h('span', {class: b.state === 'running' ? 'badge' : 'muted'}, b.state),
      h('span', {class: 'pass-text'}, `${c.passed} passed`),
      h('span', {class: 'fail-text'}, `${c.failed} failed`),
      c.errors ? h('span', {class: 'fail-text'}, `${c.errors} stopped with an error`) : null,
      c.open ? h('span', {class: 'muted'}, `${c.open} to run`) : null));
}

function assetCell(b, run, a) {
  const link = child => h('a', {href: runHref(b.folder, `${run.id}/${a.name}/results.json`)}, child);
  if (a.state === 'passed') return link(h('span', {class: 'v pass'}, '✓ PASSED'));
  if (a.state === 'failed') return link(h('span', {class: 'v fail'}, '✕ FAILED'));
  if (a.state === 'error') return link(h('span', {class: 'v err', title: a.error || ''}, 'ERROR'));
  if (a.state === 'stopped') return h('span', {class: 'v err', title: a.error || ''}, 'STOPPED');
  if (a.state === 'running') {
    const parts = [a.check || 'reading the asset', a.total ? `${a.done} of ${a.total}` : a.done ? `${a.done}` : null,
      typeof a.elapsed === 'number' ? seconds(a.elapsed) : null];
    return h('span', {class: 'running'}, h('span', {class: 'spinner', 'aria-hidden': 'true'}),
      parts.filter(Boolean).join(' · '));
  }
  return h('span', {class: 'muted'}, a.state);
}

async function cancelRun(b, runId, refresh) {
  const what = runId ? `the run ${runId}` : 'every run of this batch';
  if (!window.confirm(`Stop ${what}? The asset a worker is on gets no results.`)) return;
  await apiJson('/api/batch-cancel', {id: b.id, run: runId});
  await refresh();
}

async function drawLog(panel, b) {
  if (!panel.log) return fill(panel.logBox);
  const found = await apiJson(`/api/batch-log?id=${encodeURIComponent(b.id)}&run=${encodeURIComponent(panel.log)}`);
  fill(panel.logBox,
    h('div', {class: 'toolbar'}, h('b', {}, `Log of ${panel.log}`), h('span', {class: 'muted'}, 'the last 200 lines'),
      h('span', {class: 'grow'}), h('button', {onclick: () => { panel.log = null; fill(panel.logBox); }}, 'Hide')),
    h('pre', {class: 'error log'}, found.text || 'Nothing yet.'));
}

function drawPanel(panel, b, refresh) {
  const busy = b.state === 'running';
  const head = h('tr', {}, h('th', {}, 'Asset'), b.runs.map(r => h('th', {},
    h('div', {}, h('span', {class: 'mono'}, r.id), ' · ', RUN_STATES[r.state] || r.state),
    r.phase ? h('div', {class: 'muted'}, `${r.phase}…`) : null,
    h('div', {class: 'toolbar'},
      ['running', 'queued'].includes(r.state) ? h('button', {onclick: () => cancelRun(b, r.id, refresh)}, 'Cancel') : null,
      r.workers ? h('button', {onclick: () => { panel.log = r.id; drawLog(panel, b); }}, 'Log') : null))));
  const rows = b.assets.map((asset, i) => h('tr', {}, h('td', {class: 'mono'}, asset.name),
    b.runs.map(r => h('td', {}, assetCell(b, r, r.assets[i])))));
  const other = b.runs.filter(r => r.version && r.version.split(' ')[1] !== state.version);
  fill(panel,
    h('h2', {}, 'Runs', h('span', {class: 'muted'}, `${b.created} · settle ${b.settle_s} s · `
      + `${b.floor ? 'floor' : 'no floor'}${b.variants.length ? ` · ${b.variants.join(' ')}` : ''}`),
      busy ? h('button', {onclick: () => cancelRun(b, null, refresh)}, 'Cancel the batch') : null),
    b.runs.filter(r => r.error).map(r => banner(`${r.id}: the engine did not start: ${r.error}. Its log says more.`)),
    other.map(r => banner(`${r.id} ran ${r.version}, and this page is ${state.version}.`)),
    b.runs.some(r => r.engine === 'physx' && r.state === 'error') ? banner(LICENCE_NOTE, true) : null,
    h('div', {class: 'scroll'}, h('table', {class: 'batch'}, h('thead', {}, head), h('tbody', {}, rows))),
    panel.logBox,
    h('details', {}, h('summary', {}, 'The command of each run'),
      b.runs.map(r => [h('p', {class: 'sub'}, r.id), h('pre', {class: 'error log'}, r.command)])));
}

async function batchView(batchId) {
  const mine = viewNumber;
  let b = await apiJson(`/api/batch?id=${encodeURIComponent(batchId)}`);
  state = await apiJson('/api/state');  // the batch's folder may have been opened just now
  const panel = h('section', {class: 'batch-panel'});
  panel.logBox = h('div');
  const ended = x => x.runs.reduce((n, r) => n + r.assets.filter(a => !['waiting', 'running'].includes(a.state)).length, 0);
  let seen = ended(b);
  const refresh = async () => {
    b = await apiJson(`/api/batch?id=${encodeURIComponent(batchId)}`);
    if (mine !== viewNumber) return;
    if (ended(b) !== seen) {  // an asset ended: /api/batch read its new results.json, so the matrix is drawn again
      seen = ended(b);
      state = await apiJson('/api/state');
      if (mine !== viewNumber) return;
      folderView(b.folder, {name: b.name, panel});
    }
    drawPanel(panel, b, refresh);
    if (panel.log) await drawLog(panel, b);
    if (b.state !== 'running' && poller) { clearInterval(poller); poller = null; }
  };
  drawPanel(panel, b, refresh);
  folderView(b.folder, {name: b.name, panel});
  if (b.state === 'running') poller = setInterval(() => refresh().catch(() => {}), 1500);
}

async function settingsView() {
  crumbs(['Settings', null]);
  const s = await apiJson('/api/settings');
  const say = status();
  const workspace = h('input', {type: 'text', size: 70, value: s.workspace, 'aria-label': 'The workspace folder',
    disabled: s.workspace_for_session});
  const fields = s.engines.map(engine => {
    const input = h('input', {type: 'text', size: 70, value: engine.python, 'aria-label': `The Python of ${engine.name}`,
      placeholder: engine.name === 'physx' ? 'C:\\isaacsim\\.venv\\Scripts\\python.exe' : 'C:\\newton\\.venv\\Scripts\\python.exe'});
    const answer = h('p', {class: 'status'});
    const test = async () => {
      await save();
      answer.textContent = 'Starting it…';
      answer.className = 'status';
      const found = await apiJson('/api/check-python', {engine: engine.name});
      answer.textContent = found.ok
        ? `✓ ${found.text}${found.same_version ? '' : `. This page is ${found.version}: results follow the spec of the version that ran them.`}`
        : `✕ ${found.text}`;
      answer.className = `status${found.ok ? '' : ' err'}`;
    };
    return {name: engine.name, input, element: h('div', {class: 'field'},
      h('label', {class: 'name'}, engine.name),
      h('p', {class: 'sub'}, `Its Python needs ${engine.needs}. The page runs `, h('code', {}, 'python -m proofmass_check'), ' in it.'),
      h('div', {class: 'toolbar'}, input, h('button', {onclick: () => test().catch(e => say.say(e.message, true))}, 'Save and test')),
      answer)};
  });
  async function save() {
    const pythons = Object.fromEntries(fields.map(f => [f.name, f.input.value]));
    await apiJson('/api/settings', {pythons, workspace: workspace.value});
    say.say(`Saved in ${s.file}.`);
  }
  fill(main, h('h1', {}, 'Settings'),
    h('p', {class: 'sub'}, `They are kept in ${s.file}, not in the repository or the workspace.`),
    h('h2', {}, 'Engines', h('span', {class: 'muted'}, 'each runs in its own Python')),
    fields.map(f => f.element),
    banner(LICENCE_NOTE, true),
    h('h2', {}, 'Workspace', h('span', {class: 'muted'}, 'the folder where new batches go')),
    h('div', {class: 'toolbar'}, workspace),
    s.workspace_for_session ? h('p', {class: 'sub'}, 'This session uses the workspace given with --workspace.') : null,
    h('div', {class: 'toolbar'}, h('button', {class: 'primary', onclick: () => save().catch(e => say.say(e.message, true))}, 'Save')),
    say);
}

async function newBatchView() {
  crumbs(['New batch', null]);
  const s = await apiJson('/api/settings');
  const say = status();
  let files = [];
  const name = h('input', {type: 'text', size: 40, value: 'batch', 'aria-label': 'The name of the batch'});
  const where = h('input', {type: 'text', size: 70, placeholder: 'C:\\assets\\lightwheel', 'aria-label': 'A USD file or a folder'});
  const filter = h('input', {type: 'text', placeholder: 'Filter the files', 'aria-label': 'Filter the files',
    oninput: () => drawFiles()});
  const filesBox = h('div');
  const engineBoxes = s.engines.map(e => ({name: e.name, box: h('input', {type: 'checkbox', checked: Boolean(e.python) && e.name === 'physx'})}));
  const repeats = h('input', {type: 'number', min: 1, max: 20, step: 1, value: 1, 'aria-label': 'Runs of each asset in Newton'});
  const settle = h('input', {type: 'number', min: 0.1, max: 60, step: 0.1, value: 1.5, 'aria-label': 'Settle time in s'});
  const floor = h('input', {type: 'checkbox', checked: true});
  const variants = h('input', {type: 'text', size: 40, placeholder: 'Physics=PhysX', 'aria-label': 'Variants, SET=VALUE'});
  const preview = h('div');
  const visible = () => files.filter(f => !filter.value || f.name.toLowerCase().includes(filter.value.toLowerCase()));

  function body() {
    return {
      name: name.value, assets: files.filter(f => f.ticked).map(f => f.path),
      engines: engineBoxes.filter(e => e.box.checked).map(e => e.name),
      repeats: Number(repeats.value), settle_s: Number(settle.value), floor: floor.checked,
      variants: variants.value.split(/[\s,]+/).filter(Boolean),
    };
  }

  let timer = null;
  function update() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      try {
        const runs = await apiJson('/api/batch-preview', body());
        fill(preview, runs.map(r => [h('p', {class: 'sub'}, r.run), h('pre', {class: 'error log'}, r.command)]));
      } catch (e) {
        fill(preview, h('p', {class: 'status'}, e.message));
      }
    }, 300);
  }

  function drawFiles() {
    const shown = visible();
    const ticked = files.filter(f => f.ticked).length;
    const names = files.filter(f => f.ticked).map(f => f.name.split('/').pop().replace(/\.[^.]+$/, ''));
    const twice = [...new Set(names.filter((n, i) => names.indexOf(n) !== i))];
    fill(filesBox,
      files.length ? h('div', {class: 'toolbar'}, filter,
        h('button', {onclick: () => { shown.forEach(f => { f.ticked = true; }); drawFiles(); update(); }}, 'Tick the files shown'),
        h('button', {onclick: () => { files.forEach(f => { f.ticked = false; }); drawFiles(); update(); }}, 'Untick all'),
        h('span', {class: 'muted'}, `${ticked} of ${files.length} ticked`)) : null,
      twice.length ? banner(`Ticked files with the same name: ${twice.join(', ')}. Each batch needs different names.`) : null,
      files.length ? h('div', {class: 'scroll'}, h('table', {}, h('tbody', {}, shown.slice(0, 500).map(f => h('tr', {},
        h('td', {class: 'c'}, h('input', {type: 'checkbox', checked: f.ticked, 'aria-label': `Tick ${f.name}`,
          onchange: e => { f.ticked = e.target.checked; drawFiles(); update(); }})),
        h('td', {class: 'mono'}, f.name),
        h('td', {}, h('a', {href: inspectHref({file: f.path, engine: (engineBoxes.find(e => e.box.checked) || {name: 'physx'}).name})}, 'Inspect')),
        h('td', {class: 'num'}, `${(f.size / 1024).toFixed(0)} kB`)))))) : null,
      shown.length > 500 ? h('p', {class: 'sub'}, `${shown.length - 500} more: filter to see them.`) : null);
  }

  const find = async () => {
    say.say('Looking for USD files…');
    try {
      const found = await apiJson('/api/usd-files', {path: where.value});
      files = found.files.map(f => ({...f, ticked: found.files.length === 1}));
      say.say(`${files.length} USD files in ${found.root}${found.truncated ? ', and more not listed' : ''}. Tick the root file of each asset.`);
      drawFiles();
      update();
    } catch (e) {
      say.say(e.message, true);
    }
  };
  const start = async () => {
    say.say('Testing the engines\' Pythons and starting the batch…');
    try {
      const made = await apiJson('/api/batches', body());
      location.hash = `#/b/${encodeURIComponent(made.id)}`;
    } catch (e) {
      say.say(e.message, true);
    }
  };
  for (const input of [name, repeats, settle, floor, variants, ...engineBoxes.map(e => e.box)]) input.addEventListener('input', update);
  fill(main, h('h1', {}, 'New batch'),
    h('p', {class: 'sub'}, 'Every asset runs in each engine you choose. The engine starts once for all the assets of a run, ',
      'and one run goes at a time. The results go to the workspace: ', h('span', {class: 'mono'}, s.workspace), '.'),
    h('h2', {}, 'Assets'),
    h('form', {class: 'toolbar', onsubmit: e => { e.preventDefault(); find(); }}, where,
      h('button', {type: 'submit'}, 'Find USD files')),
    filesBox,
    h('h2', {}, 'Engines'),
    engineBoxes.map(e => {
      const python = s.engines.find(x => x.name === e.name).python;
      return h('div', {class: 'toolbar'}, h('label', {}, e.box, e.name),
        python ? h('span', {class: 'mono muted'}, python) : h('span', {class: 'fail-text'}, 'no Python set: ', h('a', {href: '#/settings'}, 'Settings')));
    }),
    h('div', {class: 'toolbar'}, h('label', {}, 'Runs of each asset in Newton', repeats),
      h('span', {class: 'muted'}, 'Newton\'s results can differ from run to run, so several runs show how much.')),
    h('h2', {}, 'Settings', h('span', {class: 'muted'}, 'a value that is not the spec\'s is marked in the results')),
    h('div', {class: 'toolbar'}, h('label', {}, 'Name', name)),
    h('div', {class: 'toolbar'}, h('label', {}, 'Settle time, s', settle), h('span', {class: 'muted'}, 'spec: 1.5')),
    h('div', {class: 'toolbar'}, h('label', {}, floor, 'Floor'), h('span', {class: 'muted'}, 'off for a pinned arm whose links reach below its base')),
    h('div', {class: 'toolbar'}, h('label', {}, 'Variants', variants), h('span', {class: 'muted'}, 'SET=VALUE, more than one with spaces')),
    h('h2', {}, 'Commands', h('span', {class: 'muted'}, 'what each run will start')),
    preview,
    h('div', {class: 'toolbar'}, h('button', {class: 'primary', onclick: start}, 'Start the batch')),
    say);
  where.focus();
  update();
}

// --- the inspector: an asset before a run, without an engine (docs/gui.md, sections 5.3, 6.5 and 6.6)

const inspectHref = spec => `#/inspect/${encodeURIComponent(JSON.stringify(spec))}`;
const EXPECTED_NOTE = 'This plan is expected, not certain: LOAD decides whether the other checks run, '
  + 'and Newton runs DROP only when it builds a free joint. A run shows the real plan.';

function number(value) {
  if (value === null || value === undefined) return '';
  return Number(value.toPrecision(3)).toLocaleString('en-US', {maximumFractionDigits: 6});
}

function position(joint, value) {
  // A joint position as people read it: degrees for a revolute joint, millimetres for a prismatic one.
  if (value === null || value === undefined) return 'none';
  return joint.kind === 'revolute' ? `${(value * 180 / Math.PI).toFixed(1)} deg` : `${(value * 1000).toFixed(1)} mm`;
}

function driveText(joint) {
  const d = joint.drive;
  if (!d) return h('span', {class: 'muted'}, 'none');
  const r = joint.kind === 'revolute';
  const parts = [`k ${number(d.stiffness)} ${r ? 'N m/rad' : 'N/m'}`, `d ${number(d.damping)} ${r ? 'N m s/rad' : 'N s/m'}`,
    d.max_force === null ? 'no force limit' : `max ${number(d.max_force)} ${r ? 'N m' : 'N'}`];
  return h('span', {}, parts.join(' · '), h('div', {class: 'muted'}, joint.drive_from));
}

function speedLimit(joint) {
  if (joint.max_speed === null) return h('span', {class: 'muted'}, 'none');
  return joint.kind === 'revolute' ? `${number(joint.max_speed * 180 / Math.PI)} deg/s` : `${number(joint.max_speed)} m/s`;
}

function loadText(joint) {
  if (joint.gravity_load === null) return '';
  const unit = joint.kind === 'revolute' ? 'N m' : 'N';
  const force = joint.drive && joint.drive.max_force !== null ? ` / ${number(joint.drive.max_force)}` : '';
  return `${number(joint.gravity_load)}${force} ${unit}`;
}

async function inspectView(spec) {
  const mine = viewNumber;
  crumbs(['Inspect', null]);
  fill(main, h('h1', {}, 'Inspect'), h('p', {class: 'status'}, `Reading ${spec.file}. A large stage can take a while.`));
  const engine = spec.engine || 'physx';
  const d = await apiJson('/api/inspect', {file: spec.file, engine, variants: spec.variants || [], floor: spec.floor !== false});
  const marks = {};
  let runName = null;
  if (spec.run) {
    try {
      const r = await apiJson(`/api/run?folder=${encodeURIComponent(spec.run[0])}&run=${encodeURIComponent(spec.run[1])}`);
      runName = `${r.asset} · ${r.engine}`;
      for (const m of r.measurements) {
        if (!m.subject) continue;
        if (!m.ok) marks[m.subject] = 'fail';
        else if (m.margin !== null && m.margin >= CLOSE && marks[m.subject] !== 'fail') marks[m.subject] = 'close';
      }
    } catch { /* the run's folder is not open any more: the view shows no marks */ }
  }
  if (mine !== viewNumber) return;
  crumbs(['Inspect', null], [d.name, null]);

  const rows = new Map();
  let viewer = null;
  // The 3D view docks in a corner when the page scrolls past it, so a joint picked in a table
  // below shows at once. The slot keeps the view's place, so the page does not jump.
  let outOfSight = false, closed = false;
  const dockName = h('span', {class: 'mono'}, d.name);
  const canvas = h('canvas', {class: 'viewer', role: 'img', 'aria-label': `The colliders and joints of ${d.name} in 3D`});
  const frame = h('div', {class: 'viewer-frame'}, canvas, h('div', {class: 'dock-bar'}, dockName,
    h('button', {type: 'button', title: 'Scroll back to the full 3D view', onclick: () => slot.scrollIntoView({block: 'center'})}, 'Full view'),
    h('button', {type: 'button', 'aria-label': 'Close the small 3D view', title: 'Close the small view until you pick another joint',
      onclick: () => { closed = true; dock(); }}, '×')));
  const slot = h('div', {class: 'viewer-slot'}, frame);
  const dock = () => frame.classList.toggle('docked', outOfSight && !closed);
  new IntersectionObserver(([seen]) => {
    outOfSight = seen.intersectionRatio < 0.3;
    if (!outOfSight) closed = false;
    dock();
  }, {threshold: [0, 0.3, 1]}).observe(slot);
  const pick = name => {
    for (const [n, row] of rows) row.classList.toggle('picked', n === name);
    if (viewer) viewer.select(name);
    dockName.textContent = name || d.name;
    closed = false;
    dock();
    const row = rows.get(name);
    if (row) row.scrollIntoView({block: 'nearest'});
  };
  const sets = Object.entries(d.variant_sets);
  const byPath = Object.fromEntries(d.bodies.map(b => [b.path, b.name]));
  const moving = d.joints.filter(j => j.kind !== 'fixed');
  const marked = Object.values(marks).filter(m => m === 'fail').length;

  const jointRows = d.joints.map(j => {
    const row = h('tr', {class: j.kind === 'fixed' ? 'muted' : null, onclick: () => pick(j.name), title: j.prim},
      h('td', {class: 'mono'}, marks[j.name] ? sign(marks[j.name] === 'fail' ? 'FAIL' : 'PASS',
        marks[j.name] === 'fail' ? 'a measurement of this joint failed' : 'close to a limit') : null, ' ', j.name),
      h('td', {}, j.kind, j.d6 ? h('div', {class: 'muted'}, `axis of ${j.d6}`) : null),
      h('td', {class: 'mono'}, byPath[j.body1] || j.body1 || 'world', h('div', {class: 'muted'}, `on ${byPath[j.body0] || j.body0 || 'world'}`)),
      h('td', {class: 'num'}, j.kind === 'fixed' ? '' : `${position(j, j.lower)} to ${position(j, j.upper)}`),
      h('td', {class: 'num'}, j.kind === 'fixed' ? '' : position(j, j.rest)),
      h('td', {}, j.kind === 'fixed' ? '' : driveText(j)),
      h('td', {class: 'num'}, j.kind === 'fixed' ? '' : speedLimit(j)),
      h('td', {class: 'num'}, j.carried_mass === null ? '' : `${number(j.carried_mass)} kg`,
        j.lever !== null ? h('div', {class: 'muted'}, `${number(j.lever * 1000)} mm from the axis`) : null),
      h('td', {class: 'num'}, loadText(j)),
      h('td', {class: 'mono'}, j.mimic ? `${j.mimic.leader} × ${number(j.mimic.ratio)}` : ''));
    rows.set(j.name, row);
    return row;
  });

  // Which joints the checks test: the same sets as the plan (plan.py), from inspect.
  const filters = [
    ['all', 'All', () => true],
    ['driven', 'Driven', j => j.driven],
    ['pushed', 'Pushed by PASSIVE', j => j.pushed],
    ['free', 'No limits', j => j.kind !== 'fixed' && !j.limited],
    ['follows', 'Follows another', j => j.mimic !== null],
    ['marked', 'Marked by the run', j => Boolean(marks[j.name])],
  ].filter(([name, , test]) => name === 'all' || (name !== 'marked' || runName) && d.joints.some(test));
  const filterLinks = filters.map(([name, label, test]) => {
    const count = d.joints.filter(test).length;
    return h('a', {href: '#', 'data-filter': name, class: name === 'all' ? 'on' : null, onclick: event => {
      event.preventDefault();
      for (const link of filterLinks) link.classList.toggle('on', link === event.currentTarget);
      for (const j of d.joints) rows.get(j.name).hidden = !test(j);
    }}, `${label} (${count})`);
  });

  fill(main,
    h('h1', {}, d.name, h('span', {class: 'seg'}, ['physx', 'newton'].map(e =>
      h('a', {class: e === engine ? 'on' : null, href: inspectHref({...spec, engine: e})}, e)))),
    h('p', {class: 'sub'}, h('span', {class: 'mono'}, d.file)),
    h('p', {class: 'sub'}, `${d.bodies.length} bodies · ${moving.length} moving joint${moving.length === 1 ? '' : 's'} · `,
      d.articulated ? 'an articulation' : 'no PhysicsArticulationRootAPI', ' · ',
      d.world_fixed.length ? `fixed to the world by ${d.world_fixed.join(', ')}` : 'free', ' · ',
      typeof d.floor === 'number' ? `floor at ${(d.floor * 1000).toFixed(1)} mm` : 'no floor',
      sets.length ? ` · variants ${Object.entries(d.variants).map(([k, v]) => `${k}=${v}`).join(' ') || 'none selected'}` : ''),
    sets.length ? h('p', {class: 'sub'}, 'Variant sets: ', sets.map(([k, vs]) => `${k} (${vs.join(', ')})`).join('; ')) : null,
    runName ? banner(`Joints are marked by the measurements of the run ${runName}: ${marked} failed. `
      + 'Red: a measurement failed. Amber: it passed close to its limit.', true) : null,
    slot,
    h('p', {class: 'sub'}, 'Drag to turn, Shift+drag to move, the wheel to zoom, double-click to reset. '
      + 'Click a joint here or in the table to find it and see its range: an arc or a segment, with a tick at the file pose. '
      + 'The view shows the colliders, which are what the engine collides. Dashed: the box GRIP closes on. '
      + 'Below this view, a smaller one stays in the corner.'),
    h('h2', {}, 'Plan', h('span', {class: 'muted'}, `for ${engine}`)),
    banner(EXPECTED_NOTE, true),
    h('div', {class: 'scroll'}, h('table', {}, h('tbody', {}, d.plan.map(p => h('tr', {},
      h('td', {class: 'mono'}, p.id),
      h('td', {}, p.runs ? h('span', {class: 'badge'}, 'runs') : h('span', {class: 'v na'}, 'N/A')),
      h('td', {}, p.title, p.reason ? h('div', {class: 'muted'}, p.reason) : null)))))),
    d.notes.length ? h('ul', {class: 'notes banner'}, d.notes.map(n => h('li', {}, n))) : null,
    h('h2', {}, 'Joints', h('span', {class: 'muted'}, 'click a row to find it in 3D and see its range')),
    h('div', {class: 'toolbar'}, h('span', {class: 'seg', role: 'group', 'aria-label': 'Show the joints'}, filterLinks)),
    h('div', {class: 'scroll'}, h('table', {class: 'joints'},
      h('thead', {}, h('tr', {}, ['Joint', 'Type', 'Moves', 'Limits', 'Rest', 'Drive', 'Speed limit', 'Carries',
        'Gravity load / max force', 'Follows'].map(t => h('th', {}, t)))),
      h('tbody', {}, jointRows))),
    h('p', {class: 'sub'}, 'The gravity load is the largest torque or force that gravity puts on the joint, from the mass it carries. '
      + 'It is the number PASSIVE starts its push from. The page shows it next to the drive\'s max force, and decides nothing from it.'),
    h('h2', {}, 'Bodies'),
    h('div', {class: 'scroll'}, h('table', {}, h('thead', {}, h('tr', {}, ['Body', 'Path', 'Mass', 'Colliders'].map(t => h('th', {}, t)))),
      h('tbody', {}, d.bodies.map(b => h('tr', {},
        h('td', {class: 'mono'}, b.name, b.path === d.root_body ? h('span', {class: 'muted'}, ' root') : null),
        h('td', {class: 'mono muted'}, b.path),
        h('td', {class: 'num'}, b.mass === null ? h('span', {class: 'muted'}, 'the engine computes it') : `${number(b.mass)} kg`),
        h('td', {class: 'num'}, b.colliders)))))),
    d.sites.length ? [h('h2', {}, 'Gripper sites'), h('div', {class: 'scroll'}, h('table', {},
      h('thead', {}, h('tr', {}, ['Site', 'Body', 'Max opening', 'Pad', 'Payload'].map(t => h('th', {}, t)))),
      h('tbody', {}, d.sites.map(s => h('tr', {}, h('td', {class: 'mono'}, s.name), h('td', {class: 'mono'}, byPath[s.body] || s.body || ''),
        h('td', {class: 'num'}, `${number(s.opening * 1000)} mm`), h('td', {class: 'num'}, `${number(s.pad * 1000)} mm`),
        h('td', {class: 'num'}, s.payload === null ? 'none' : `${number(s.payload)} kg`))))))] : null,
    d.wheeled ? [h('h2', {}, 'Wheels'), h('p', {}, `${d.wheeled.drive} drive · track ${number(d.wheeled.track * 1000)} mm · `
      + `wheel radius ${number(d.wheeled.radius * 1000)} mm · ${d.wheeled.wheels.map(w => `${w.name} (${w.side}${w.driven ? ', driven' : ''})`).join(', ')}`)] : null,
    h('h2', {}, 'Attributes of the joint prims', h('span', {class: 'muted'}, 'as written in the file, also the ones the checks do not read')),
    d.joints.map(j => h('details', {},
      h('summary', {}, h('span', {class: 'mono'}, j.name), ` · ${j.prim} · ${j.schemas.join(', ') || 'no applied schemas'}`),
      h('div', {class: 'attributes'}, Object.entries(j.attributes).map(([k, v]) => `${k} = ${v}`).join('\n') || 'no authored attributes'))));
  viewer = makeViewer(canvas, d, marks, pick);
}

window.addEventListener('hashchange', () => { viewNumber += 1; route(); window.scrollTo(0, 0); });
route();
