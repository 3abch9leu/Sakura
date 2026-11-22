// @ts-nocheck
/*
 * INBETWEEN living lattice: the 3D prototype of the landing page.
 * Ported from inbetween-lattice.html (same scene, same logic); data from samples/make_lattice_model.py
 * (geometry, HydroEngine allocation, SolarEngine sun) served as /data/lattice-model.json.
 * Three.js comes from the site's own bundle (lazy chunk), no CDN.
 */
export interface LatticeHandle { setVisible(v: boolean): void; dispose(): void }

export async function mountLattice(root: HTMLElement, M: any): Promise<LatticeHandle> {
  const THREE = await import("three");
  const { OrbitControls } = await import("three/examples/jsm/controls/OrbitControls.js");
  const { CSS2DRenderer, CSS2DObject } = await import("three/examples/jsm/renderers/CSS2DRenderer.js");
  const { RoundedBoxGeometry } = await import("three/examples/jsm/geometries/RoundedBoxGeometry.js");
  const { RoomEnvironment } = await import("three/examples/jsm/environments/RoomEnvironment.js");
  const q = (sel) => root.querySelector(sel);
  const state = { visible: true };

  const stage = q("#stage");
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 0.95;
  stage.appendChild(renderer.domElement);
  const labels = new CSS2DRenderer();
  Object.assign(labels.domElement.style, { position: "absolute", inset: "0", pointerEvents: "none" });
  stage.appendChild(labels.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xefe9dd);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;
  scene.environmentIntensity = 0.45;
  const camera = new THREE.PerspectiveCamera(34, 1, 0.02, 50);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true; controls.minDistance = 0.35; controls.maxDistance = 5; controls.maxPolarAngle = Math.PI * 0.5;

  scene.add(new THREE.HemisphereLight(0xfff6ea, 0xb8a98f, 0.55));
  const sun = new THREE.DirectionalLight(0xfff0d6, 2.4);
  sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -1.2, right: 1.2, top: 1.2, bottom: -1.2, near: 0.2, far: 8 });
  sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.01; sun.shadow.radius = 4;
  sun.target.position.set(0, 0.8, 0); scene.add(sun, sun.target);
  sun.position.set(1.6, 2.6, 2.2);

  // ---------------------------------------------------------------- materials
  function woodTexture() {
    const c = document.createElement("canvas"); c.width = 1024; c.height = 128;
    const g = c.getContext("2d");
    g.fillStyle = "#b5865a"; g.fillRect(0, 0, 1024, 128);
    for (let i = 0; i < 70; i++) {
      const y = Math.random() * 128, a = 0.05 + Math.random() * 0.12;
      g.strokeStyle = `rgba(90,55,28,${a})`; g.lineWidth = 0.6 + Math.random() * 2;
      g.beginPath(); g.moveTo(0, y);
      for (let x = 0; x <= 1024; x += 32) g.lineTo(x, y + Math.sin(x / 90 + i) * 3 + (Math.random() - 0.5) * 1.5);
      g.stroke();
    }
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 8; return t;
  }
  function clayTexture() {
    const c = document.createElement("canvas"); c.width = c.height = 256;
    const g = c.getContext("2d"); g.fillStyle = "#b8643c"; g.fillRect(0, 0, 256, 256);
    for (let i = 0; i < 2500; i++) { g.fillStyle = `rgba(${Math.random() < 0.5 ? "70,30,15" : "235,170,130"},${Math.random() * 0.08})`; g.fillRect(Math.random() * 256, Math.random() * 256, 2, 2); }
    const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.wrapS = t.wrapT = THREE.RepeatWrapping; return t;
  }
  const WOOD = woodTexture(), CLAYT = clayTexture();
  const woodMat = new THREE.MeshStandardMaterial({ map: WOOD, roughness: 0.72, metalness: 0 });
  const hubMat = new THREE.MeshStandardMaterial({ map: CLAYT, color: 0xa8775c, roughness: 0.85 });
  const insertMat = new THREE.MeshStandardMaterial({ map: CLAYT, roughness: 0.9 });
  const shadeMat = new THREE.MeshStandardMaterial({ map: CLAYT, color: 0xf7e7da, roughness: 0.85, side: THREE.DoubleSide });
  const soilMat = new THREE.MeshStandardMaterial({ color: 0x3f2c20, roughness: 1 });
  const steelMat = new THREE.MeshStandardMaterial({ color: 0x6f777b, roughness: 0.45, metalness: 0.6 });
  const chanMat = new THREE.MeshStandardMaterial({ color: 0x2a86c4, roughness: 0.25, emissive: 0x0b2a44, emissiveIntensity: 0.6 });
  const linerMat = new THREE.MeshStandardMaterial({ color: 0xd6e6ef, roughness: 0.2, transparent: true, opacity: 0.35, depthWrite: false });
  const waterMat = new THREE.MeshStandardMaterial({ color: 0x2f8fd0, roughness: 0.1, transparent: true, opacity: 0.85 });
  const wickMat = new THREE.MeshStandardMaterial({ color: 0xf1ebdf, roughness: 1 });
  const drainMat = new THREE.MeshStandardMaterial({ color: 0x8fb7cf, roughness: 0.3, transparent: true, opacity: 0.8 });
  const fadeable = [woodMat, hubMat, insertMat, shadeMat, soilMat];
  fadeable.forEach((m) => (m.userData.baseOpacity = 1));

  // ---------------------------------------------------------------- stage
  const floor = new THREE.Mesh(new THREE.CircleGeometry(6, 64), new THREE.MeshStandardMaterial({ color: 0xece4d6, roughness: 0.95 }));
  floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; scene.add(floor);
  const wall = new THREE.Mesh(new THREE.PlaneGeometry(5, 3.2), new THREE.MeshStandardMaterial({ color: 0xf3ede3, roughness: 0.95 }));
  wall.position.set(0, 1.6, -0.22); wall.receiveShadow = true; wall.visible = false; scene.add(wall);

  // ---------------------------------------------------------------- lattice data
  const V = M.verts.map(([x, y]) => new THREE.Vector3(x, y, 0));
  const D = 0.12;                                       // structural depth of struts (m)
  const edgeCount = new Map();
  for (const c of M.cells) { const v = c.v; for (const [a, b] of [[v[0], v[1]], [v[1], v[2]], [v[2], v[0]]]) { const k = [a, b].sort((x, y) => x - y).join("-"); edgeCount.set(k, (edgeCount.get(k) || 0) + 1); } }
  const floorEdges = new Map();
  for (const c of M.cells) if (c.role === "plant") floorEdges.set([...c.floor].sort((x, y) => x - y).join("-"), c);

  const groups = {
    structure: new THREE.Group(), shading: new THREE.Group(), inserts: new THREE.Group(), plants: new THREE.Group(),
    channels: new THREE.Group(), reservoirs: new THREE.Group(), drainage: new THREE.Group(), frame: new THREE.Group(), electronics: new THREE.Group(),
  };
  for (const g of Object.values(groups)) scene.add(g);
  const EXPLODE = {
    structure: [0, 0, 0], shading: [0, 0, 0.16], inserts: [0, 0, 0.34], plants: [0, 0, 0.34],
    channels: [0, 0, -0.2], reservoirs: [0, -0.02, -0.38], drainage: [0, -0.06, -0.2], frame: [0, 0, -0.58], electronics: [0.42, 0, 0.1],
  };

  // struts
  for (const [a, b] of M.edges) {
    const key = `${a}-${b}`, pa = V[a], pb = V[b];
    const len = pa.distanceTo(pb);
    const isFloor = floorEdges.has(key), outer = edgeCount.get(key) === 1;
    const th = isFloor ? 0.062 : outer ? 0.044 : 0.032;
    const geo = new RoundedBoxGeometry(len - 0.05, th, D, 3, 0.007);
    const uv = geo.attributes.uv; for (let i = 0; i < uv.count; i++) uv.setX(i, uv.getX(i) * len * 3);
    const m = new THREE.Mesh(geo, woodMat);
    m.position.copy(pa).lerp(pb, 0.5); m.rotation.z = Math.atan2(pb.y - pa.y, pb.x - pa.x);
    if (isFloor) m.position.y -= 0.008;
    m.castShadow = m.receiveShadow = true; m.userData = { kind: "strut" };
    groups.structure.add(m);
  }
  // eight-point star connectors (Tunisian)
  function starShape(R, r) {
    const s = new THREE.Shape();
    for (let k = 0; k < 16; k++) { const rad = k % 2 ? r : R, a = Math.PI / 8 * k + Math.PI / 16; k ? s.lineTo(rad * Math.cos(a), rad * Math.sin(a)) : s.moveTo(rad * Math.cos(a), rad * Math.sin(a)); }
    s.closePath(); return s;
  }
  const hubGeo = new THREE.ExtrudeGeometry(starShape(0.042, 0.03), { depth: D + 0.014, bevelEnabled: true, bevelThickness: 0.003, bevelSize: 0.003, bevelSegments: 2 });
  hubGeo.translate(0, 0, -(D + 0.014) / 2);
  const pinGeo = new THREE.CylinderGeometry(0.006, 0.006, 0.006, 12); pinGeo.rotateX(Math.PI / 2);
  V.forEach((p) => {
    const h = new THREE.Mesh(hubGeo, hubMat); h.position.copy(p); h.castShadow = h.receiveShadow = true; h.userData = { kind: "hub" }; groups.structure.add(h);
    const pin = new THREE.Mesh(pinGeo, steelMat); pin.position.set(p.x, p.y, D / 2 + 0.012); groups.structure.add(pin);
  });

  // ---------------------------------------------------------------- cells
  const cellInfo = new Map();
  const centroid = (c) => new THREE.Vector3().add(V[c.v[0]]).add(V[c.v[1]]).add(V[c.v[2]]).multiplyScalar(1 / 3);
  const S = M.S, H = M.H;
  function trapezoid(yb, y0, y1, inset) {          // planting insert outline inside an upward cell
    const hw = (y) => (S / 2) * (1 - (y - yb) / H) - inset;
    const s = new THREE.Shape();
    s.moveTo(-hw(y0), y0 - yb); s.lineTo(hw(y0), y0 - yb); s.lineTo(hw(y1), y1 - yb); s.lineTo(-hw(y1), y1 - yb); s.closePath();
    return s;
  }
  const petal = new THREE.Shape();
  petal.moveTo(0, 0); petal.bezierCurveTo(0.03, 0.012, 0.034, 0.05, 0.012, 0.062); petal.lineTo(0, 0.054); petal.lineTo(-0.012, 0.062); petal.bezierCurveTo(-0.034, 0.05, -0.03, 0.012, 0, 0);
  const petalGeo = new THREE.ExtrudeGeometry(petal, { depth: 0.012, bevelEnabled: true, bevelThickness: 0.002, bevelSize: 0.002, bevelSegments: 1 });
  petalGeo.translate(0, 0.004, -0.006);

  for (const c of M.cells) {
    const ctr = centroid(c);
    if (c.role === "plant") {
      const [fa, fb] = c.floor.map((i) => V[i]);
      const yb = fa.y, cx = (fa.x + fb.x) / 2;
      const y0 = yb + 0.03, y1 = yb + 0.118;
      const g = new THREE.ExtrudeGeometry(trapezoid(yb, y0, y1, 0.028), { depth: 0.1, bevelEnabled: true, bevelThickness: 0.004, bevelSize: 0.004, bevelSegments: 2 });
      g.translate(0, 0, -0.05);
      const ins = new THREE.Mesh(g, insertMat); ins.position.set(cx, yb, 0); ins.castShadow = ins.receiveShadow = true; ins.userData = { kind: "insert", cell: c.id };
      groups.inserts.add(ins);
      const sg = new THREE.ShapeGeometry(trapezoid(yb, y1 - 0.004, y1 - 0.003, 0.036)); // thin soil top
      const soil = new THREE.Mesh(new THREE.ExtrudeGeometry(trapezoid(yb, y1 - 0.016, y1 - 0.004, 0.035), { depth: 0.088, bevelEnabled: false }), soilMat);
      soil.geometry.translate(0, 0, -0.044); soil.position.set(cx, yb, 0); soil.userData = { kind: "insert", cell: c.id }; groups.inserts.add(soil);
      const lip = new THREE.Mesh(new RoundedBoxGeometry(0.04, 0.012, 0.012, 2, 0.004), insertMat);
      lip.position.set(cx, y1 - 0.01, 0.058); lip.userData = { kind: "insert", cell: c.id }; groups.inserts.add(lip);
      const hole = new THREE.Mesh(new THREE.CircleGeometry(0.006, 16), new THREE.MeshBasicMaterial({ color: 0x2a1a12 }));
      hole.position.set(cx + 0.04, y0 + 0.012, 0.0545); groups.inserts.add(hole);
      // compartment in the floor beam
      const comp = M.compartment;
      const liner = new THREE.Mesh(new THREE.BoxGeometry(comp.len, comp.h, comp.d), linerMat);
      liner.position.set(cx, yb - 0.008, 0); liner.userData = { kind: "reservoir", cell: c.id };
      const water = new THREE.Mesh(new THREE.BoxGeometry(comp.len - 0.006, 1, comp.d - 0.006), waterMat.clone());
      water.userData = { kind: "reservoir", cell: c.id };
      groups.reservoirs.add(liner, water);
      const wick = new THREE.Mesh(new THREE.CylinderGeometry(0.004, 0.004, y1 - (yb - 0.02), 8), wickMat);
      wick.position.set(cx - 0.02, (y1 + yb - 0.02) / 2, 0.01); groups.reservoirs.add(wick);
      cellInfo.set(c.id, { c, cx, yb, y1, liner, water, plantBase: new THREE.Vector3(cx, y1 - 0.006, 0.0) });
    } else if (c.role === "asanoha") {
      for (const vi of c.v) {
        const p = V[vi], len = p.distanceTo(ctr) - 0.045;
        const fin = new THREE.Mesh(new RoundedBoxGeometry(len, 0.012, 0.085, 2, 0.003), shadeMat);
        fin.position.copy(ctr).lerp(p, 0.5 - 0.02 / p.distanceTo(ctr)); fin.rotation.z = Math.atan2(p.y - ctr.y, p.x - ctr.x);
        fin.castShadow = true; fin.userData = { kind: "shade" }; groups.shading.add(fin);
      }
      const knot = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.012, 0.09, 16), shadeMat); knot.rotation.x = Math.PI / 2; knot.position.copy(ctr); knot.castShadow = true; groups.shading.add(knot);
    } else if (c.role === "sakura") {
      for (let k = 0; k < 5; k++) {
        const p = new THREE.Mesh(petalGeo, shadeMat); p.position.copy(ctr); p.rotation.z = k * 2 * Math.PI / 5 + (c.kind === "down" ? Math.PI : 0);
        p.castShadow = true; p.userData = { kind: "shade" }; groups.shading.add(p);
      }
      const ctrM = new THREE.Mesh(new THREE.CylinderGeometry(0.01, 0.01, 0.02, 16), new THREE.MeshStandardMaterial({ color: 0xc9a24a, roughness: 0.6 }));
      ctrM.rotation.x = Math.PI / 2; ctrM.position.copy(ctr); groups.shading.add(ctrM);
    }
  }

  // ---------------------------------------------------------------- plants (instanced, per species)
  function leafGeometry(L, W, curl, fold) {
    const s = new THREE.Shape();
    s.moveTo(0, 0); s.quadraticCurveTo(W, L * 0.35, 0, L); s.quadraticCurveTo(-W, L * 0.35, 0, 0);
    const g = new THREE.ShapeGeometry(s, 8); const p = g.attributes.position;
    for (let i = 0; i < p.count; i++) { const x = p.getX(i), y = p.getY(i); p.setZ(i, curl * (y / L) ** 2 * L + fold * Math.abs(x)); }
    g.computeVertexNormals(); return g;
  }
  const leafMat = new THREE.MeshStandardMaterial({ roughness: 0.6, side: THREE.DoubleSide });
  const SPECIES = {
    mint: { geo: leafGeometry(0.05, 0.024, -0.25, 0.25), cols: [0x4f9a3e, 0x62ad4c] },
    basil: { geo: leafGeometry(0.068, 0.038, -0.35, 0.3), cols: [0x3b8a31, 0x4c9b3c] },
    strawberry: { geo: leafGeometry(0.046, 0.034, -0.2, 0.15), cols: [0x356f2f, 0x427f38] },
    lettuce: { geo: leafGeometry(0.09, 0.06, 0.35, 0.05), cols: [0x8cc46a, 0xa6d27f] },
    rosemary: { geo: leafGeometry(0.028, 0.004, -0.1, 0), cols: [0x6d8c69, 0x7f9c78] },
  };
  const rnd = (() => { let s = 11; return () => ((s = (s * 1664525 + 1013904223) >>> 0) / 4294967296); })();
  const leafXf = Object.fromEntries(Object.keys(SPECIES).map((k) => [k, []]));
  const stems = [], fruits = [], flowers = [];
  const tmp = new THREE.Object3D();
  function addLeaf(sp, pos, yaw, pitch, scale, cell) { leafXf[sp].push({ pos, yaw, pitch, scale, cell }); }
  for (const [id, info] of cellInfo) {
    const sp = info.c.plant, b = info.plantBase;
    if (sp === "mint" || sp === "basil") {
      const nStems = sp === "mint" ? 5 : 4;
      for (let s = 0; s < nStems; s++) {
        const sx = b.x + (rnd() - 0.5) * 0.08, sz = (rnd() - 0.5) * 0.05, hgt = (sp === "mint" ? 0.1 : 0.12) + rnd() * 0.04;
        stems.push({ a: new THREE.Vector3(sx, b.y, sz), b: new THREE.Vector3(sx + (rnd() - 0.5) * 0.02, b.y + hgt, sz), r: 0.0018, cell: id });
        const step = sp === "mint" ? 0.02 : 0.028;
        for (let y = 0.02, k = 0; y < hgt; y += step, k++) for (const side of [0, Math.PI]) {
          const t = 1 - y / hgt * 0.5;
          addLeaf(sp, new THREE.Vector3(sx, b.y + y, sz), side + k * Math.PI / 2, 1.0 - y / hgt * 0.4, t * (0.9 + rnd() * 0.3), id);
        }
      }
    } else if (sp === "strawberry") {
      for (let s = 0; s < 6; s++) {
        const yaw = s / 6 * Math.PI * 2 + rnd() * 0.4, L = 0.06 + rnd() * 0.03;
        const tip = new THREE.Vector3(b.x + Math.cos(yaw) * L * 0.55, b.y + L * 0.8, Math.sin(yaw) * L * 0.4);
        stems.push({ a: b.clone(), b: tip, r: 0.0015, cell: id });
        for (let l = 0; l < 3; l++) addLeaf(sp, tip.clone(), yaw + (l - 1) * 0.9, 0.9, 1, id);
      }
      for (let f = 0; f < 3; f++) fruits.push({ p: new THREE.Vector3(b.x - 0.035 + f * 0.035, b.y - 0.005 - rnd() * 0.02, 0.055 + rnd() * 0.01), cell: id });
      for (let f = 0; f < 2; f++) flowers.push({ p: new THREE.Vector3(b.x + (rnd() - 0.5) * 0.06, b.y + 0.05 + rnd() * 0.02, 0.03), cell: id });
    } else if (sp === "lettuce") {
      for (let l = 0; l < 13; l++) { const yaw = l * 2.4, inner = l > 7; addLeaf(sp, b.clone().add(new THREE.Vector3(0, 0.004, 0)), yaw, inner ? 0.35 : 0.95, inner ? 0.75 : 1, id); }
    } else if (sp === "rosemary") {
      for (let s = 0; s < 6; s++) {
        const sx = b.x + (rnd() - 0.5) * 0.08, sz = (rnd() - 0.5) * 0.04, hgt = 0.1 + rnd() * 0.05;
        stems.push({ a: new THREE.Vector3(sx, b.y, sz), b: new THREE.Vector3(sx + (rnd() - 0.5) * 0.03, b.y + hgt, sz), r: 0.0022, cell: id, woody: true });
        for (let y = 0.015; y < hgt; y += 0.007) addLeaf(sp, new THREE.Vector3(sx + (y / hgt) * (rnd() - 0.5) * 0.01, b.y + y, sz), rnd() * Math.PI * 2, 0.6 + rnd() * 0.5, 1, id);
      }
    }
  }
  const plantMeshes = [];
  for (const [sp, list] of Object.entries(leafXf)) {
    if (!list.length) continue;
    const im = new THREE.InstancedMesh(SPECIES[sp].geo, leafMat, list.length);
    const col = SPECIES[sp].cols.map((c) => new THREE.Color(c));
    list.forEach((l, i) => {
      tmp.position.copy(l.pos); tmp.rotation.set(0, 0, 0); tmp.rotateY(l.yaw); tmp.rotateX(-l.pitch); tmp.scale.setScalar(l.scale); tmp.updateMatrix();
      im.setMatrixAt(i, tmp.matrix); im.setColorAt(i, col[i % 2].clone().multiplyScalar(0.9 + rnd() * 0.2));
    });
    im.castShadow = true; im.userData = { kind: "plant", cells: list.map((l) => l.cell) }; groups.plants.add(im); plantMeshes.push(im);
  }
  {
    const im = new THREE.InstancedMesh(new THREE.CylinderGeometry(1, 1, 1, 6), new THREE.MeshStandardMaterial({ roughness: 0.8 }), stems.length);
    const up = new THREE.Vector3(0, 1, 0);
    stems.forEach((s, i) => {
      const dir = s.b.clone().sub(s.a), len = dir.length();
      tmp.position.copy(s.a).addScaledVector(dir, 0.5); tmp.quaternion.setFromUnitVectors(up, dir.normalize()); tmp.scale.set(s.r, len, s.r); tmp.updateMatrix();
      im.setMatrixAt(i, tmp.matrix); im.setColorAt(i, new THREE.Color(s.woody ? 0x6b5a3e : 0x4f7a37));
    });
    im.castShadow = true; groups.plants.add(im);
    const fr = new THREE.InstancedMesh(new THREE.SphereGeometry(0.008, 12, 10), new THREE.MeshStandardMaterial({ color: 0xc0281f, roughness: 0.35 }), fruits.length);
    fruits.forEach((f, i) => { tmp.position.copy(f.p); tmp.rotation.set(0, 0, 0); tmp.scale.set(1, 1.3, 1); tmp.updateMatrix(); fr.setMatrixAt(i, tmp.matrix); });
    fr.castShadow = true; groups.plants.add(fr);
    const fl = new THREE.InstancedMesh(new THREE.CircleGeometry(0.007, 5), new THREE.MeshStandardMaterial({ color: 0xfbfaf4, side: THREE.DoubleSide }), flowers.length);
    flowers.forEach((f, i) => { tmp.position.copy(f.p); tmp.rotation.set(0, 0, 0); tmp.scale.set(1, 1, 1); tmp.updateMatrix(); fl.setMatrixAt(i, tmp.matrix); });
    groups.plants.add(fl);
  }

  // ---------------------------------------------------------------- hidden channels (gravity paths from HydroEngine routing)
  const pathCurves = new Map(), drainCurves = new Map();
  function poly(pts) { const p = new THREE.CurvePath(); for (let i = 0; i < pts.length - 1; i++) p.add(new THREE.LineCurve3(pts[i], pts[i + 1])); return p; }
  const chanSeen = new Set();
  const chanGeo = (a, b, r) => { const len = a.distanceTo(b); const g = new THREE.CylinderGeometry(r, r, len, 8); const m = new THREE.Mesh(g, chanMat); m.position.copy(a).lerp(b, 0.5); m.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize()); return m; };
  for (const [id, info] of cellInfo) {
    const c = info.c;
    const pts = c.path.map((i) => V[i].clone());
    pts.push(new THREE.Vector3(info.cx, info.yb - 0.008, 0));
    pathCurves.set(id, poly(pts));
    for (let i = 0; i < c.path.length - 1; i++) { const k = [c.path[i], c.path[i + 1]].sort().join("-"); if (chanSeen.has(k)) continue; chanSeen.add(k); groups.channels.add(chanGeo(V[c.path[i]], V[c.path[i + 1]], 0.0045)); }
    const dpts = [new THREE.Vector3(info.cx, info.yb - 0.01, 0.03), ...c.drain.map((i) => V[i].clone().setZ(0.03)), new THREE.Vector3(V[c.drain[c.drain.length - 1]].x, 0.2, 0.03)];
    drainCurves.set(id, poly(dpts));
    for (let i = 0; i < dpts.length - 1; i++) { const m = chanGeo(dpts[i], dpts[i + 1], 0.0025); m.material = drainMat; groups.drainage.add(m); }
  }
  // visible supply tube from above (the only external supply part)
  const SUP = V[M.supply_vertex];
  const supplyCurve = new THREE.CatmullRomCurve3([SUP.clone().setY(SUP.y + 0.02), SUP.clone().setY(SUP.y + 0.35), SUP.clone().add(new THREE.Vector3(0.0, 0.6, -0.12)), SUP.clone().add(new THREE.Vector3(0, 0.85, -0.2))]);
  const supplyTube = new THREE.Mesh(new THREE.TubeGeometry(supplyCurve, 40, 0.0045, 10), new THREE.MeshStandardMaterial({ color: 0x3a4246, roughness: 0.5 }));
  supplyTube.castShadow = true; scene.add(supplyTube);
  const clamp = new THREE.Mesh(new THREE.CylinderGeometry(0.009, 0.009, 0.025, 16), steelMat); clamp.position.copy(SUP).setY(SUP.y + 0.04); scene.add(clamp);

  // ---------------------------------------------------------------- base: drip tray, jar, frame
  const minX = Math.min(...V.map((v) => v.x)), maxX = Math.max(...V.map((v) => v.x)), topY = Math.max(...V.map((v) => v.y));
  const tray = new THREE.Mesh(new RoundedBoxGeometry(maxX - minX + 0.08, 0.035, 0.16, 2, 0.006), new THREE.MeshStandardMaterial({ color: 0x8d9aa0, roughness: 0.45, metalness: 0.3 }));
  tray.position.set(0, 0.2, 0); tray.castShadow = tray.receiveShadow = true; groups.drainage.add(tray);
  const jar = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.055, 0.14, 24), new THREE.MeshStandardMaterial({ map: CLAYT, roughness: 0.85 }));
  jar.position.set(maxX + 0.12, 0.07 + 0.06, 0.05); jar.castShadow = true; groups.drainage.add(jar);
  groups.drainage.add(chanGeo(new THREE.Vector3(maxX + 0.02, 0.2, 0.0), new THREE.Vector3(maxX + 0.12, 0.2, 0.05), 0.004));
  const plinth = new THREE.Mesh(new RoundedBoxGeometry(maxX - minX + 0.3, 0.07, 0.42, 2, 0.01), woodMat);
  plinth.position.set(0, 0.035, -0.04); plinth.castShadow = plinth.receiveShadow = true; groups.frame.add(plinth);
  for (const x of [minX + 0.15, maxX - 0.15]) {
    const post = new THREE.Mesh(new RoundedBoxGeometry(0.03, topY + 0.02, 0.03, 2, 0.004), steelMat);
    post.position.set(x, (topY + 0.02) / 2 + 0.07, -0.095); post.castShadow = true; groups.frame.add(post);
  }
  V.forEach((p) => { if (Math.abs(Math.abs(p.x) - (maxX - 0.15)) < 0.02) { const br = new THREE.Mesh(new THREE.BoxGeometry(0.02, 0.02, 0.05), steelMat); br.position.set(p.x, p.y, -0.07); groups.frame.add(br); } });
  groups.drainage.add(chanGeo(new THREE.Vector3(minX + 0.15, 0.1, -0.1), new THREE.Vector3(minX + 0.15, 0.19, -0.02), 0.003));

  // optional monitoring station
  {
    const box = new THREE.Mesh(new RoundedBoxGeometry(0.1, 0.05, 0.07, 2, 0.006), new THREE.MeshStandardMaterial({ color: 0xe8e4dc, roughness: 0.6 }));
    box.position.set(maxX + 0.05, 0.095, 0.15); box.castShadow = true; groups.electronics.add(box);
    const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.06, 0.02), new THREE.MeshBasicMaterial({ color: 0x1b4fa8 })); scr.position.set(maxX + 0.05, 0.1, 0.1855); groups.electronics.add(scr);
    const low = [...cellInfo.values()].sort((a, b) => a.yb - b.yb)[0];
    const probe = new THREE.Mesh(new THREE.BoxGeometry(0.012, 0.05, 0.004), new THREE.MeshStandardMaterial({ color: 0x16324f })); probe.position.set(low.cx + 0.06, low.yb - 0.008, 0.03); groups.electronics.add(probe);
    const wire = new THREE.Mesh(new THREE.TubeGeometry(new THREE.CatmullRomCurve3([probe.position.clone(), new THREE.Vector3(low.cx + 0.2, 0.15, 0.1), new THREE.Vector3(maxX + 0.05, 0.12, 0.15)]), 24, 0.0015, 6), new THREE.MeshStandardMaterial({ color: 0x2a2a2a }));
    groups.electronics.add(wire);
  }

  // ---------------------------------------------------------------- water state (HydroEngine numbers + simulated levels)
  let orient = "W", tuned = true;
  const hydro = () => M.hydro[orient];
  const cellHydro = (id) => hydro().cells.find((h) => h.id === id);
  const CAP = M.compartment.litres;
  const level = new Map();
  [...cellInfo.keys()].forEach((id, i) => level.set(id, CAP * (0.35 + ((i * 37) % 60) / 100)));
  let simDays = 0, simOn = false;
  function waterStatus(id) {
    const h = cellHydro(id), litres = level.get(id), auto = litres / h.need_l_day;
    const supply = tuned ? h.alloc_l_day : h.alloc_equal_l_day;
    const st = auto < 1 ? "crit" : auto < 2 ? "warn" : "ok";
    return { h, litres, auto, supply, st };
  }
  function updateWaterMeshes() {
    for (const [id, info] of cellInfo) {
      const f = Math.max(0.02, level.get(id) / CAP), hgt = (M.compartment.h - 0.004) * f;
      info.water.scale.y = hgt; info.water.position.set(info.cx, info.yb - 0.008 - M.compartment.h / 2 + 0.002 + hgt / 2, 0);
      const st = waterStatus(id).st; info.water.material.color.set(st === "crit" ? 0xc0392b : st === "warn" ? 0xd9a43a : 0x2f8fd0);
    }
  }
  updateWaterMeshes();

  // ---------------------------------------------------------------- pins
  const pins = [];
  for (const [id, info] of cellInfo) {
    const n = [...cellInfo.keys()].indexOf(id) + 1;
    const el = document.createElement("div"); el.className = "pin hidden"; el.textContent = n; el.style.pointerEvents = "auto";
    el.addEventListener("click", (e) => { e.stopPropagation(); selectCell(id); });
    const o = new CSS2DObject(el); o.position.set(info.cx, info.y1 + 0.13, 0.07); scene.add(o);
    pins.push({ id, el, o, n });
  }

  // ---------------------------------------------------------------- panel content
  const panel = q("#panel");
  let mode = "architecture", selected = null;
  const fmt = (x, d = 2) => Number(x).toFixed(d);
  const plantName = { mint: "Mint", basil: "Basil", strawberry: "Strawberry", lettuce: "Lettuce", rosemary: "Rosemary" };
  const insertVolL = 0.9;
  function renderPanel() {
    const hy = hydro();
    if (mode === "architecture") {
      panel.innerHTML = `<p class="eyebrow">Architecture</p><h2>The geometry is the growing structure</h2>
        <p>24 asanoha cells, 0.30 m each, form one interconnected lattice 1.05 × 1.04 m. Ten flat-floored cells hold plants, eight pointed cells shade with asanoha fins or sakura blossoms, and the rest stay open for light and air.</p>
        <dl class="kv"><dt>Cells</dt><dd>24 (10 planted · 8 shading · 6 open)</dd><dt>Strut depth</dt><dd>120 mm</dd><dt>Connectors</dt><dd>${V.length} eight-point stars</dd><dt>Water inside</dt><dd>${fmt(CAP * cellInfo.size, 1)} L in 10 compartments</dd></dl>
        <p class="src">Treated wood struts, terracotta connectors and inserts. Waterproof liners and tubing do the water work: wood and clay are never assumed watertight.</p>`;
    } else if (mode === "planting") {
      if (selected == null) {
        panel.innerHTML = `<p class="eyebrow">Planting pockets</p><h2>Click a growing cell</h2><p>Each planted cell has a removable terracotta insert sitting on the floor beam, about ${insertVolL} L of light growing medium, root space below the surface, a wick from its own water compartment and a drainage hole.</p>${cellTable()}`;
      } else {
        const { h, auto } = waterStatus(selected);
        panel.innerHTML = `<p class="eyebrow">Planting cell ${pins.find((p) => p.id === selected).n} · row ${cellInfo.get(selected).c.row + 1}</p><h2>${plantName[h.plant]}</h2>
          <dl class="kv"><dt>Water need (July, this facade)</dt><dd>${fmt(h.need_l_day)} L/day</dd><dt>Delivered, AI-tuned inlet</dt><dd>${fmt(h.alloc_l_day)} L/day</dd><dt>Inlet labyrinth width</dt><dd>${fmt(h.inlet_mm)} mm</dd>
          <dt>Container</dt><dd>removable terracotta insert</dd><dt>Growing medium</dt><dd>≈ ${insertVolL} L, 9 cm deep</dd><dt>Compartment below</dt><dd>${fmt(CAP)} L, ${fmt(auto, 1)} days</dd></dl>
          <p class="src">Need: config plant demand scaled by SolarEngine irradiance for this orientation. Delivery: HydroEngine channel model for this lattice.</p>${cellTable()}`;
      }
    } else if (mode === "water") {
      const sim = `<span class="badge sim">${window.INBETWEEN_SENSOR ? "LIVE SENSOR" : "SIMULATION"}</span>`;
      let mon = "";
      if (selected != null) {
        const s = waterStatus(selected), need = s.h.need_l_day;
        const badge = s.st === "crit" ? `<span class="badge crit">REFILL NOW</span>` : s.st === "warn" ? `<span class="badge warn">REFILL SOON</span>` : `<span class="badge ok">OK</span>`;
        const refill = Math.max(0, CAP - s.litres);
        mon = `<div><p class="eyebrow">Compartment ${pins.find((p) => p.id === selected).n} · cutaway</p><h2>${plantName[s.h.plant]} reservoir ${badge}</h2>
          <div class="level"><div style="width:${fmt(100 * s.litres / CAP, 0)}%"></div></div>
          <dl class="kv"><dt>Capacity</dt><dd>${fmt(CAP)} L</dd><dt>Estimated remaining</dt><dd>${fmt(s.litres)} L</dd><dt>Connected plant</dt><dd>${plantName[s.h.plant]}</dd><dt>Daily requirement</dt><dd>${fmt(need)} L/day</dd><dt>Autonomy</dt><dd>${fmt(s.auto, 1)} days</dd></dl>
          <p>${s.st === "ok" ? `No action needed. Next top-up of about ${fmt(refill, 1)} L ${s.auto - 2 >= 1 ? `within ${fmt(s.auto - 2, 1)} days` : "within a day"}.` : `Open the supply valve or pour about ${fmt(refill, 1)} L into the header: less than ${s.st === "crit" ? "one day" : "two days"} of water is left for this plant.`}</p>
          <p class="src">Alert = remaining litres ÷ this plant’s daily need, not a fixed percentage. ${sim}</p>
          <div class="btnrow"><button id="refill">Refill this compartment</button><button id="refill-all">Refill all</button></div></div>`;
      }
      panel.innerHTML = `${mon}<p class="eyebrow">Water distribution · HydroEngine</p><h2>${mon ? "Whole lattice" : "Gravity, from top to roots"}</h2>
        <dl class="kv"><dt>Daily supply (10 % to drainage)</dt><dd>${fmt(hy.supply_l_day)} L</dd><dt>Storage capacity</dt><dd>${fmt(CAP * cellInfo.size, 1)} L</dd><dt>Highest head</dt><dd>${fmt(hy.max_head_m)} m · ${fmt(hy.max_pressure_kpa, 1)} kPa</dd>
        <dt>Delivery time per dose</dt><dd>${fmt(hy.drip_minutes, 0)} min</dd><dt>Max Reynolds (laminar &lt; 2000)</dt><dd>${fmt(hy.reynolds_max, 0)}</dd><dt>Internal channels</dt><dd>${M.tube_d_mm} mm, downward only</dd>
        <dt>Inlet labyrinth</dt><dd>${M.inlet.length_m * 1000} × ${M.inlet.depth_mm} mm, width varies</dd></dl>
        ${cellTable(true)}<p class="src">Click a blue compartment to open its cutaway. ${sim}</p>`;
      const r1 = q("#refill"), r2 = q("#refill-all");
      if (r1) r1.onclick = () => { level.set(selected, CAP); updateWaterMeshes(); renderPanel(); refreshPins(); };
      if (r2) r2.onclick = () => { for (const k of level.keys()) level.set(k, CAP); updateWaterMeshes(); renderPanel(); refreshPins(); };
    } else if (mode === "solar") {
      renderSolarPanel();
    } else if (mode === "exploded") {
      panel.innerHTML = `<p class="eyebrow">Exploded view</p><h2>How it is assembled</h2>
        <dl class="kv"><dt>Front</dt><dd>Planting inserts and plants</dd><dt>+ 16 cm</dt><dd>Shading inserts (asanoha, sakura)</dd><dt>0</dt><dd>Lattice: struts and star connectors</dd><dt>− 20 cm</dt><dd>Hidden channels and drainage lines</dd><dt>− 38 cm</dt><dd>Waterproof compartment liners</dd><dt>− 58 cm</dt><dd>Supporting frame and plinth</dd><dt>Side</dt><dd>Optional monitoring station</dd></dl>
        <p>Struts slot into star connectors with one steel pin each. Liners drop into the hollow floor beams, inserts sit on top and lift out by their lip.</p>`;
    }
  }
  function cellTable(water) {
    const rows = [...cellInfo.keys()].map((id) => {
      const s = waterStatus(id), n = pins.find((p) => p.id === id).n;
      return `<tr class="${id === selected ? "sel" : ""}"><td>${n} ${plantName[s.h.plant]}</td><td>${fmt(s.h.need_l_day)}</td><td>${fmt(tuned ? s.h.alloc_l_day : s.h.alloc_equal_l_day)}</td>${water ? `<td>${fmt(s.h.inlet_mm)}</td><td>${fmt(s.auto, 1)}</td>` : `<td>${fmt(s.h.head_m)}</td>`}</tr>`;
    }).join("");
    return `<div class="tbl-wrap"><table><tr><th>Cell</th><th>Need L/d</th><th>${tuned ? "Tuned" : "Equal"} L/d</th>${water ? "<th>Inlet mm</th><th>Days</th>" : "<th>Head m</th>"}</tr>${rows}</table></div>`;
  }

  // ---------------------------------------------------------------- solar: SolarEngine sun position + per-plant direct sun check
  const sunInput = q("#sun"), sunOut = q("#sun-out");
  const sunDisc = new THREE.Mesh(new THREE.SphereGeometry(0.06, 24, 16), new THREE.MeshBasicMaterial({ color: 0xffd27a })); sunDisc.visible = false; scene.add(sunDisc);
  let sunState = null;
  const ray = new THREE.Raycaster();
  function sunAt(h) {
    const hrs = M.solar[orient].hours;
    let i = hrs.findIndex((x) => x.h >= h); if (i <= 0) i = 1; if (i === -1) i = hrs.length - 1;
    const a = hrs[i - 1], b = hrs[i], t = Math.min(1, Math.max(0, (h - a.h) / (b.h - a.h || 1)));
    const lerp = (k) => a[k] + (b[k] - a[k]) * t;
    return { az: lerp("az"), el: lerp("el"), beam: lerp("beam"), diffuse: lerp("diffuse") };
  }
  function updateSun() {
    const h = parseFloat(sunInput.value), s = sunAt(h), Af = M.solar[orient].azimuth;
    const e = THREE.MathUtils.degToRad(s.el), g = THREE.MathUtils.degToRad(s.az - Af);
    const dir = new THREE.Vector3(-Math.sin(g) * Math.cos(e), Math.sin(e), Math.cos(g) * Math.cos(e)).normalize();
    sun.position.copy(sun.target.position).addScaledVector(dir, 3.2);
    sunDisc.position.copy(sun.target.position).addScaledVector(dir, 2.4);
    sun.intensity = s.el > 0 ? 0.5 + 2.4 * Math.min(1, (s.beam + 120) / 750) : 0.0;
    sunDisc.visible = mode === "solar" && s.el > 0;
    const lit = [];
    const blockers = [groups.structure, groups.shading, groups.inserts];
    for (const [id, info] of cellInfo) {
      let hits = 0, tot = 0;
      if (s.el > 0 && dir.z > 0.02) {
        for (const dx of [-0.05, 0, 0.05]) for (const dy of [0.02, 0.06, 0.1]) for (const dz of [-0.03, 0.03]) {
          const o = info.plantBase.clone().add(new THREE.Vector3(dx, dy, dz));
          ray.set(o, dir); ray.near = 0.005; ray.far = 3; tot++;
          if (ray.intersectObjects(blockers, true).length === 0) hits++;
        }
      }
      const frac = tot ? hits / tot : 0;
      lit.push({ id, inSun: frac > 0.5, frac });
    }
    sunState = { h, ...s, dir, lit };
    const hh = Math.floor(h), mm = Math.round((h - hh) * 60);
    sunOut.textContent = `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")} · sun ${fmt(s.el, 0)}° high, azimuth ${fmt(s.az, 0)}°`;
    if (mode === "solar") { renderSolarPanel(); refreshPins(); }
  }
  function renderSolarPanel() {
    if (!sunState) return;
    const s = sunState, n = s.lit.filter((l) => l.inSun).length, onFace = s.el > 0 && s.dir.z > 0.02;
    const names = { W: "west", S: "south", E: "east" };
    const avg = s.lit.reduce((a, l) => a + l.frac, 0) / s.lit.length;
    panel.innerHTML = `<p class="eyebrow">Solar shading · SolarEngine (pvlib), Tunis, 15 July</p><h2>${onFace ? `${fmt(avg * 100, 0)} % of plant canopy in direct sun` : "Facade out of direct sun"}</h2>
      <dl class="kv"><dt>Facade</dt><dd>facing ${names[orient]}</dd><dt>Direct sun on facade</dt><dd>${fmt(s.beam, 0)} W/m²</dd><dt>Diffuse light</dt><dd>${fmt(s.diffuse, 0)} W/m²</dd><dt>Daily total on facade</dt><dd>${fmt(M.solar[orient].daily_kwh_m2, 2)} kWh/m²</dd><dt>Plants mostly in sun</dt><dd>${n} of 10</dd></dl>
      <p>${onFace ? "Each pin shows how much of that plant’s canopy the sun reaches now. When the sun is high, the floor beam and insert of the cell above shade the plant below; low evening sun reaches deep into every cell. The lattice gives midday shade without blocking the gentle hours." : "The sun is behind or beside the structure: only diffuse light reaches the plants, so the struts and fins cast no shade on them now."}</p>
      <p class="src">Sun position and irradiance come from SolarEngine for a clear July day; direct sun per plant is a ray test through the 3D geometry.</p>`;
  }
  sunInput.addEventListener("input", updateSun);
  q("#orient").addEventListener("change", (e) => { orient = e.target.value; updateSun(); updateWaterMeshes(); renderPanel(); });

  // ---------------------------------------------------------------- water particles (downward only)
  const dropGeo = new THREE.SphereGeometry(0.005, 8, 6);
  const drops = new THREE.InstancedMesh(dropGeo, new THREE.MeshBasicMaterial({ color: 0x1e88e5 }), 400);
  drops.count = 0; scene.add(drops);
  const flows = [];
  function buildFlows() {
    flows.length = 0;
    for (const [id] of cellInfo) {
      const h = cellHydro(id), q = tuned ? h.alloc_l_day : h.alloc_equal_l_day;
      const n = Math.max(2, Math.round(q * 34));
      for (let k = 0; k < n; k++) flows.push({ curve: pathCurves.get(id), phase: k / n, speed: 0.12 });
      const over = Math.max(0, q - h.need_l_day);
      const nd = Math.round(over * 40) + 1;
      for (let k = 0; k < nd; k++) flows.push({ curve: drainCurves.get(id), phase: k / nd, speed: 0.1 });
    }
  }
  buildFlows();

  // ---------------------------------------------------------------- modes
  const fade = (on) => {
    const sets = [[woodMat, 0.16], [hubMat, 0.3], [insertMat, 0.32], [soilMat, 0.32], [shadeMat, 0.25]];
    for (const [m, o] of sets) { m.transparent = on; m.opacity = on ? o : 1; m.depthWrite = !on; m.needsUpdate = true; }
  };
  function highlightInserts(on) { insertMat.emissive.setHex(on ? 0x3a1d0c : 0x000000); }
  let explodeT = 0, explodeTarget = 0;
  function setMode(m) {
    mode = m; selected = null;
    root.querySelectorAll("#modes button").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mode === m));
    const water = m === "water";
    fade(water);
    groups.channels.visible = groups.reservoirs.visible = water || m === "exploded";
    groups.drainage.children.forEach((c) => { if (c !== tray && c !== jar) c.visible = water || m === "exploded"; });
    highlightInserts(m === "planting");
    explodeTarget = m === "exploded" ? 1 : 0;
    q("#tb-solar").hidden = m !== "solar";
    q("#tb-water").hidden = !water;
    sunDisc.visible = false;
    if (m === "solar") updateSun(); else { sun.position.set(1.6, 2.6, 2.2); sun.intensity = 2.4; }
    flyTo(m === "planting" ? "front" : "three");   // every mode starts from a readable view of the whole lattice
    refreshPins(); renderPanel();
  }
  function refreshPins() {
    for (const p of pins) {
      const show = mode === "planting" || mode === "water" || mode === "solar";
      p.el.classList.toggle("hidden", !show);
      p.el.classList.toggle("on", p.id === selected);
      const st = waterStatus(p.id).st;
      p.el.classList.toggle("warn", mode === "water" && st === "warn");
      p.el.classList.toggle("crit", mode === "water" && st === "crit");
      if (mode === "solar" && sunState) { const l = sunState.lit.find((x) => x.id === p.id); p.el.textContent = l && l.frac > 0 ? `${p.n} · ${Math.round(l.frac * 100)}%` : `${p.n} · shade`; } else p.el.textContent = p.n;
    }
  }
  function selectCell(id) {
    if (mode === "architecture" || mode === "exploded" || mode === "solar") setMode("planting");
    selected = id;
    if (mode === "water") { const info = cellInfo.get(id); tween = { t: 0, fromP: camera.position.clone(), fromT: controls.target.clone(), toP: new THREE.Vector3(info.cx + 0.25, info.yb + 0.12, 0.42), toT: new THREE.Vector3(info.cx, info.yb, 0) }; }
    refreshPins(); renderPanel();
  }
  root.querySelectorAll("#modes button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  q("#btn-tuned").addEventListener("click", (e) => { tuned = !tuned; e.target.setAttribute("aria-pressed", tuned); e.target.textContent = tuned ? "AI-tuned inlets" : "Equal inlets"; buildFlows(); renderPanel(); });
  q("#btn-sim").addEventListener("click", (e) => { simOn = !simOn; e.target.setAttribute("aria-pressed", simOn); });
  root.querySelectorAll("#ctx button").forEach((b) => b.addEventListener("click", () => {
    root.querySelectorAll("#ctx button").forEach((x) => x.setAttribute("aria-pressed", x === b));
    wall.visible = b.dataset.ctx === "wall";
  }));

  // ---------------------------------------------------------------- cameras
  const CAMS = {
    three: [new THREE.Vector3(1.75, 1.3, 2.35), new THREE.Vector3(0, 0.74, 0)],
    front: [new THREE.Vector3(0, 0.8, 2.75), new THREE.Vector3(0, 0.76, 0)],
    side: [new THREE.Vector3(2.6, 1.0, 0.05), new THREE.Vector3(0, 0.76, 0)],
    rear: [new THREE.Vector3(-0.9, 1.2, -2.5), new THREE.Vector3(0, 0.76, 0)],
  };
  let tween = null;
  function flyTo(k) {
    if (k === "rear" && wall.visible) root.querySelector('#ctx button[data-ctx="standalone"]').click();
    tween = { t: 0, fromP: camera.position.clone(), fromT: controls.target.clone(), toP: CAMS[k][0], toT: CAMS[k][1] };
  }
  root.querySelectorAll("#cams button").forEach((b) => b.addEventListener("click", () => flyTo(b.dataset.cam)));
  camera.position.copy(CAMS.three[0]); controls.target.copy(CAMS.three[1]);

  // ---------------------------------------------------------------- picking
  const pick = new THREE.Raycaster(), ptr = new THREE.Vector2(); let down = null;
  renderer.domElement.addEventListener("pointerdown", (e) => (down = [e.clientX, e.clientY]));
  renderer.domElement.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5) return;
    const r = renderer.domElement.getBoundingClientRect();
    ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    pick.setFromCamera(ptr, camera);
    const targets = mode === "water" ? [groups.reservoirs, groups.inserts] : [groups.inserts, groups.plants];
    const hit = pick.intersectObjects(targets, true)[0];
    if (!hit) return;
    let id = hit.object.userData.cell;
    if (id === undefined && hit.object.userData.cells && hit.instanceId != null) id = hit.object.userData.cells[hit.instanceId];
    if (id !== undefined) selectCell(id);
  });

  // ---------------------------------------------------------------- loop
  function resize() {
    const w = stage.clientWidth, h = stage.clientHeight;
    renderer.setSize(w, h, false); renderer.domElement.style.width = w + "px"; renderer.domElement.style.height = h + "px";
    labels.setSize(w, h); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix();
  }
  const ro = new ResizeObserver(resize); ro.observe(stage); resize();
  setMode("architecture");
  const clock = new THREE.Clock();
  const simClock = q("#sim-clock");
  let lastPanel = 0;
  renderer.setAnimationLoop(() => {
    if (!state.visible) { clock.getDelta(); return; }
    const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
    if (tween) { tween.t = Math.min(1, tween.t + dt / 1.0); const k = tween.t * tween.t * (3 - 2 * tween.t); camera.position.lerpVectors(tween.fromP, tween.toP, k); controls.target.lerpVectors(tween.fromT, tween.toT, k); if (tween.t >= 1) tween = null; }
    explodeT += (explodeTarget - explodeT) * Math.min(1, dt * 5);
    for (const [k, g] of Object.entries(groups)) g.position.set(...EXPLODE[k].map((v) => v * explodeT));
    supplyTube.visible = clamp.visible = explodeT < 0.5;
    if (mode === "water") {
      let i = 0;
      for (const f of flows) { if (i >= 400) break; tmp.position.copy(f.curve.getPointAt((t * f.speed + f.phase) % 1)); tmp.position.z += 0.0; tmp.rotation.set(0, 0, 0); tmp.scale.setScalar(1); tmp.updateMatrix(); drops.setMatrixAt(i++, tmp.matrix); }
      drops.count = i; drops.instanceMatrix.needsUpdate = true;
      if (simOn) {
        const days = dt * 0.25; simDays += days;
        for (const id of level.keys()) level.set(id, Math.max(0, level.get(id) - cellHydro(id).need_l_day * days));
        updateWaterMeshes();
        if (t - lastPanel > 0.5) { lastPanel = t; renderPanel(); refreshPins(); }
      }
      simClock.textContent = `Day ${fmt(simDays, 1)} · ${window.INBETWEEN_SENSOR ? "live sensor" : "simulation"}`;
    } else drops.count = 0;
    controls.update(); renderer.render(scene, camera); labels.render(scene, camera);
  });
  updateSun();

  return {
    setVisible(v) { state.visible = v; },
    dispose() {
      renderer.setAnimationLoop(null);
      ro.disconnect();
      controls.dispose();
      scene.traverse((o) => {
        o.geometry?.dispose?.();
        const m = o.material;
        (Array.isArray(m) ? m : m ? [m] : []).forEach((x) => { x.map?.dispose?.(); x.dispose(); });
      });
      pmrem.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      labels.domElement.remove();
    },
  };
}
