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

/** One continuous Gemini Live session for natural, Japanese audio conversation. */
export class GeminiLiveCall {
  private ws: WebSocket | null = null;
  private mic: MediaStream | null = null;
  private capture: AudioContext | null = null;
  private processor: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private playback: AudioContext | null = null;
  private nextAudioAt = 0;
  private pending: number[] = [];
  private outputText = '';
  private startedAt = 0;
  private disposed = false;
  private phase: VoicePhase = 'idle';
  private connectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly cb: VoiceCallbacks) {}

  async start(system: string): Promise<void> {
    if (this.disposed) return;
    this.setState('connecting');
    try {
      this.playback = new AudioContext({ sampleRate: 24_000 });
      await this.playback.resume();
      await this.openMic();

      const base = (environment.punicaLiveServer || '').trim().replace(/\/+$/, '');
      if (!base) throw new Error('Voice relay is not configured.');
      const response = await fetch(`${base}/api/gemini/live-token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: AbortSignal.timeout(20_000),
      });
      const data = await response.json().catch(() => null) as { token?: string; message?: string } | null;
      if (!response.ok || !data?.token) {
        throw new Error(data?.message || `Gemini voice setup failed (${response.status}).`);
      }

      const ws = new WebSocket(
        `wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContentConstrained?access_token=${encodeURIComponent(data.token)}`,
      );
      ws.binaryType = 'arraybuffer';
      this.ws = ws;
      this.connectTimer = setTimeout(() => {
        const message = ws.readyState === WebSocket.OPEN
          ? 'Gemini connected but did not acknowledge voice setup. Check model availability and retry.'
          : 'Could not open the Gemini voice connection. Check that WebSockets are allowed on this network and retry.';
        this.fail(message);
      }, 45_000);
      ws.onopen = () => {
        ws.send(JSON.stringify({
          setup: {
            model: 'models/gemini-3.8-live',
            generationConfig: {
              responseModalities: ['AUDIO'],
              speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: 'Kore' } } },
            },
            inputAudioTranscription: {},
            outputAudioTranscription: {},
            systemInstruction: { parts: [{ text: system }] },
          },
        }));
      };
      ws.onmessage = (event) => { void this.readMessage(event.data); };
      ws.onerror = () => this.fail('Could not connect to Gemini voice. Check the network and API key.');
      ws.onclose = (event) => {
        if (!this.disposed && this.phase !== 'error') {
          const details = event.reason ? `: ${event.reason}` : '';
          this.fail(`Gemini ended the voice connection (code ${event.code})${details}`);
        }
      };
    } catch (error) {
      this.fail(messageOf(error));
    }
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.connectTimer) clearTimeout(this.connectTimer);
    this.connectTimer = null;
    this.stopMic();
    const ws = this.ws;
    this.ws = null;
    if (ws) {
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      try { ws.close(); } catch { /* already closed */ }
    }
    this.playback?.close().catch(() => undefined);
    this.playback = null;
    if (this.startedAt) this.cb.onBilled(Math.ceil((Date.now() - this.startedAt) / 1000));
    this.setState('idle');
  }

  private async openMic(): Promise<void> {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error('This browser cannot access a microphone.');
    try {
      this.mic = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
    } catch {
      throw new Error('Allow microphone access to start the Japanese conversation.');
    }
    const ctx = new AudioContext({ sampleRate: 16_000 });
    this.capture = ctx;
    await ctx.resume();
    const source = ctx.createMediaStreamSource(this.mic);
    const processor = ctx.createScriptProcessor(2048, 1, 1);
    const mute = ctx.createGain();
    mute.gain.value = 0;
    processor.onaudioprocess = (event) => {
      const input = event.inputBuffer.getChannelData(0);
      const ratio = ctx.sampleRate / 16_000;
      for (let i = 0; i * ratio < input.length; i++) {
        const sample = Math.max(-1, Math.min(1, input[Math.floor(i * ratio)]));
        this.pending.push((sample < 0 ? sample * 32768 : sample * 32767) | 0);
      }
      while (this.pending.length >= 1600) {
        const samples = this.pending.splice(0, 1600);
        this.sendAudio(samples);
      }
    };
    source.connect(processor);
    processor.connect(mute);
    mute.connect(ctx.destination);
    this.source = source;
    this.processor = processor;
  }

  private sendAudio(samples: number[]): void {
    if (this.ws?.readyState !== WebSocket.OPEN || this.phase !== 'listening') return;
    const pcm = new Int16Array(samples);
    const bytes = new Uint8Array(pcm.buffer);
    let binary = '';
    for (let i = 0; i < bytes.length; i += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(i, Math.min(i + 0x8000, bytes.length)));
    }
    this.ws.send(JSON.stringify({
      realtimeInput: { audio: { mimeType: 'audio/pcm;rate=16000', data: btoa(binary) } },
    }));
  }

  private async readMessage(data: string | Blob | ArrayBuffer | ArrayBufferView): Promise<void> {
    try {
      if (typeof data === 'string') {
        this.onMessage(data);
      } else if (data instanceof Blob) {
        this.onMessage(await data.text());
      } else if (data instanceof ArrayBuffer) {
        this.onMessage(new TextDecoder().decode(data));
      } else {
        this.onMessage(new TextDecoder().decode(data));
      }
    } catch {
      /* Ignore a non-JSON control frame; the setup timeout reports missing acknowledgement. */
    }
  }

  private onMessage(raw: string): void {
    let message: any;
    try { message = JSON.parse(raw); } catch { return; }
    if (message.setupComplete) {
      if (this.connectTimer) clearTimeout(this.connectTimer);
      this.connectTimer = null;
      this.startedAt = Date.now();
      this.setState('listening');
      return;
    }
    if (message.error) {
      this.fail(message.error.message || 'Gemini returned a voice error.');
      return;
    }

    const content = message.serverContent;
    const input = content?.inputTranscription?.text;
    if (input) this.cb.onHeard(input, true);
    const output = content?.outputTranscription?.text;
    if (output) this.outputText += output;

    for (const part of content?.modelTurn?.parts ?? []) {
      const encoded = part.inlineData?.data;
      if (encoded) {
        this.setState('speaking');
        this.playPcm(encoded);
      }
      if (part.text && !part.thought) this.outputText += part.text;
    }

    if (content?.turnComplete) {
      const answer = this.outputText.trim();
      this.outputText = '';
      if (answer) this.cb.onReply(answer);
      this.setState('listening');
    }
  }

  private playPcm(encoded: string): void {
    const ctx = this.playback;
    if (!ctx) return;
    const binary = atob(encoded);
    const count = Math.floor(binary.length / 2);
    const pcm = new Int16Array(count);
    for (let i = 0; i < count; i++) {
      const value = binary.charCodeAt(i * 2) | (binary.charCodeAt(i * 2 + 1) << 8);
      pcm[i] = value > 32767 ? value - 65536 : value;
    }
    const buffer = ctx.createBuffer(1, count, 24_000);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < count; i++) channel[i] = pcm[i] / 32768;
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const when = Math.max(ctx.currentTime + 0.03, this.nextAudioAt);
    source.start(when);
    this.nextAudioAt = when + buffer.duration;
  }

  private stopMic(): void {
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
  }

  private setState(state: VoicePhase): void {
    if (this.phase === state) return;
    this.phase = state;
    this.cb.onState(state);
  }

  private fail(message: string): void {
    if (this.disposed) return;
    this.cb.onError(message);
    this.setState('error');
    this.dispose();
    this.setState('error');
  }
}

function messageOf(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'صار مشكل في المكالمة. عاود جرّب.';
}
