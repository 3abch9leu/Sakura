import { Component, inject } from '@angular/core';
import { NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { filter, map } from 'rxjs';
import { AppNavComponent } from './shell/app-nav';
import { ChatComponent } from './chat/chat';

/** Pages that keep their own full-screen navigation (the landing page and the sign-in page). */
const NO_NAV = new Set(['/', '/login']);
/** Pages with their own assistant (the bill assistant on /energy) or no chat at all. */
const NO_CHAT = new Set(['/login', '/energy']);

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, AppNavComponent, ChatComponent],
  templateUrl: './app.html',
  styleUrl: './app.css',
})
export class App {
  private readonly router = inject(Router);
  private readonly url = toSignal(this.router.events.pipe(filter((e) => e instanceof NavigationEnd), map(() => this.router.url)),
    { initialValue: '/' });

  showChat(): boolean {
    return !NO_CHAT.has((this.url() || '/').split('?')[0].split('#')[0]);
  }

  showNav(): boolean {
    return !NO_NAV.has((this.url() || '/').split('?')[0].split('#')[0]);
  }
}
