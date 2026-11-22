/**
 * ROOTCODE Water Quality Analyzer (Universal JavaScript Module)
 * Team Sakura - Kizuna 2026 Hackathon
 * Works in Node.js, Web Browsers, ES Modules, and CommonJS
 */

(function (root, factory) {
  if (typeof define === 'function' && define.amd) {
    define([], factory);
  } else if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.WaterAnalyzer = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {

  const DEFAULT_THRESHOLDS = {
    ph: { cleanLo: 6.5, cleanHi: 8.4, warnLo: 6.0, warnHi: 9.0, badLo: 0, badHi: 14, ref: 'FAO 29', absMin: 0, absMax: 14 },
    turbidity_ntu: { cleanLo: 0, cleanHi: 5.0, warnLo: 5.0, warnHi: 25.0, badLo: 25.0, badHi: 999999, ref: 'WHO', absMin: 0, absMax: null },
    ec_us_cm: { cleanLo: 0, cleanHi: 700, warnLo: 700, warnHi: 3000, badLo: 3000, badHi: 999999, ref: 'FAO 29', absMin: 0, absMax: null },
    temp_c: { cleanLo: 10.0, cleanHi: 30.0, warnLo: 5.0, warnHi: 35.0, badLo: 0, badHi: 45.0, ref: 'FAO', absMin: 0, absMax: 60 },
    level_pct: { cleanLo: 20.0, cleanHi: 100.0, warnLo: 10.0, warnHi: 20.0, badLo: 0, badHi: 10.0, ref: 'Tank Supply', absMin: 0, absMax: 100 }
  };

  const PRELOADED_WATER_DATA = {
    clean: { source: 'clean', dataType: 'MEASURED', ph: 7.20, turbidity_ntu: 1.8, ec_us_cm: 420, temp_c: 21.5, level_pct: 84, orp_mv: 345 },
    rain: { source: 'rain', dataType: 'MEASURED', ph: 6.40, turbidity_ntu: 7.8, ec_us_cm: 48, temp_c: 18.2, level_pct: 65, orp_mv: 295 },
    ac: { source: 'ac', dataType: 'MEASURED', ph: 6.85, turbidity_ntu: 0.9, ec_us_cm: 18, temp_c: 16.0, level_pct: 45, orp_mv: 320 },
    grey: { source: 'grey', dataType: 'MEASURED', ph: 7.60, turbidity_ntu: 28.5, ec_us_cm: 1150, temp_c: 22.8, level_pct: 28, orp_mv: 180 }
  };

  function compensateEC(ec, temp) {
    if (temp === null || temp === undefined || isNaN(temp)) {
      return { ec: Number(ec), compensated: false };
    }
    return { ec: Number(ec) / (1 + 0.02 * (Number(temp) - 25)), compensated: true };
  }

  function judgeParam(paramKey, value, tempForEC, customThresholds) {
    const thresholds = customThresholds || DEFAULT_THRESHOLDS;
    if (value === null || value === undefined || value === '' || isNaN(Number(value))) {
      return { status: 'missing' };
    }
    const v = Number(value);
    const th = thresholds[paramKey];
    if (!th) return { status: 'ok', raw: v };

    if (paramKey === 'ph' && (v < 0 || v > 14)) {
      return { status: 'invalid', reason: `pH ${v} outside scale (0–14)`, raw: v };
    }
    if ((paramKey === 'turbidity_ntu' || paramKey === 'ec_us_cm') && v < 0) {
      return { status: 'invalid', reason: `${paramKey} negative`, raw: v };
    }
    if (paramKey === 'level_pct' && (v < 0 || v > 100)) {
      return { status: 'invalid', reason: `Tank level ${v}% outside 0–100%`, raw: v };
    }

    let judgedVal = v;
    let ecNote = '';
    if (paramKey === 'ec_us_cm' && tempForEC !== null && tempForEC !== undefined && !isNaN(tempForEC)) {
      const comp = compensateEC(v, tempForEC);
      judgedVal = comp.ec;
      ecNote = ' (comp. @25°C)';
    } else if (paramKey === 'ec_us_cm') {
      ecNote = ' (not temp-compensated)';
    }

    if (paramKey === 'ph') {
      if (judgedVal >= th.cleanLo && judgedVal <= th.cleanHi) return { status: 'ok', note: '', raw: v };
      if (judgedVal >= th.warnLo && judgedVal <= th.warnHi) return { status: 'warn', note: '', raw: v };
      return { status: 'bad', note: '', raw: v };
    }
    if (paramKey === 'turbidity_ntu' || paramKey === 'ec_us_cm') {
      if (judgedVal <= th.cleanHi) return { status: 'ok', note: ecNote, raw: v };
      if (judgedVal <= th.warnHi) return { status: 'warn', note: ecNote, raw: v };
      return { status: 'bad', note: ecNote, raw: v };
    }
    if (paramKey === 'temp_c') {
      if (judgedVal >= th.cleanLo && judgedVal <= th.cleanHi) return { status: 'ok', note: '', raw: v };
      if (judgedVal >= th.warnLo && judgedVal <= th.warnHi) return { status: 'warn', note: '', raw: v };
      return { status: 'bad', note: '', raw: v };
    }
    if (paramKey === 'level_pct') {
      if (judgedVal >= th.cleanLo) return { status: 'ok', note: '', raw: v };
      if (judgedVal >= th.warnLo) return { status: 'warn', note: '', raw: v };
      return { status: 'bad', note: '', raw: v };
    }
    return { status: 'ok', note: '', raw: v };
  }

  function computeVerdict(reading, hasMicroPassing, hasMicroFailing, customThresholds) {
    const isSimulated = reading && reading.dataType === 'SIMULATED';

    if (reading.source === 'grey') {
      return {
        verdict: 'bad',
        emoji: '❌',
        label: 'NOT CLEAN',
        reason: 'Greywater: not permitted for edible crops (FAO guidelines)',
        confidence: 'MEDIUM',
        paramResults: {},
        missingParams: [],
        hasInvalid: false,
        action: 'DO NOT USE for edible crops',
        isGreywater: true
      };
    }

    const judgedKeys = ['ph', 'turbidity_ntu', 'ec_us_cm', 'temp_c'];
    const paramResults = {};
    const missing = [];
    let hasInvalid = false;
    let hasBad = false;
    let hasWarn = false;

    for (const key of judgedKeys) {
      const raw = reading[key];
      const tempVal = key === 'ec_us_cm' ? reading.temp_c : null;
      const res = judgeParam(key, raw, tempVal, customThresholds);
      paramResults[key] = res;
      if (res.status === 'missing') missing.push(key);
      if (res.status === 'invalid') { hasInvalid = true; hasBad = true; }
      if (res.status === 'bad') hasBad = true;
      if (res.status === 'warn') hasWarn = true;
    }

    if (reading.level_pct !== undefined && reading.level_pct !== null) {
      paramResults['level_pct'] = judgeParam('level_pct', reading.level_pct, null, customThresholds);
    }

    if (missing.length > 0) {
      return {
        verdict: 'unknown',
        emoji: '❔',
        label: 'CANNOT DECIDE',
        reason: `Missing required parameters: ${missing.join(', ')}`,
        confidence: isSimulated ? 'LOW' : 'MEDIUM',
        paramResults,
        missingParams: missing,
        hasInvalid,
        action: 'Supply missing sensor data before irrigation'
      };
    }

    if (isSimulated) {
      return {
        verdict: 'unknown',
        emoji: '❔',
        label: 'CANNOT DECIDE',
        reason: 'Data is SIMULATED — not a physical measurement',
        confidence: 'LOW',
        paramResults,
        missingParams: [],
        hasInvalid,
        action: 'Simulated data cannot verify cleanliness'
      };
    }

    if (hasMicroFailing) {
      return {
        verdict: 'bad',
        emoji: '❌',
        label: 'NOT CLEAN',
        reason: 'Microbiology FAIL: pathogens/coliforms detected',
        confidence: 'HIGH',
        paramResults,
        missingParams: [],
        hasInvalid,
        action: 'DO NOT USE for edible crops'
      };
    }

    if (hasBad || hasInvalid) {
      let reason = 'One or more parameters exceed hazardous limit';
      if (paramResults.turbidity_ntu && paramResults.turbidity_ntu.status === 'bad') reason = `Turbidity ${reading.turbidity_ntu} NTU exceeds limit`;
      else if (paramResults.ph && paramResults.ph.status === 'bad') reason = `pH ${reading.ph} outside permissible range`;
      else if (paramResults.ec_us_cm && paramResults.ec_us_cm.status === 'bad') reason = `EC ${reading.ec_us_cm} µS/cm exceeds salinity threshold`;
      else if (paramResults.temp_c && paramResults.temp_c.status === 'bad') reason = `Temperature ${reading.temp_c}°C outside safe biological range`;

      return {
        verdict: 'bad',
        emoji: '❌',
        label: 'NOT CLEAN',
        reason,
        confidence: hasInvalid ? 'LOW' : (hasMicroPassing ? 'HIGH' : 'MEDIUM'),
        paramResults,
        missingParams: [],
        hasInvalid,
        action: 'DO NOT USE for edible crops'
      };
    }

    if (hasWarn) {
      let reason = 'Parameter in warning range';
      if (paramResults.turbidity_ntu && paramResults.turbidity_ntu.status === 'warn') reason = `Turbidity ${reading.turbidity_ntu} NTU is in warning band (5–25 NTU)`;
      else if (paramResults.ph && paramResults.ph.status === 'warn') reason = `pH ${reading.ph} is in warning band`;
      else if (paramResults.ec_us_cm && paramResults.ec_us_cm.status === 'warn') reason = `EC ${reading.ec_us_cm} µS/cm is in warning band`;

      return {
        verdict: 'warn',
        emoji: '⚠️',
        label: 'ACCEPTABLE WITH CAUTION',
        reason,
        confidence: hasMicroPassing ? 'HIGH' : 'MEDIUM',
        paramResults,
        missingParams: [],
        hasInvalid: false,
        action: 'Use with caution for plant irrigation'
      };
    }

    return {
      verdict: 'ok',
      emoji: '✅',
      label: 'CLEAN',
      reason: 'All judged parameters within clean range',
      confidence: hasMicroPassing ? 'HIGH' : 'MEDIUM',
      paramResults,
      missingParams: [],
      hasInvalid: false,
      action: 'SAFE to use for plant irrigation'
    };
  }

  function getOverallVerdict(verdicts) {
    if (!verdicts || verdicts.length === 0) {
      return { overallVerdict: 'unknown', actionSentence: 'CANNOT DETERMINE suitability', worstReason: 'No data' };
    }
    const priority = { bad: 0, warn: 1, ok: 2, unknown: 3 };
    const sorted = [...verdicts].sort((a, b) => priority[a.verdict] - priority[b.verdict]);
    const worst = sorted[0];
    let action = 'CANNOT DETERMINE suitability';
    if (worst.verdict === 'ok') action = 'USE this water for plant irrigation';
    else if (worst.verdict === 'warn') action = 'Use WITH CAUTION for plant irrigation';
    else if (worst.verdict === 'bad') action = 'DO NOT USE this water for plant irrigation';
    return { overallVerdict: worst.verdict, actionSentence: action, worstReason: worst.reason };
  }

  return {
    DEFAULT_THRESHOLDS,
    PRELOADED_WATER_DATA,
    compensateEC,
    judgeParam,
    computeVerdict,
    getOverallVerdict
  };
}));
