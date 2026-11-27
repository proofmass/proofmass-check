// SPDX-FileCopyrightText: 2026 Paweł Kikta
// SPDX-License-Identifier: Apache-2.0
'use strict';
/* The replay of a run's checks, in the inspector's 3D view (docs/gui.md, section 6.11).

   It reads replay.bin (section 5.5): a header in JSON, then float32 frames. A frame is its time,
   then x y z qw qx qy qz of each body, and of the grip box in a grip trial. The player shows the
   frame of the current time and draws what the clip did to the asset. It decides nothing: the
   verdicts and numbers come from results.json. h(), fill(), sign() and banner() are app.js's. */

const REPLAY_FORMAT = 1;
const SPEEDS = [0.1, 0.25, 0.5, 1, 2];

function parseReplay(buffer) {
  const bytes = new Uint8Array(buffer);
  if (bytes.length < 16 || new TextDecoder().decode(bytes.subarray(0, 8)) !== 'PMREPLAY') {
    throw new Error('The replay file is not one that proofmass-check wrote.');
  }
  const head = new DataView(buffer, 8, 8);
  const version = head.getUint32(0, true);
  if (version !== REPLAY_FORMAT) throw new Error(`The replay has format ${version}: this page reads format ${REPLAY_FORMAT}.`);
  const n = head.getUint32(4, true);
  const header = JSON.parse(new TextDecoder().decode(bytes.subarray(16, 16 + n)));
  // The file is little-endian, as the platform of every browser is, and its frames start on a
  // multiple of 4 bytes, as a Float32Array needs.
  const values = new Float32Array(buffer, 16 + n);
  const clips = header.clips.map((c, index) => {
    const width = 1 + 7 * (header.bodies.length + (c.box ? 1 : 0));
    const data = values.subarray(c.offset, c.offset + c.frames * width);
    const times = Array.from({length: c.frames}, (_, k) => data[k * width]);
    // The last frame whose values are all finite. An engine that blows up gives NaN, and the view stops there.
    let finite = c.frames - 1;
    for (let k = 0; k < c.frames; k++) {
      if (data.subarray(k * width, (k + 1) * width).some(v => !Number.isFinite(v))) {
        finite = k - 1;
        break;
      }
    }
    return {...c, index, width, data, times, finite};
  });
  return {header, clips};
}

// A pose as rows [r0 r1 r2 t], from x y z qw qx qy qz at `at` in a frame.
function poseAt(row, at) {
  const [x, y, z] = [row[at], row[at + 1], row[at + 2]];
  let [w, i, j, k] = [row[at + 3], row[at + 4], row[at + 5], row[at + 6]];
  const length = Math.hypot(w, i, j, k) || 1;
  [w, i, j, k] = [w / length, i / length, j / length, k / length];
  return [
    [1 - 2 * (j * j + k * k), 2 * (i * j - k * w), 2 * (i * k + j * w), x],
    [2 * (i * j + k * w), 1 - 2 * (i * i + k * k), 2 * (j * k - i * w), y],
    [2 * (i * k - j * w), 2 * (j * k + i * w), 1 - 2 * (i * i + j * j), z],
  ];
}

const seconds2 = t => `${t.toFixed(2)} s`;

/* The player: controls and the list of clips, in a section for the inspector page.
   options: replay (parseReplay's), viewer (makeViewer's), inspect (the inspector's data), run (the
   run's details from /api/run), select(name) to mark a joint without scrolling, play ({check,
   subject, case} of a measurement, or {}), alive() false once the page shows another view. */
function makePlayer(options) {
  const {replay, viewer, inspect, run} = options;
  const {header, clips} = replay;
  const bodies = header.bodies;
  const jointNames = new Set(inspect.joints.map(j => j.name));
  const root = bodies.indexOf(inspect.root_body);
  const known = new Set(inspect.bodies.map(b => b.path));
  const missing = bodies.filter(p => !known.has(p));
  const wanted = options.play && options.play.check ? options.play : null;
  const ofMeasurement = wanted ? clipsOf(wanted) : [];
  let clip = null, t = 0, playing = false, last = null, raf = null, speed = 1, loop = false;
  let filter = ofMeasurement.length ? 'measurement' : 'all';

  // The clips of a measurement: those of its check with its subject and case, or else those of its
  // check that show the whole asset (docs/gui.md, section 6.11).
  function clipsOf(m) {
    const own = clips.filter(c => c.check === m.check && c.subject === m.subject && c.case === m.case);
    return own.length ? own : clips.filter(c => c.check === m.check && !c.subject);
  }

  const end = c => (c.finite >= 0 ? c.times[c.finite] : 0);
  const frameAt = (c, time) => {
    let low = 0, high = Math.max(c.finite, 0);
    while (low < high) {
      const middle = (low + high + 1) >> 1;
      if (c.times[middle] <= time + 1e-9) low = middle; else high = middle - 1;
    }
    return low;
  };
  const rowOf = (c, k) => c.data.subarray(k * c.width, (k + 1) * c.width);
  const posesOf = (c, k) => {
    const row = rowOf(c, k);
    return new Map(bodies.map((path, i) => [path, poseAt(row, 1 + 7 * i)]));
  };
  const title = c => [c.check, c.subject, c.case, c.attempt].filter(Boolean).join(' · ');
  const number = v => Number(Number(v).toPrecision(3)).toString();

  // The measurements of results.json that this clip gives, as text for the last frame.
  function results(c) {
    return run.measurements
      .filter(m => m.check === c.check && m.subject === c.subject && m.case === c.case)
      .slice(0, 3)
      .map(m => `${m.quantity} ${m.shown_value} ${m.shown_unit}`
        + (m.shown_limit === '' ? '' : `, limit ${m.bound === 'min' ? '≥' : '≤'} ${m.shown_limit} ${m.shown_unit}`)
        + ` ${m.ok ? 'PASS' : 'FAIL'}`);
  }

  // What the clip adds to the view at frame k: the target, the push, the grip box and its pull, the path.
  function marksAt(c, k, time) {
    const a = c.arguments || {};
    const found = {lines: [title(c), `${seconds2(time)} of ${seconds2(c.times[c.frames - 1] || 0)}`]};
    if ((c.operation === 'settle' || c.operation === 'move') && a.targets && c.subject in a.targets) {
      found.target = {joint: c.subject, value: a.targets[c.subject]};
    }
    if (c.operation === 'push' && a.joint) found.push = {joint: a.joint, sign: Math.sign(a.effort || 0), label: c.attempt};
    if (c.box) {
      const m = poseAt(rowOf(c, k), 1 + 7 * bodies.length);
      found.box = {size: c.box, m};
      if (typeof a.close_seconds === 'number' && time >= a.close_seconds && a.direction) {
        // The pull starts when the fingers have closed. Shaken, it is load x g x (1 + sin(2 pi f t)).
        const factor = a.shake ? 1 + Math.sin(2 * Math.PI * a.shake_hz * (time - a.close_seconds)) : 1;
        const label = a.shake ? `${number(a.mass)} kg shaken at ${number(a.shake_hz)} Hz` : `${number(a.mass)} kg × g`;
        found.pull = {at: [m[0][3], m[1][3], m[2][3]], direction: a.direction, factor, label};
      }
    }
    if (c.operation === 'drive' && root >= 0) {
      const floor = typeof inspect.floor === 'number' ? inspect.floor : null;
      found.path = Array.from({length: k + 1}, (_, n) => {
        const row = rowOf(c, n), at = 1 + 7 * root;
        return [row[at], row[at + 1], floor === null ? row[at + 2] : floor];
      });
    }
    if (k === c.finite) found.lines.push(...results(c));  // the last frame the view shows
    if (c.finite < c.frames - 1 && k >= c.finite) {
      found.warn = `The engine gave values that are not finite from ${seconds2(c.times[c.finite + 1])}: the view stops at the last finite frame.`;
    }
    return found;
  }

  function render() {
    if (!clip) return;
    if (clip.finite < 0) {
      viewer.show(null, {lines: [title(clip)], warn: 'The engine gave values that are not finite from the first frame: there is nothing to show.'});
    } else {
      const k = frameAt(clip, t);
      viewer.show(posesOf(clip, k), marksAt(clip, k, t));
    }
    bar.value = String(t);
    timeText.textContent = `${seconds2(t)} / ${seconds2(end(clip))}`;
  }

  function load(index, start) {
    clip = clips[index];
    t = 0;
    bar.max = String(end(clip) || 0.001);
    // The view holds every frame of the clip, so a robot that drives away stays in it. 120 frames are enough.
    const sampled = [];
    const every = Math.max(1, Math.floor((clip.finite + 1) / 120));
    for (let k = 0; k <= clip.finite; k += every) sampled.push(posesOf(clip, k));
    if (clip.finite >= 0) sampled.push(posesOf(clip, clip.finite));
    viewer.fit(sampled);
    const joint = jointNames.has(clip.subject) ? clip.subject
      : clip.operation === 'push' && clip.arguments ? clip.arguments.joint
        : wanted && jointNames.has(wanted.subject) ? wanted.subject : null;
    if (joint) options.select(joint);
    clipTitle.textContent = title(clip);
    clipTitle.prepend(sign(clip.ok === null ? null : clip.ok ? 'PASS' : 'FAIL'), ' ');
    drawList();
    render();
    if (start) play(); else pause();
  }

  function tick(now) {
    raf = null;
    if (!options.alive()) return stop();
    if (!playing) return;
    t += last === null ? 0 : ((now - last) / 1000) * speed;
    last = now;
    if (t >= end(clip)) {
      if (loop) t = 0;
      else { t = end(clip); playing = false; }
    }
    render();
    updateButton();
    if (playing) raf = requestAnimationFrame(tick);
  }
  function play() {
    if (!clip || end(clip) <= 0) return;
    if (t >= end(clip)) t = 0;
    playing = true;
    last = null;
    raf = raf || requestAnimationFrame(tick);
    updateButton();
  }
  function pause() { playing = false; updateButton(); }
  function toggle() { if (playing) pause(); else play(); }
  function step(by) {
    pause();
    if (!clip || clip.finite < 0) return;
    t = clip.times[Math.min(Math.max(frameAt(clip, t) + by, 0), clip.finite)];
    render();
  }
  function stop() {
    playing = false;
    if (raf) cancelAnimationFrame(raf);
    document.removeEventListener('keydown', onKey);
  }
  function updateButton() {
    playButton.textContent = playing ? '❚❚ Pause' : '▶ Play';
    playButton.setAttribute('aria-label', playing ? 'Pause' : 'Play');
  }
  const shift = by => { if (clip) load(Math.min(Math.max(clip.index + by, 0), clips.length - 1), playing); };

  // Space plays and pauses, the arrows step one frame, unless a control has the focus.
  function onKey(e) {
    if (!options.alive()) return stop();
    if (e.altKey || e.ctrlKey || e.metaKey || ['INPUT', 'SELECT', 'TEXTAREA', 'BUTTON', 'A'].includes(e.target.tagName)) return;
    if (e.key === ' ') { e.preventDefault(); toggle(); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
  }
  document.addEventListener('keydown', onKey);

  const playButton = h('button', {type: 'button', class: 'primary', onclick: toggle}, '▶ Play');
  const bar = h('input', {type: 'range', min: 0, max: 1, step: 'any', value: 0, 'aria-label': 'Time in the clip',
    oninput: e => { pause(); t = Number(e.target.value); render(); }});
  const timeText = h('span', {class: 'time mono'});
  const speedBox = h('select', {'aria-label': 'Speed', onchange: e => { speed = Number(e.target.value); }},
    SPEEDS.map(s => h('option', {value: s, selected: s === 1}, `${s}×`)));
  const loopBox = h('input', {type: 'checkbox', onchange: e => { loop = e.target.checked; }});
  const clipTitle = h('p', {class: 'clip-title'});
  const list = h('div', {class: 'scroll clips'});
  const filters = h('span', {class: 'seg', role: 'group', 'aria-label': 'Show the clips'});

  function drawList() {
    const shown = {
      all: clips,
      failed: clips.filter(c => c.ok === false),
      measurement: ofMeasurement,
    };
    fill(filters, [
      ['all', `All (${clips.length})`],
      ['failed', `Not ok (${shown.failed.length})`],
      ...(wanted ? [['measurement', `This measurement (${ofMeasurement.length})`]] : []),
    ].map(([name, label]) => h('a', {href: '#', class: name === filter ? 'on' : null,
      onclick: e => { e.preventDefault(); filter = name; drawList(); }}, label)));
    const rows = [];
    let group = null;
    for (const c of shown[filter]) {
      if (c.check !== group) {
        group = c.check;
        rows.push(h('tr', {class: 'group'}, h('td', {colspan: 5, class: 'mono'}, group)));
      }
      const row = h('tr', {class: c === clip ? 'picked' : null, onclick: () => load(c.index, true),
        title: `${c.operation}: play this clip`},
        h('td', {class: 'c'}, sign(c.ok === null ? null : c.ok ? 'PASS' : 'FAIL')),
        h('td', {class: 'mono'}, c.subject || h('span', {class: 'muted'}, 'the asset')),
        h('td', {}, c.case), h('td', {}, c.attempt),
        h('td', {class: 'num'}, seconds2(c.times[c.frames - 1] || 0)));
      rows.push(row);
    }
    fill(list, rows.length ? h('table', {}, h('tbody', {}, rows))
      : h('p', {class: 'empty'}, filter === 'failed' ? 'Every clip is ok.' : 'No clip.'));
  }

  const notes = [];
  if (header.engine === 'newton') notes.push(banner(NEWTON_NOTE, true));
  if (header.sha256 && inspect.sha256 && header.sha256 !== inspect.sha256) {
    notes.push(banner('The asset file changed after this run: its SHA-256 is not the one in the results. '
      + 'The colliders drawn can differ from those the engine moved.'));
  }
  if (missing.length) {
    notes.push(banner(`${missing.length} bodies of the replay are not in the asset now, so the view does not draw them: `
      + `${missing.slice(0, 5).join(', ')}${missing.length > 5 ? ', …' : ''}.`));
  }
  if (wanted && !ofMeasurement.length) {
    notes.push(banner(`The replay has no clip of ${[wanted.check, wanted.subject, wanted.case].filter(Boolean).join(' · ')}.`, true));
  }

  const section = h('section', {class: 'player', 'aria-label': 'Replay of the checks'},
    h('h2', {}, 'Replay', h('span', {class: 'muted'},
      `${clips.length} clip${clips.length === 1 ? '' : 's'} of the run, as the engine moved the bodies`)),
    notes,
    clipTitle,
    h('div', {class: 'toolbar player-bar'},
      h('button', {type: 'button', title: 'The previous clip', 'aria-label': 'Previous clip', onclick: () => shift(-1)}, '⏮'),
      h('button', {type: 'button', title: 'One frame back (←)', 'aria-label': 'One frame back', onclick: () => step(-1)}, '◂'),
      playButton,
      h('button', {type: 'button', title: 'One frame forward (→)', 'aria-label': 'One frame forward', onclick: () => step(1)}, '▸'),
      h('button', {type: 'button', title: 'The next clip', 'aria-label': 'Next clip', onclick: () => shift(1)}, '⏭'),
      bar, timeText,
      h('label', {}, 'Speed', speedBox),
      h('label', {}, loopBox, 'Loop')),
    h('p', {class: 'sub'}, 'Space plays and pauses, ← and → step one frame. 1× is the speed of the simulation. '
      + 'Green: the target of a drive. Amber: a push or a pull. The text in the view gives the measurement at the last frame.'),
    h('div', {class: 'toolbar'}, filters),
    list);

  if (clips.length) {
    const first = ofMeasurement[0] || clips.find(c => c.ok === false) || clips[0];
    load(first.index, Boolean(ofMeasurement.length));
  } else {
    fill(list, h('p', {class: 'empty'}, 'The replay has no clips: the run stopped before its first engine operation.'));
  }
  return section;
}
