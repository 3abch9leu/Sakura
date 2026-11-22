/* Shared types: studio (design) -> digital twin (monitoring). Mirrors rootcode/styles.py, space.py, water.py */

export type XY = [number, number];

export interface Reservoir { capacity_l: number; top_y: number; bottom_y: number }

export interface Cell {
  id: number;
  cx: number; cy: number; w: number; h: number;
  row: number; col: number;
  poly: XY[];
  role: 'plant' | 'open';
  plant?: string;
  motif: XY[][];
  reservoir: Reservoir | null;
  branch: number | null;
  zone: 'high' | 'medium' | 'low';
  exposure_kwh_m2: number;
  exposure_winter_kwh_m2?: number;
  direct_fraction: number[];
  direct_fraction_winter?: number[];
  need_l_day?: number;
}

export interface Branch { id: number; cells: number[]; plants: string[]; capacity_l: number; need_l_day: number }

export type Greenery = 'full' | 'balanced' | 'pattern';

export interface GenDesign {
  style: string; name: string; culture: string; text: string;
  width_m: number; height_m: number; depth_m: number;
  cells: Cell[];
  segments: { a: XY; b: XY; w: number }[];
  channels: { branch: number | null; points: XY[]; w: number }[];
  supply: { x: number; y_top: number; y_in: number };
  branches: Branch[];
  metrics: {
    cells: number; planting_cells: number; open_cells: number; open_fraction: number; screen_porosity: number;
    aperture_mm: number; storage_l: number; plant_need_l_day: number; frame_length_m: number; wood_m3: number;
    screen_m2: number; hidden_channel_m: number; area_m2: number; water_limited: boolean; greenery?: Greenery;
  };
  /** What the design asks of the owner: litres per day, reservoir size and refill interval (model estimate). */
  water?: {
    summer_l_day: number; winter_l_day: number; storage_l: number; pockets: number; per_plant: Record<string, number>;
    refill_days_summer: number | null; refill_days_winter: number | null; basis: string; hand_watered_pockets?: number;
  };
  svg?: string;
  fit?: string;
  optimisation?: { feasible: boolean; message: string | null; summary: {
    heat_reduction_pct: number; water_l_day: number; plant_deficit: number; drain_time_min: number; reynolds_max: number;
    widths_mm: number[]; water_per_root_tile_l: number; plant_safe: boolean } | null };
  cost_tnd?: number | null;
  cost_note?: string | null;
  context?: { lat: number; lon: number; facade_azimuth: number; city?: string };
  demo?: boolean;
  error?: string;
}

export interface SolarDay {
  date: string; times: string[]; sun_azimuth: number[]; sun_elevation: number[]; facing: boolean[];
  tan_v: number[]; tan_h: number[]; beam_w_m2: number[]; diffuse_w_m2: number[];
  sunrise: string; sunset: string; direct_hours: number; daily_kwh_m2: number; daily_direct_kwh_m2: number;
  peak_w_m2: number; azimuth_facade: number; note: string;
}

export interface Suggestion {
  kind: 'surface' | 'opening' | 'other'; score: number | null; area_frac: number; bbox: number[]; seed: XY;
  polygons: { outer: XY[]; holes: XY[][] }[];
}

export interface UploadResponse {
  image_id: string; width: number; height: number;
  exif: { lat: number | null; lon: number | null; camera_heading_deg: number | null; facade_azimuth_deg: number | null; date: string | null };
  suggestions: { backend: string | null; regions: Suggestion[]; note: string } | null;
  suggest_seconds?: number;
}

export interface Obstacle { kind: 'opening' | 'obstacle'; label: string; polygon: XY[]; bbox: number[]; source: string }

export interface SegmentResponse {
  backend: string; score: number | null; area_frac: number; overlay_png_base64: string;
  polygons: { outer: XY[]; holes: XY[][] }[]; obstacles: Obstacle[]; seconds: number;
}

export interface AreaResponse {
  width_m: number; height_m: number; usable_area_m2: number; selected_area_m2: number;
  region_polygons_m: { outer: XY[]; holes: XY[][] }[];
  obstacles_m: { x: number; y: number; w: number; h: number }[];
  quad_px: XY[]; plane_to_photo: number[][];
  scale: { m_per_px: number; height_source: string };
  warnings: string[];
}

export interface StylesResponse {
  exposure_class: 'high' | 'moderate' | 'low';
  recommendations: { topic: string; text: string }[];
  sun: Record<'summer' | 'winter' | 'design', { date: string; sunrise: string; sunset: string; direct_hours: number; daily_kwh_m2: number; daily_direct_kwh_m2: number; peak_w_m2: number }>;
  sun_times: { summer: string[]; winter: string[] };
  designs: GenDesign[];
  seconds: number;
  note: string;
}

export interface PreviewResponse {
  segmented_overlay_png_base64: string; geometry_png_base64: string; realistic_png_base64: string | null;
  realistic: boolean; message: string | null; seconds: number; render_seconds?: number;
}

export interface Alert { level: 'critical' | 'warning' | 'info'; code: string; title: string; text: string }

export interface BranchStatus {
  id: number; plants: string[]; capacity_l: number; level_frac: number; remaining_l: number; level_source: string;
  need_today_l: number; need_tomorrow_l: number; required_until_refill_l: number; dynamic_threshold_frac: number;
  autonomy_hours: number; status: 'ok' | 'warning' | 'critical'; alerts: Alert[]; refill_l: number;
  timeline: { date: string | null; need_l: number; rain_gain_l: number; net_l: number; heat_factor: number; humidity_factor: number; tmax_c: number | null; rain_mm: number | null }[];
}

export interface SensorReading {
  source: string; branch: number | null; level_raw: number | null; level_frac: number | null;
  temp_c: number | null; humidity: number | null; ts: number; stale?: boolean;
}

export interface WaterResponse {
  branches: BranchStatus[];
  weather: { date: string | null; tmax_c: number | null; rh: number | null; rain_mm: number | null }[];
  weather_source: string; sensor: SensorReading | null;
  device: { code: string; buzz: boolean; line1: string; line2: string };
  model: string;
}

export interface SavedInstallation {
  design: GenDesign;
  context: { lat: number; lon: number; facade_azimuth: number; city: string };
  plants: string[];
  water_available_l_day: number;
  saved_at: string;
}

export const INSTALL_KEY = 'inbetween.installation.v1';

export function loadInstallation(): SavedInstallation | null {
  try {
    const s = localStorage.getItem(INSTALL_KEY);
    return s ? (JSON.parse(s) as SavedInstallation) : null;
  } catch {
    return null;
  }
}

export function saveInstallation(i: SavedInstallation): void {
  const d = { ...i, design: { ...i.design, svg: undefined } };
  localStorage.setItem(INSTALL_KEY, JSON.stringify(d));
}

export const PLANT_LABEL: Record<string, string> = {
  mint: 'Mint', basil: 'Basil', parsley: 'Parsley', lettuce: 'Lettuce', strawberry: 'Strawberry',
  chili: 'Chili', cherry_tomato: 'Cherry tomato',
};
