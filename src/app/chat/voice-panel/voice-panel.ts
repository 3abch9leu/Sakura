import {
  Component,
  OnDestroy,
  OnInit,
  computed,
  input,
  output,
  signal,
} from '@angular/core';
import { environment } from '../../../environments/environment';
import { VoiceCall, VoicePhase, VoiceTurn } from '../voice-live';

interface Quota {
  day: string;
  turns: number;
  seconds: number;
}

const STORE = 'ib-voice-quota-v1';
const MAX_TURNS = environment.punicaVoiceTurnsPerDay;
const MAX_SECONDS = environment.punicaVoiceDailySeconds;

function today(): string {
  const date = new Date();
  return `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
}

function readQuota(): Quota {
  try {
    const stored = JSON.parse(localStorage.getItem(STORE) ?? 'null') as Quota | null;
    if (stored && stored.day === today()) {
      return {
        day: stored.day,
        turns: Number(stored.turns) || 0,
        seconds: Number(stored.seconds) || 0,
      };
    }
  } catch {
    /* private mode or a corrupted entry: start clean */
  }
  return { day: today(), turns: 0, seconds: 0 };
}

/**
 * Push-to-talk voice stage for the chat panel.
 *
 * Every turn is its own very short Punica Live call and the call is closed as
 * soon as the answer is complete, because Punica bills connected minutes, not
 * words. Local caps (turns and seconds per day) sit in front of that, so a
 * demo cannot drain the account in one sitting.
 */
@Component({
  selector: 'app-voice-panel',
  templateUrl: './voice-panel.html',
  styleUrl: './voice-panel.css',
})
export class VoicePanelComponent implements OnInit, OnDestroy {
  readonly systemPrompt = input.required<string>();
  readonly closed = output<void>();

  readonly phase = signal<VoicePhase>('idle');
  readonly heard = signal('');
  readonly reply = signal('');
  readonly error = signal<string | null>(null);
  readonly quota = signal<Quota>(readQuota());
  readonly configured = signal<boolean | null>(null);

  readonly maxSeconds = MAX_SECONDS;
  readonly maxTurns = MAX_TURNS;

  readonly turnsLeft = computed(() =>
    Math.max(0, MAX_TURNS - this.quota().turns),
  );
  readonly secondsLeft = computed(() =>
    Math.max(0, MAX_SECONDS - this.quota().seconds),
  );
  readonly spentSeconds = computed(() => Math.round(this.quota().seconds));
  readonly busy = computed(
    () =>
      this.phase() === 'connecting' ||
      this.phase() === 'thinking' ||
      this.phase() === 'speaking',
  );
  readonly canTalk = computed(
    () =>
      this.turnsLeft() > 0 &&
      this.secondsLeft() > 0 &&
      this.configured() !== false &&
      this.phase() !== 'connecting',
  );
  readonly setupMissing = computed(() => this.configured() === false);
  readonly status = computed(() => {
    if (this.setupMissing()) return 'خدمة الصوت موش مربوطة.';
    if (this.turnsLeft() === 0) return 'وصلت للحد اليومي. نجم نحكيو غدوة.';
    if (this.secondsLeft() === 0) return 'الحد اليومي متاع الثواني تكمل.';

    switch (this.phase()) {
      case 'connecting':
        return 'قاعدين نوجدو المكالمة…';
      case 'listening':
        return 'أنا نسمع… احكي، و كي تكمّل اضغط.';
      case 'thinking':
        return 'ثانية… راني نخدم على الجواب.';
      case 'speaking':
        return 'ها أنا نجاوبك بالدارجة…';
      case 'error':
        return 'صار مشكل. عاود جرّب.';
      default:
        return 'اضغط على الميكرو و احكي بالدارجة.';
    }
  });

  private call: VoiceCall | null = null;
  private turns: VoiceTurn[] = [];
  private counted = false;

  private readonly onHide = () => {
    if (
      typeof document !== 'undefined' &&
      document.hidden &&
      this.call &&
      this.phase() !== 'idle' &&
      this.phase() !== 'error'
    ) {
      this.call.dispose();
      this.phase.set('idle');
    }
  };

  ngOnInit(): void {
    this.checkRelay();
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', this.onHide);
    }
  }

  ngOnDestroy(): void {
    this.call?.dispose();
    this.call = null;
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this.onHide);
    }
  }

  toggle(): void {
    if (this.phase() === 'listening') {
      this.call?.finalize();
      return;
    }
    if (this.busy() || !this.canTalk() || this.setupMissing()) return;
    void this.beginTurn();
  }

  close(): void {
    this.call?.dispose();
    this.call = null;
    this.closed.emit();
  }

  private async beginTurn(): Promise<void> {
    this.error.set(null);
    this.heard.set('');
    this.reply.set('');
    this.counted = false;

    const call = new VoiceCall({
      onState: (phase) => {
        this.phase.set(phase);
        if (phase === 'listening' && !this.counted) {
          this.counted = true;
          this.reserveTurn();
        }
      },
      onHeard: (text, final) => {
        if (text) this.heard.set(text);
        if (final && text.trim()) this.remember('user', text.trim());
      },
      onReply: (text) => {
        this.heard.set('');
        this.reply.set(text);
        this.remember('assistant', text);
      },
      onBilled: (seconds) => this.addSeconds(seconds),
      onError: (message) => {
        this.error.set(message);
        this.phase.set('error');
      },
    });

    this.call = call;
    await call.startTurn(this.turns.slice(-8), this.systemPrompt());
  }

  private remember(role: VoiceTurn['role'], content: string): void {
    const last = this.turns[this.turns.length - 1];
    if (last && last.role === role && last.content === content) return;
    this.turns.push({ role, content });
    if (this.turns.length > 12) {
      this.turns.splice(0, this.turns.length - 12);
    }
  }

  private reserveTurn(): void {
    const quota = readQuota();
    this.commit({ ...quota, turns: quota.turns + 1 });
  }

  private addSeconds(seconds: number): void {
    if (!Number.isFinite(seconds) || seconds <= 0) return;
    const quota = readQuota();
    this.commit({ ...quota, seconds: quota.seconds + seconds });
  }

  private commit(quota: Quota): void {
    this.quota.set(quota);
    try {
      localStorage.setItem(STORE, JSON.stringify(quota));
    } catch {
      /* storage unavailable: the in-memory guard still works this visit */
    }
  }

  private async checkRelay(): Promise<void> {
    const base = (environment.punicaLiveServer || '').trim().replace(/\/+$/, '');
    if (!base) {
      this.configured.set(false);
      return;
    }
    try {
      const response = await fetch(`${base}/health`, { cache: 'no-store' });
      if (!response.ok) {
        this.configured.set(false);
        return;
      }
      const data = (await response.json()) as { configured?: boolean };
      this.configured.set(Boolean(data?.configured));
    } catch {
      this.configured.set(false);
    }
  }
}
