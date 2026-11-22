// SPDX-FileCopyrightText: 2026 Paweł Kikta
// SPDX-License-Identifier: Apache-2.0
'use strict';
/* A 3D view of an asset as the engine collides it: its colliders, joints and gripper sites, in the
   file pose (docs/gui.md, section 6.6). It takes the output of `proofmass-check inspect --geometry`.

   No library: the triangles are sorted from far to near and filled on a 2D canvas. That is enough
   for colliders, which are convex hulls of a few dozen faces. Z is up, as in the spec. */

function makeViewer(canvas, data, marks, onPick) {
  // marks: {joint name: 'fail' or 'close'}, from the measurements of a run. onPick(name) when a
  // click lands on a joint.
  const color = name => {
    const hex = getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888888';
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  };
  const css = ([r, g, b], a = 1) => `rgba(${r | 0},${g | 0},${b | 0},${a})`;
  const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
  const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
  const scale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
  const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
  const unit = a => { const l = Math.hypot(...a) || 1; return scale(a, 1 / l); };
  const apply = (m, p) => [0, 1, 2].map(i => m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3]);

  // The triangles of every collider, in the world, with the body they belong to. Each collider is
  // convex, so each triangle's normal is turned to point away from the collider's centre. A face
  // turned away from the camera is then left out, and the near faces of one collider never hide
  // behind its far ones, whatever order the file gives.
  const triangles = [];
  const outward = (p, centre, body) => {
    let n = cross(sub(p[1], p[0]), sub(p[2], p[0]));
    if (Math.hypot(...n) < 1e-12) return;  // a triangle of no area
    const middle = scale(add(add(p[0], p[1]), p[2]), 1 / 3);
    if (dot(n, sub(middle, centre)) < 0) n = scale(n, -1);
    triangles.push({p, n: unit(n), body});
  };
  for (const body of data.bodies) {
    for (const hull of body.hulls || []) {
      const points = hull.points.map(p => apply(body.pose, p));
      const centre = scale(points.reduce(add, [0, 0, 0]), 1 / Math.max(points.length, 1));
      for (const [i, j, k] of hull.triangles) outward([points[i], points[j], points[k]], centre, body.path);
    }
    for (const c of body.cylinders || []) {
      // A prism of 16 sides along the cylinder's axis, in the body's frame, then in the world.
      const axis = unit(c.axis);
      const u = unit(Math.abs(axis[2]) < 0.9 ? cross(axis, [0, 0, 1]) : cross(axis, [1, 0, 0]));
      const v = cross(axis, u);
      const ring = (h) => Array.from({length: 16}, (_, i) => {
        const a = (i / 16) * 2 * Math.PI;
        return apply(body.pose, add(add(c.centre, scale(axis, h)), add(scale(u, c.radius * Math.cos(a)), scale(v, c.radius * Math.sin(a)))));
      });
      const low = ring(-c.height / 2);
      const high = ring(c.height / 2);
      const ends = [apply(body.pose, add(c.centre, scale(axis, -c.height / 2))), apply(body.pose, add(c.centre, scale(axis, c.height / 2)))];
      const centre = apply(body.pose, c.centre);
      for (let i = 0; i < 16; i++) {
        const j = (i + 1) % 16;
        for (const p of [[low[i], low[j], high[j]], [low[i], high[j], high[i]], [ends[0], low[j], low[i]], [ends[1], high[i], high[j]]]) {
          outward(p, centre, body.path);
        }
      }
    }
  }
  const joints = data.joints.filter(j => j.pivot && j.direction && j.kind !== 'fixed');

  // The scene's size, for the camera and the length of the joint axes.
  const points = triangles.flatMap(t => t.p).concat(joints.map(j => j.pivot));
  const low = [0, 1, 2].map(i => Math.min(...points.map(p => p[i])));
  const high = [0, 1, 2].map(i => Math.max(...points.map(p => p[i])));
  const centre = scale(add(low, high), 0.5);
  const size = Math.max(Math.hypot(...sub(high, low)), 0.05);
  const home = {yaw: -0.9, pitch: 0.45, distance: size * 1.7, target: centre};
  let camera = {...home};
  let selected = null;
  let frame = null;
  let shown = [];  // where each joint's pivot is on the canvas, for a click

  const palette = () => ({
    part: color('--part'), fg: color('--fg'), dim: color('--dim'), grid: color('--grid'), accent: color('--accent'),
    bad: color('--bad'), warn: color('--warn'), x: color('--ax-x'), y: color('--ax-y'), z: color('--ax-z'),
  });

  function basis() {
    const c = Math.cos(camera.pitch);
    const eye = add(camera.target, scale([c * Math.cos(camera.yaw), c * Math.sin(camera.yaw), Math.sin(camera.pitch)], camera.distance));
    const forward = unit(sub(camera.target, eye));
    const right = unit(cross(forward, [0, 0, 1]));
    return {eye, forward, right, up: cross(right, forward)};
  }

  function draw() {
    frame = null;
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const colours = palette();
    const b = basis();
    const focal = height / (2 * Math.tan((40 * Math.PI) / 360));
    const near = size * 0.01;
    const toView = p => { const d = sub(p, b.eye); return [dot(d, b.right), dot(d, b.up), dot(d, b.forward)]; };
    const toScreen = v => [width / 2 + (v[0] * focal) / v[2], height / 2 - (v[1] * focal) / v[2]];
    const line = (from, to, rgb, widthPx) => {
      const a = toView(from);
      const c = toView(to);
      if (a[2] < near || c[2] < near) return;
      const [x1, y1] = toScreen(a);
      const [x2, y2] = toScreen(c);
      ctx.strokeStyle = css(rgb);
      ctx.lineWidth = widthPx;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    };

    // The floor, as a grid at the run's floor height.
    if (typeof data.floor === 'number') {
      const step = Math.pow(10, Math.floor(Math.log10(size / 2)));
      const reach = Math.ceil((size * 0.9) / step) * step;
      for (let s = -reach; s <= reach + 1e-9; s += step) {
        line([centre[0] - reach, centre[1] + s, data.floor], [centre[0] + reach, centre[1] + s, data.floor], colours.grid, 1);
        line([centre[0] + s, centre[1] - reach, data.floor], [centre[0] + s, centre[1] + reach, data.floor], colours.grid, 1);
      }
    }

    // The colliders, far to near. A face is lit by how much it faces the camera.
    const chosen = selected ? data.joints.find(j => j.name === selected) : null;
    const tinted = new Map();
    for (const j of data.joints) {
      if (marks[j.name] && j.body1) tinted.set(j.body1, marks[j.name] === 'fail' ? colours.bad : tinted.get(j.body1) || colours.warn);
    }
    if (chosen && chosen.body1) tinted.set(chosen.body1, colours.accent);
    const faces = [];
    for (const t of triangles) {
      const facing = dot(t.n, unit(sub(b.eye, t.p[0])));
      if (facing <= 0) continue;  // it faces away from the camera
      const v = t.p.map(toView);
      if (v.some(p => p[2] < near)) continue;
      faces.push({v, depth: (v[0][2] + v[1][2] + v[2][2]) / 3, light: 0.35 + 0.65 * facing, body: t.body});
    }
    faces.sort((a, c) => c.depth - a.depth);
    for (const f of faces) {
      const base = tinted.get(f.body);
      const rgb = (base ? colours.part.map((c, i) => c * 0.45 + base[i] * 0.55) : colours.part).map(c => c * f.light);
      const [a, c, d] = f.v.map(toScreen);
      ctx.fillStyle = css(rgb);
      ctx.strokeStyle = css(rgb);
      ctx.lineWidth = 0.6;
      ctx.beginPath();
      ctx.moveTo(a[0], a[1]);
      ctx.lineTo(c[0], c[1]);
      ctx.lineTo(d[0], d[1]);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }

    // The joints: an axis through each pivot. A gripper site: its grasp centre and closing axis.
    shown = [];
    const length = size * 0.12;
    for (const j of joints) {
      const mark = marks[j.name];
      const isChosen = j.name === selected;
      const rgb = isChosen ? colours.accent : mark === 'fail' ? colours.bad : mark === 'close' ? colours.warn : colours.fg;
      line(sub(j.pivot, scale(j.direction, length)), add(j.pivot, scale(j.direction, length)), rgb, isChosen ? 3 : mark ? 2.5 : 1.5);
      const v = toView(j.pivot);
      if (v[2] < near) continue;
      const [x, y] = toScreen(v);
      shown.push({name: j.name, x, y});
      ctx.fillStyle = css(rgb);
      ctx.beginPath();
      ctx.arc(x, y, isChosen ? 5 : 3.5, 0, 2 * Math.PI);
      ctx.fill();
      if (isChosen || mark === 'fail') {
        ctx.font = '12px "IBM Plex Mono", ui-monospace, Consolas, monospace';
        ctx.fillText(j.name, x + 8, y - 8);
      }
    }
    for (const s of data.sites || []) {
      line(sub(s.centre, scale(s.closing, s.opening / 2)), add(s.centre, scale(s.closing, s.opening / 2)), colours.accent, 2);
    }

    // The world axes, in the corner: X red, Y green, Z blue.
    const corner = [42, height - 42];
    for (const [axis, rgb, label] of [[[1, 0, 0], colours.x, 'X'], [[0, 1, 0], colours.y, 'Y'], [[0, 0, 1], colours.z, 'Z']]) {
      const end = [corner[0] + dot(axis, b.right) * 26, corner[1] - dot(axis, b.up) * 26];
      ctx.strokeStyle = css(rgb);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(corner[0], corner[1]);
      ctx.lineTo(end[0], end[1]);
      ctx.stroke();
      ctx.fillStyle = css(rgb);
      ctx.font = '11px "IBM Plex Mono", ui-monospace, Consolas, monospace';
      ctx.fillText(label, end[0] + 3, end[1] + 3);
    }
  }

  const redraw = () => { if (!frame) frame = requestAnimationFrame(draw); };

  // Drag to turn, Shift+drag or the right button to move, the wheel to zoom, double-click to reset.
  let drag = null;
  canvas.addEventListener('pointerdown', e => {
    drag = {x: e.clientX, y: e.clientY, moved: false, pan: e.shiftKey || e.button === 2};
    canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener('pointermove', e => {
    if (!drag) return;
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
    drag.x = e.clientX;
    drag.y = e.clientY;
    if (drag.pan) {
      const b = basis();
      const step = camera.distance * 0.0015;
      camera.target = add(camera.target, add(scale(b.right, -dx * step), scale(b.up, dy * step)));
    } else {
      camera.yaw -= dx * 0.01;
      camera.pitch = Math.max(-1.5, Math.min(1.5, camera.pitch + dy * 0.01));
    }
    redraw();
  });
  canvas.addEventListener('pointerup', e => {
    if (drag && !drag.moved && onPick) {
      const rect = canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const near = shown.map(s => ({...s, d: Math.hypot(s.x - x, s.y - y)})).sort((a, b) => a.d - b.d)[0];
      if (near && near.d < 14) onPick(near.name);
    }
    drag = null;
  });
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    camera.distance *= Math.exp(e.deltaY * 0.001);
    redraw();
  }, {passive: false});
  canvas.addEventListener('contextmenu', e => e.preventDefault());
  canvas.addEventListener('dblclick', () => { camera = {...home}; redraw(); });
  new ResizeObserver(redraw).observe(canvas);
  draw();

  return {
    select(name) { selected = name; redraw(); },
    counts: {triangles: triangles.length, joints: joints.length},
  };
}
