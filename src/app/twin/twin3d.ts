import {
  AfterViewInit, Component, ElementRef, NgZone, OnDestroy, ViewChild, effect, inject, input, output, signal,
} from '@angular/core';
import type * as THREE_NS from 'three';
import type { Cell, GenDesign, XY } from './types';

export type TwinView = 'architecture' | 'hydraulic' | 'environment';

/** Sun in the facade frame: elevation (deg) and azimuth relative to the wall normal (deg, + = to the right). */
export interface TwinSun { elevation: number; relAzimuth: number; beam: number; index: number; season: 'summer' | 'winter' }

const LEAF = [0x4f7f45, 0x5b8c4e, 0x3f7a3f, 0x6f9c58];
const FRUIT: Record<string, number> = { strawberry: 0xc0392b, cherry_tomato: 0xd84a2b, chili: 0xc8321c };

/**
 * The INBETWEEN installation in 3D, built from the generator's real geometry (metres):
 * frame cells, motif screens, planting cells with integrated lower reservoirs (transparent cutaway),
 * hidden channels inside the frame, a discreet supply tube entering from above. No large tank on top.
 */
@Component({
  selector: 'app-twin3d',
  template: `
    <div class="t3" #stage>
      <canvas #canvas aria-label="Interactive 3D model of the installation: drag to rotate, scroll to zoom, click a cell to inspect it"></canvas>
      @if (!ready()) { <div class="t3__load"><span class="spin"></span> Building the 3D model…</div> }
      @if (hoverLabel()) { <div class="t3__hover" [style.left.px]="hoverPos().x" [style.top.px]="hoverPos().y">{{ hoverLabel() }}</div> }
    </div>
  `,
  styles: [`
    :host { display: block; position: relative; }
    .t3 { position: relative; width: 100%; height: 100%; min-height: 320px; overflow: hidden; }
    canvas { display: block; width: 100%; height: 100%; cursor: grab; touch-action: none; }
    canvas:active { cursor: grabbing; }
    .t3__load { position: absolute; inset: 0; display: grid; place-items: center; color: #6a6d63; font-size: .9rem; }
    .t3__hover { position: absolute; transform: translate(12px, -110%); pointer-events: none; padding: 5px 9px; border-radius: 2px;
      background: rgba(41, 44, 37, .86); color: #f5f1e8; font-size: .76rem; white-space: nowrap; }
    .spin { display: inline-block; width: 14px; height: 14px; margin-right: 8px; border-radius: 50%; border: 2px solid rgba(65,75,48,.25);
      border-top-color: #414b30; animation: s .8s linear infinite; vertical-align: -2px; }
    @keyframes s { to { transform: rotate(360deg); } }
  `],
})
export class Twin3dComponent implements AfterViewInit, OnDestroy {
  readonly design = input.required<GenDesign>();
  readonly view = input<TwinView>('architecture');
  readonly showChannels = input(false);
  readonly sun = input<TwinSun | null>(null);
  readonly levels = input<Record<number, number>>({});          // branch id -> level 0..1
  readonly thresholds = input<Record<number, number>>({});      // branch id -> dynamic threshold 0..1
  readonly selected = input<number | null>(null);               // cell id
  /** Transparent scene: the page background (e.g. a photo of the wall) shows behind, shadows are cast onto it. */
  readonly backdrop = input(false);
  /** 'plants': open cells fade so the planting cells and their water compartments stand out. */
  readonly focus = input<'all' | 'plants'>('all');
  readonly cellPick = output<number | null>();

  readonly ready = signal(false);
  readonly hoverLabel = signal('');
  readonly hoverPos = signal({ x: 0, y: 0 });

  private readonly zone = inject(NgZone);
  @ViewChild('canvas', { static: true }) private canvasRef!: ElementRef<HTMLCanvasElement>;
  @ViewChild('stage', { static: true }) private stageRef!: ElementRef<HTMLElement>;

  private T!: typeof THREE_NS;
  private renderer?: THREE_NS.WebGLRenderer;
  private scene?: THREE_NS.Scene;
  private camera?: THREE_NS.PerspectiveCamera;
  private controls?: { update(): void; dispose(): void; target: THREE_NS.Vector3 };
  private sunLight?: THREE_NS.DirectionalLight;
  private hemi?: THREE_NS.HemisphereLight;
  private root?: THREE_NS.Group;
  private raf = 0;
  private ro?: ResizeObserver;
  private io?: IntersectionObserver;
  private visible = true;
  private destroyed = false;
  private built: GenDesign | null = null;

  // per-cell handles
  private frames = new Map<number, THREE_NS.Mesh>();
  private frameMats = new Map<number, THREE_NS.MeshStandardMaterial>();
  private waters = new Map<number, { mesh: THREE_NS.Mesh; h: number; base: number; level: number; branch: number }>();
  private tanks: THREE_NS.Mesh[] = [];
  private screens: THREE_NS.Mesh[] = [];
  private channelGroup?: THREE_NS.Group;
  private particles: { mesh: THREE_NS.Mesh; curve: THREE_NS.Curve<THREE_NS.Vector3>; t: number; v: number }[] = [];
  private pickables: THREE_NS.Object3D[] = [];
  private hovered: number | null = null;
  private down = { x: 0, y: 0 };
  private W = 1;
  private H = 1;

  constructor() {
    effect(() => {
      const d = this.design();
      if (this.T && this.scene && d !== this.built) this.build(d);
    });
    effect(() => {
      this.view(); this.showChannels(); this.selected(); this.thresholds(); this.focus();
      this.applyView();
    });
    effect(() => {
      const s = this.sun();
      this.applySun(s);
    });
    effect(() => {
      const lv = this.levels();
      for (const w of this.waters.values()) w.level = Math.max(0.02, Math.min(1, lv[w.branch] ?? w.level));
    });
  }

  ngAfterViewInit(): void {
    this.io = new IntersectionObserver((es) => (this.visible = es.some((e) => e.isIntersecting)));
    this.io.observe(this.stageRef.nativeElement);
    this.init();
  }

  ngOnDestroy(): void {
    this.destroyed = true;
    cancelAnimationFrame(this.raf);
    this.ro?.disconnect();
    this.io?.disconnect();
    this.controls?.dispose();
    this.dispose(this.scene);
    this.renderer?.dispose();
  }

  /** Camera presets. */
  frontView(): void {
    if (!this.camera || !this.controls) return;
    const d = Math.max(this.W, this.H) * 1.9 + 0.6;
    this.camera.position.set(0, this.H / 2, d);
    this.controls.target.set(0, this.H / 2, 0);
  }

  isoView(): void {
    if (!this.camera || !this.controls) return;
    const d = Math.max(this.W, this.H) * 1.6 + 0.6;
    this.camera.position.set(d * 0.55, this.H * 0.75, d * 0.85);
    this.controls.target.set(0, this.H / 2, 0);
  }

  /* ------------------------------------------------------------------ setup */
  private async init(): Promise<void> {
    const THREE = (this.T = await import('three'));
    const { OrbitControls } = await import('three/examples/jsm/controls/OrbitControls.js');
    if (this.destroyed) return;
    const canvas = this.canvasRef.nativeElement;
    const stage = this.stageRef.nativeElement;
    this.zone.runOutsideAngular(() => {
      const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      renderer.shadowMap.enabled = true;
      renderer.shadowMap.type = THREE.PCFSoftShadowMap;
      renderer.outputColorSpace = THREE.SRGBColorSpace;
      this.renderer = renderer;
      const scene = (this.scene = new THREE.Scene());
      this.camera = new THREE.PerspectiveCamera(32, 1, 0.02, 60);
      this.hemi = new THREE.HemisphereLight(0xfff6e8, 0xb7ad97, 1.15);
      scene.add(this.hemi);
      const sun = (this.sunLight = new THREE.DirectionalLight(0xfff0d6, 2.0));
      sun.castShadow = true;
      sun.shadow.mapSize.set(2048, 2048);
      sun.shadow.bias = -0.0005;
      sun.shadow.normalBias = 0.01;
      scene.add(sun, sun.target);
      const fill = new THREE.DirectionalLight(0xf2efe6, 0.5);
      fill.position.set(-2, 2, -3);
      scene.add(fill);

      const controls = new OrbitControls(this.camera, canvas);
      controls.enableDamping = true;
      controls.minDistance = 0.4;
      controls.maxDistance = 14;
      this.controls = controls as unknown as typeof this.controls;

      const resize = () => {
        const w = stage.clientWidth, h = Math.max(stage.clientHeight, 320);
        renderer.setSize(w, h, false);
        this.camera!.aspect = w / h;
        this.camera!.updateProjectionMatrix();
      };
      this.ro = new ResizeObserver(resize);
      this.ro.observe(stage);
      resize();

      canvas.addEventListener('pointerdown', (e) => (this.down = { x: e.clientX, y: e.clientY }));
      canvas.addEventListener('pointerup', (e) => {
        if (Math.hypot(e.clientX - this.down.x, e.clientY - this.down.y) > 5) return;   // it was a drag
        const id = this.pick(e);
        this.zone.run(() => this.cellPick.emit(id));
      });
      canvas.addEventListener('pointermove', (e) => this.onHover(e));
      canvas.addEventListener('pointerleave', () => { this.setHover(null); this.zone.run(() => this.hoverLabel.set('')); });
      this.build(this.design());
      this.isoView();
      this.loop();
    });
    this.ready.set(true);
  }

  private mat(color: number, extra: Partial<THREE_NS.MeshStandardMaterialParameters> = {}) {
    return new this.T.MeshStandardMaterial({ color, roughness: 0.8, metalness: 0, ...extra });
  }

  /** design metres (x right, y down) -> world (x right, y up, z out of the wall). */
  private v2(p: XY): [number, number] {
    return [p[0] - this.W / 2, this.H - p[1]];
  }

  private shapeOf(poly: XY[], holes: XY[][] = []): THREE_NS.Shape {
    const THREE = this.T;
    const s = new THREE.Shape(poly.map((p) => new THREE.Vector2(...this.v2(p))));
    for (const h of holes) s.holes.push(new THREE.Path(h.map((p) => new THREE.Vector2(...this.v2(p)))));
    return s;
  }

  private inside(p: XY, poly: XY[]): boolean {
    let ins = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i], [xj, yj] = poly[j];
      if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) ins = !ins;
    }
    return ins;
  }

  private inset(c: Cell, m: number): XY[] {
    const k = Math.max(0.5, 1 - (2 * m) / Math.min(c.w, c.h));
    return c.poly.map(([x, y]) => [c.cx + (x - c.cx) * k, c.cy + (y - c.cy) * k] as XY);
  }

  /* ------------------------------------------------------------------ geometry */
  private build(d: GenDesign): void {
    const THREE = this.T;
    const scene = this.scene!;
    if (this.root) { scene.remove(this.root); this.dispose(this.root); }
    this.frames.clear(); this.frameMats.clear(); this.waters.clear();
    this.tanks = []; this.screens = []; this.particles = []; this.pickables = [];
    this.built = d;
    this.W = d.width_m; this.H = d.height_m;
    const root = (this.root = new THREE.Group());
    scene.add(root);
    const D = d.depth_m || 0.1;

    // wall + ground (backdrop mode: an invisible wall that only receives shadows, over the page's photo)
    if (this.backdrop()) {
      const wall = new THREE.Mesh(new THREE.PlaneGeometry(this.W + 3, this.H + 3), new THREE.ShadowMaterial({ opacity: 0.3 }));
      wall.position.set(0, this.H / 2, -0.012);
      wall.receiveShadow = true;
      root.add(wall);
    } else {
      const wall = new THREE.Mesh(new THREE.BoxGeometry(this.W + 1.6, this.H + 1.4, 0.06), this.mat(0xefe9dc));
      wall.position.set(0, this.H / 2 + 0.05, -0.035);
      wall.receiveShadow = true;
      root.add(wall);
      const ground = new THREE.Mesh(new THREE.BoxGeometry(this.W + 1.6, 0.03, 1.4), this.mat(0xd9cfbd));
      ground.position.set(0, -0.62, 0.66);
      ground.receiveShadow = true;
      root.add(ground);
    }

    const wood = 0xc9a06e;
    const screenMat = this.mat(0xe1c79c, { roughness: 0.7, side: THREE.DoubleSide });
    for (const c of d.cells) {
      // frame ring (the cell's structure), extruded to the cell depth
      const inner = this.inset(c, 0.022);
      const fm = this.mat(wood, { roughness: 0.62 });
      const frame = new THREE.Mesh(new THREE.ExtrudeGeometry(this.shapeOf(c.poly, [inner.slice().reverse()]),
        { depth: D, bevelEnabled: false }), fm);
      frame.castShadow = frame.receiveShadow = true;
      frame.userData['cell'] = c.id;
      root.add(frame);
      this.frames.set(c.id, frame);
      this.frameMats.set(c.id, fm);
      this.pickables.push(frame);

      if (c.role === 'open') {
        // the cultural motif cut through a thin screen at mid-depth: light, air, shadow patterns
        // only openings fully inside the frame's inner edge (a hole crossing the outline breaks triangulation)
        const holes = c.motif.filter((m) => m.every((p) => this.inside(p, inner)));
        const scr = new THREE.Mesh(new THREE.ExtrudeGeometry(this.shapeOf(inner, holes.map((m) => m.slice().reverse())),
          { depth: 0.006, bevelEnabled: false }), screenMat);
        scr.position.z = D * 0.45;
        scr.castShadow = scr.receiveShadow = true;
        scr.userData['cell'] = c.id;
        root.add(scr);
        this.screens.push(scr);
        this.pickables.push(scr);
      } else {
        // back plate of the planting cell
        const back = new THREE.Mesh(new THREE.ExtrudeGeometry(this.shapeOf(inner), { depth: 0.008, bevelEnabled: false }), this.mat(0x8e6a48));
        back.receiveShadow = true;
        back.userData['cell'] = c.id;
        root.add(back);
        this.pickables.push(back);
        // integrated reservoir: the lower section of the cell (transparent cutaway) + animated water
        const r = c.reservoir!;
        const rw = c.w * 0.62, rh = Math.max(0.02, r.bottom_y - r.top_y), rd = D * 0.7;
        const [x, yTop] = this.v2([c.cx, r.top_y]);
        const tank = new THREE.Mesh(new THREE.BoxGeometry(rw, rh, rd),
          this.mat(0xdfe9ea, { transparent: true, opacity: 0.22, roughness: 0.1, depthWrite: false }));
        tank.position.set(x, yTop - rh / 2, rd / 2 + 0.01);
        tank.userData['cell'] = c.id;
        root.add(tank);
        this.tanks.push(tank);
        this.pickables.push(tank);
        const water = new THREE.Mesh(new THREE.BoxGeometry(rw * 0.94, rh, rd * 0.9),
          this.mat(0x4f8fb0, { transparent: true, opacity: 0.78, roughness: 0.2, emissive: 0x123548, emissiveIntensity: 0.3 }));
        water.position.set(x, yTop - rh, rd / 2 + 0.01);
        water.userData['cell'] = c.id;
        root.add(water);
        this.waters.set(c.id, { mesh: water, h: rh, base: yTop - rh, level: 0.7, branch: c.branch ?? 0 });
        // soil + plant above the water compartment (the plant grows INSIDE the cell)
        const [sx, sy] = this.v2([c.cx, r.top_y - 0.012]);
        const soil = new THREE.Mesh(new THREE.BoxGeometry(c.w * 0.6, 0.024, D * 0.8), this.mat(0x4a3424));
        soil.position.set(sx, sy, D * 0.45);
        root.add(soil);
        root.add(this.plant(sx, sy + 0.01, D * 0.55, c));
      }
    }
    // organic style: hollow branches (wood) - water runs inside them
    for (const s of d.segments || []) {
      const a = new THREE.Vector3(...this.v2(s.a), D / 2), b = new THREE.Vector3(...this.v2(s.b), D / 2);
      const len = a.distanceTo(b);
      const cyl = new THREE.Mesh(new THREE.CylinderGeometry(s.w / 2, s.w / 2 * 1.08, len, 12), this.mat(0xa97e50, { roughness: 0.7 }));
      cyl.position.copy(a.clone().add(b).multiplyScalar(0.5));
      cyl.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.clone().sub(a).normalize());
      cyl.castShadow = cyl.receiveShadow = true;
      root.add(cyl);
    }
    // discreet supply tube entering from above
    const [tx] = this.v2([d.supply.x, 0]);
    const tube = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.6, 12), this.mat(0x6f7a60, { roughness: 0.4 }));
    tube.position.set(tx, this.H + 0.3, D * 0.5);
    tube.castShadow = true;
    root.add(tube);

    // hidden channels (inside the frame members) + water particles
    const cg = (this.channelGroup = new THREE.Group());
    const chMat = this.mat(0x3f8fcf, { emissive: 0x1d4a63, emissiveIntensity: 0.6, roughness: 0.3 });
    const pmat = new THREE.MeshBasicMaterial({ color: 0x6fc0ff });
    const pgeo = new THREE.SphereGeometry(0.007, 8, 8);
    const supplyPath: XY[] = [[d.supply.x, -0.3], [d.supply.x, 0]];
    for (const ch of [{ points: supplyPath, w: 0.012 }, ...d.channels]) {
      const pts = ch.points.map((p) => new THREE.Vector3(...this.v2(p as XY), D * 0.5));
      if (pts.length < 2) continue;
      const path = new THREE.CurvePath<THREE_NS.Vector3>();
      for (let k = 0; k < pts.length - 1; k++) if (pts[k].distanceTo(pts[k + 1]) > 1e-4) path.add(new THREE.LineCurve3(pts[k], pts[k + 1]));
      if (!path.curves.length) continue;
      cg.add(new THREE.Mesh(new THREE.TubeGeometry(path, 16 * path.curves.length, Math.max(0.004, (ch.w || 0.012) / 2.4), 6, false), chMat));
      const n = Math.min(10, Math.max(2, Math.round(path.getLength() / 0.12)));
      for (let k = 0; k < n; k++) {
        const m = new THREE.Mesh(pgeo, pmat);
        cg.add(m);
        this.particles.push({ mesh: m, curve: path, t: k / n, v: 0.05 / Math.max(0.3, path.getLength()) });
      }
    }
    root.add(cg);

    const sun = this.sunLight!;
    const ext = Math.max(this.W, this.H) * 0.9 + 0.6;
    Object.assign(sun.shadow.camera, { left: -ext, right: ext, top: ext, bottom: -ext, near: 0.1, far: 20 });
    sun.shadow.camera.updateProjectionMatrix();
    sun.target.position.set(0, this.H / 2, 0);
    this.applyView();
    this.applySun(this.sun());
    if (this.camera) this.isoView();
  }

  private plant(x: number, y: number, z: number, c: Cell) {
    const THREE = this.T;
    const g = new THREE.Group();
    const r = Math.min(c.w, c.h) * 0.28;
    const geo = new THREE.SphereGeometry(r * 0.32, 8, 6);
    const n = 9;
    const seed = c.id * 7.13;
    for (let k = 0; k < n; k++) {
      const a = (k / n) * Math.PI * 2 + seed;
      const leaf = new THREE.Mesh(geo, this.mat(LEAF[(k + c.id) % 4], { roughness: 0.7 }));
      leaf.scale.set(1.3, 0.55, 1);
      leaf.position.set(Math.cos(a) * r * 0.55, r * (0.35 + 0.35 * ((k * 37 + c.id) % 5) / 5), Math.sin(a) * r * 0.4 + r * 0.2);
      leaf.rotation.set(0.5, a, 0.3);
      leaf.castShadow = true;
      g.add(leaf);
    }
    const fruit = FRUIT[c.plant ?? ''];
    if (fruit) {
      for (let k = 0; k < 3; k++) {
        const b = new THREE.Mesh(new THREE.SphereGeometry(r * 0.12, 8, 8), this.mat(fruit, { roughness: 0.4 }));
        b.position.set((k - 1) * r * 0.35, r * 0.25, r * 0.55);
        g.add(b);
      }
    }
    g.position.set(x, y, z);
    return g;
  }

  /* ------------------------------------------------------------------ view modes */
  private applyView(): void {
    if (!this.T || !this.root) return;
    const v = this.view();
    const xray = v === 'hydraulic' || this.showChannels();
    const plantsOnly = this.focus() === 'plants';
    const sel = this.selected();
    const selBranch = sel != null ? this.built?.cells.find((c) => c.id === sel)?.branch ?? null : null;
    for (const [id, m] of this.frameMats) {
      const cell = this.built!.cells.find((c) => c.id === id)!;
      const fade = xray ? 0.28 : plantsOnly && cell.role !== 'plant' ? 0.22 : 1;
      m.transparent = fade < 1;
      m.opacity = fade;
      m.depthWrite = fade >= 1;
      const isSel = id === sel;
      const inBranch = selBranch != null && cell.branch === selBranch && cell.role === 'plant';
      const lit = plantsOnly && cell.role === 'plant';
      m.emissive.setHex(isSel ? 0x7a3d1c : inBranch ? 0x2f4f6a : lit ? 0x6b4a1c : 0x000000);
      m.emissiveIntensity = isSel ? 0.55 : inBranch ? 0.35 : lit ? 0.3 : 0;
      m.color.setHex(0xc9a06e);
      m.needsUpdate = true;
    }
    for (const s of this.screens) {
      const m = s.material as THREE_NS.MeshStandardMaterial;
      const o = xray ? 0.25 : plantsOnly ? 0.12 : 1;
      m.transparent = o < 1; m.opacity = o; m.depthWrite = o >= 1; m.needsUpdate = true;
    }
    for (const t of this.tanks) (t.material as THREE_NS.MeshStandardMaterial).opacity = v === 'hydraulic' || plantsOnly ? 0.34 : 0.18;
    if (this.channelGroup) this.channelGroup.visible = xray;
    if (v === 'environment') this.colorExposure();
  }

  /** Environmental view: each cell tinted by the direct sun it receives at the current time (model). */
  private colorExposure(): void {
    const s = this.sun();
    if (!s || !this.built || this.view() !== 'environment') return;
    const lo = new this.T.Color(0xe9e4d8), mid = new this.T.Color(0xe0a258), hi = new this.T.Color(0xb7552f);
    for (const c of this.built.cells) {
      const m = this.frameMats.get(c.id);
      if (!m) continue;
      const fr = (s.season === 'winter' ? c.direct_fraction_winter : c.direct_fraction) ?? [];
      const val = Math.max(0, Math.min(1, ((fr[s.index] ?? 0) * s.beam) / 700));
      const col = val < 0.5 ? lo.clone().lerp(mid, val * 2) : mid.clone().lerp(hi, (val - 0.5) * 2);
      m.color.copy(col);
      if (c.id !== this.selected()) { m.emissive.copy(col); m.emissiveIntensity = 0.12 + val * 0.25; }
    }
  }

  private applySun(s: TwinSun | null): void {
    const sun = this.sunLight, hemi = this.hemi;
    if (!sun || !hemi || !this.T) return;
    if (!s) {
      sun.position.set(this.W * 0.8 + 1.2, this.H + 2.2, 2.6);
      sun.intensity = 2.0;
      hemi.intensity = 1.15;
      return;
    }
    const r = Math.PI / 180;
    const el = Math.max(-5, s.elevation) * r, rel = s.relAzimuth * r;
    const dir = new this.T.Vector3(-Math.sin(rel) * Math.cos(el), Math.max(0.03, Math.sin(el)), Math.cos(rel) * Math.cos(el)).normalize();
    sun.position.copy(dir.multiplyScalar(6)).add(sun.target.position);
    const facing = Math.cos(rel) > 0.02 && s.elevation > 0;
    sun.intensity = s.elevation <= 0 ? 0.05 : facing ? 0.9 + 2.3 * Math.min(1, Math.sin(el) * 1.5 + 0.2) : 0.35;
    hemi.intensity = 0.6;
    this.colorExposure();
  }

  /* ------------------------------------------------------------------ picking */
  private ray(e: PointerEvent) {
    const THREE = this.T;
    const r = this.canvasRef.nativeElement.getBoundingClientRect();
    const p = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    const rc = new THREE.Raycaster();
    rc.setFromCamera(p, this.camera!);
    const hit = rc.intersectObjects(this.pickables, false)[0];
    return hit ? (hit.object.userData['cell'] as number) : null;
  }

  private pick(e: PointerEvent): number | null {
    return this.camera ? this.ray(e) : null;
  }

  private onHover(e: PointerEvent): void {
    if (!this.camera || e.buttons) return;
    const id = this.ray(e);
    this.setHover(id);
    const r = this.canvasRef.nativeElement.getBoundingClientRect();
    const c = id != null ? this.built?.cells.find((x) => x.id === id) : null;
    const label = c ? (c.role === 'plant' ? `${c.plant?.replace('_', ' ')} · reservoir ${c.reservoir?.capacity_l.toFixed(2)} L` : 'Open cell · light and air') : '';
    this.zone.run(() => { this.hoverLabel.set(label); this.hoverPos.set({ x: e.clientX - r.left, y: e.clientY - r.top }); });
  }

  private setHover(id: number | null): void {
    if (id === this.hovered) return;
    const prev = this.hovered != null ? this.frameMats.get(this.hovered) : null;
    if (prev && this.hovered !== this.selected()) { prev.emissiveIntensity = 0; this.applyView(); }
    this.hovered = id;
    const m = id != null ? this.frameMats.get(id) : null;
    if (m && id !== this.selected()) { m.emissive.setHex(0x5a6545); m.emissiveIntensity = 0.35; }
    this.canvasRef.nativeElement.style.cursor = id != null ? 'pointer' : '';
  }

  /* ------------------------------------------------------------------ loop */
  private loop = () => {
    if (this.destroyed) return;
    this.raf = requestAnimationFrame(this.loop);
    if (!this.visible || !this.renderer) return;
    for (const w of this.waters.values()) {
      const cur = w.mesh.scale.y;
      const next = cur + (w.level - cur) * 0.06;                // water rises / falls smoothly
      w.mesh.scale.y = Math.max(0.001, next);
      w.mesh.position.y = w.base + (w.h * next) / 2;
      const th = this.thresholds()[w.branch];
      (w.mesh.material as THREE_NS.MeshStandardMaterial).color.setHex(th != null && w.level < th ? 0xc97a4a : 0x4f8fb0);
    }
    const flowing = this.channelGroup?.visible;
    for (const p of this.particles) {
      p.mesh.visible = !!flowing;
      if (!flowing) continue;
      p.t = (p.t + p.v / 60 * 6) % 1;
      p.mesh.position.copy(p.curve.getPointAt(p.t));
    }
    this.controls?.update();
    this.renderer.render(this.scene!, this.camera!);
  };

  private dispose(o?: THREE_NS.Object3D): void {
    o?.traverse((x) => {
      const m = x as THREE_NS.Mesh;
      m.geometry?.dispose?.();
      const mat = m.material as THREE_NS.Material | THREE_NS.Material[] | undefined;
      (Array.isArray(mat) ? mat : mat ? [mat] : []).forEach((q) => q.dispose());
    });
  }
}
