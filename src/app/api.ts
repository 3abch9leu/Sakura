import { Injectable } from '@angular/core';

/* ------------------------------------------------------------------ types (mirror api.py) */
export type DesignName = 'water_saver' | 'shade_maximizer' | 'balanced' | 'baseline';

export interface TileDesign {
  plants: string[];
  widths_mm: number[];
  cool_width_mm: number;
  water_l_day: number;
  porosity: number;
  aperture_mm: number;
  layers: number;
  screen_depth_mm: number;
  cooling_open: boolean;
}

export interface Pocket {
  plant: string;
  received_l: number;
  need_l: number;
  ratio: number;
}

export interface DesignResult {
  objectives: { water_l_day: number; heat_kwh_day: number; plant_deficit: number };
  constraints: Record<string, boolean>;
  panel: {
    n_tiles: number;
    root_tiles: number;
    shade_tiles: number;
    heat_unshaded_kwh_day: number;
    heat_reduction_pct: number;
    evaporative_cooling_kwh_day: number;
    water_drained_l_day: number;
    effective_porosity: number;
  };
  pockets: Pocket[];
  distribution_cv: number;
  hydraulics: { drain_time_min: number; reynolds_max: number; laminar: boolean };
  facade_irradiation_kwh_m2_day: number;
}

export interface DesignOption {
  design: TileDesign;
  result: DesignResult;
  preview_svg: string;
}

export interface DesignResponse {
  designs: Record<DesignName, DesignOption>;
  pareto: number[][];
  plant_safe_found: boolean;
  n_gen: number;
  optimizer_seconds: number;
}

export interface FacadeResponse {
  backend: string;
  window_w_m: number;
  window_h_m: number;
  height_source: string;
  area_m2: number;
  tiles: { columns: number; rows: number; total: number; root_tiles: number };
  quad_px: number[][];
  tilt_deg: number;
  warnings: string[];
  image_size_px: [number, number];
}

export interface SunResponse {
  facade: string;
  kwh_per_m2_day: number;
  peak_hour: string | number;   // "16:10" from pvlib
  peak_w_m2: number;
  hourly: { hour: number; beam_w_m2: number; diffuse_w_m2: number }[];
}

export interface TryonResponse {
  tryon_png_base64: string;
  tiles: { columns: number; rows: number; total: number; root_tiles: number };
  window_w_m: number;
  window_h_m: number;
  seconds: number;
}

export interface RenderResponse {
  enhanced: boolean;
  message: string;
  render_png_base64: string;
  render_seconds: number;
  seconds: number;
  seed: number;
  strength: number;
}

export interface Health {
  status: string;
  gpu?: { cuda_available?: boolean; device?: string | null };
  diffusion?: { weights_cached?: boolean; pipeline_loaded?: boolean; diffusers?: string | null };
  llm_backends?: { name: string; reachable: boolean | string }[];
}

export interface ChatMessage {
  role: string;
  content?: string | null;
  [k: string]: unknown;
}

/** Common context sent with design / try-on requests. */
export interface SiteContext {
  plants: string[];
  facade: string;
  rh: number;
  window_w: number;
  window_h: number;
  root_tiles: number;
  water_available_l_day: number;
  lat: number;
  lon: number;
}

/* ------------------------------------------------------------------ Energy & Comfort types (mirror /bill/*) */
export type BillLang = 'fr' | 'ar' | 'darija' | 'en';
export type FieldStatus = 'found' | 'uncertain' | 'missing';

export interface BillFields {
  consumption_kwh?: number | null;
  index_previous?: number | null;
  index_current?: number | null;
  period_start?: string | null;
  period_end?: string | null;
  period_months?: number | null;
  subscribed_power_kva?: number | null;
  reading_type?: 'actual' | 'estimated' | null;
  energy_amount_tnd?: number | null;
  fixed_charges_tnd?: number | null;
  taxes_tnd?: number | null;
  electricity_total_tnd?: number | null;
  other_charges_tnd?: number | null;
  total_tnd?: number | null;
}

export interface BillReadResponse {
  /** box = [x0, y0, x1, y1] as fractions of the preview image (page 1), or null */
  fields: Record<string, { value: number | string | null; status: FieldStatus; confidence: number; box: number[] | null }>;
  /** page-1 image with personal details blurred on the server */
  preview: { jpeg_base64: string | null; width: number; height: number; blurred_regions: number } | null;
  source: string;
  engine: string;
  arabic_text_detected: boolean;
  redacted: string[];
  privacy: string;
  warnings: string[];
  seconds: number;
}

export interface BillCheck {
  line: string;
  label: string;
  printed_tnd: number;
  calculated_tnd: number;
  difference_tnd: number;
  match: boolean;
}

export interface BillCalculation {
  status: 'complete' | 'partial' | 'unavailable';
  reason?: string;
  lines?: Record<string, number>;
  monthly_kwh?: number;
  months?: number;
  category?: 'economic' | 'normal' | null;
  band?: { price_mill_per_kwh: number; footnote: string };
  vat_rate?: number;
  fte_exempt?: boolean;
  assumptions?: string[];
  sources?: string[];
}

export interface Verification {
  status: 'match' | 'partial' | 'mismatch' | 'unavailable';
  summary: string;
  calculation: BillCalculation | null;
  checks: BillCheck[];
  causes: string[];
  warnings: string[];
}

export interface Understanding {
  consumption_kwh: number | null;
  days: number | null;
  months: number | null;
  kwh_per_day: number | null;
  kwh_per_month: number | null;
  reading_type: string | null;
  band?: { price_mill_per_kwh: number; monthly_kwh: number; vat_rate: number };
  next_band?: { limit_kwh_month: number; headroom_kwh_month: number; next_price_mill_per_kwh: number | null } | null;
  notes: string[];
}

export interface BillVerifyResponse {
  verification: Verification;
  understanding: Understanding;
  tariff_version: string;
  tariff_conflicts: string[];
  not_verified: string[];
}

export interface BillExplainResponse {
  lang: BillLang;
  mode: 'llm' | 'template';
  text: string;
  paragraphs: string[];
  sources: string[];
  llm_error: string | null;
}

export interface ApplianceInput {
  name: string;
  power_w: number;
  hours_per_day: number;
  days: number;
  quantity?: number;
  reduce_hours_per_day?: number;
}

export interface AdviceRequest {
  bill?: BillFields | null;
  appliances?: ApplianceInput[];
  setpoint_current_c?: number | null;
  setpoint_target_c?: number | null;
  facade?: string | null;
  lat?: number;
  lon?: number;
  run_optimizer?: boolean;
  window_w?: number;
  window_h?: number;
}

export interface AdviceResponse {
  understanding: Understanding | null;
  scenarios: {
    appliances: { name: string; power_w: number; hours_per_day: number; days: number; quantity: number; kwh: number; formula: string; kwh_saved_by_fewer_hours: number }[];
    total_kwh: number;
    total_kwh_saved: number;
    setpoint: { kwh: number; degrees: number; fraction: number; assumption: string; source: string } | null;
    money: { base_total_tnd: number; base_band_mill: number; with_savings_total_tnd?: number; saving_tnd?: number; band_after_mill?: number; band_changes?: boolean; note: string; assumption: string } | null;
    assumptions: string[];
  } | null;
  shading: {
    facade: string;
    kwh_per_m2_day: number;
    peak_hour: string;
    note: string;
    designs: { name: string; heat_reduction_pct: number; solar_heat_kwh_day: number; unshaded_solar_heat_kwh_day: number }[] | null;
    designs_note?: string;
    electricity_savings: string;
  } | null;
}

export interface AskResponse {
  mode: 'llm' | 'retrieval';
  lang: BillLang;
  answer: string;
  sources: { title: string; url: string }[];
  snippets?: { title: string; text: string; source: string; url: string }[];
  llm_error?: string;
}

/* ------------------------------------------------------------------ service */
const DEFAULT_URL = 'http://localhost:8000';

export class ApiError extends Error {
  constructor(message: string, readonly status = 0) {
    super(message);
  }
}

@Injectable({ providedIn: 'root' })
export class Api {
  /** Override from the browser console: localStorage.setItem('apiUrl', 'http://192.168.1.20:8000') */
  readonly base = (typeof localStorage !== 'undefined' && localStorage.getItem('apiUrl')) || DEFAULT_URL;

  health(): Promise<Health> {
    // the first /health call imports PyTorch on the server (~10-15 s)
    return this.req('/health', { method: 'GET' }, 30000);
  }

  /** Fast reachability check (no heavy imports on the server). */
  ping(): Promise<unknown> {
    return this.req('/plants', { method: 'GET' }, 6000);
  }

  plants(): Promise<Record<string, number>> {
    return this.req('/plants', { method: 'GET' });
  }

  sun(facade: string, lat: number, lon: number): Promise<SunResponse> {
    const q = new URLSearchParams({ facade, lat: String(lat), lon: String(lon) });
    return this.req(`/sun?${q}`, { method: 'GET' });
  }

  facade(image: Blob, points: number[][], realWidth: number, realHeight: number | null, rootTiles: number): Promise<FacadeResponse> {
    const f = new FormData();
    f.append('image', image, 'photo.jpg');
    f.append('points', JSON.stringify(points.map((p) => p.map(Math.round))));
    f.append('real_width_m', String(realWidth));
    if (realHeight) f.append('real_height_m', String(realHeight));
    f.append('root_tiles', String(rootTiles));
    f.append('return_mask', 'false');
    return this.req('/facade', { method: 'POST', body: f }, 60000);
  }

  design(ctx: SiteContext, fast = true): Promise<DesignResponse> {
    return this.req('/design', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...ctx, fast }),
    }, 90000);
  }

  tryon(image: Blob, corners: number[][], ctx: SiteContext, realHeight: number | null, design: TileDesign): Promise<TryonResponse> {
    return this.req('/tryon', { method: 'POST', body: this.stageForm(image, corners, ctx, realHeight, design) }, 60000);
  }

  render(image: Blob, corners: number[][], ctx: SiteContext, realHeight: number | null, design: TileDesign,
         strength: number, seed: number): Promise<RenderResponse> {
    const f = this.stageForm(image, corners, ctx, realHeight, design);
    f.append('strength', String(strength));
    f.append('seed', String(seed));
    return this.req('/render', { method: 'POST', body: f }, 240000);
  }

  chat(messages: ChatMessage[]): Promise<{ reply: string; messages: ChatMessage[] }> {
    return this.req('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages }),
    }, 150000);
  }

  /* ---------------- Energy & Comfort Companion ---------------- */
  billRead(file: File): Promise<BillReadResponse> {
    const f = new FormData();
    f.append('file', file, file.name);
    return this.req('/bill/read', { method: 'POST', body: f }, 120000);
  }

  billVerify(bill: BillFields): Promise<BillVerifyResponse> {
    return this.json('/bill/verify', { bill }, 30000);
  }

  billExplain(bill: BillFields, lang: BillLang, useLlm = true): Promise<BillExplainResponse> {
    return this.json('/bill/explain', { bill, lang, use_llm: useLlm }, 150000);
  }

  billAdvice(body: AdviceRequest): Promise<AdviceResponse> {
    return this.json('/bill/advice', body, 90000);
  }

  billAsk(question: string, history: ChatMessage[], bill: BillFields | null, lang?: BillLang): Promise<AskResponse> {
    return this.json('/bill/ask', { question, history, bill, lang }, 150000);
  }

  private json<T>(path: string, body: unknown, timeout: number): Promise<T> {
    return this.req(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }, timeout);
  }

  private stageForm(image: Blob, corners: number[][], ctx: SiteContext, realHeight: number | null, design: TileDesign): FormData {
    const f = new FormData();
    f.append('image', image, 'photo.jpg');
    f.append('corners', JSON.stringify(corners.map((p) => p.map((v) => Math.round(v * 10) / 10))));
    f.append('real_width_m', String(ctx.window_w));
    if (realHeight) f.append('real_height_m', String(realHeight));
    f.append('plants', ctx.plants.join(','));
    f.append('facade', ctx.facade);
    f.append('rh', String(ctx.rh));
    f.append('water_available_l_day', String(ctx.water_available_l_day));
    f.append('root_tiles', String(ctx.root_tiles));
    f.append('design_params', JSON.stringify(design));
    return f;
  }

  private async req<T>(path: string, init: RequestInit, timeoutMs = 30000): Promise<T> {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    let res: Response;
    try {
      res = await fetch(this.base + path, { ...init, signal: ctrl.signal });
    } catch (e) {
      throw new ApiError(
        (e as Error).name === 'AbortError'
          ? 'The design engine took too long to answer. Try again.'
          : `Can't reach the design engine at ${this.base}.`,
      );
    } finally {
      clearTimeout(timer);
    }
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const j = await res.json();
        detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j);
      } catch { /* not JSON */ }
      throw new ApiError(detail, res.status);
    }
    return res.json() as Promise<T>;
  }
}

/* ------------------------------------------------------------------ image helpers */
/** Downscale to <= maxSide and re-encode as JPEG, so the API never rescales (keeps pixel coords 1:1). */
export async function prepareImage(file: File, maxSide = 1600): Promise<{ blob: Blob; url: string; w: number; h: number }> {
  const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' } as ImageBitmapOptions);
  const s = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  const w = Math.round(bmp.width * s);
  const h = Math.round(bmp.height * s);
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  c.getContext('2d')!.drawImage(bmp, 0, 0, w, h);
  bmp.close();
  const blob = await new Promise<Blob>((ok, ko) => c.toBlob((b) => (b ? ok(b) : ko(new Error('encode failed'))), 'image/jpeg', 0.92));
  return { blob, url: URL.createObjectURL(blob), w, h };
}

export const png = (b64: string) => `data:image/png;base64,${b64}`;
