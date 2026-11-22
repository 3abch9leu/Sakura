import { Component, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { filter, map } from 'rxjs';

interface NavItem { path: string; label: string; hint: string; icon: string }
interface NavGroup { title: string; items: NavItem[] }

const GROUPS: NavGroup[] = [
  { title: 'Start', items: [
    { path: '/', label: 'Home', hint: 'What INBETWEEN is', icon: 'M4 11l8-6 8 6v9h-5v-6h-6v6H4z' },
    { path: '/space', label: 'Choose your space', hint: 'Building or farm', icon: 'M4 20V9l8-5 8 5v11M9 20v-6h6v6' },
    { path: '/map', label: 'Scenarios map', hint: 'Where it could go in Tunisia', icon: 'M12 21s-6-5.5-6-11a6 6 0 0112 0c0 5.5-6 11-6 11zM12 12a2 2 0 100-4 2 2 0 000 4z' },
  ] },
  { title: 'Design', items: [
    { path: '/studio', label: 'Design studio', hint: 'Photo → patterns → preview', icon: 'M4 20l6-6m-2-6l8 8M14 4l6 6-8 8-6-6z' },
    { path: '/design', label: 'Quick window design', hint: 'One window, fast', icon: 'M5 4h14v16H5zM5 12h14M12 4v16' },
  ] },
  { title: 'Grow & monitor', items: [
    { path: '/dashboard', label: 'Digital twin', hint: '3D model, water, sensors', icon: 'M12 3s6 7 6 11a6 6 0 01-12 0c0-4 6-11 6-11z' },
    { path: '/plant-health', label: 'Plant health', hint: 'Check a leaf, get a care plan', icon: 'M5 19c8 0 14-6 14-14C11 5 5 11 5 19zm0 0l7-7' },
    { path: '/camera', label: 'Plant camera', hint: 'A phone takes photos for you', icon: 'M4 8h4l2-3h4l2 3h4v11H4zM12 17a4 4 0 100-8 4 4 0 000 8z' },
    { path: '/gallery', label: 'Plant gallery', hint: 'Live photos from the phone', icon: 'M4 5h16v14H4zM4 15l5-5 4 4 3-3 4 4M15 9h.01' },
  ] },
  { title: 'Water & weather', items: [
    { path: '/weather', label: 'Weather & climate', hint: 'AI forecast, sensors, advice', icon: 'M7 17a4 4 0 010-8 5 5 0 019.6-1.5A3.5 3.5 0 1117 17zM9 20l-1 2m5-2l-1 2m5-2l-1 2' },
    { path: '/water-quality', label: 'Water quality', hint: 'Is this water safe for plants?', icon: 'M12 3s6 7 6 11a6 6 0 01-12 0c0-4 6-11 6-11zM9 14l2 2 4-4' },
  ] },
  { title: 'Save', items: [
    { path: '/energy', label: 'Energy · STEG bill', hint: 'Read and check your bill', icon: 'M13 3L5 14h6l-1 7 8-11h-6z' },
  ] },
];

/** Global navigation for every app page: where you are, and one click to any feature. */
@Component({
  selector: 'app-nav',
  imports: [RouterLink, RouterLinkActive],
  template: `
    <aside class="nav" [class.nav--mini]="mini()" [class.nav--open]="open()" aria-label="INBETWEEN features">
      <div class="nav__top">
        <a class="nav__brand" routerLink="/" (click)="open.set(false)">
          <img src="images/logo-mark-96.png" alt="" width="28" height="28" /><b>INBETWEEN</b>
        </a>
        <span class="nav__here">{{ current()?.label }}</span>
        <button type="button" class="nav__menu" (click)="open.set(!open())" [attr.aria-expanded]="open()" aria-label="Menu">
          <i></i><i></i>
        </button>
      </div>
      <nav class="nav__list">
        @for (g of groups; track g.title) {
          <p class="nav__group">{{ g.title }}</p>
          @for (it of g.items; track it.path) {
            <a [routerLink]="it.path" routerLinkActive="on" [routerLinkActiveOptions]="{ exact: it.path === '/' }" (click)="open.set(false)"
               [attr.title]="mini() ? it.label + ' · ' + it.hint : null">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path [attr.d]="it.icon" /></svg>
              <span class="nav__txt"><b>{{ it.label }}</b><small>{{ it.hint }}</small></span>
            </a>
          }
        }
      </nav>
      <button type="button" class="nav__fold" (click)="toggleMini()" [attr.aria-label]="mini() ? 'Expand the menu' : 'Collapse the menu'">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path [attr.d]="mini() ? 'M9 6l6 6-6 6' : 'M15 6l-6 6 6 6'" /></svg>
        <span class="nav__txt">Collapse</span>
      </button>
    </aside>
    @if (open()) { <div class="nav__scrim" (click)="open.set(false)"></div> }
  `,
  styles: [`
    :host { --olive: #414b30; --ink: #292c25; --muted: #6a6d63; --line: rgba(41, 44, 37, .13); --ivory: #f5f1e8; display: contents; }
    .nav { position: sticky; top: 0; height: 100vh; width: 248px; display: flex; flex-direction: column; background: #efe9dd;
      border-right: 1px solid var(--line); font-family: 'Inter', system-ui, sans-serif; color: var(--ink); z-index: 40; transition: width .25s; }
    .nav--mini { width: 68px; }
    .nav__top { display: flex; align-items: center; gap: 10px; padding: 16px 16px 10px; }
    .nav__brand { display: flex; align-items: center; gap: 10px; text-decoration: none; color: inherit; }
    .nav__brand img { border-radius: 2px; mix-blend-mode: multiply; }
    .nav__brand b { font-size: .74rem; letter-spacing: .24em; color: var(--olive); }
    .nav--mini .nav__brand b { display: none; }
    .nav__here, .nav__menu { display: none; }
    .nav__list { flex: 1; overflow-y: auto; padding: 4px 10px 10px; display: grid; align-content: start; gap: 2px; }
    .nav__group { margin: 14px 8px 4px; font-size: .64rem; letter-spacing: .16em; text-transform: uppercase; color: #9a7a64; }
    .nav--mini .nav__group { visibility: hidden; height: 6px; margin: 6px 0; }
    .nav__list a { display: grid; grid-template-columns: 22px 1fr; gap: 12px; align-items: center; padding: 8px 10px; border-radius: 2px;
      text-decoration: none; color: var(--ink); border-left: 2px solid transparent; transition: background .2s; }
    .nav__list a:hover { background: rgba(65, 75, 48, .07); }
    .nav__list a.on { background: var(--ivory); border-left-color: var(--olive); }
    .nav__list a.on b { color: var(--olive); }
    .nav__list svg, .nav__fold svg { width: 20px; height: 20px; fill: none; stroke: currentColor; stroke-width: 1.4; stroke-linecap: round; stroke-linejoin: round; color: var(--olive); }
    .nav__txt { display: grid; min-width: 0; }
    .nav__txt b { font-size: .86rem; font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .nav__txt small { font-size: .7rem; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .nav--mini .nav__txt { display: none; }
    .nav--mini .nav__list a { grid-template-columns: 22px; justify-content: center; }
    .nav__fold { display: flex; align-items: center; gap: 10px; margin: 8px 10px 14px; padding: 8px 10px; border: 1px solid var(--line); border-radius: 2px;
      background: none; font: inherit; font-size: .78rem; color: var(--muted); cursor: pointer; }
    .nav--mini .nav__fold { justify-content: center; }
    a:focus-visible, button:focus-visible { outline: 2px solid #b77b59; outline-offset: 2px; }

    /* phones and small tablets: a top bar with the current page, the full menu in a drawer */
    @media (max-width: 900px) {
      .nav, .nav--mini { position: fixed; inset: 0 0 auto 0; width: auto; height: auto; flex-direction: column; border-right: 0; border-bottom: 1px solid var(--line); }
      .nav__top { padding: 10px 14px; }
      .nav--mini .nav__brand b { display: inline; }
      .nav__here { display: block; flex: 1; text-align: right; font-size: .8rem; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
      .nav__menu { display: block; width: 38px; height: 38px; border: 1px solid var(--line); border-radius: 2px; background: var(--ivory); cursor: pointer; }
      .nav__menu i { display: block; width: 15px; height: 1.5px; margin: 4px auto; background: var(--ink); }
      .nav__list, .nav__fold { display: none; }
      .nav--open .nav__list { display: grid; max-height: calc(100vh - 60px); padding-bottom: 18px; }
      .nav--open .nav__txt, .nav--mini.nav--open .nav__txt { display: grid; }
      .nav--mini.nav--open .nav__list a { grid-template-columns: 22px 1fr; justify-content: stretch; }
      .nav--mini .nav__group { visibility: visible; height: auto; margin: 14px 8px 4px; }
      .nav__scrim { position: fixed; inset: 0; z-index: 39; background: rgba(41, 44, 37, .25); }
    }
    @media (prefers-reduced-motion: reduce) { .nav { transition: none; } }
  `],
})
export class AppNavComponent {
  private readonly router = inject(Router);
  readonly groups = GROUPS;
  readonly open = signal(false);
  readonly mini = signal(typeof localStorage !== 'undefined' && localStorage.getItem('inbetween.nav.mini') === '1');
  private readonly url = toSignal(this.router.events.pipe(filter((e) => e instanceof NavigationEnd), map(() => this.router.url)),
    { initialValue: this.router.url });
  readonly current = computed(() => {
    const path = (this.url() || '/').split('?')[0];
    return GROUPS.flatMap((g) => g.items).find((i) => i.path === path) ?? null;
  });

  toggleMini(): void {
    this.mini.set(!this.mini());
    localStorage.setItem('inbetween.nav.mini', this.mini() ? '1' : '0');
  }
}
