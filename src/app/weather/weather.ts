import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { Api, ClimateAdvice, WeatherAccuracy, WeatherForecast, WeatherHour } from '../api';

const ACTION_LABEL: Record<string, string> = {
  ventilation: 'Ventilation', irrigation: 'Watering', evaporative_cooling: 'Evaporative cooling', shading: 'Shading',
};
const REC_LABEL: Record<string, string> = {
  open_or_run_fan: 'Open or run the fan', keep_closed: 'Keep closed', irrigate: 'Water now', blocked: 'Blocked: reservoir low',
  defer_and_recheck: 'Wait and recheck', not_needed: 'Not needed', favorable: 'Favourable', unfavorable_or_unknown: 'Not favourable',
  consider_shading: 'Consider shading', not_indicated: 'Not needed',
};
const SKY: Record<string, string> = {
  Clear: 'M12 7a5 5 0 100 10 5 5 0 000-10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  Cloudy: 'M7 18a4 4 0 010-8 5.5 5.5 0 0110.6-1.6A3.8 3.8 0 1117.5 18z',
  Fog: 'M4 9h16M3 13h18M5 17h14',
  Drizzle: 'M7 14a4 4 0 010-8 5.5 5.5 0 0110.6-1.6A3.8 3.8 0 1117.5 14zM9 17l-.5 2M13 17l-.5 2M17 17l-.5 2',
  Rain: 'M7 14a4 4 0 010-8 5.5 5.5 0 0110.6-1.6A3.8 3.8 0 1117.5 14zM8 16l-1 4M12 16l-1 4M16 16l-1 4',
  Snow: 'M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9',
  Thunderstorm: 'M7 13a4 4 0 010-8 5.5 5.5 0 0110.6-1.6A3.8 3.8 0 1117.5 13zM12 13l-2 4h4l-2 4',
};

/** AI weather prediction (team model DistilHweh-446k) + ESP32 greenhouse climate advice. */
@Component({
  selector: 'app-weather',
  imports: [DecimalPipe, RouterLink],
  templateUrl: './weather.html',
  styleUrl: './weather.css',
})
export class WeatherComponent implements OnInit, OnDestroy {
  private readonly api = inject(Api);
  readonly fc = signal<WeatherForecast | null>(null);
  readonly acc = signal<WeatherAccuracy | null>(null);
  readonly advice = signal<ClimateAdvice | null>(null);
  readonly loading = signal(true);
  readonly error = signal('');
  readonly waited = signal(0);
  readonly hover = signal<number | null>(null);
  readonly sky = SKY;
  private timers: ReturnType<typeof setInterval>[] = [];

  readonly hours = computed<WeatherHour[]>(() => this.fc()?.forecast ?? []);
  readonly now = computed(() => this.hours()[0] ?? null);
  readonly focus = computed(() => this.hours()[this.hover() ?? 0] ?? null);
  readonly maxRain = computed(() => Math.max(0, ...this.hours().map((h) => h.rain_probability)));
  readonly rainMm = computed(() => this.hours().reduce((s, h) => s + h.precipitation_mm, 0));

  /** Temperature line (one series, one axis) and rain-chance bars (their own small chart). */
  readonly chart = computed(() => {
    const hs = this.hours();
    if (!hs.length) return null;
    const W = 640, H = 180, L = 40, R = 16, T = 18, B = 26;
    const ts = hs.map((h) => h.temperature_c);
    let lo = Math.floor(Math.min(...ts) - 1), hi = Math.ceil(Math.max(...ts) + 1);
    if (hi - lo < 4) { const m = (hi + lo) / 2; lo = Math.floor(m - 2); hi = Math.ceil(m + 2); }
    const x = (i: number) => L + (i / Math.max(1, hs.length - 1)) * (W - L - R);
    const y = (t: number) => T + (1 - (t - lo) / (hi - lo)) * (H - T - B);
    const line = ts.map((t, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(t).toFixed(1)}`).join(' ');
    const area = `${line} L${x(hs.length - 1).toFixed(1)} ${H - B} L${x(0).toFixed(1)} ${H - B} Z`;
    const step = (hi - lo) <= 6 ? 1 : 2;
    const yTicks: { v: number; y: number }[] = [];
    for (let v = lo; v <= hi; v += step) yTicks.push({ v, y: y(v) });
    const pts = hs.map((h, i) => ({ x: x(i), y: y(h.temperature_c), t: this.hhmm(h.time_local), i }));
    const bw = (W - L - R) / hs.length;
    const bars = hs.map((h, i) => ({ x: x(i) - Math.min(14, bw * 0.6) / 2, w: Math.min(14, bw * 0.6), h: h.rain_probability * 60, p: h.rain_probability, i }));
    return { W, H, B, L, R, line, area, yTicks, pts, bars, hit: bw };
  });

  /** Plain-language water advice for the living wall, from the forecast (a transparent rule, shown as such). */
  readonly waterTip = computed(() => {
    const r = this.maxRain(), mm = this.rainMm(), t = Math.max(...this.hours().map((h) => h.temperature_c));
    if (!this.hours().length) return null;
    if (r >= 0.6) return { tone: 'rain', text: `Rain is likely (up to ${(r * 100).toFixed(0)} %, about ${mm.toFixed(1)} mm in 12 h): the rain collector may top up the reservoir. Wait before refilling.` };
    if (t >= 30) return { tone: 'heat', text: `Hot hours ahead (up to ${t.toFixed(0)} °C) and little rain: plants drink more. Check the reservoir level this evening.` };
    return { tone: 'ok', text: `No significant rain expected (max ${(r * 100).toFixed(0)} %). Follow your normal refill plan.` };
  });

  ngOnInit(): void {
    this.timers.push(setInterval(() => this.loading() && this.waited.update((s) => s + 1), 1000));
    this.load();
    this.api.weatherAccuracy().then((a) => this.acc.set(a)).catch(() => { /* optional */ });
    this.timers.push(setInterval(() => this.loadAdvice(), 30000));   // sensors post every few seconds
  }

  ngOnDestroy(): void {
    this.timers.forEach((t) => clearInterval(t));
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set('');
    this.waited.set(0);
    try {
      this.fc.set(await this.api.weatherForecast());
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.loading.set(false);
    }
    this.loadAdvice();
  }

  async loadAdvice(): Promise<void> {
    try { this.advice.set(await this.api.climateRecommendations()); } catch { /* shown as offline */ }
  }

  hhmm(iso: string): string {
    return iso.slice(11, 16);
  }

  skyPath(c: string): string { return SKY[c] ?? SKY['Cloudy']; }
  actionLabel(a: string): string { return ACTION_LABEL[a] ?? a; }
  recLabel(r: string): string { return REC_LABEL[r] ?? r.replace(/_/g, ' '); }
  isGo(r: string): boolean { return ['open_or_run_fan', 'irrigate', 'favorable', 'consider_shading'].includes(r); }
}
