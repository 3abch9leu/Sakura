/**
 * Runtime configuration.
 *
 * Create a Gemini API key at https://aistudio.google.com/apikey and paste it
 * into `geminiApiKey` below. Never commit a real key to a public repository:
 * for a public deployment, proxy the request through a small server instead.
 */
export const environment = {
  production: false,
  geminiApiKey: 'AIzaSyBgv9KMy_jINSjtMjQtfB5OrAAvcr_H3V4',
  geminiModel: 'gemini-3.8-flash',
  /** Tried in order when the main model is congested or slow to start. */
  geminiFallbackModels: ['gemini-3.5-flash', 'gemini-3.1-flash-lite'],

  /**
   * Punica Live voice calls.
   *
   * `punicaLiveServer` is the local relay in server/punica-live.mjs. It keeps
   * provider keys server-side and returns one-use tickets for live voice.
   * Run it with: npm run voice:server
   */
  punicaLiveServer: 'http://127.0.0.1:8788',
  /** A ready Tunisian voice id (see GET /api/v1/voices). */
  punicaVoice: 'nour_tn',
  /** Quota guards. Punica bills $0.167 per connected minute. */
  punicaVoiceTurnsPerDay: 6,
  punicaVoiceDailySeconds: 180,
  punicaVoiceMaxSpeakSeconds: 20,
  punicaVoiceMaxAnswerSeconds: 30,
};
