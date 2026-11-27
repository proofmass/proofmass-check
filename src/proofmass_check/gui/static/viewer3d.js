// SPDX-FileCopyrightText: 2026 Paweł Kikta
// SPDX-License-Identifier: Apache-2.0
'use strict';
/* A 3D view of an asset as the engine collides it: its colliders, joints and gripper sites, in the
   file pose (docs/gui.md, section 6.6). It takes the output of `proofmass-check inspect --geometry`.
   A replay moves each body to the pose of a frame, with show() (section 6.11).

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
  const rotate = (m, v) => [0, 1, 2].map(i => m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2]);
  // Rigid transforms as rows [r0 r1 r2 t]: the product of two, and the inverse of one.
  const times = (a, b) => [0, 1, 2].map(i => [0, 1, 2, 3].map(k =>
    a[i][0] * b[0][k] + a[i][1] * b[1][k] + a[i][2] * b[2][k] + (k === 3 ? a[i][3] : 0)));
  const inverse = m => {
    const r = [0, 1, 2].map(i => [m[0][i], m[1][i], m[2][i]]);
    const t = [m[0][3], m[1][3], m[2][3]];
    return r.map(row => [...row, -dot(row, t)]);
  };
  // v turned by angle (rad) about the unit axis k, by the right-hand rule, as a joint turns (Rodrigues).
  const turn = (v, k, angle) => add(add(scale(v, Math.cos(angle)), scale(cross(k, v), Math.sin(angle))),
    scale(k, dot(k, v) * (1 - Math.cos(angle))));

  // The triangles of every collider, in the frame of the body they belong to. Each collider is
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
  // A collider written as a full render mesh (a convexHull approximation over a million points) is too much
  // for this view: past MAX_TRIANGLES the hulls are left out, and the view says so.
  const MAX_TRIANGLES = 100000;
  const hullTriangles = data.bodies.reduce((n, b) => n + (b.hulls || []).reduce((m, h) => m + h.triangles.length, 0), 0);
  const drawHulls = hullTriangles <= MAX_TRIANGLES;
  for (const body of drawHulls ? data.bodies : []) {
    for (const hull of body.hulls || []) {
      const points = hull.points;
      const centre = scale(points.reduce(add, [0, 0, 0]), 1 / Math.max(points.length, 1));
      for (const [i, j, k] of hull.triangles) outward([points[i], points[j], points[k]], centre, body.path);
    }
    for (const c of body.cylinders || []) {
      // A prism of 16 sides along the cylinder's axis.
      const axis = unit(c.axis);
      const u = unit(Math.abs(axis[2]) < 0.9 ? cross(axis, [0, 0, 1]) : cross(axis, [1, 0, 0]));
      const v = cross(axis, u);
      const ring = (h) => Array.from({length: 16}, (_, i) => {
        const a = (i / 16) * 2 * Math.PI;
        return add(add(c.centre, scale(axis, h)), add(scale(u, c.radius * Math.cos(a)), scale(v, c.radius * Math.sin(a))));
      });
      const low = ring(-c.height / 2);
      const high = ring(c.height / 2);
      const ends = [add(c.centre, scale(axis, -c.height / 2)), add(c.centre, scale(axis, c.height / 2))];
      for (let i = 0; i < 16; i++) {
        const j = (i + 1) % 16;
        for (const p of [[low[i], low[j], high[j]], [low[i], high[j], high[i]], [ends[0], low[j], low[i]], [ends[1], high[i], high[j]]]) {
          outward(p, c.centre, body.path);
        }
      }
    }
  }
  for (const body of data.bodies) {
    for (const s of body.spheres || []) {
      // A sphere of 8 bands and 12 sectors.
      const at = (lat, lon) => add(s.centre, scale([Math.cos(lat) * Math.cos(lon), Math.cos(lat) * Math.sin(lon), Math.sin(lat)], s.radius));
      for (let i = 0; i < 8; i++) {
        const a0 = -Math.PI / 2 + (i / 8) * Math.PI, a1 = -Math.PI / 2 + ((i + 1) / 8) * Math.PI;
        for (let k = 0; k < 12; k++) {
          const b0 = (k / 12) * 2 * Math.PI, b1 = ((k + 1) / 12) * 2 * Math.PI;
          for (const p of [[at(a0, b0), at(a0, b1), at(a1, b1)], [at(a0, b0), at(a1, b1), at(a1, b0)]]) {
            outward(p, s.centre, body.path);
          }
        }
      }
    }
  }
  const joints = data.joints.filter(j => j.pivot && j.direction && j.kind !== 'fixed');
  // Each body's colliders as the 8 corners of their box in the body's frame, for fit().
  const boxes = new Map();
  for (const t of triangles) {
    const [low, high] = boxes.get(t.body) || [[Infinity, Infinity, Infinity], [-Infinity, -Infinity, -Infinity]];
    for (const p of t.p) for (let i = 0; i < 3; i++) { low[i] = Math.min(low[i], p[i]); high[i] = Math.max(high[i], p[i]); }
    boxes.set(t.body, [low, high]);
  }
  const corners = new Map([...boxes].map(([body, [low, high]]) =>
    [body, Array.from({length: 8}, (_, n) => [0, 1, 2].map(i => (n & (1 << i) ? high[i] : low[i])))]));

  // Where each body is: in the file pose, or at the frame of a replay (show()). The triangles in the
  // world are made again only when the poses change, not for every turn of the camera.
  const filePose = new Map(data.bodies.map(b => [b.path, b.pose]));
  const fileInverse = new Map(data.bodies.map(b => [b.path, inverse(b.pose)]));
  let poses = null;  // Map: body path → pose, during a replay
  let overlay = null;  // what a clip of a replay adds (show())
  let world = null;
  const poseOf = path => (poses && poses.get(path)) || filePose.get(path);
  const placed = () => {
    world = world || triangles.map(t => { const m = poseOf(t.body); return {p: t.p.map(q => apply(m, q)), n: rotate(m, t.n), body: t.body}; });
    return world;
  };
  // How a body moved from its file pose, for the marks that move with it: a joint with its first
  // body (body0), a gripper site with its body. null when it did not move.
  const moved = path => (poses && path && poses.has(path) && fileInverse.has(path) ? times(poses.get(path), fileInverse.get(path)) : null);
  const placeJoint = j => {
    const m = moved(j.body0);
    return m ? {...j, pivot: apply(m, j.pivot), direction: rotate(m, j.direction), carried_centre: j.carried_centre && apply(m, j.carried_centre)} : j;
  };
  const placeSite = s => {
    const m = moved(s.body);
    if (!m) return s;
    const box = s.grip_box && {...s.grip_box, centre: apply(m, s.grip_box.centre),
      rotation: [0, 1, 2].map(i => [0, 1, 2].map(k => m[i][0] * s.grip_box.rotation[0][k] + m[i][1] * s.grip_box.rotation[1][k] + m[i][2] * s.grip_box.rotation[2][k]))};
    return {...s, centre: apply(m, s.centre), closing: rotate(m, s.closing), grip_box: box};
  };

  // The asset's size, for the length of the marks, from the file pose. The camera and the floor grid
  // hold `view`, which a replay can widen to hold all of a clip (fit()).
  const points = placed().flatMap(t => t.p).concat(joints.map(j => j.pivot));
  // A loop, not Math.min(...points): a spread of many points overflows the call stack.
  const bounds = found => [0, 1, 2].map(i => [found.reduce((m, p) => Math.min(m, p[i]), Infinity), found.reduce((m, p) => Math.max(m, p[i]), -Infinity)]);
  const fileBounds = bounds(points);
  const low = fileBounds.map(([min]) => min);
  const high = fileBounds.map(([, max]) => max);
  const centre = scale(add(low, high), 0.5);
  const size = Math.max(Math.hypot(...sub(high, low)), 0.05);
  let view = {centre, span: size};
  let home = {yaw: -0.9, pitch: 0.45, distance: size * 1.7, target: centre};
  let camera = {...home};
  let selected = null;
  let frame = null;
  let shown = [];  // where each joint's pivot is on the canvas, for a click

  const palette = () => ({
    part: color('--part'), fg: color('--fg'), dim: color('--dim'), grid: color('--grid'), accent: color('--accent'),
    bad: color('--bad'), warn: color('--warn'), ok: color('--ok'), x: color('--ax-x'), y: color('--ax-y'), z: color('--ax-z'),
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
    const font = '12px "IBM Plex Mono", ui-monospace, Consolas, monospace';
    let textLine = 20;  // the next line of text in the top left corner
    const say = (words, rgb) => {
      ctx.fillStyle = css(rgb);
      ctx.font = font;
      ctx.fillText(words, 12, textLine);
      textLine += 17;
    };
    if (!drawHulls) {
      say(`The hull colliders have ${hullTriangles.toLocaleString('en')} triangles, too many to draw here: `
        + 'only spheres, cylinders and joints are drawn.', colours.dim);
    }
    const b = basis();
    const focal = height / (2 * Math.tan((40 * Math.PI) / 360));
    const near = size * 0.01;
    const toView = p => { const d = sub(p, b.eye); return [dot(d, b.right), dot(d, b.up), dot(d, b.forward)]; };
    const toScreen = v => [width / 2 + (v[0] * focal) / v[2], height / 2 - (v[1] * focal) / v[2]];
    const polyline = (points, rgb, widthPx, dash = []) => {
      const v = points.map(toView);
      if (v.some(p => p[2] < near)) return;
      ctx.strokeStyle = css(rgb);
      ctx.lineWidth = widthPx;
      ctx.setLineDash(dash);
      ctx.beginPath();
      v.map(toScreen).forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
      ctx.stroke();
      ctx.setLineDash([]);
    };
    const line = (from, to, rgb, widthPx, dash = []) => polyline([from, to], rgb, widthPx, dash);
    const text = (at, words, rgb) => {
      const v = toView(at);
      if (v[2] < near) return;
      const [x, y] = toScreen(v);
      ctx.fillStyle = css(rgb);
      ctx.font = font;
      ctx.fillText(words, x + 6, y - 6);
    };
    // An arrow from `from` to `to`, its head across the line of sight.
    const arrow = (from, to, rgb, label) => {
      const d = sub(to, from);
      const length = Math.hypot(...d);
      if (!(length > 1e-9)) return;
      const along = scale(d, 1 / length);
      let side = cross(along, b.forward);
      side = unit(Math.hypot(...side) < 1e-6 ? b.up : side);
      const back = sub(to, scale(along, length * 0.22));
      line(from, to, rgb, 2.5);
      line(to, add(back, scale(side, length * 0.11)), rgb, 2.5);
      line(to, sub(back, scale(side, length * 0.11)), rgb, 2.5);
      if (label) text(to, label, rgb);
    };

    // The floor, as a grid at the run's floor height, under what the camera holds.
    if (typeof data.floor === 'number') {
      const step = Math.pow(10, Math.floor(Math.log10(view.span / 2)));
      const reach = Math.ceil((view.span * 0.9) / step) * step;
      const [cx, cy] = [Math.round(view.centre[0] / step) * step, Math.round(view.centre[1] / step) * step];
      for (let s = -reach; s <= reach + 1e-9; s += step) {
        line([cx - reach, cy + s, data.floor], [cx + reach, cy + s, data.floor], colours.grid, 1);
        line([cx + s, cy - reach, data.floor], [cx + s, cy + reach, data.floor], colours.grid, 1);
      }
    }

    // The colliders, and the grip box of a replay, far to near. A face is lit by how much it faces the camera.
    const shownJoints = joints.map(placeJoint);
    const chosen = selected ? shownJoints.find(j => j.name === selected) : null;
    const tinted = new Map();
    for (const j of data.joints) {
      if (marks[j.name] && j.body1) tinted.set(j.body1, marks[j.name] === 'fail' ? colours.bad : tinted.get(j.body1) || colours.warn);
    }
    if (chosen && chosen.body1) tinted.set(chosen.body1, colours.accent);
    const solids = placed().concat(overlay && overlay.box ? boxTriangles(overlay.box) : []);
    const faces = [];
    for (const t of solids) {
      const facing = dot(t.n, unit(sub(b.eye, t.p[0])));
      if (facing <= 0) continue;  // it faces away from the camera
      const v = t.p.map(toView);
      if (v.some(p => p[2] < near)) continue;
      faces.push({v, depth: (v[0][2] + v[1][2] + v[2][2]) / 3, light: 0.35 + 0.65 * facing, tint: t.box ? colours.accent : tinted.get(t.body)});
    }
    faces.sort((a, c) => c.depth - a.depth);
    for (const f of faces) {
      const rgb = (f.tint ? colours.part.map((c, i) => c * 0.45 + f.tint[i] * 0.55) : colours.part).map(c => c * f.light);
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
    for (const j of shownJoints) {
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
        ctx.font = font;
        ctx.fillText(j.name, x + 8, y - 8);
      }
    }
    for (const s of (data.sites || []).map(placeSite)) {
      line(sub(s.centre, scale(s.closing, s.opening / 2)), add(s.centre, scale(s.closing, s.opening / 2)), colours.accent, 2);
      if (s.grip_box && !(overlay && overlay.box)) gripBox(s.grip_box, colours.accent);
    }
    if (chosen && chosen.pivot && chosen.direction && chosen.kind !== 'fixed') range(chosen, colours);
    if (data.wheeled) front(colours.fg);
    if (overlay) marksOfClip(colours);

    // The range of the chosen joint, where the body it moves goes: an arc for a revolute joint,
    // around its axis through the centre of what it carries; a segment for a prismatic one. A
    // tick marks the file pose, where the joint is at its rest position. In a replay, the target
    // a drive gets is a tick too.
    function range(j, c) {
      if (j.lower === null || j.upper === null) {
        text(j.pivot, 'no limits', c.warn);
        return;
      }
      const rest = j.rest || 0;
      const target = overlay && overlay.target && overlay.target.joint === j.name ? overlay.target.value : null;
      if (j.kind === 'prismatic') {
        const at = value => add(j.pivot, scale(j.direction, value - rest));
        line(at(j.lower), at(j.upper), c.accent, 3);
        text(at(j.lower), `lower ${(j.lower * 1000).toFixed(1)} mm`, c.accent);
        text(at(j.upper), `upper ${(j.upper * 1000).toFixed(1)} mm`, c.accent);
        if (target !== null) {
          const across = scale(unit(cross(j.direction, b.forward)), size * 0.04);
          line(add(at(target), across), sub(at(target), across), c.ok, 3);
          text(at(target), `target ${(target * 1000).toFixed(1)} mm`, c.ok);
        }
        return;
      }
      let arm = j.carried_centre ? sub(j.carried_centre, j.pivot) : [0, 0, 0];
      arm = sub(arm, scale(j.direction, dot(arm, j.direction)));
      if (Math.hypot(...arm) < size * 0.02) {
        arm = cross(j.direction, Math.abs(j.direction[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0]);
      }
      arm = scale(unit(arm), Math.min(Math.max(Math.hypot(...arm), size * 0.06), size * 0.3));
      const at = angle => add(j.pivot, turn(arm, j.direction, angle - rest));
      const steps = Math.max(8, Math.ceil(Math.abs(j.upper - j.lower) / 0.1));
      const arc = Array.from({length: steps + 1}, (_, i) => at(j.lower + ((j.upper - j.lower) * i) / steps));
      polyline(arc, c.accent, 3);
      line(j.pivot, arc[0], c.accent, 1, [4, 3]);
      line(j.pivot, arc[arc.length - 1], c.accent, 1, [4, 3]);
      line(j.pivot, at(rest), c.fg, 2);
      const deg = a => `${((a * 180) / Math.PI).toFixed(1)} deg`;
      text(arc[0], `lower ${deg(j.lower)}`, c.accent);
      text(arc[arc.length - 1], `upper ${deg(j.upper)}`, c.accent);
      if (target !== null) {
        line(j.pivot, at(target), c.ok, 2.5, [6, 3]);
        text(at(target), `target ${deg(target)}`, c.ok);
      }
    }

    // The box GRIP closes the fingers on, as dashed edges.
    function gripBox(box, rgb) {
      const axes = [0, 1, 2].map(i => box.rotation.map(row => row[i] * box.size[i] / 2));
      const corner = n => [0, 1, 2].reduce((p, i) => add(p, scale(axes[i], n & (1 << i) ? 1 : -1)), box.centre);
      for (let n = 0; n < 8; n++) {
        for (let i = 0; i < 3; i++) {
          if (!(n & (1 << i))) line(corner(n), corner(n | (1 << i)), rgb, 1.5, [3, 3]);
        }
      }
    }

    // A wheeled robot's front: an arrow along +X from its driven axle, on the floor (docs/wheeled-robots.md).
    function front(rgb) {
      const z = typeof data.floor === 'number' ? data.floor : centre[2];
      const start = [data.wheeled.axle_centre[0], data.wheeled.axle_centre[1], z];
      const reach = Math.max(data.wheeled.track || 0, size * 0.25);
      const tip = add(start, [reach, 0, 0]);
      line(start, tip, rgb, 2.5);
      line(tip, add(tip, [-reach * 0.15, reach * 0.08, 0]), rgb, 2.5);
      line(tip, add(tip, [-reach * 0.15, -reach * 0.08, 0]), rgb, 2.5);
      text(tip, 'front +X', rgb);
    }

    // What a clip of a replay adds: the push on a joint, the pull on the grip box, the path a
    // wheeled robot drove, and its text in the top left corner.
    function marksOfClip(c) {
      const push = overlay.push && shownJoints.find(j => j.name === overlay.push.joint);
      if (push && overlay.push.sign) {
        if (push.kind === 'prismatic') {
          arrow(push.pivot, add(push.pivot, scale(push.direction, overlay.push.sign * size * 0.2)), c.warn, overlay.push.label);
        } else {
          // An arc about the axis, in the direction of the torque, with its head at the end.
          const radius = scale(unit(cross(push.direction, Math.abs(push.direction[2]) < 0.9 ? [0, 0, 1] : [1, 0, 0])), size * 0.1);
          const arc = Array.from({length: 13}, (_, i) => add(push.pivot, turn(radius, push.direction, overlay.push.sign * 1.6 * i / 12)));
          polyline(arc.slice(0, -1), c.warn, 2.5);
          arrow(arc[arc.length - 2], arc[arc.length - 1], c.warn, overlay.push.label);
        }
      }
      if (overlay.pull) {
        const reach = size * 0.2 * overlay.pull.factor;
        arrow(overlay.pull.at, add(overlay.pull.at, scale(unit(overlay.pull.direction), reach)), c.warn, overlay.pull.label);
      }
      if (overlay.path && overlay.path.length > 1) polyline(overlay.path, c.accent, 2);
      for (const words of overlay.lines || []) say(words, c.fg);
      if (overlay.warn) say(overlay.warn, c.bad);
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

  // The grip box of a replay as 12 triangles in the world: box = {size: [x, y, z], m: its pose}.
  function boxTriangles(box) {
    const corner = n => apply(box.m, [0, 1, 2].map(i => (n & (1 << i) ? 0.5 : -0.5) * box.size[i]));
    const middle = apply(box.m, [0, 0, 0]);
    const found = [];
    for (const [a, c, d, e] of [[0, 1, 3, 2], [4, 5, 7, 6], [0, 1, 5, 4], [2, 3, 7, 6], [0, 2, 6, 4], [1, 3, 7, 5]]) {
      for (const p of [[corner(a), corner(c), corner(d)], [corner(a), corner(d), corner(e)]]) {
        let n = unit(cross(sub(p[1], p[0]), sub(p[2], p[0])));
        if (dot(n, sub(p[0], middle)) < 0) n = scale(n, -1);
        found.push({p, n, box: true});
      }
    }
    return found;
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
    // A frame of a replay: newPoses maps a body path to its pose (rows [r0 r1 r2 t]), or null for the
    // file pose. clip: what the clip adds, as marksOfClip() and range() read it.
    show(newPoses, clip) {
      poses = newPoses;
      overlay = clip || null;
      world = null;
      redraw();
    },
    // The camera and the floor grid hold the asset in its file pose, and its colliders at each of these
    // poses too (Maps as show() takes them), such as the frames of a clip. The camera keeps its direction.
    fit(frames) {
      const found = points.slice();
      for (const posed of frames || []) {
        for (const [body, box] of corners) {
          const m = posed.get(body);
          if (!m) continue;
          for (const corner of box) {
            const p = apply(m, corner);
            if (p.every(Number.isFinite)) found.push(p);
          }
        }
      }
      const [x, y, z] = bounds(found);
      const middle = [(x[0] + x[1]) / 2, (y[0] + y[1]) / 2, (z[0] + z[1]) / 2];
      view = {centre: middle, span: Math.max(Math.hypot(x[1] - x[0], y[1] - y[0], z[1] - z[0]), size)};
      home = {...home, target: middle, distance: view.span * 1.7};
      camera = {...camera, target: middle, distance: view.span * 1.7};
      redraw();
    },
    counts: {triangles: triangles.length, joints: joints.length},
  };
}
