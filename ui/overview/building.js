import * as THREE from '../vendor/three/three.module.min.js';
import { RoundedBoxGeometry } from '../vendor/three/RoundedBoxGeometry.js';
import { mergeGeometries } from '../vendor/three/BufferGeometryUtils.js';

// One storey holds six desks. "campus" gives each computer its own building; "tower" stacks every
// computer's storeys into one tower. Selecting a storey shows it from above with name tags.
export function createBuilding(data, preferences = {}, openMember = () => {}) {
const controller = new AbortController();
const on = (target, type, fn, options = {}) => target.addEventListener(type, fn, {...options, signal: controller.signal});
const resources = new Set(), mats = new Map(), geos = new Map();
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const reduced = matchMedia('(prefers-reduced-motion: reduce)');
const small = () => innerWidth < 560, portrait = () => innerWidth / innerHeight < .8;
const TOWER = preferences.layout === 'tower', PER_FLOOR = 6, H = 3.5;
const palettes = [
  {color:0x79c9b3,rug:0x8fb39b,wall:0xe2eee2}, {color:0xf0c786,rug:0xc2b088,wall:0xf3ead4},
  {color:0xaca5d3,rug:0xa79ec2,wall:0xe9e5f1}, {color:0x8fbcd8,rug:0x95b4c3,wall:0xdeecef}
];
const hash = s => { let h = 2166136261; for (const c of String(s)) { h ^= c.codePointAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };

// ---------------------------------------------------------------- layout: storeys, then buildings
const FLOORS = [], BUILDINGS = [];
data.groups.forEach((group, gi) => {
  const parts = Math.max(1, Math.ceil(group.members.length / PER_FLOOR));
  for (let part = 0; part < parts; part++) FLOORS.push({id: FLOORS.length, group, gi, part, parts, key: group.key + ':' + part,
    members: group.members.slice(part * PER_FLOOR, (part + 1) * PER_FLOOR), ...palettes[gi % 4]});
});
if (TOWER) BUILDINGS.push({id: 0, x: 0, z: 0, floors: FLOORS, name: data.company, ...palettes[0]});
else {
  const n = data.groups.length, columns = small() ? Math.min(2, Math.ceil(Math.sqrt(n / 2))) : Math.min(3, Math.ceil(Math.sqrt(n))), rows = Math.ceil(n / columns);
  data.groups.forEach((group, gi) => BUILDINGS.push({id: gi, group, name: group.name, ...palettes[gi % 4],
    x: ((gi % columns) - (columns - 1) / 2) * 18, z: (Math.floor(gi / columns) - (rows - 1) / 2) * 17,
    floors: FLOORS.filter(f => f.gi === gi)}));
}
for (const b of BUILDINGS) b.floors.forEach((f, level) => Object.assign(f, {building: b, level}));
const xs = BUILDINGS.map(b => b.x), zs = BUILDINGS.map(b => b.z);
const campusWidth = Math.max(...xs) - Math.min(...xs) + (TOWER ? 20 : 18), campusDepth = Math.max(...zs) - Math.min(...zs) + (TOWER ? 16 : 17);
const maxHeight = Math.max(...BUILDINGS.map(b => b.floors.length)) * H + 3;
const state = {floor: null, t: 0, hover: null, selected: null, zoom: 1, yaw: .36, pitch: .42, drag: false};

// ---------------------------------------------------------------- renderer
const renderer = new THREE.WebGLRenderer({antialias: true, alpha: true, powerPreference: 'high-performance'});
renderer.setPixelRatio(Math.min(devicePixelRatio, small() ? 2 : 1.75)); renderer.setSize(innerWidth, innerHeight);
renderer.setClearColor(0x000000, 0);
renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFShadowMap;
renderer.shadowMap.autoUpdate = false; renderer.shadowMap.needsUpdate = true;
renderer.outputColorSpace = THREE.SRGBColorSpace; renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.toneMappingExposure = 1.3;
$('#world').replaceChildren(renderer.domElement);
renderer.domElement.setAttribute('aria-label', TOWER ? 'One tower with a storey for each computer.' : 'Campus. Each computer is a building with its bots and human collaborators.');
renderer.domElement.setAttribute('role', 'img'); renderer.domElement.setAttribute('aria-describedby', 'scene-instructions');
const scene = new THREE.Scene();
const camera = new THREE.OrthographicCamera(-20, 20, 15, -15, .1, 1000);
let currentTarget = new THREE.Vector3(0, 3, 0), currentPosition = new THREE.Vector3(22, 28, 55), currentScale = 40;
scene.add(new THREE.HemisphereLight(0xd2ecef, 0x6b8f7c, 1.9));
const sun = new THREE.DirectionalLight(0xffe7bd, 2.5); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
sun.shadow.normalBias = .04; sun.shadow.bias = -.0002; sun.shadow.radius = 4; scene.add(sun, sun.target);
const fill = new THREE.DirectionalLight(0x9cc0f0, 1.1); fill.position.set(14, 18, -14); scene.add(fill);
// The sun's shadow camera hugs whatever is on screen, so a single storey gets crisp shadows.
function aimSun(cx, cy, cz, size) {
  sun.target.position.set(cx, cy, cz); sun.position.set(cx - 20, cy + 40, cz + 30);
  Object.assign(sun.shadow.camera, {left: -size, right: size, top: size, bottom: -size, near: .1, far: 160});
  sun.shadow.camera.updateProjectionMatrix(); renderer.shadowMap.needsUpdate = true;
}
const world = new THREE.Group(), landscape = new THREE.Group(), tunnels = new THREE.Group(); scene.add(world); world.add(landscape, tunnels);
const characters = [], buildingGroups = [], hitMeshes = [], pods = [];

// ---------------------------------------------------------------- primitives
function material(color, opts = {}) { const key = String(color) + JSON.stringify(opts); if (!mats.has(key)) mats.set(key, new THREE.MeshStandardMaterial({color, roughness: .72, metalness: 0, ...opts})); return mats.get(key); }
function track(m) { resources.add(m.geometry); resources.add(m.material); if (m.material.map) resources.add(m.material.map); return m; }
function mesh(g, geo, mat, x, y, z, shadow = true) { const m = new THREE.Mesh(geo, typeof mat === 'number' || typeof mat === 'string' ? material(mat) : mat); m.position.set(x, y, z); m.castShadow = shadow; m.receiveShadow = true; g.add(m); return track(m); }
function box(g, x, y, z, w, h, d, c, r = .04) { const key = `b:${w}:${h}:${d}:${r}`; if (!geos.has(key)) geos.set(key, r ? new RoundedBoxGeometry(w, h, d, 2, Math.min(r, w / 3, h / 3, d / 3)) : new THREE.BoxGeometry(w, h, d)); return mesh(g, geos.get(key), c, x, y, z); }
function ball(g, x, y, z, r, c, scale, detail = 1) { const key = 'ball' + detail; if (!geos.has(key)) geos.set(key, detail ? new THREE.SphereGeometry(1, 18, 14) : new THREE.SphereGeometry(1, 10, 8)); const m = mesh(g, geos.get(key), c, x, y, z); m.scale.set(r * (scale?.[0] || 1), r * (scale?.[1] || 1), r * (scale?.[2] || 1)); return m; }
function cyl(g, x, y, z, rt, rb, h, c, sides = 16) { const key = `c:${rt}:${rb}:${h}:${sides}`; if (!geos.has(key)) geos.set(key, new THREE.CylinderGeometry(rt, rb, h, sides)); return mesh(g, geos.get(key), c, x, y, z); }
function rod(g, a, b, r, c) { const aa = new THREE.Vector3(...a), bb = new THREE.Vector3(...b), v = bb.clone().sub(aa); const m = cyl(g, ...aa.clone().add(bb).multiplyScalar(.5).toArray(), r, r, v.length(), c, 6); m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), v.normalize()); return m; }
function glowing(c, intensity = .5) { return material(c, {emissive: c, emissiveIntensity: intensity}); }
function basic(color, opts = {}) { const key = 'basic' + String(color) + JSON.stringify(opts); if (!mats.has(key)) mats.set(key, new THREE.MeshBasicMaterial({color, toneMapped: false, ...opts})); return mats.get(key); }
const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
function sign(g, label, x, y, z, w, h, fg, bg = null, weight = 600) {
  const cw = 1024, ch = Math.max(48, Math.round(cw * h / w)), cv = document.createElement('canvas'); cv.width = cw; cv.height = ch;
  const ctx = cv.getContext('2d'); if (bg) { ctx.fillStyle = bg; ctx.fillRect(0, 0, cw, ch); }
  let font = Math.round(ch * .7); ctx.font = `${weight} ${font}px ${FONT}`;
  while (ctx.measureText(label).width > cw - 40 && font > 10) ctx.font = `${weight} ${--font}px ${FONT}`;
  ctx.fillStyle = fg; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.fillText(label, cw / 2, ch / 2);
  const tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  return mesh(g, new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({map: tex, transparent: true, depthWrite: false}), x, y, z, false);
}
function plant(g, x, y, z, size = 1, pot = 0xd7a788) { const p = new THREE.Group(); p.position.set(x, y, z); p.scale.setScalar(size); g.add(p); cyl(p, 0, .22, 0, .25, .2, .44, pot); cyl(p, 0, .45, 0, .2, .2, .03, 0x675c48); for (let i = 0; i < 6; i++) { const t = i * 2.4, yy = .62 + (i % 3) * .2; const l = ball(p, Math.cos(t) * .17, yy, Math.sin(t) * .17, .23, [0x8fbe75, 0x72a95f, 0xa8c986][i % 3], [.62, 1.6, .7], 0); l.rotation.z = Math.sin(t) * .6; l.rotation.x = Math.cos(t) * .6; } return p; }
function tree(g, x, y, z, s = 1, tone = 0) { const t = new THREE.Group(); g.add(t); t.position.set(x, y, z); t.scale.setScalar(s); const leaf = [[0x93c187, 0xaad49a, 0x85b779], [0xe7a6b8, 0xf2c0cc, 0xd98fa5], [0xa8cf7e, 0xc0dd95, 0x92bd6b]][tone % 3]; cyl(t, 0, 1, 0, .12, .18, 2, 0x9b7a5e, 7); ball(t, 0, 2.3, 0, .88, leaf[0], [1, 1.2, 1]); ball(t, .5, 2.05, .15, .56, leaf[1]); ball(t, -.42, 2.15, -.1, .62, leaf[2]); ball(t, .1, 2.95, -.05, .52, leaf[1]); return t; }
function screen(g, x, y, z, w = 1.02) { const s = new THREE.Group(); s.position.set(x, y, z); g.add(s); box(s, 0, 0, 0, w, .66, .1, 0x3f5c62, .06); box(s, 0, .015, .056, w - .1, .54, .012, glowing(0xa9e0cf, .5), .02); box(s, 0, -.39, 0, .075, .17, .075, 0x687f78, 0); box(s, 0, -.48, .06, .4, .05, .3, 0x91a196, .02); return s; }
function desk(g, x, z, c) { const d = new THREE.Group(); d.position.set(x, 0, z); g.add(d); box(d, 0, 1.03, 0, 2.5, .16, 1.25, c, .08); for (const xx of [-1.02, 1.02]) box(d, xx, .48, 0, .12, .96, 1.05, 0xcabda0, .03); screen(d, 0, 1.62, -.25); box(d, 0, 1.13, .25, .68, .045, .23, 0xd4ddca, .02); cyl(d, .92, 1.2, -.05, .095, .085, .19, 0xe59b7a, 10); return d; }
function couch(g, x, z, c) { const co = new THREE.Group(); co.position.set(x, 0, z); g.add(co); box(co, 0, .34, 0, 2.55, .47, 1, c, .15); box(co, 0, .83, -.4, 2.6, .86, .26, c, .1); for (const xx of [-1.15, 1.15]) box(co, xx, .69, 0, .28, .68, 1.08, c, .09); for (const xx of [-.64, .05, .7]) box(co, xx, .61, .04, .6, .16, .72, 0xf0e4c6, .07); return co; }

// ---------------------------------------------------------------- robot faces: the bot's own symbol, glowing on a CRT
const faceCache = new Map();
let symbolsFont = null, symbolsReady = false;
function neonOf(css) { const c = new THREE.Color(css), hsl = {}; c.getHSL(hsl); return new THREE.Color().setHSL(hsl.h, Math.min(1, hsl.s * .6 + .45), .64); }
function faceTexture(face) {
  const key = JSON.stringify(face); if (faceCache.has(key)) return faceCache.get(key);
  const W = 256, Hh = 192, cv = document.createElement('canvas'); cv.width = W; cv.height = Hh; const ctx = cv.getContext('2d');
  const neon = '#' + neonOf(face.color).getHexString(), tex = new THREE.CanvasTexture(cv); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  let img = null;
  const draw = () => {
    const bg = ctx.createRadialGradient(W / 2, Hh / 2, 10, W / 2, Hh / 2, W * .62); bg.addColorStop(0, '#16343a'); bg.addColorStop(1, '#050d12');
    ctx.globalCompositeOperation = 'source-over'; ctx.fillStyle = bg; ctx.fillRect(0, 0, W, Hh);
    const S = 118; ctx.shadowColor = neon; ctx.fillStyle = neon;
    if (img?.complete && img.naturalWidth) {
      const tint = document.createElement('canvas'); tint.width = tint.height = S; const tc = tint.getContext('2d');
      tc.drawImage(img, 0, 0, S, S); tc.globalCompositeOperation = 'source-in'; tc.fillStyle = neon; tc.fillRect(0, 0, S, S);
      for (const blur of [34, 14, 0]) { ctx.shadowBlur = blur; ctx.drawImage(tint, (W - S) / 2, (Hh - S) / 2); }
    } else {
      // A symbol missing from the bundled subset would print as its name: such a bot shows initials.
      ctx.font = `${S}px "Tico Symbols"`;
      const glyph = face.glyph && symbolsReady && ctx.measureText(face.glyph).width < S * 1.4;
      if (!glyph) ctx.font = `800 ${face.initials.length > 1 ? 74 : 92}px ${FONT}`;
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
      for (const blur of [34, 14, 0]) { ctx.shadowBlur = blur; ctx.fillText(glyph ? face.glyph : face.initials, W / 2, Hh / 2 + (glyph ? 0 : 4)); }
    }
    ctx.shadowBlur = 0; ctx.fillStyle = 'rgba(0,0,0,.22)'; for (let y = 0; y < Hh; y += 4) ctx.fillRect(0, y, W, 1.5);
    const shine = ctx.createLinearGradient(0, 0, W * .6, Hh * .7); shine.addColorStop(0, 'rgba(255,255,255,.16)'); shine.addColorStop(.5, 'rgba(255,255,255,0)');
    ctx.fillStyle = shine; ctx.fillRect(0, 0, W, Hh); tex.needsUpdate = true;
  };
  if (face.svg) { img = new Image(); img.decoding = 'async'; img.onload = draw; img.src = face.svg; }
  else if (face.glyph) {
    symbolsFont ||= new FontFace('Tico Symbols', 'url(/vendor/fonts/material-symbols-outlined.woff2)').load().then(f => { document.fonts.add(f); symbolsReady = true; return f; });
    symbolsFont.then(draw, () => {});
  }
  draw(); resources.add(tex); faceCache.set(key, tex); return tex;
}
let glowTex = null;
function glowTexture() {
  if (glowTex) return glowTex;
  const cv = document.createElement('canvas'); cv.width = cv.height = 128; const ctx = cv.getContext('2d');
  const g = ctx.createRadialGradient(64, 64, 0, 64, 64, 64); g.addColorStop(0, 'rgba(255,255,255,0)'); g.addColorStop(.42, 'rgba(255,255,255,0)'); g.addColorStop(.56, 'rgba(255,255,255,.55)'); g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, 128, 128); glowTex = new THREE.CanvasTexture(cv); resources.add(glowTex); return glowTex;
}

// ---------------------------------------------------------------- characters
const SKIN = [0xf1c6a2, 0xe2b08a, 0xc68b62, 0x9b6745, 0xf5d3b8], HAIR = [0x5a3f30, 0x2f2a28, 0x8a5a3a, 0xd9a35f, 0x6d4b8f, 0xc4573e];
const SHIRT = [0xf09b84, 0x86b6e0, 0xf3c46b, 0x9ccf9e, 0xc6a3e0, 0xf2a7c3];
function character(g, member, x, z, floor) {
  const {id: actorId, name, type, state: activity, detail: message, href} = member, h = hash(actorId);
  const root = new THREE.Group(); root.position.set(x, .27, z); g.add(root);
  const ch = {actorId, href, activity, root, name, type, message, floor, index: characters.length, wave: 0, h, head: null, arms: []};
  const body = new THREE.Group(); root.add(body); ch.body = body;
  if (type === 'bot') {
    const face = member.face || {initials: name.slice(0, 2).toUpperCase(), color: '#79c9b3'};
    const tone = new THREE.Color(face.color), shell = tone.clone().lerp(new THREE.Color(0xffffff), .38).getHex(), deep = tone.clone().lerp(new THREE.Color(0x203038), .25).getHex();
    const cream = 0xf3ead6, metal = 0x8f9ea3, neon = neonOf(face.color);
    // Stubby legs on chunky boots, a cream torso with a coloured control panel.
    for (const xx of [-.13, .13]) { box(body, xx, .05, .04, .17, .1, .26, 0x3d4d55, .04); cyl(body, xx, .17, 0, .055, .055, .16, metal, 8); }
    box(body, 0, .45, 0, .52, .44, .38, cream, .12);
    box(body, 0, .45, .19, .52, .1, .02, shell, .02);
    box(body, 0, .5, .2, .3, .16, .03, 0x2c3d44, .03);
    [0xff7a6b, 0xffd166, 0x6ee7b7].forEach((c, i) => ball(body, -.08 + i * .08, .52, .218, .022, basic(c), null, 0));
    for (let i = 0; i < 3; i++) box(body, .0, .335 - i * .03, .192, .2, .012, .01, 0xb7aa92, 0);
    cyl(body, 0, .72, 0, .07, .09, .1, metal, 10);
    // Arms: a shoulder ball, a bent tube and a C-claw.
    for (const side of [-1, 1]) {
      const arm = new THREE.Group(); arm.position.set(side * .31, .6, 0); body.add(arm);
      ball(arm, 0, 0, 0, .085, shell, null, 0); cyl(arm, side * .02, -.15, 0, .04, .04, .24, metal, 8);
      const claw = mesh(arm, new THREE.TorusGeometry(.065, .022, 6, 12, Math.PI * 1.45), deep, side * .02, -.31, 0); claw.rotation.set(Math.PI / 2, 0, -Math.PI * .22 + Math.PI / 2);
      ch.arms.push(arm);
    }
    // The CRT head: a rounded shell in the bot's colour around a glowing screen.
    const head = new THREE.Group(); head.position.y = .78; body.add(head); ch.head = head;
    box(head, 0, .3, 0, .78, .6, .58, shell, .14);
    box(head, 0, .3, .27, .64, .48, .06, 0x1d2a30, .07);
    const faceMat = new THREE.MeshBasicMaterial({map: faceTexture(face), toneMapped: false}); ch.faceMat = faceMat;
    const facePlane = mesh(head, new THREE.PlaneGeometry(.56, .42), faceMat, 0, .3, .302, false); facePlane.userData.keep = true;
    const glowMat = new THREE.MeshBasicMaterial({map: glowTexture(), color: neon, transparent: true, opacity: .5, blending: THREE.AdditiveBlending, depthWrite: false, toneMapped: false});
    const glow = mesh(head, new THREE.PlaneGeometry(1.15, .95), glowMat, 0, .3, .31, false); glow.userData.keep = true; ch.glowMat = glowMat;
    for (const side of [-1, 1]) { const ear = cyl(head, side * .41, .3, 0, .09, .09, .07, deep, 14); ear.rotation.z = Math.PI / 2; const nub = ball(head, side * .455, .3, 0, .035, basic(neon.getHex()), null, 0); nub.userData.keep = true; }
    for (let i = 0; i < 3; i++) box(head, -.18 + i * .18, .6, -.08, .1, .025, .18, deep, .01);
    rod(head, [0, .58, 0], [0, .84, 0], .016, metal);
    ch.bulbMat = new THREE.MeshBasicMaterial({color: neon.clone(), toneMapped: false}); ch.neon = neon;
    const bulb = ball(head, 0, .88, 0, .055, ch.bulbMat, null, 0); bulb.userData.keep = true;
    root.scale.setScalar(1.2);
  } else {
    const skin = SKIN[h % 5], hair = HAIR[(h >>> 3) % 6], shirt = SHIRT[(h >>> 6) % 6];
    for (const xx of [-.1, .1]) { cyl(body, xx, .2, 0, .075, .07, .3, 0x4a5d73, 8); box(body, xx, .05, .04, .15, .09, .24, 0xf2ece0, .04); }
    box(body, 0, .5, 0, .44, .4, .3, shirt, .14);
    for (const side of [-1, 1]) { const arm = new THREE.Group(); arm.position.set(side * .25, .64, 0); body.add(arm); box(arm, 0, -.12, 0, .12, .28, .13, shirt, .05); ball(arm, 0, -.29, 0, .065, skin, null, 0); ch.arms.push(arm); }
    const head = new THREE.Group(); head.position.y = .72; body.add(head); ch.head = head;
    ball(head, 0, .3, 0, .33, skin, [1, .95, .95]);
    const style = (h >>> 9) % 3;
    ball(head, 0, .4, -.04, .345, hair, style === 1 ? [1.04, .78, 1.02] : [1.02, .72, 1]);
    if (style === 2) ball(head, 0, .58, -.18, .13, hair, null, 0);
    if (style === 1) for (const side of [-1, 1]) ball(head, side * .28, .18, -.06, .11, hair, [1, 1.6, 1], 0);
    for (const xx of [-.11, .11]) { ball(head, xx, .29, .29, .038, 0x2c2a2a, [1, 1.25, .6], 0); ball(head, xx * 1.55, .2, .27, .045, basic(0xf4a4a0, {transparent: true, opacity: .55}), [1, .6, .4], 0); }
    root.scale.setScalar(1.12);
    const smile = mesh(head, new THREE.TorusGeometry(.045, .012, 5, 10, Math.PI), 0x8a4b45, 0, .2, .31, false); smile.rotation.z = Math.PI;
  }
  // A soft disc under each teammate, brightening when selected.
  const halo = mesh(root, new THREE.CircleGeometry(.48, 28), new THREE.MeshBasicMaterial({color: 0xfff1c9, transparent: true, opacity: 0, depthWrite: false}), 0, .02, 0, false); halo.rotation.x = -Math.PI / 2; ch.halo = halo; halo.userData.keep = true;
  root.traverse(o => { if (o.isMesh) o.userData.character = ch; });
  characters.push(ch); return ch;
}

// ---------------------------------------------------------------- scenery
const groundShadow = mesh(scene, new THREE.PlaneGeometry(800, 800), new THREE.ShadowMaterial({opacity: .22}), 0, -1.87, 0, false); groundShadow.rotation.x = -Math.PI / 2;
box(landscape, 0, -1.15, 0, campusWidth + 2, 1.15, campusDepth + 1, 0x35504f, .6);
box(landscape, 0, -1.77, 0, campusWidth + 1.2, .18, campusDepth + .2, 0x203f40, .15);
function solarGarden(roof, b) {
  box(roof, 0, 0, -2.65, 12.6, .24, 3.1, 0xe1ead9, .12); box(roof, 0, .15, -2.65, 12.1, .08, 2.7, 0x8fbf81, .12);
  for (const x of [-4.8, .5]) for (const z of [-3.6, -1.5]) box(roof, x, 1.2, z, .1, 2.05, .1, 0xa5c3b1, .02);
  for (let j = 0; j < 2; j++) box(roof, -2.15, 2.25, -3.22 + j * 1.12, 5.6, .12, .93, material(0x2a5f70, {metalness: .45, roughness: .28}), .04);
  for (const z of [-3.25, -1.85]) { box(roof, 3.25, .32, z, 3.3, .35, .72, 0xb6c8a0, .1); for (let j = 0; j < 6; j++) ball(roof, 2 + j * .5, .65, z, .29, j % 2 ? 0x9fd283 : 0x78ba7b, [1, .65, 1], 0); }
  tree(roof, 5.1, .22, -2.5, .58, 1); plant(roof, 1.3, .22, -2.5, .75);
  box(roof, 0, .18, -1.07, 12.45, .05, .06, glowing(b.color, .9), .02);
}
function island(b, w, d) {
  const g = new THREE.Group(); landscape.add(g); g.position.set(b.x, 0, b.z);
  box(g, 0, -.13, 0, w, .95, d, 0x9ac38c, .4); box(g, 0, .38, 0, w - .5, .08, d - .5, 0x78a872, .25); box(g, 0, .44, .1, 13.3, .11, 9.6, 0xd6e0cc, .17);
  for (const x of [-(w / 2 - .65), w / 2 - .65]) { tree(g, x, .42, -3.3, .82, (b.id + 1) % 3); tree(g, x, .42, 2.1, .63, b.id % 3); for (const z of [-1, 0, 1]) ball(g, x, .78, z, .29, 0xb5cf85, [1, .65, 1], 0); }
  box(g, 0, .49, 4.8, 4.2, .12, 1.5, 0xe0e4cf, .08);
  for (const x of [-2.6, 2.6]) { cyl(g, x, 1.25, 5, .04, .06, 1.6, 0x618879, 8); ball(g, x, 2.07, 5, .15, basic(0xffe2a8), null, 0); }
  return g;
}
const floorMeta = new Map();   // floor id -> {group, hit, trim, chars}
for (const b of BUILDINGS) {
  const isle = island(b, TOWER ? 20 : 15.8, TOWER ? 15 : 12.2);
  if (TOWER) for (const [x, z, s] of [[-8.6, -5.6, .9], [8.4, -5.8, .75], [-8.2, 5.4, .7], [8.6, 5.2, .85]]) tree(isle, x, .42, z, s, (x > 0) + 1);
  const group = new THREE.Group(); group.position.set(b.x, .65, b.z); world.add(group); b.room = group; buildingGroups.push(group);
  const roof = b.roof = new THREE.Group(); roof.userData.storey = true; roof.position.y = b.floors.length * H; group.add(roof); solarGarden(roof, b);
  for (const f of b.floors) {
    const floor = new THREE.Group(); floor.userData.storey = true; floor.position.y = f.level * H; group.add(floor);
    box(floor, 0, 0, 0, 12.5, .3, 8.3, 0xe4eadb, .1); box(floor, 0, .19, 0, 12, .08, 7.9, 0xe2cfa9, .035);
    for (let j = 0; j < 12; j++) box(floor, -5.7 + j * 1.03, .237, 0, .013, .008, 7.7, 0xc9bd98, 0);
    box(floor, 0, 1.8, -3.95, 12.3, 3.3, .18, f.wall, .06);
    box(floor, -6.12, 1.78, 0, .16, 3.3, 8.1, 0xcfe0cf, .035);
    for (const x of [-3.8, 0, 3.8]) { box(floor, x, 1.95, -3.81, 2.7, 1.6, .06, 0x5a8f8a, .025); box(floor, x, 1.95, -3.77, 2.57, 1.46, .012, glowing(0x8cc4b6, .35), .015); }
    for (const x of [-6.1, 6.1]) for (const z of [-3.9, 3.9]) box(floor, x, 1.76, z, .16, 3.5, .16, 0xc5d6c0, .02);
    const trim = box(floor, 0, .18, 4.13, 12.35, .06, .07, glowing(f.color, .7), .02);
    box(floor, 0, .248, .2, 10.7, .012, 6.2, f.rug, .12);
    plant(floor, -5.46, .26, 2.85, .7); plant(floor, 5.55, .26, -2.7, .85);
    // The storey's own name plate: the computer in a tower, the storey number in a multi-storey building.
    if (TOWER) { box(floor, -3.4, .05, 4.2, 5.4, .32, .06, 0x264b4c, .04); sign(floor, f.group.name + (f.parts > 1 ? `  ${f.part + 1}/${f.parts}` : ''), -3.4, .05, 4.235, 5.1, .26, '#f3e6be'); }
    // Every identity has a workstation. No representative sampling or fabricated teammates.
    const chars = [];
    f.members.forEach((member, index) => {
      const x = -3.65 + (index % 3) * 3.65, z = index < 3 ? 1.55 : -1.85;
      const work = new THREE.Group(); floor.add(work); work.position.set(x, .25, z); work.scale.setScalar(.83);
      desk(work, 0, 0, member.type === 'human' ? 0xe6cba2 : 0xcfe2c8);
      chars.push(character(floor, member, x + .05, z + 1.02, f.id));
    });
    if (!f.members.length) { couch(floor, 0, 1, 0x98c8a8); plant(floor, -2.3, .25, 1, .9); sign(floor, 'Ready for your bots', 0, 2.8, -3.82, 5, .5, '#5e7a70'); }
    // Lit floor edge that appears on hover, and an invisible box for picking the storey.
    const ring = mesh(floor, new THREE.BoxGeometry(12.8, .05, 8.6), new THREE.MeshBasicMaterial({color: f.color, transparent: true, opacity: 0, depthWrite: false, toneMapped: false}), 0, .22, 0, false); ring.userData.keep = true;
    const hit = box(floor, 0, H / 2, 0, 12.4, H, 8.1, material(0xffffff, {transparent: true, opacity: 0, depthWrite: false}), 0);
    hit.userData.pickFloor = f.id; hit.userData.keep = true; hit.castShadow = false; hit.receiveShadow = false; hit.visible = false; hitMeshes.push(hit);
    floorMeta.set(f.id, {group: floor, ring, trim, chars});
  }
  // The building name is part of the architecture and stays legible in the campus view.
  box(group, 0, .39, 4.45, 10.7, .77, .12, 0x264b4c, .08);
  sign(group, b.name, 0, .51, 4.53, 9.7, .43, '#f3e6be');
  const bots = (b.floors.flatMap(f => f.members)).filter(m => m.type === 'bot').length;
  sign(group, TOWER ? `${data.groups.filter(g => g.kind === 'computer').length} COMPUTERS  /  ${bots} BOTS` : b.group.kind === 'computer' ? `COMPUTER  /  ${bots} BOTS` : 'SHARED SPACE', 0, .16, 4.54, 4.8, .16, '#8fd6c1');
  for (const z of [5.05, 6.15]) { mesh(isle, new THREE.TorusGeometry(.73, .1, 6, 20, Math.PI), 0xdbe6cd, 0, .12, z); mesh(isle, new THREE.TorusGeometry(.62, .023, 6, 20, Math.PI), basic(b.color), 0, .12, z + .015, false); }
  box(isle, 0, -.44, 5.55, 1.4, .15, 2.5, 0x223f42, .05);
}
// A cutaway Loop joins the campus portals. Pods are scenery, not reported bot traffic.
for (let i = 1; i < BUILDINGS.length; i++) {
  const a = BUILDINGS[i - 1], b = BUILDINGS[i], sameRow = a.z === b.z, edge = Math.max(...xs) + 9.3;
  const points = sameRow ? [[a.x, .18, a.z + 6.15], [a.x, .02, a.z + 7.15], [b.x, .02, b.z + 7.15], [b.x, .18, b.z + 6.15]]
    : [[a.x, .18, a.z + 6.15], [a.x + 8.5, .02, a.z + 7], [edge, .02, a.z + 7], [edge, .02, b.z + 7], [b.x, .02, b.z + 7], [b.x, .18, b.z + 6.15]];
  const curve = new THREE.CatmullRomCurve3(points.map(p => new THREE.Vector3(...p)), false, 'catmullrom', .12);
  mesh(tunnels, new THREE.TubeGeometry(curve, 48, .68, 10, false), material(0x9bcab8, {transparent: true, opacity: .18, depthWrite: false, side: THREE.DoubleSide, roughness: .25}), 0, 0, 0, false);
  for (const side of [-.42, .42]) mesh(tunnels, new THREE.TubeGeometry(new THREE.CatmullRomCurve3(curve.points.map(p => p.clone().add(new THREE.Vector3(0, -.18, side))), false, 'catmullrom', .12), 48, .022, 4, false), basic(0x74e2ca), 0, 0, 0, false);
  const pod = new THREE.Group(); tunnels.add(pod);
  box(pod, 0, 0, 0, .62, .48, 1.05, 0xf0dfc2, .18); box(pod, 0, .16, .06, .5, .26, .61, 0x37575e, .11); box(pod, 0, -.12, .5, .4, .04, .02, basic(0xbef8dc), .01);
  pods.push({root: pod, curve, phase: i * .29});
}
// Merge opaque static scenery by material; characters, glass, signs and pickers stay separate.
// Storeys and roofs keep their own visibility, so a building's batch leaves them alone.
const nested = (o, root) => { for (let p = o.parent; p && p !== root; p = p.parent) if (p.userData.storey) return true; return false; };
function batchStatic(root, skipCharacters = true) {
  root.updateWorldMatrix(true, true);
  const inverse = root.matrixWorld.clone().invert(), batches = new Map(), originals = [];
  root.traverse(o => {
    if (!o.isMesh || (skipCharacters && o.userData.character) || o.userData.keep || o.material.transparent || nested(o, root)) return;
    const key = o.material.uuid + ':' + o.castShadow;
    if (!batches.has(key)) batches.set(key, {material: o.material, cast: o.castShadow, geos: []});
    const geo = o.geometry.index ? o.geometry.toNonIndexed() : o.geometry.clone();
    geo.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inverse, o.matrixWorld));
    batches.get(key).geos.push(geo); originals.push(o);
  });
  for (const b of batches.values()) {
    const geo = mergeGeometries(b.geos, false); b.geos.forEach(g => g.dispose()); if (!geo) continue;
    const m = new THREE.Mesh(geo, b.material); m.castShadow = b.cast; m.receiveShadow = true; root.add(m); resources.add(geo);
    if (!skipCharacters) m.userData.character = originals[0]?.userData.character;
  }
  originals.forEach(o => o.removeFromParent());
}
for (const b of BUILDINGS) batchStatic(b.roof);
for (const [, meta] of floorMeta) batchStatic(meta.group);
for (const b of BUILDINGS) batchStatic(b.room);
// Each robot or person is a handful of draws: its body, head and arms merge separately so they can still move.
for (const ch of characters) {
  const parts = [ch.head, ...ch.arms]; parts.forEach(p => batchStatic(p, false));
  parts.forEach(p => ch.body.remove(p)); batchStatic(ch.body, false); parts.forEach(p => ch.body.add(p));
}
batchStatic(landscape);

// ---------------------------------------------------------------- camera and views
const raycaster = new THREE.Raycaster(), pointer = new THREE.Vector2();
const floorCenter = f => new THREE.Vector3(f.building.x, .65 + f.level * H + .9, f.building.z + .2);
function desiredCamera() {
  const aspect = innerWidth / innerHeight;
  let target, scale;
  if (state.floor === null) {
    target = new THREE.Vector3(0, maxHeight * .32, 0);
    const width = campusWidth * Math.cos(state.yaw) + campusDepth * Math.abs(Math.sin(state.yaw)) + 7;
    const height = maxHeight * Math.cos(state.pitch) + campusDepth * Math.sin(state.pitch) + 9;
    scale = Math.max(height, width / aspect) * (small() ? 1.1 : 1.03) / state.zoom;
  } else {
    target = floorCenter(FLOORS[state.floor]);
    // A portrait screen looks along the room's long side (see setFloor), so its short side must fit across.
    scale = (portrait() ? Math.max(13.5, 10.4 / aspect) : Math.max(9.6, 14 / aspect)) * (small() ? 1.06 : 1.12) / state.zoom;
  }
  const distance = Math.max(80, campusWidth + campusDepth + maxHeight);
  return {target, scale, position: target.clone().add(new THREE.Vector3(Math.sin(state.yaw) * Math.cos(state.pitch) * distance, Math.sin(state.pitch) * distance, Math.cos(state.yaw) * Math.cos(state.pitch) * distance))};
}
function updateCamera(dt) {
  const desired = desiredCamera(), lerp = reduced.matches ? 1 : 1 - Math.exp(-dt * 6);
  currentTarget.lerp(desired.target, lerp); currentPosition.lerp(desired.position, lerp); currentScale = THREE.MathUtils.lerp(currentScale, desired.scale, lerp);
  camera.position.copy(currentPosition); camera.lookAt(currentTarget);
  const aspect = innerWidth / innerHeight; camera.left = -currentScale * aspect / 2; camera.right = currentScale * aspect / 2; camera.top = currentScale / 2; camera.bottom = -currentScale / 2; camera.updateProjectionMatrix();
}
const project = v => { const p = v.clone().project(camera); return {x: (p.x + 1) * innerWidth / 2, y: (1 - p.y) * innerHeight / 2}; };
const floorName = f => f.parts > 1 ? `${f.group.name} · ${f.part + 1} of ${f.parts}` : f.group.name;
$('#floors').replaceChildren();
for (const f of FLOORS) {
  const button = document.createElement('button'); button.className = 'scene-access'; button.dataset.floor = f.id; button.dataset.computer = f.group.key;
  button.textContent = floorName(f); button.setAttribute('aria-label', floorName(f) + ', ' + f.members.length + ' teammates'); $('#floors').append(button);
}
function tags() {
  $('#people').replaceChildren(); characters.forEach(c => c.tag = null);
  for (const ch of characters.filter(c => c.floor === state.floor)) {
    const button = document.createElement('button'); button.className = 'tag'; button.dataset.person = ch.actorId; button.dataset.state = mood(ch); button.dataset.type = ch.type;
    button.innerHTML = '<i></i><span></span>'; button.lastChild.textContent = ch.name.replace(/ · Your branch$/, '');
    button.setAttribute('aria-label', ch.name + ' · ' + ch.message); button.onclick = () => sayHi(ch); ch.tag = button; $('#people').append(button);
  }
}
function setHover(id) {
  state.hover = id; $$('[data-floor]').forEach(b => b.classList.toggle('hovered', Number(b.dataset.floor) === id));
}
function closeSpeech() { state.selected = null; $('#speech').hidden = true; }
function subtitle(f) { const m = f.members; return m.filter(x => x.type === 'human').length + ' people · ' + m.filter(x => x.type === 'bot').length + ' bots · ' + m.filter(x => x.state === 'running').length + ' running'; }
function setFloor(id) {
  if (id !== null && !FLOORS[id]) id = null;
  const wasCampus = state.floor === null;
  state.floor = id; state.zoom = 1;
  state.yaw = id === null ? (small() ? .14 : .36) : (wasCampus ? (portrait() ? Math.PI / 2 : 0) : state.yaw); state.pitch = id === null ? (small() ? .58 : .42) : 1.02;
  setHover(null); closeSpeech(); $('#hover-label').hidden = true;
  characters.forEach(c => { if (c.floor !== id) { c.root.rotation.y = 0; c.head?.rotation.set(0, 0, 0); } });
  $('#floors').hidden = id !== null; $('#floor-heading').hidden = id === null; $('#back').hidden = id === null; $('#people').hidden = id === null;
  document.body.classList.toggle('inside', id !== null); tags();
  $('#campus-hint').textContent = id === null ? 'Select a floor to look inside' : 'Select a teammate · Drag to turn';
  const f = FLOORS[id];
  if (f) {
    const b = f.building;
    $('#floor-title').textContent = f.group.name;
    $('#floor-number').textContent = (f.group.kind === 'computer' ? 'Computer' : 'Shared space') + (b.floors.length > 1 ? ` · Floor ${f.level + 1} of ${b.floors.length}` : '');
    $('#floor-subtitle').textContent = subtitle(f);
    $('#floor-up').disabled = f.level >= b.floors.length - 1; $('#floor-down').disabled = f.level === 0;
    $('#floor-step').hidden = b.floors.length < 2;
    const c = floorCenter(f); aimSun(c.x, c.y, c.z, 9);
  } else aimSun(0, 0, 0, Math.max(campusWidth, campusDepth, maxHeight) * .75 + 6);
  // Inside, only the chosen storey shows: storeys above would block the view from overhead.
  for (const b of BUILDINGS) {
    b.room.visible = id === null || f.building === b; b.roof.visible = id === null;
    b.room.children.forEach(o => { if (!o.userData.storey) o.visible = id === null; });
    b.roof.visible = id === null;
  }
  for (const [fid, meta] of floorMeta) meta.group.visible = id === null || fid === id;
  landscape.visible = id === null; tunnels.visible = id === null;
  groundShadow.visible = id === null;
  preferences.floorId = f ? f.key : null;
}
$('#floor-up').onclick = () => { const f = FLOORS[state.floor]; const next = f && f.building.floors[f.level + 1]; if (next) setFloor(next.id); };
$('#floor-down').onclick = () => { const f = FLOORS[state.floor]; const next = f && f.building.floors[f.level - 1]; if (next) setFloor(next.id); };
$$('[data-floor]').forEach(b => { b.onclick = () => setFloor(+b.dataset.floor); b.onfocus = () => setHover(+b.dataset.floor); b.onblur = () => setHover(null); });
$('#back').onclick = () => { const id = state.floor; setFloor(null); $(`[data-floor="${id}"]`)?.focus({preventScroll: true}); };
function mood(ch) {
  if (ch.type === 'human') return 'human';
  if (String(ch.message).startsWith('Stuck')) return 'stuck';
  if (!data.fresh) return 'unknown';
  return ['running', 'paused', 'planned', 'restricted', 'unknown'].includes(ch.activity) ? (ch.activity === 'planned' ? 'paused' : ch.activity) : 'idle';
}
function sayHi(ch) {
  if (state.floor !== ch.floor) setFloor(ch.floor);
  state.selected = ch; ch.wave = 2.4; $('#speech-type').textContent = (ch.type === 'human' ? 'Person' : 'Bot') + ' · ' + FLOORS[ch.floor].group.name;
  $('#speech-name').textContent = ch.name;
  $('#speech-message').textContent = ch.type === 'human' ? (FLOORS[ch.floor].group.kind === 'commons' ? 'Human teammate. Presence is not tracked.' : 'Works with bots on this computer. Presence is not tracked.') : (!data.fresh ? 'Status is unavailable. Reconnecting…' : ch.message);
  $('#speech-open').hidden = !ch.href; $('#speech-open').onclick = () => openMember(ch.actorId); $('#speech').hidden = false;
}
$('#speech-close').onclick = closeSpeech;
function pick(ev) {
  pointer.set(ev.clientX / innerWidth * 2 - 1, -ev.clientY / innerHeight * 2 + 1); raycaster.setFromCamera(pointer, camera);
  if (state.floor === null) {
    hitMeshes.forEach(m => m.visible = true); const hits = raycaster.intersectObjects(hitMeshes, false); hitMeshes.forEach(m => m.visible = false);
    return hits.length ? {floor: hits[0].object.userData.pickFloor} : null;
  }
  const chars = floorMeta.get(state.floor).chars;
  const hits = raycaster.intersectObjects(chars.map(c => c.root), true);
  if (hits.length) return {character: hits[0].object.userData.character};
  const room = raycaster.intersectObject(floorMeta.get(state.floor).group, true).find(h => !h.object.material?.transparent);
  return room ? {room: true} : null;
}
let down = null;
on(renderer.domElement, 'pointerdown', e => { down = {x: e.clientX, y: e.clientY, yaw: state.yaw, pitch: state.pitch}; state.drag = false; renderer.domElement.setPointerCapture(e.pointerId); });
on(renderer.domElement, 'pointermove', e => {
  if (down) {
    const dx = e.clientX - down.x, dy = e.clientY - down.y; if (Math.hypot(dx, dy) > 6) state.drag = true;
    if (state.drag) {
      const inside = state.floor !== null;
      state.yaw = inside ? down.yaw - dx * .005 : THREE.MathUtils.clamp(down.yaw - dx * .004, -.65, .85);
      state.pitch = THREE.MathUtils.clamp(down.pitch + dy * .003, inside ? .55 : .08, inside ? 1.45 : .75); $('#hover-label').hidden = true;
    }
  } else if (e.pointerType === 'mouse') {
    const hit = pick(e); if (state.floor === null) setHover(hit?.floor ?? null); renderer.domElement.style.cursor = hit?.floor !== undefined || hit?.character ? 'pointer' : 'grab';
    const label = hit?.character ? hit.character.name + ' · ' + hit.character.message : hit?.floor !== undefined ? floorName(FLOORS[hit.floor]) : null;
    $('#hover-label').hidden = !label;
    if (label) { $('#hover-label').textContent = label; $('#hover-label').style.left = THREE.MathUtils.clamp(e.clientX, 100, innerWidth - 100) + 'px'; $('#hover-label').style.top = e.clientY + 'px'; }
  }
});
on(renderer.domElement, 'pointerup', e => {
  if (down && !state.drag) { const hit = pick(e); if (hit?.floor !== undefined) setFloor(hit.floor); else if (hit?.character) sayHi(hit.character); else if (!hit && state.floor !== null && !state.selected) setFloor(null); else closeSpeech(); }
  down = null; state.drag = false;
});
on(renderer.domElement, 'pointercancel', () => { down = null; state.drag = false; });
on(renderer.domElement, 'pointerleave', () => { $('#hover-label').hidden = true; if (!down) setHover(null); });
on(renderer.domElement, 'wheel', e => { e.preventDefault(); state.zoom = THREE.MathUtils.clamp(state.zoom * Math.exp(-e.deltaY * .0008), .7, 2.2); }, {passive: false});
on(document, 'keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (e.key === 'Escape') { if (state.selected) closeSpeech(); else if (state.floor !== null) $('#back').click(); }
  if (state.floor !== null && e.key === 'ArrowUp') { e.preventDefault(); $('#floor-up').click(); }
  if (state.floor !== null && e.key === 'ArrowDown') { e.preventDefault(); $('#floor-down').click(); }
  if (/^[1-9]$/.test(e.key) && +e.key <= FLOORS.length) setFloor(+e.key - 1);
  if (e.key === '0') setFloor(null);
});
on(window, 'resize', () => renderer.setSize(innerWidth, innerHeight));
on(renderer.domElement, 'webglcontextlost', e => { e.preventDefault(); controller.abort(); cancelAnimationFrame(frameId); window.dispatchEvent(new Event('overview-context-lost')); });

// ---------------------------------------------------------------- animation
let last = 0, frameId = 0, frames = 0, loadingTimer = 0;
const up = new THREE.Vector3(0, 1.75, 0), tmp = new THREE.Vector3();
function animate(now) {
  frameId = 0; if (document.hidden) { last = 0; return; } const dt = last ? Math.min(.05, (now - last) / 1000) : .016; last = now;
  // Read the live query: some iframe browsers update matches without delivering a change event.
  const still = reduced.matches;
  if (!still) state.t += dt; const t = state.t; updateCamera(dt);
  for (const [id, meta] of floorMeta) meta.ring.material.opacity = THREE.MathUtils.lerp(meta.ring.material.opacity, state.hover === id ? .85 : 0, .18);
  const inside = state.floor !== null;
  for (const ch of characters) {
    ch.halo.material.opacity = THREE.MathUtils.lerp(ch.halo.material.opacity, state.selected === ch ? .75 : 0, .2);
    const m = mood(ch), working = m === 'running', i = ch.index;
    if (ch.type === 'bot') {
      const dim = m === 'paused' || m === 'restricted' ? .35 : m === 'unknown' ? .6 : 1;
      const flicker = working && !still ? .9 + Math.sin(t * 23 + i) * .05 + Math.sin(t * 3.1 + i) * .05 : 1;
      ch.faceMat.color.setScalar(dim * flicker); ch.glowMat.opacity = .5 * dim * (working ? 1.15 : 1);
      const blink = m === 'stuck' ? (Math.sin(t * 6) > 0 ? 1 : .15) : working ? .55 + .45 * Math.sin(t * 5 + i) : m === 'idle' ? .75 + .25 * Math.sin(t * 1.4 + i) : .15;
      ch.bulbMat.color.copy(m === 'stuck' ? new THREE.Color(0xffb547) : ch.neon).multiplyScalar(still ? 1 : blink);
    }
    if (ch.head && state.floor === ch.floor && !still) {
      // Inside, everyone glances up at the viewer; idle bots look around a little.
      ch.head.rotation.x = THREE.MathUtils.lerp(ch.head.rotation.x, inside ? -.32 : 0, .08);
      ch.root.rotation.y = THREE.MathUtils.lerp(ch.root.rotation.y, inside ? Math.atan2(Math.sin(state.yaw), Math.cos(state.yaw)) * .85 : 0, .08);
      ch.head.rotation.y = ch.type === 'bot' && !working ? Math.sin(t * .6 + i * 1.7) * .3 : 0;
    }
    if (still) continue;
    ch.wave = Math.max(0, ch.wave - dt);
    ch.body.position.y = working ? Math.abs(Math.sin(t * 5 + i)) * .05 : Math.sin(t * 1.6 + i) * .012;
    const [left, right] = ch.arms;
    if (right) right.rotation.z = ch.wave > 0 ? 2.4 + Math.sin(t * 12) * .35 : working ? Math.sin(t * 9 + i) * .25 : 0;
    if (left) left.rotation.z = working ? -Math.sin(t * 9 + i + 1.4) * .25 : 0;
    if (right) right.rotation.x = working && ch.wave <= 0 ? -.6 : 0; if (left) left.rotation.x = working ? -.6 : 0;
  }
  pods.forEach(({root, curve, phase}) => { const pos = (t * .035 + phase) % 1; root.position.copy(curve.getPointAt(pos)); const tan = curve.getTangentAt(pos); root.rotation.y = Math.atan2(tan.x, tan.z); });
  if (inside) for (const ch of floorMeta.get(state.floor).chars) {
    if (!ch.tag) continue; const p = project(ch.root.getWorldPosition(tmp).add(up));
    ch.tag.style.transform = `translate(${p.x.toFixed(1)}px,${p.y.toFixed(1)}px) translate(-50%,-100%)`;
  }
  if (state.selected) {
    const p = project(state.selected.root.getWorldPosition(tmp).add(new THREE.Vector3(0, 2.2, 0)));
    $('#speech').style.left = THREE.MathUtils.clamp(p.x, 125, innerWidth - 125) + 'px'; $('#speech').style.top = THREE.MathUtils.clamp(p.y, 270, innerHeight - 50) + 'px';
  }
  renderer.render(scene, camera); frames++;
  // Expose actual render progress only to the synthetic browser check; production has no per-frame DOM writes.
  if (window.__TICO_OVERVIEW_TEST_PROBE__) { window.__TICO_OVERVIEW_TEST_PROBE__.frame = frames; window.__TICO_OVERVIEW_TEST_PROBE__.time = t; }
  if (frames === 2) { $('#loading').classList.add('gone'); loadingTimer = setTimeout(() => $('#loading').hidden = true, 250); document.body.dataset.sceneReady = 'true'; }
  frameId = requestAnimationFrame(animate);
}
on(document, 'visibilitychange', () => { if (!document.hidden && !frameId) { last = 0; frameId = requestAnimationFrame(animate); } });
const remembered = FLOORS.findIndex(f => f.key === preferences.floorId);
setFloor(remembered >= 0 ? remembered : null);
// Start from where the camera will settle: no swoop on first paint.
{ const d = desiredCamera(); currentTarget.copy(d.target); currentPosition.copy(d.position); currentScale = d.scale * 1.08; }
renderer.compile(scene, camera);
frameId = requestAnimationFrame(animate);
return {
  select(key) { const id = FLOORS.findIndex(f => f.group.key === key); setFloor(id >= 0 ? id : null); },
  update(next) {
    data = next;
    const members = new Map(next.groups.flatMap(g => g.members).map(m => [m.id, m]));
    for (const f of FLOORS) { const g = next.groups.find(x => x.key === f.group.key); if (g) f.members = g.members.slice(f.part * PER_FLOOR, (f.part + 1) * PER_FLOOR); }
    for (const ch of characters) {
      const member = members.get(ch.actorId); if (!member) continue;
      ch.activity = member.state; ch.message = member.detail; ch.href = member.href;
      if (ch.tag) { ch.tag.dataset.state = mood(ch); ch.tag.setAttribute('aria-label', ch.name + ' · ' + ch.message); }
    }
    if (state.floor !== null) $('#floor-subtitle').textContent = subtitle(FLOORS[state.floor]);
    if (state.selected) sayHi(state.selected);
  },
  dispose() {
    controller.abort(); clearTimeout(loadingTimer); cancelAnimationFrame(frameId);
    scene.traverse(o => { if (o.geometry) resources.add(o.geometry); if (o.material) { resources.add(o.material); if (o.material.map) resources.add(o.material.map); } });
    geos.forEach(g => resources.add(g)); mats.forEach(m => resources.add(m)); resources.forEach(r => r.dispose?.());
    renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); $('#people').replaceChildren();
  }
};
}
