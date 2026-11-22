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

import type {
  AreaResponse, Branch, GenDesign, PreviewResponse, SegmentResponse, SensorReading, SolarDay, StylesResponse, UploadResponse,
  WaterResponse,
} from './twin/types';

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

  /** useLlm=false: instant deterministic text. useLlm=true: the AI rewrite (server caps it at ~45 s). */
  billExplain(bill: BillFields, lang: BillLang, useLlm = false): Promise<BillExplainResponse> {
    return this.json('/bill/explain', { bill, lang, use_llm: useLlm }, useLlm ? 60000 : 15000);
  }

  billAdvice(body: AdviceRequest): Promise<AdviceResponse> {
    return this.json('/bill/advice', body, 90000);
  }

  billAsk(question: string, history: ChatMessage[], bill: BillFields | null, lang?: BillLang): Promise<AskResponse> {
    return this.json('/bill/ask', { question, history, bill, lang }, 150000);
  }

  /* ---------------- Studio: space -> sun -> styles -> preview ---------------- */
  spaceUpload(file: Blob, name = 'photo.jpg'): Promise<UploadResponse> {
    const f = new FormData();
    f.append('image', file, name);
    f.append('suggest', 'true');
    return this.req('/space/upload', { method: 'POST', body: f }, 180000);
  }

  spaceSegment(body: { image_id: string; mode: 'click' | 'polygon' | 'rect'; points?: number[][]; labels?: number[];
    polygon?: number[][]; rect?: number[] }): Promise<SegmentResponse> {
    return this.json('/space/segment', body, 90000);
  }

  spaceArea(body: { image_id: string; selection: unknown[]; obstacles: number[][][];
    reference: { p1?: number[]; p2?: number[]; edge?: 'width' | 'height'; length_m: number };
    height_m?: number | null }): Promise<AreaResponse> {
    return this.json('/space/area', body, 30000);
  }

  solarDay(azimuth: number, lat: number, lon: number, date: string, stepMin = 30): Promise<SolarDay> {
    const q = new URLSearchParams({ azimuth: String(azimuth), lat: String(lat), lon: String(lon), date, step_min: String(stepMin) });
    return this.req(`/solar/day?${q}`, { method: 'GET' }, 30000);
  }

  studioStyles(body: { area: unknown; plants: string[]; styles: string[]; facade_azimuth: number; lat: number; lon: number;
    water_available_l_day: number | null; greenery: string; prices?: Record<string, number> | null }): Promise<StylesResponse> {
    return this.json('/studio/styles', body, 180000);
  }

  studioPreview(body: { image_id: string; area: unknown; design: GenDesign; realistic: boolean; ai?: boolean; seed?: number }): Promise<PreviewResponse> {
    return this.json('/studio/preview', body, body.ai ? 300000 : 60000);
  }

  /** Small drawing of every cultural pattern (real generator output), for the pattern picker. */
  studioPatterns(): Promise<{ id: string; name: string; culture: string; text: string; svg: string | null }[]> {
    return this.req('/studio/patterns', { method: 'GET' }, 30000);
  }

  installationDemo(): Promise<GenDesign> {
    return this.req('/installation/demo', { method: 'GET' }, 30000);
  }

  /* ---------------- Digital twin: water + sensors ---------------- */
  waterStatus(body: { branches: Branch[]; levels: Record<string, number>; sensor_branch?: number | null; lat: number; lon: number;
    hours_to_refill: number; safety_margin: number; losses: number; collector_m2: number }): Promise<WaterResponse> {
    return this.json('/water/status', body, 30000);
  }

  sensorsPost(r: { source: string; branch: number | null; level_raw?: number; level_frac?: number; temp_c?: number | null; humidity?: number | null }): Promise<SensorReading> {
    return this.json('/sensors', r, 10000);
  }

  sensorsGet(): Promise<{ reading: SensorReading | null; history: SensorReading[] }> {
    return this.req('/sensors', { method: 'GET' }, 10000);
  }

  /* ---------------- Leaf health (team DeepLabV3) + phone camera ---------------- */
  leafAnalyze(file: Blob, plant: string | null, cell: number | null, loc?: { lat: number; lon: number } | null): Promise<LeafResult> {
    const f = new FormData();
    f.append('file', file, 'leaf.jpg');
    if (plant) f.append('plant', plant);
    if (cell != null) f.append('cell', String(cell));
    if (loc) { f.append('lat', String(loc.lat)); f.append('lon', String(loc.lon)); }
    return this.req('/leaf/analyze', { method: 'POST', body: f }, 90000);
  }

  leafAnalyzePhoto(id: string, plant: string | null, loc?: { lat: number; lon: number } | null): Promise<LeafResult> {
    const f = new FormData();
    if (plant) f.append('plant', plant);
    if (loc) { f.append('lat', String(loc.lat)); f.append('lon', String(loc.lon)); }
    return this.req(`/api/camera/photos/${encodeURIComponent(id)}/analyze`, { method: 'POST', body: f }, 90000);
  }

  cameraPhotos(cell: number | null): Promise<CameraPhoto[]> {
    const q = cell != null ? `?cell=${cell}&limit=12` : '?limit=12';
    return this.req(`/api/camera/photos${q}`, { method: 'GET' }, 10000);
  }

  /* ---------------- AI weather prediction + ESP32 climate (weather_prediction branch) ---------------- */
  weatherForecast(): Promise<WeatherForecast> {
    return this.req('/api/weather/forecast', { method: 'GET' }, 90000);
  }

  weatherAccuracy(): Promise<WeatherAccuracy> {
    return this.req('/api/weather/accuracy', { method: 'GET' }, 15000);
  }

  climateRecommendations(): Promise<ClimateAdvice> {
    return this.req('/api/climate/recommendations', { method: 'GET' }, 90000);
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

export interface LeafResult {
  image_size: [number, number];
  original_jpg_base64: string;
  overlay_jpg_base64: string;
  affected_share: number;
  lesion_share_of_image: number;
  leaf_share_of_image: number;
  spots: number;
  regions_ignored: number;
  mean_confidence: number | null;
  severity: 'none' | 'low' | 'moderate' | 'high';
  label: string;
  recommendations: string[];
  warnings: string[];
  plant: string | null;
  cell: number | null;
  model: { name: string; device: string; input: string; validation: string };
  timing_ms: { decode: number; inference: number; post: number; total: number; includes_model_load: boolean };
  disclaimer: string;
  camera_photo?: { id: string; ts: number };
  care: { summary: string; today: string[]; week: string[]; prevention: string[]; expert: string | null; why: string[]; plant_note: string | null };
  measurements: { lesion_tone: string | null; yellowing_share: number; mean_area_share: number; largest_area_share: number };
  weather_used: boolean;
}

export interface CameraPhoto { id: string; ts: number; cell: number | null; thumb_jpg_base64: string }

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


/* ---------------- weather / climate types ---------------- */
export interface WeatherHour {
  lead_hours: number; time_local: string; temperature_c: number; humidity_pct: number; apparent_temperature_c: number;
  precipitation_mm: number; cloud_cover_pct: number; wind_speed_kmh: number; rain_probability: number;
  weather_class: string; weather_probabilities: Record<string, number>;
}
export interface WeatherForecast { city: string; model: string; history_hours: number; forecast_hours: number; forecast: WeatherHour[] }
export interface WeatherAccuracy {
  samples: number; source: string; period?: string[];
  metrics: Record<string, { mae: number; rmse: number; n: number }>;
}
export interface ClimateAction { action: string; recommendation: string; reason: string; actuator_command?: string }
export interface ClimateAdvice {
  status: string; sensor_status?: string; actions: ClimateAction[]; safety_constraints: string[];
  current_conditions: { temperature_c: number; humidity_pct: number; light_adc: number; soil_moisture_pct: number;
    water_level_low: boolean; timestamp: string; device_id: string } | null;
  forecast_error?: string;
}
