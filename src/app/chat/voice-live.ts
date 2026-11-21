import { environment } from '../../environments/environment';

export type VoicePhase =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'thinking'
  | 'speaking'
  | 'error';

export interface VoiceTurn {
  role: 'user' | 'assistant';
  content: string;
}

export interface VoiceCallbacks {
  onState(state: VoicePhase): void;
  onHeard(text: string, final: boolean): void;
  onReply(text: string): void;
  onBilled(seconds: number): void;
  onError(message: string): void;
}

interface LiveSession {
  url?: string;
  client_secret?: { value?: string } | string;
}

interface ServerEvent {
  type?: string;
  text?: string;
  delta?: string;
  audio?: { seq?: number; wav_b64?: string };
  done?: boolean;
  success?: boolean;
  usage?: { billable_seconds?: number };
  message?: string;
}

const CAPTURE_RATE = 16_000;
/** 60 ms of PCM16 per frame; the API accepts up to 64 KiB. */
const FRAME_SAMPLES = 960;
/** Keep the first 300 ms so speech that starts before `ready` is not lost. */
const PRE_ROLL_SAMPLES = 4_800;

/**
 * One short Punica Live turn.
 *
 * Punica bills $0.167 per connected minute from the first AI audio until the
 * socket closes (listening, pauses and tool time included). So this class
 * never keeps a call open: it opens a session when the mic is pressed, sends
 * `end` the moment the turn is complete, and lets playback finish locally.
 */
export class VoiceCall {
  private ws: WebSocket | null = null;
  private mic: MediaStream | null = null;
  private capture: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private playback: AudioContext | null = null;
  private playing = new Set<AudioBufferSourceNode>();
  private audioChain: Promise<void> = Promise.resolve();
  private nextAudioAt = 0;

  private pending: number[] = [];
  private preRoll: number[] = [];
  private sending = false;
  private finalized = false;
  private turnDone = false;
  private ending = false;
  private reported = false;
  private disposed = false;
  private phase: VoicePhase = 'idle';

  private answer = '';
  private billedAt = 0;
  private speakTimer: ReturnType<typeof setTimeout> | null = null;
  private answerTimer: ReturnType<typeof setTimeout> | null = null;
  private closeTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly cb: VoiceCallbacks) {}

  async startTurn(history: VoiceTurn[], system: string): Promise<void> {
    if (this.disposed) return;

    this.resetTurn();
    this.setState('connecting');

    try {
      this.ensurePlayback();
      await this.openMic();
      const session = await this.createSession();
      this.connect(session, history.slice(-8), system);
    } catch (error) {
      this.fail(messageOf(error));
    }
  }

  finalize(): void {
    if (this.phase !== 'listening' || this.finalized || this.disposed) return;

    this.finalized = true;
    this.sending = false;
    this.clearSpeakTimer();
    this.stopMic();
    this.send({ type: 'finalize' });
    this.setState('thinking');

    this.answerTimer = setTimeout(() => {
      if (this.turnDone || this.disposed) return;
      if (this.answer.trim()) {
        this.finishWith(this.answer);
      } else {
        this.fail('خادم الصوت ما جاوبش في الوقت. عاود جرّب.');
      }
    }, environment.punicaVoiceMaxAnswerSeconds * 1000);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.clearTimers();
    this.stopMic();
    this.stopPlayback();

    if (this.ws && this.ws.readyState === WebSocket.OPEN && !this.ending) {
      this.ending = true;
      try {
        this.ws.send(JSON.stringify({ type: 'end' }));
      } catch {
        /* socket already going away */
      }
    }

    this.reportBilled();
    this.closeSocket();

    this.playback?.close().catch(() => undefined);
    this.playback = null;
  }

  // ------------------------------------------------------------------ session

  private async createSession(): Promise<LiveSession> {
    const base = (environment.punicaLiveServer || '').trim().replace(/\/+$/, '');
    if (!base) {
      throw new Error('خدمة الصوت موش مضبوطة. زيد punicaLiveServer في environment.ts.');
    }

    const response = await fetch(`${base}/api/live/session`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'punica-live', origin: location.origin }),
      signal: AbortSignal.timeout(20_000),
    });

    const data = (await response.json().catch(() => null)) as
      | { url?: string; client_secret?: LiveSession['client_secret']; message?: string }
      | null;

    if (!response.ok) {
      throw new Error(data?.message || `الخدمة رفضت المكالمة (${response.status}).`);
    }
    if (!data?.url || !data.client_secret) {
      throw new Error('الخدمة ما رجّعتش معلومات الاتصال. عاود جرّب.');
    }

    return { url: data.url, client_secret: data.client_secret };
  }

  private connect(session: LiveSession, history: VoiceTurn[], system: string): void {
    const secret =
      typeof session.client_secret === 'string'
        ? session.client_secret
        : session.client_secret?.value;
    if (!secret || !session.url) {
      this.fail('التذكرة الصوتية ناقصة. عاود جرّب.');
      return;
    }

    const ws = new WebSocket(session.url, ['punica-live', `ticket.${secret}`]);
    ws.binaryType = 'arraybuffer';
    this.ws = ws;

    ws.onopen = () => {
      this.send({
        type: 'start',
        model: 'punica-live',
        voice: environment.punicaVoice,
        sample_rate: CAPTURE_RATE,
        channels: 1,
        format: 'pcm_s16le',
        audio_format: 'wav',
        playback_ready: true,
        system,
        history,
      });
    };

    ws.onmessage = (event) => {
      if (typeof event.data === 'string') this.onEvent(event.data);
    };

    ws.onerror = () => {
      if (!this.turnDone && !this.disposed) {
        this.fail('ما قدرناش نوصلو لخادم الصوت. عاود جرّب.');
      }
    };

    ws.onclose = () => {
      if (!this.turnDone && !this.disposed && !this.ending) {
        this.fail('تقطعت المكالمة قبل ما تكمّل. عاود جرّب.');
      }
    };
  }

  private onEvent(raw: string): void {
    let event: ServerEvent;
    try {
      event = JSON.parse(raw) as ServerEvent;
    } catch {
      return;
    }

    if (event.type === 'ready') {
      this.sending = true;
      this.setState('listening');
      this.flushPreRoll();
      this.speakTimer = setTimeout(
        () => this.finalize(),
        environment.punicaVoiceMaxSpeakSeconds * 1000,
      );
      return;
    }

    if (event.type === 'partial') {
      this.cb.onHeard(event.text ?? '', false);
      return;
    }

    if (event.type === 'final') {
      this.cb.onHeard(event.text ?? '', true);
      return;
    }

    if (event.type === 'session.billing_started') {
      this.billedAt = Date.now();
      return;
    }

    if (event.type === 'session.ended') {
      this.reportBilled(event.usage?.billable_seconds);
      return;
    }

    if (event.type === 'turn.cancelled') {
      this.fail('تلغى الدور. عاود اضغط على الميكرو.');
      return;
    }

    if (event.type === 'error') {
      this.fail(event.message || 'خادم الصوت رجّع مشكل. عاود جرّب.');
      return;
    }

    if (event.delta) {
      this.answer += event.delta;
      if (this.phase !== 'speaking') this.setState('speaking');
      if (this.answerTimer) {
        clearTimeout(this.answerTimer);
        this.answerTimer = null;
      }
    }

    if (event.audio?.wav_b64) {
      this.playWav(event.audio.wav_b64);
    }

    if (event.done) {
      this.finishWith(this.answer);
    }
  }

  private finishWith(text: string): void {
    if (this.turnDone || this.disposed) return;

    this.turnDone = true;
    this.finalized = true;
    this.sending = false;
    this.clearTimers();
    this.stopMic();

    const reply = text.trim();
    if (reply) {
      this.setState('speaking');
      this.cb.onReply(reply);
    } else {
      this.fail('الجواب رجع خاوي. عاود جرّب.');
      return;
    }

    // Stop the billed clock before the audio has even finished playing here.
    this.endCall();
  }

  private endCall(): void {
    if (this.ending) return;
    this.ending = true;

    if (this.ws?.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify({ type: 'end' }));
      } catch {
        /* ignore */
      }
    }

    this.closeTimer = setTimeout(() => {
      this.reportBilled();
      this.closeSocket();
      if (!this.disposed) this.setState('idle');
    }, 900);
  }

  private reportBilled(seconds?: number): void {
    if (this.reported) return;
    const value =
      typeof seconds === 'number' && seconds > 0
        ? Math.ceil(seconds)
        : this.billedAt
          ? Math.ceil((Date.now() - this.billedAt) / 1000)
          : 0;
    if (value <= 0) return;
    this.reported = true;
    this.cb.onBilled(value);
  }

  private closeSocket(): void {
    const socket = this.ws;
    this.ws = null;
    if (!socket) return;
    socket.onopen = null;
    socket.onmessage = null;
    socket.onerror = null;
    socket.onclose = null;
    try {
      socket.close();
    } catch {
      /* ignore */
    }
  }

  // ------------------------------------------------------------------ capture

  private async openMic(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error('المتصفح ما ينجمش يفتح الميكرو.');
    }

    try {
      this.mic = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch {
      throw new Error('لازم تسمح للميكرو باش نحكيو. عاود جرّب و أعطي الإذن.');
    }

    const ctx = new AudioContext();
    this.capture = ctx;
    await ctx.resume().catch(() => undefined);

    const source = ctx.createMediaStreamSource(this.mic);
    const processor = ctx.createScriptProcessor(2048, 1, 1);
    const mute = ctx.createGain();
    mute.gain.value = 0;

    processor.onaudioprocess = (event) => {
      if (this.sending) {
        this.collect(event.inputBuffer.getChannelData(0), ctx.sampleRate);
      } else if (!this.finalized) {
        this.keepPreRoll(event.inputBuffer.getChannelData(0), ctx.sampleRate);
      }
    };

    source.connect(processor);
    processor.connect(mute);
    mute.connect(ctx.destination);

    this.source = source;
    this.processor = processor;
  }

  /** Downsample to 16 kHz mono PCM16 and send 60 ms frames. */
  private collect(input: Float32Array, rate: number): void {
    const step = rate / CAPTURE_RATE;
    for (let i = 0; i * step < input.length - 1; i++) {
      const pos = i * step;
      const low = Math.floor(pos);
      const frac = pos - low;
      const sample = input[low] * (1 - frac) + input[low + 1] * frac;
      const clamped = Math.max(-1, Math.min(1, sample));
      this.pending.push((clamped < 0 ? clamped * 32768 : clamped * 32767) | 0);
    }

    while (this.pending.length >= FRAME_SAMPLES) {
      const frame = new Int16Array(FRAME_SAMPLES);
      frame.set(this.pending.splice(0, FRAME_SAMPLES));
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(frame.buffer);
    }
  }

  private keepPreRoll(input: Float32Array, rate: number): void {
    const step = rate / CAPTURE_RATE;
    for (let i = 0; i * step < input.length - 1; i++) {
      const sample = input[Math.floor(i * step)];
      const clamped = Math.max(-1, Math.min(1, sample));
      this.preRoll.push((clamped < 0 ? clamped * 32768 : clamped * 32767) | 0);
    }
    const extra = this.preRoll.length - PRE_ROLL_SAMPLES;
    if (extra > 0) this.preRoll.splice(0, extra);
  }

  private flushPreRoll(): void {
    if (!this.preRoll.length) return;
    this.pending.unshift(...this.preRoll.splice(0));
    if (!this.pending.length) return;
    while (this.pending.length >= FRAME_SAMPLES) {
      const frame = new Int16Array(FRAME_SAMPLES);
      frame.set(this.pending.splice(0, FRAME_SAMPLES));
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(frame.buffer);
    }
  }

  private stopMic(): void {
    this.sending = false;
    if (this.processor) {
      this.processor.onaudioprocess = null;
      this.processor.disconnect();
      this.processor = null;
    }
    this.source?.disconnect();
    this.source = null;
    this.mic?.getTracks().forEach((track) => track.stop());
    this.mic = null;
    this.capture?.close().catch(() => undefined);
    this.capture = null;
    this.pending = [];
    this.preRoll = [];
  }

  // ------------------------------------------------------------------ playback

  private ensurePlayback(): void {
    if (!this.playback) {
      this.playback = new AudioContext();
    }
    void this.playback.resume().catch(() => undefined);
    this.nextAudioAt = 0;
  }

  private playWav(base64: string): void {
    const ctx = this.playback;
    if (!ctx || this.disposed) return;

    if (this.phase !== 'speaking') this.setState('speaking');

    this.audioChain = this.audioChain.then(async () => {
      if (this.disposed || !this.playback) return;
      try {
        const binary = atob(base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

        const buffer = await this.playback.decodeAudioData(bytes.buffer);
        if (this.disposed || !this.playback) return;

        const node = this.playback.createBufferSource();
        node.buffer = buffer;
        node.connect(this.playback.destination);
        const at = Math.max(this.playback.currentTime + 0.04, this.nextAudioAt);
        node.start(at);
        this.nextAudioAt = at + buffer.duration;
        this.playing.add(node);
        node.onended = () => this.playing.delete(node);
      } catch {
        /* a single bad segment must not kill the call */
      }
    });
  }

  private stopPlayback(): void {
    for (const node of this.playing) {
      try {
        node.stop();
      } catch {
        /* already ended */
      }
    }
    this.playing.clear();
    this.nextAudioAt = 0;
  }

  // ------------------------------------------------------------------ helpers

  private send(payload: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(payload));
    }
  }

  private setState(state: VoicePhase): void {
    if (this.phase === state) return;
    this.phase = state;
    this.cb.onState(state);
  }

  private fail(message: string): void {
    if (this.disposed) return;
    this.clearTimers();
    this.stopMic();
    this.stopPlayback();
    this.reportBilled();
    this.closeSocket();
    this.setState('error');
    this.cb.onError(message);
  }

  private resetTurn(): void {
    this.clearTimers();
    this.stopPlayback();
    this.stopMic();
    this.ws?.close();
    this.ws = null;
    this.answer = '';
    this.pending = [];
    this.preRoll = [];
    this.sending = false;
    this.finalized = false;
    this.turnDone = false;
    this.ending = false;
    this.reported = false;
    this.billedAt = 0;
    this.nextAudioAt = 0;
  }

  private clearSpeakTimer(): void {
    if (this.speakTimer) {
      clearTimeout(this.speakTimer);
      this.speakTimer = null;
    }
  }

  private clearTimers(): void {
    this.clearSpeakTimer();
    if (this.answerTimer) {
      clearTimeout(this.answerTimer);
      this.answerTimer = null;
    }
    if (this.closeTimer) {
      clearTimeout(this.closeTimer);
      this.closeTimer = null;
    }
  }
}

function messageOf(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'صار مشكل في المكالمة. عاود جرّب.';
}
