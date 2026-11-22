import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import {
  AdviceResponse, Api, ApiError, AskResponse, BillExplainResponse, BillFields, BillLang, BillVerifyResponse,
  ChatMessage, FieldStatus,
} from '../api';
import { PARTS, PartDef, PartId, UI } from './bill-parts';

interface ApplianceRow { name: string; power_w: number | null; hours_per_day: number | null; days: number | null; reduce: number | null }

interface Part extends PartDef {
  n: number;
  box: number[] | null;
  status: FieldStatus;
  display: string;
}

const LANGS: { id: BillLang; label: string }[] = [
  { id: 'en', label: 'English' }, { id: 'fr', label: 'Français' }, { id: 'ar', label: 'العربية' }, { id: 'darija', label: 'Darija' },
];

const SUGGESTIONS: Record<BillLang, string[]> = {
  fr: ['Pourquoi ma facture est-elle si élevée ?', 'Que veut dire « relevé estimé » ?', 'Comment sont calculées les taxes ?'],
  ar: ['لماذا فاتورتي مرتفعة؟', 'ما معنى القراءة التقديرية؟', 'كيف تُحتسب الأداءات؟'],
  darija: ['علاش الفاتورة غالية برشا؟', 'شنوة معناها قراية تقديرية؟', 'قداش لازم نحط الكليماتيزور؟'],
  en: ['Why is my bill so high?', 'What does an estimated reading mean?', 'How are the taxes calculated?'],
};

const BAND_EDGES = [0, 50, 100, 200, 300, 500, 700];
const BAND_PRICES = [62, 96, 176, 218, 341, 414];

/** Typical split air conditioners. Approximate electrical power: the label on the unit is the reference. */
const AC_SIZES = [
  { id: 'small', label: 'Small', note: '9,000 BTU · one bedroom', watts: 900 },
  { id: 'medium', label: 'Medium', note: '12,000 BTU · living room', watts: 1200 },
  { id: 'large', label: 'Large', note: '18,000 BTU · large room', watts: 1800 },
];

@Component({
  selector: 'app-energy',
  imports: [DecimalPipe, RouterLink],
  templateUrl: './energy.html',
  styleUrls: ['./energy.css', './energy.steps.css'],
})
export class EnergyComponent implements OnInit, OnDestroy {
  readonly api = inject(Api);
  readonly engine = signal<'checking' | 'online' | 'offline'>('checking');
  readonly langs = LANGS;
  readonly lang = signal<BillLang>('en');
  readonly t = computed(() => UI[this.lang()]);
  readonly rtl = computed(() => this.lang() === 'ar' || this.lang() === 'darija');

  /* ---------------- stepper ---------------- */
  readonly steps = [
    { t: 'Your bill', s: 'Upload' },
    { t: 'Explained', s: 'Part by part' },
    { t: 'Your result', s: 'Checked by tariff' },
    { t: 'Pay less', s: 'Your habits' },
  ];
  readonly step = signal(0);

  /* ---------------- 1. upload ---------------- */
  readonly dragging = signal(false);
  readonly reading = signal(false);
  readonly readError = signal('');
  readonly fileName = signal('');
  readonly preview = signal<string | null>(null);
  readonly previewRatio = signal(1.414);
  readonly manualMode = signal(false);
  readonly redacted = signal<string[]>([]);
  readonly readWarnings = signal<string[]>([]);

  /* ---------------- 2. explained ---------------- */
  readonly values = signal<Record<string, string>>({});
  readonly status = signal<Record<string, FieldStatus>>({});
  readonly boxes = signal<Record<string, number[] | null>>({});
  readonly readingType = signal<'actual' | 'estimated' | null>(null);
  readonly active = signal<PartId | null>(null);
  readonly editing = signal<PartId | null>(null);
  readonly showMissing = signal(false);

  /* ---------------- 3. result ---------------- */
  readonly verifying = signal(false);
  readonly verifyError = signal('');
  readonly result = signal<BillVerifyResponse | null>(null);
  readonly explanation = signal<BillExplainResponse | null>(null);
  readonly explaining = signal(false);
  /** The optional AI rewrite runs on demand, never blocking the instant explanation. */
  readonly rewriting = signal(false);
  readonly rewriteNote = signal('');
  private readonly explainCache = new Map<string, BillExplainResponse>();
  readonly bandHover = signal<number | null>(null);
  readonly showMethod = signal(false);

  /* ---------------- 4. pay less ---------------- */
  readonly acSizes = AC_SIZES;
  readonly hasAc = signal(true);
  readonly acSize = signal('medium');
  readonly acWatts = signal(1200);
  readonly acCount = signal(1);
  readonly acHours = signal(4);
  readonly acDays = signal(30);
  readonly acHoursLess = signal(1);
  readonly setCurrent = signal(22);
  readonly setTarget = signal(26);
  readonly others = signal<ApplianceRow[]>([]);
  readonly presets = [
    { name: 'Water heater', power_w: 2000, hours_per_day: 1.5 },
    { name: 'Fridge', power_w: 150, hours_per_day: 10 },
    { name: 'Television', power_w: 100, hours_per_day: 5 },
    { name: 'Washing machine', power_w: 500, hours_per_day: 1 },
  ];
  readonly advising = signal(false);
  readonly adviceError = signal('');
  readonly advice = signal<AdviceResponse | null>(null);

  readonly directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  readonly cities = [
    { name: 'Tunis', lat: 36.81, lon: 10.18 }, { name: 'Sousse', lat: 35.83, lon: 10.64 },
    { name: 'Sfax', lat: 34.74, lon: 10.76 }, { name: 'Bizerte', lat: 37.27, lon: 9.87 },
    { name: 'Gabès', lat: 33.88, lon: 10.1 }, { name: 'Kairouan', lat: 35.68, lon: 10.1 },
  ];
  readonly facing = signal<string>('W');
  readonly city = signal(this.cities[0]);
  readonly shadeLoading = signal(false);
  readonly shadeError = signal('');
  readonly shade = signal<AdviceResponse['shading']>(null);
  readonly designLabel: Record<string, string> = {
    balanced: 'Balanced', shade_maximizer: 'Coolest room', water_saver: 'Water saver', baseline: 'Standard screen',
  };

  /* ---------------- assistant ---------------- */
  readonly chatOpen = signal(false);
  readonly chatLog = signal<{ role: 'user' | 'assistant'; text: string; sources?: { title: string; url: string }[];
    snippets?: AskResponse['snippets']; mode?: string }[]>([]);
  readonly chatInput = signal('');
  readonly chatBusy = signal(false);
  readonly chatError = signal('');
  readonly suggestions = computed(() => SUGGESTIONS[this.lang()]);
  private history: ChatMessage[] = [];

  private pingTimer?: ReturnType<typeof setTimeout>;

  ngOnInit(): void {
    this.checkEngine();
  }

  ngOnDestroy(): void {
    clearTimeout(this.pingTimer);
  }

  /** Reachability check; keeps retrying every 5 s while offline, so starting the server later just works. */
  checkEngine(): void {
    this.api.ping()
      .then(() => this.engine.set('online'))
      .catch(() => {
        this.engine.set('offline');
        this.pingTimer = setTimeout(() => this.checkEngine(), 5000);
      });
  }

  /* ================================================================ navigation */
  go(i: number): void {
    if (i === 2 && !this.result()) return;
    if (i === 1 && !this.hasBill()) return;
    this.step.set(i);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  readonly hasBill = computed(() => this.manualMode() || this.preview() !== null || Object.keys(this.values()).length > 0);

  canOpen(i: number): boolean {
    return i === 0 || (i === 1 && this.hasBill()) || (i === 2 && !!this.result()) || i === 3;
  }

  /* ================================================================ upload */
  onFile(e: Event): void {
    const input = e.target as HTMLInputElement;
    const f = input.files?.[0];
    if (f) this.read(f);
    input.value = '';
  }

  onDrop(e: DragEvent): void {
    e.preventDefault();
    this.dragging.set(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) this.read(f);
  }

  async useSpecimen(): Promise<void> {
    try {
      const b = await (await fetch('images/bill-specimen.png')).blob();
      this.read(new File([b], 'specimen-bill.png', { type: 'image/png' }));
    } catch {
      this.readError.set('Specimen bill not found.');
    }
  }

  manual(): void {
    this.reset();
    this.manualMode.set(true);
    this.go(1);
  }

  private reset(): void {
    this.values.set({});
    this.status.set({});
    this.boxes.set({});
    this.readingType.set(null);
    this.preview.set(null);
    this.redacted.set([]);
    this.readWarnings.set([]);
    this.result.set(null);
    this.explanation.set(null);
    this.advice.set(null);
    this.active.set(null);
    this.editing.set(null);
    this.manualMode.set(false);
  }

  private async read(f: File): Promise<void> {
    const okType = f.type.startsWith('image/') || f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf');
    if (!okType) {
      this.readError.set('Please upload a photo (JPG, PNG) or a PDF of your STEG bill.');
      return;
    }
    if (f.size > 15 * 1024 * 1024) {
      this.readError.set('The file must be under 15 MB.');
      return;
    }
    this.readError.set('');
    this.fileName.set(f.name);
    this.reading.set(true);
    try {
      const r = await this.api.billRead(f);
      this.reset();
      const v: Record<string, string> = {}, s: Record<string, FieldStatus> = {}, b: Record<string, number[] | null> = {};
      for (const [k, fld] of Object.entries(r.fields)) {
        b[k] = fld.box ?? null;
        if (k === 'reading_type') continue;
        v[k] = fld.value === null || fld.value === undefined ? '' : String(fld.value);
        s[k] = fld.status;
      }
      this.values.set(v);
      this.status.set(s);
      this.boxes.set(b);
      const rt = r.fields['reading_type'];
      this.readingType.set((rt?.value as 'actual' | 'estimated' | null) ?? null);
      this.status.update((o) => ({ ...o, reading_type: rt?.status ?? 'missing' }));
      if (r.preview?.jpeg_base64) {
        this.preview.set(`data:image/jpeg;base64,${r.preview.jpeg_base64}`);
        this.previewRatio.set(r.preview.height / r.preview.width);
      }
      this.redacted.set(r.redacted);
      this.readWarnings.set(r.warnings.filter((w) => !/actual or estimated/.test(w)));
      this.go(1);
      setTimeout(() => this.active.set(this.parts()[0]?.id ?? null));
    } catch (e) {
      this.readError.set(e instanceof ApiError && e.status === 422 ? `We couldn't read this file: ${e.message}.` : (e as Error).message);
    } finally {
      this.reading.set(false);
    }
  }

  /* ================================================================ parts */
  val(k: string): string {
    return this.values()[k] ?? '';
  }

  setVal(k: string, v: string): void {
    this.values.update((o) => ({ ...o, [k]: v }));
    this.status.update((o) => ({ ...o, [k]: v === '' ? 'missing' : 'found' }));
    this.result.set(null);
  }

  setReading(t: 'actual' | 'estimated'): void {
    this.readingType.set(t);
    this.status.update((o) => ({ ...o, reading_type: 'found' }));
    this.result.set(null);
  }

  private display(p: PartDef): string {
    if (p.kind === 'reading') {
      const r = this.readingType();
      return r ? UI[this.lang()][r] : '';
    }
    if (p.kind === 'date') {
      const a = this.val(p.keys[0]), b = this.val(p.keys[1]);
      const f = (d: string) => (d ? d.split('-').reverse().join('/') : '…');
      return a || b ? `${f(a)} → ${f(b)}` : '';
    }
    const v = this.val(p.keys[0]);
    if (!v) return '';
    const n = parseFloat(v);
    if (p.unit === 'TND') return `${n.toFixed(3)} TND`;
    return `${v}${p.unit ? ' ' + p.unit : ''}`;
  }

  private partStatus(p: PartDef): FieldStatus {
    if (p.kind === 'reading') return this.readingType() ? (this.status()['reading_type'] === 'uncertain' ? 'uncertain' : 'found') : 'missing';
    const sts = p.keys.map((k) => (this.val(k) === '' ? 'missing' : this.status()[k] ?? 'found'));
    if (sts.every((x) => x === 'missing')) return 'missing';
    if (sts.includes('uncertain') || sts.includes('missing')) return 'uncertain';
    return 'found';
  }

  /** Parts found on the bill, numbered top-to-bottom as they appear on the page. */
  readonly parts = computed<Part[]>(() => {
    this.values(); this.status(); this.readingType(); this.lang();
    const all = PARTS.map((p) => ({ ...p, n: 0, box: this.boxes()[p.keys[0]] ?? null, status: this.partStatus(p), display: this.display(p) }));
    const shown = this.manualMode() ? all : all.filter((p) => p.status !== 'missing');
    shown.sort((a, b) => (a.box?.[1] ?? 2) - (b.box?.[1] ?? 2));
    shown.forEach((p, i) => (p.n = i + 1));
    return shown;
  });

  readonly missingParts = computed(() => (this.manualMode() ? [] : PARTS.filter((p) => this.partStatus(p) === 'missing')));
  readonly toCheck = computed(() => this.parts().filter((p) => p.status === 'uncertain').length);
  readonly canVerify = computed(() => !!this.val('consumption_kwh') || (!!this.val('index_previous') && !!this.val('index_current')));

  select(id: PartId): void {
    this.active.set(this.active() === id ? null : id);
    setTimeout(() => document.getElementById('part-' + id)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' }), 30);
  }

  readonly indexCheck = computed(() => {
    const v = this.values();
    const a = parseFloat(v['index_previous']), b = parseFloat(v['index_current']), c = parseFloat(v['consumption_kwh']);
    if (isNaN(a) || isNaN(b)) return null;
    const d = b - a;
    if (d < 0) return { ok: false, text: 'The new index is lower than the old one. Please check both readings.' };
    if (!isNaN(c) && Math.abs(d - c) > 0.5) return { ok: false, text: `New − old index = ${d} kWh, but the consumption says ${c} kWh.` };
    return { ok: true, text: `New index − old index = ${d} kWh, the same as the consumption ✓` };
  });

  bill(): BillFields {
    const v = this.values();
    const out: Record<string, unknown> = {};
    for (const p of PARTS) {
      for (const k of p.keys) {
        if (k === 'reading_type') continue;
        const raw = (v[k] ?? '').trim();
        if (!raw) continue;
        if (p.kind === 'date') out[k] = raw;
        else {
          const n = parseFloat(raw.replace(',', '.'));
          if (!isNaN(n)) out[k] = n;
        }
      }
    }
    const oc = parseFloat((v['other_charges_tnd'] ?? '').replace(',', '.'));
    if (!isNaN(oc)) out['other_charges_tnd'] = oc;
    if (this.readingType()) out['reading_type'] = this.readingType();
    return out as BillFields;
  }

  /* ================================================================ result */
  async verify(): Promise<void> {
    this.verifying.set(true);
    this.verifyError.set('');
    this.editing.set(null);
    try {
      this.result.set(await this.api.billVerify(this.bill()));
      this.advice.set(null);
      this.go(2);
      this.explain();
    } catch (e) {
      this.verifyError.set((e as Error).message);
    } finally {
      this.verifying.set(false);
    }
  }

  /** Instant: the deterministic explanation (numbers from the bill and the tariff calculator). */
  async explain(): Promise<void> {
    if (!this.result()) return;
    this.rewriteNote.set('');
    const key = JSON.stringify(this.bill()) + '|' + this.lang();
    const ai = this.explainCache.get(key + '|llm');
    const hit = ai ?? this.explainCache.get(key);
    if (hit) { this.explanation.set(hit); return; }
    this.explaining.set(true);
    try {
      const r = await this.api.billExplain(this.bill(), this.lang(), false);
      this.explainCache.set(key, r);
      this.explanation.set(r);
    } catch {
      this.explanation.set(null);
    } finally {
      this.explaining.set(false);
    }
  }

  /** Optional: ask the AI assistant to rephrase. The instant text stays visible meanwhile. */
  async rewriteWithAi(): Promise<void> {
    if (!this.result() || this.rewriting()) return;
    const key = JSON.stringify(this.bill()) + '|' + this.lang() + '|llm';
    this.rewriting.set(true);
    this.rewriteNote.set('');
    try {
      const r = await this.api.billExplain(this.bill(), this.lang(), true);
      if (r.mode === 'llm') {
        this.explainCache.set(key, r);
        this.explanation.set(r);
      } else {
        this.rewriteNote.set('The AI assistant is not available right now. The explanation above is complete and uses your checked numbers.');
      }
    } catch {
      this.rewriteNote.set('The AI assistant took too long. The explanation above is complete and uses your checked numbers.');
    } finally {
      this.rewriting.set(false);
    }
  }

  setLang(l: BillLang): void {
    if (this.lang() === l) return;
    this.lang.set(l);
    if (this.result()) this.explain();
  }

  readonly verdict: Record<string, { title: string; icon: string; plain: string }> = {
    match: { title: 'Your bill is correct', icon: '✓', plain: 'We recalculated it with the official STEG tariff and got the same amounts.' },
    partial: { title: 'Partly checked', icon: '◐', plain: 'The lines we could check are correct. Add the missing values to check the rest.' },
    mismatch: { title: 'Some amounts are different', icon: '!', plain: 'Our calculation with the official tariff gives different amounts. See the possible reasons below.' },
    unavailable: { title: 'We can\'t check this bill yet', icon: '?', plain: '' },
  };

  readonly bandLadder = computed(() => {
    const u = this.result()?.understanding;
    const m = u?.band?.monthly_kwh ?? u?.kwh_per_month;
    if (m == null) return null;
    const max = Math.max(700, Math.ceil((m * 1.1) / 100) * 100);
    const segs = BAND_PRICES.map((p, i) => {
      const lo = BAND_EDGES[i], hi = i === BAND_PRICES.length - 1 ? max : BAND_EDGES[i + 1];
      return { price: p, lo, hi, x: (lo / max) * 100, w: ((hi - lo) / max) * 100, last: i === BAND_PRICES.length - 1,
               active: (m > lo && (m <= hi || i === BAND_PRICES.length - 1)) || (m === 0 && i === 0), shade: i };
    });
    return { segs, marker: Math.min(100, (m / max) * 100), monthly: m, max };
  });

  readonly breakdown = computed(() => {
    const L = this.result()?.verification.calculation?.lines;
    if (!L || L['electricity_total_tnd'] == null) return null;
    const parts = [
      { key: 'energy', label: 'Energy', value: L['energy_tnd'], cls: 'seg-a' },
      { key: 'fixed', label: 'Fixed charges', value: L['fixed_charges_tnd'], cls: 'seg-b' },
      { key: 'taxes', label: 'Taxes', value: L['taxes_tnd'], cls: 'seg-c' },
    ];
    const total = L['electricity_total_tnd'];
    return { total, parts: parts.map((p) => ({ ...p, pct: (p.value / total) * 100 })),
             taxes: { vat: L['vat_tnd'], municipal: L['municipal_tnd'], fte: L['fte_tnd'] } };
  });

  /* ================================================================ pay less */
  pickAc(id: string): void {
    this.acSize.set(id);
    this.acWatts.set(AC_SIZES.find((s) => s.id === id)!.watts);
  }

  readonly billDays = computed(() => this.result()?.understanding.days ?? 60);

  addPreset(p: { name: string; power_w: number; hours_per_day: number }): void {
    this.others.update((l) => [...l, { ...p, days: this.billDays(), reduce: 0 }]);
  }

  addRow(): void {
    this.others.update((l) => [...l, { name: '', power_w: null, hours_per_day: null, days: this.billDays(), reduce: 0 }]);
  }

  removeRow(i: number): void {
    this.others.update((l) => l.filter((_, j) => j !== i));
  }

  setRow(i: number, k: keyof ApplianceRow, v: string): void {
    this.others.update((l) => l.map((r, j) => (j === i ? { ...r, [k]: k === 'name' ? v : v === '' ? null : +v } : r)));
  }

  async runAdvice(): Promise<void> {
    const rows = this.others().filter((r) => r.power_w && r.hours_per_day != null && r.days);
    const apps = rows.map((r) => ({ name: r.name || 'Appliance', power_w: r.power_w!, hours_per_day: r.hours_per_day!, days: r.days!, reduce_hours_per_day: r.reduce ?? 0 }));
    if (this.hasAc()) {
      apps.unshift({ name: 'Air conditioner', power_w: this.acWatts(), hours_per_day: this.acHours(), days: Math.min(this.acDays(), this.billDays()),
                     reduce_hours_per_day: this.acHoursLess(), ...(this.acCount() > 1 ? { quantity: this.acCount() } : {}) } as never);
    }
    if (!apps.length) {
      this.adviceError.set('Tell us about at least one appliance.');
      return;
    }
    this.advising.set(true);
    this.adviceError.set('');
    try {
      this.advice.set(await this.api.billAdvice({
        bill: this.result() ? this.bill() : null,
        appliances: apps,
        setpoint_current_c: this.hasAc() ? this.setCurrent() : null,
        setpoint_target_c: this.hasAc() ? this.setTarget() : null,
      }));
      setTimeout(() => document.getElementById('advice-result')?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
    } catch (e) {
      this.adviceError.set((e as Error).message);
    } finally {
      this.advising.set(false);
    }
  }

  /** Appliances using more than the whole bill means the hours or days entered are too high. */
  readonly overBill = computed(() => {
    const s = this.advice()?.scenarios, c = this.result()?.understanding.consumption_kwh;
    return s && c ? s.total_kwh > c : false;
  });

  readonly maxApplianceKwh = computed(() => Math.max(1, ...(this.advice()?.scenarios?.appliances.map((a) => a.kwh) ?? [1])));

  async runShading(): Promise<void> {
    this.shadeLoading.set(true);
    this.shadeError.set('');
    try {
      const c = this.city();
      const r = await this.api.billAdvice({ facade: this.facing(), lat: c.lat, lon: c.lon, run_optimizer: true });
      this.shade.set(r.shading);
    } catch (e) {
      this.shadeError.set((e as Error).message);
    } finally {
      this.shadeLoading.set(false);
    }
  }

  /* ================================================================ assistant */
  async ask(text?: string): Promise<void> {
    const q = (text ?? this.chatInput()).trim();
    if (!q || this.chatBusy()) return;
    this.chatInput.set('');
    this.chatError.set('');
    this.chatLog.update((l) => [...l, { role: 'user', text: q }]);
    this.chatBusy.set(true);
    try {
      const r = await this.api.billAsk(q, this.history, this.result() ? this.bill() : null);
      this.history = [...this.history, { role: 'user', content: q }, { role: 'assistant', content: r.answer }].slice(-8);
      this.chatLog.update((l) => [...l, { role: 'assistant', text: r.answer, sources: r.sources, snippets: r.snippets, mode: r.mode }]);
    } catch (e) {
      this.chatError.set((e as Error).message);
    } finally {
      this.chatBusy.set(false);
    }
  }

  dirOf(text: string): 'rtl' | 'ltr' {
    return /[؀-ۿ]/.test(text) ? 'rtl' : 'ltr';
  }

  isRtl(l: BillLang | undefined): boolean {
    return l === 'ar' || l === 'darija';
  }
}
