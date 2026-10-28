(function (root) {
  'use strict';
  const finite = Number.isFinite;
  const labels = {
    no_face: '얼굴이 보이지 않습니다.', multiple_faces: '얼굴 후보가 여러 개 잡혔습니다. 주변 무늬를 피하고 얼굴 하나만 잡히게 해 주세요.',
    motion: '움직임을 줄여 주세요.', illumination: '얼굴의 밝기를 일정하게 유지해 주세요.',
    diffuse_spectrum: '맥박 주기가 아직 뚜렷하지 않습니다.', flat_or_low_signal: '신호가 약합니다.',
    invalid_roi: '얼굴을 화면 중앙에 맞춰 주세요.', long_gap: '측정이 끊겨 다시 확인하고 있습니다.', insufficient_valid_samples: '측정 자료를 더 모으고 있습니다.',
    sampling_rate_too_low: '영상 전달 속도가 느립니다.'
  };
  function dimensions(w, h) {
    if (!(w > 0 && h > 0)) return null;
    const scale = Math.min(1, 640 / w, 480 / h);
    return [Math.max(1, Math.floor(w * scale)), Math.max(1, Math.floor(h * scale))];
  }
  function measurementInfo(state) {
    const empty = { progressLabel: '측정 대기', analysisLabel: '—', signalLabel: '—' };
    if (!state.active) return empty;
    const analysis = state.data?.analysis;
    const age = analysis ? state.elapsed - analysis.timestamp_s : Infinity;
    const freshFrames = finite(state.replyAge) && state.replyAge >= 0 && state.replyAge <= 1.5;
    const freshAnalysis = freshFrames && analysis && finite(analysis.timestamp_s) && age >= 0 && age <= 1.5;
    const progressLabel = state.data && !freshFrames ? '영상 갱신 대기' : state.progress < 20
      ? `첫 분석 준비 ${state.progress.toFixed(1)} / 20초`
      : freshAnalysis ? '최근 20초를 매초 분석 중' : '20초 자료 준비됨 · 분석 갱신 대기';
    const analysisLabel = analysis && finite(analysis.timestamp_s)
      ? `경과 ${analysis.timestamp_s.toFixed(1)}초 구간 · ${freshAnalysis ? `${age.toFixed(1)}초 전 갱신` : '갱신 대기'}` : '—';
    const concentration = analysis?.peak_concentration;
    const signalLabel = freshAnalysis && finite(concentration) && concentration >= 0 && concentration <= 1
      ? `${(concentration * 100).toFixed(1)}% / 표시 기준 35%` : '—';
    return { progressLabel, analysisLabel, signalLabel };
  }
  class ReceivedFrames {
    constructor(startedAt) { this.startedAt = startedAt; this.times = []; this.lastCapture = -Infinity; }
    record(captureAt, receivedAt) {
      if (!finite(captureAt) || !finite(receivedAt) || captureAt <= this.lastCapture ||
          receivedAt < this.startedAt || receivedAt < (this.times.at(-1) ?? this.startedAt)) return;
      this.lastCapture = captureAt;
      this.times.push(receivedAt);
      this.prune(receivedAt);
    }
    prune(now) { this.times = this.times.filter(t => t > now - 3000).slice(-200); }
    rate(now) {
      this.prune(now);
      const duration = Math.min(3000, Math.max(0, now - this.startedAt));
      return duration > 0 ? this.times.length * 1000 / duration : 0;
    }
  }
  class Scene {
    constructor() { this.reset(); }
    reset() {
      this.segment = null; this.seenIds = new Set(); this.seenTimes = new Set();
      this.latest = null; this.confirmed = null; this.streak = 0; this.replyAt = null;
      this.elapsed = 0; this.captureAt = 0; this.captures = []; this.data = null; this.blocked = true;
    }
    receive(data, captureAt, now) {
      if (this.segment !== data.segment_id) { this.reset(); this.segment = data.segment_id; }
      if (this.replyAt !== null && now - this.replyAt > 1500) this.streak = 0;
      this.captures.push(captureAt); this.captures = this.captures.filter(t => captureAt - t <= 2000);
      this.data = data; this.replyAt = now; this.captureAt = captureAt; this.elapsed = data.elapsed_s;
      this.blocked = data.face_count !== 1 || !Array.isArray(data.frame_reasons) || data.frame_reasons.length > 0;
      if (this.blocked) this.streak = 0;
      const a = data.analysis;
      if (!a || !finite(a.timestamp_s) || typeof a.event_id !== 'string' ||
          this.seenIds.has(a.event_id) || this.seenTimes.has(a.timestamp_s)) return;
      this.seenIds.add(a.event_id); this.seenTimes.add(a.timestamp_s);
      if (this.latest && a.timestamp_s <= this.latest.timestamp_s) return;
      if (this.latest && a.timestamp_s - this.latest.timestamp_s > 1.5) this.streak = 0;
      const age = data.elapsed_s + (now - captureAt) / 1000 - a.timestamp_s;
      const valid = !this.blocked && finite(a.hr_bpm) && a.hr_bpm > 0 &&
        Array.isArray(a.reasons) && a.reasons.length === 0 && age >= -0.1 && age <= 1.5;
      this.streak = valid ? this.streak + 1 : 0;
      this.latest = a;
      if (this.streak >= 2) this.confirmed = { hr: a.hr_bpm, at: a.timestamp_s };
    }
    view(now) {
      const elapsed = this.elapsed + (this.replyAt === null ? 0 : (now - this.captureAt) / 1000);
      const age = this.confirmed ? elapsed - this.confirmed.at : Infinity;
      const fresh = this.replyAt !== null && now - this.replyAt <= 1500 && this.latest && elapsed - this.latest.timestamp_s <= 1.5;
      if (!fresh) this.streak = 0;
      const current = fresh && !this.blocked && this.streak >= 2 && age >= 0 && age <= 1.5;
      const held = !current && this.confirmed && age >= 0 && age <= 3;
      return { status: current ? 'current' : held ? 'held' : 'waiting',
        hr: current || held ? this.confirmed.hr : null, age, elapsed,
        replyAge: this.replyAt === null ? null : (now - this.replyAt) / 1000,
        fps: this.captures.length > 1 ? (this.captures.length - 1) * 1000 / (this.captures.at(-1) - this.captures[0]) : null,
        progress: Math.min(20, Math.max(0, (this.data?.segment_elapsed_s || 0))), data: this.data };
    }
  }
  const phaseNames = ['휴식', '암산', '회복'];
  const pilotEpsilon = 1e-8; // Floating-point tolerance for inclusive bounds only.
  function median(values) {
    const sorted = [...values].sort((a, b) => a - b), n = sorted.length;
    return n ? (sorted[Math.floor((n - 1) / 2)] + sorted[Math.floor(n / 2)]) / 2 : null;
  }
  function csvCell(value) {
    if (typeof value === 'number' && finite(value)) return String(value);
    let s = value == null ? '' : String(value);
    if (/^[\s]*[=+\-@]/.test(s) || /^[\t\r\n]/.test(s)) s = "'" + s;
    return '"' + s.replace(/"/g, '""') + '"';
  }
  class StressPilot {
    constructor(code, note) {
      this.runId = root.crypto.randomUUID(); this.startedUtc = new Date().toISOString();
      this.runtimeId = null; this.terminalElapsed = null; this.reportTimes = [null, null, null];
      this.code = String(code || '').slice(0, 80); this.note = String(note || '').slice(0, 1000);
      this.status = 'preparing'; this.reason = null; this.origin = null; this.lastTick = null;
      this.phases = phaseNames.map(name => ({ name, start: null, end: null, complete: false }));
      this.events = []; this.seen = new Set(); this.endpoints = new Set(); this.latest = -Infinity;
      this.reports = [null, null, null]; this.phase = 0;
    }
    get acquiring() { return this.status === 'preparing' || this.status === 'running'; }
    capture(now) {
      if (this.status === 'preparing') {
        this.origin = now; this.lastTick = now; this.phases[0].start = 0; this.status = 'running';
      }
    }
    advance(now) {
      if (this.status !== 'running') return;
      const elapsed = (now - this.origin) / 1000;
      if (now < this.lastTick || now - this.lastTick > 1500) { this.abort('timer_gap', now); return; }
      this.lastTick = now;
      if (elapsed >= (this.phase + 1) * 60) {
        // Never synthesize missed cues, or backdate an actual transition.
        if (elapsed >= (this.phase + 2) * 60) { this.abort('missed_cue', now); return; }
        this.phases[this.phase].end = elapsed; this.phases[this.phase].complete = true;
        if (++this.phase === 3) { this.status = 'complete'; this.terminalElapsed = elapsed; }
        else this.phases[this.phase].start = elapsed;
      }
    }
    abort(reason, now) {
      if (!this.acquiring) return;
      if (this.status === 'running') this.phases[this.phase].end = Math.max(0, (now - this.origin) / 1000);
      this.terminalElapsed = this.origin === null ? null : Math.max(0, (now - this.origin) / 1000);
      this.status = 'aborted'; this.reason = reason;
    }
    receive(data, captureAt, receivedAt) {
      if (this.status !== 'running') return;
      const a = data.analysis;
      if (!a || !finite(a.timestamp_s) || typeof a.event_id !== 'string') return;
      const key = `${data.segment_id}/${a.event_id}`, end = a.timestamp_s;
      if (this.seen.has(key) || this.endpoints.has(end)) return;
      this.seen.add(key); this.endpoints.add(end);
      const exclusions = [];
      if (end <= this.latest) exclusions.push('nonincreasing_endpoint');
      this.latest = Math.max(end, this.latest);
      const age = data.elapsed_s + (receivedAt - captureAt) / 1000 - end;
      if (!finite(age) || age < -0.1 - pilotEpsilon || age > 1.5 + pilotEpsilon) exclusions.push('stale_analysis');
      if (!finite(a.hr_bpm) || a.hr_bpm <= 0) exclusions.push('invalid_hr');
      if (!Array.isArray(a.reasons) || a.reasons.length) exclusions.push('analysis_quality');
      if (data.face_count !== 1 || !Array.isArray(data.frame_reasons) || data.frame_reasons.length) exclusions.push('frame_quality');
      // Explicit allowlist: never copy a server response, credentials or image data.
      this.events.push({ ordinal: this.events.length + 1,
        segment_id: Number.isInteger(data.segment_id) ? data.segment_id : null,
        event_id: /^\d+:\d+$/.test(a.event_id) ? a.event_id : null, window_start_s: end - 20, window_end_s: end,
        received_elapsed_s: (receivedAt - this.origin) / 1000, age_s: finite(age) ? age : null,
        hr_bpm: finite(a.hr_bpm) ? a.hr_bpm : null,
        peak_concentration: finite(a.peak_concentration) ? a.peak_concentration : null,
        valid_fraction: finite(a.valid_fraction) ? a.valid_fraction : null,
        sampling_rate_hz: finite(a.sampling_rate_hz) ? a.sampling_rate_hz : null,
        max_gap_seconds: finite(a.max_gap_seconds) ? a.max_gap_seconds : null,
        analysis_reasons: Array.isArray(a.reasons) ? a.reasons.filter(r => typeof r === 'string') : null,
        frame_reasons: Array.isArray(data.frame_reasons) ? data.frame_reasons.filter(r => typeof r === 'string') : null,
        exclusions });
    }
    summary() {
      return this.phases.map((p, i) => {
        const contained = this.events.filter(e => p.start !== null && p.end !== null &&
          e.window_start_s >= p.start - pilotEpsilon && e.window_end_s < p.end && e.window_end_s < 180);
        const usable = contained.filter(e => !e.exclusions.length);
        const gate = p.complete && usable.length >= 30;
        return { phase: p.name, actual_start_s: p.start, actual_end_s: p.end, complete: p.complete,
          contained_count: contained.length, usable_count: usable.length,
          quality_excluded_count: contained.length - usable.length, engineering_gate: gate,
          median_hr_bpm: gate ? median(usable.map(e => e.hr_bpm)) : null,
          self_report: this.reports[i], self_report_submitted_utc: this.reportTimes[i] };
      });
    }
    setReport(index, value) {
      if (this.acquiring || !Number.isInteger(index) || index < 0 || index > 2) return;
      if (this.phases[index].start === null) return;
      const n = value === '' || value == null ? null : Number(value);
      this.reports[index] = n === null || (Number.isInteger(n) && n >= 0 && n <= 10) ? n : null;
      this.reportTimes[index] = this.reports[index] === null ? null : new Date().toISOString();
    }
    exportData() {
      const phases = this.summary(), base = phases[0].median_hr_bpm;
      return { schema: 'rppg-stress-pilot-1', run_id: this.runId, started_utc: this.startedUtc,
        runtime_id: this.runtimeId, terminal_elapsed_s: this.terminalElapsed, status: this.status, abort_reason: this.reason,
        anonymous_code: this.code, condition_note: this.note,
        protocol: { duration_s: 180, window_s: 20, minimum_unique_usable_events: 30,
          clock: 'first capture = 0; actual cues; strict upper containment',
          interpretation: 'Engineering completeness gate only. Overlapping analyses are not independent. No stress or HRV inference. Notes and self-reports are not labels.' },
        phases, task_minus_rest_bpm: base !== null && phases[1].engineering_gate ? phases[1].median_hr_bpm - base : null,
        recovery_minus_rest_bpm: base !== null && phases[2].engineering_gate ? phases[2].median_hr_bpm - base : null,
        unassigned_count: this.events.length - phases.reduce((n, p) => n + p.contained_count, 0), events: this.events.map(e => {
          const i = this.phases.findIndex(p => p.start !== null && p.end !== null && e.window_start_s >= p.start - pilotEpsilon && e.window_end_s < p.end && e.window_end_s < 180);
          return { ...e, phase: i < 0 ? null : phaseNames[i], exclusions: [...e.exclusions,
            ...(i < 0 ? ['cross_phase_or_outside'] : !this.phases[i].complete ? ['incomplete_phase'] : [])] };
        }) };
    }
    csv() {
      const d = this.exportData();
      const rows = [['run_id','started_utc','runtime_id','anonymous_code','condition_note','status','phase','complete','actual_start_s','actual_end_s','contained_count','usable_count','quality_excluded_count','engineering_gate','median_hr_bpm','self_report','delta_vs_rest_bpm']];
      d.phases.forEach((p, i) => rows.push([this.runId,this.startedUtc,this.runtimeId,this.code,this.note,this.status,p.phase,p.complete,p.actual_start_s,p.actual_end_s,p.contained_count,p.usable_count,p.quality_excluded_count,p.engineering_gate,p.median_hr_bpm,p.self_report,i === 1 ? d.task_minus_rest_bpm : i === 2 ? d.recovery_minus_rest_bpm : null]));
      return rows.map(row => row.map(csvCell).join(',')).join('\r\n');
    }
  }
  class Live {
    constructor(env) {
      this.e = env; this.scene = new Scene(); this.generation = 0; this.active = false;
      this.pending = new Set(); this.session = null; this.stream = null; this.callback = null;
      this.watch = null; this.busy = false; this.message = '시작을 누르면 카메라 사용 권한을 요청합니다.';
      this.emit();
    }
    emit() {
      const now = this.e.now();
      const receivedFps = this.received ? this.received.rate(now) : null;
      const slowTransfer = this.active && this.received && now - this.received.startedAt >= 3000 && receivedFps < 10;
      this.e.render({ ...this.scene.view(now), active: this.active, message: this.message,
        pilot: this.pilot || null,
        processingLocation: this.active && this.config?.execution_mode === 'local' ? '이 컴퓨터에서 분석 · 영상은 외부로 보내지 않습니다' : this.active && this.config?.execution_mode === 'remote' ? '원격 PC에서 분석' : '',
        receivedFps, transferWarning: slowTransfer ? '전송 속도가 부족해 심박수를 계산할 수 없습니다. 연결 상태를 확인해 주세요.' : '' });
    }
    async request(path, options = {}, timeout = 6000) {
      const controller = new AbortController(); this.pending.add(controller);
      const timer = this.e.setTimeout(() => controller.abort(), timeout);
      try {
        const response = await this.e.fetch(path, { cache: 'no-store', ...options, signal: controller.signal });
        if (!response.ok) throw new Error('network');
        return await response.json();
      } finally { this.e.clearTimeout(timer); this.pending.delete(controller); }
    }
    post(config, body) { return { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-RPPG-Token': config.token }, body: JSON.stringify(body) }; }
    dispose(stream) { if (stream) for (const track of stream.getTracks()) track.stop(); }
    bestStop(config, session) {
      if (!config || !session) return;
      const controller = new AbortController();
      const timer = this.e.setTimeout(() => controller.abort(), 2000);
      Promise.resolve().then(() => this.e.fetch('/api/stop', { ...this.post(config, { session_id: session.session_id }), keepalive: true, signal: controller.signal }))
        .catch(() => {}).finally(() => this.e.clearTimeout(timer));
    }
    stop(message = '측정을 종료했습니다.') {
      this.pilot?.abort(message, this.e.now());
      this.generation++; this.active = false;
      for (const controller of this.pending) controller.abort(); this.pending.clear();
      if (this.callback !== null) this.e.cancelFrame(this.callback);
      if (this.watch !== null) this.e.clearInterval(this.watch);
      this.callback = this.watch = null;
      this.dispose(this.stream); this.stream = null;
      try { Promise.resolve(this.e.attach(null)).catch(() => {}); } catch (_) { /* Tracks are already disposed. */ }
      this.bestStop(this.config, this.session); this.session = null;
      this.busy = false; this.received = null; this.scene.reset(); this.message = message; this.emit();
    }
    async prepare(stream) {
      const controller = new AbortController(); this.pending.add(controller);
      let timer;
      try {
        await new Promise((resolve, reject) => {
          controller.signal.addEventListener('abort', () => reject(new Error('media_timeout')), { once: true });
          timer = this.e.setTimeout(() => controller.abort(), 8000);
          Promise.resolve().then(() => this.e.attach(stream)).then(resolve, reject);
        });
      } finally { this.e.clearTimeout(timer); this.pending.delete(controller); }
    }
    hidden() { this.stop('화면을 떠나 측정을 종료했습니다. 다시 시작해 주세요.'); }
    async startPilot(code, note) {
      if (this.active || this.pilot) return false;
      this.pilot = new StressPilot(code, note);
      await this.start(); return true;
    }
    resetPilot() {
      if (this.active || this.pilot?.acquiring) return false;
      this.pilot = null; this.emit(); return true;
    }
    advancePilot() {
      if (!this.pilot?.acquiring) return true;
      const previousPhase = this.pilot.phase;
      this.pilot.advance(this.e.now());
      if (this.pilot.acquiring && this.pilot.phase !== previousPhase) this.emit();
      if (!this.pilot.acquiring) {
        this.stop(this.pilot.status === 'complete' ? '3분 예비 실험을 마쳤습니다. 단계별 느낌을 기록하고 내려받아 주세요.' : '타이머가 끊겨 예비 실험을 중단했습니다. 부분 기록을 내려받을 수 있습니다.');
        return false;
      }
      return true;
    }
    async start() {
      if (this.active) return;
      const generation = ++this.generation;
      const alive = () => this.active && this.generation === generation;
      this.config = null; this.active = true; this.message = '카메라를 준비하고 있습니다.'; this.emit();
      let config, session;
      try {
        config = await this.request('/api/config');
        if (!alive()) return;
        if (!config.token || !config.boot_id) throw new Error('config');
        this.config = config;
        if (this.pilot?.acquiring && typeof config.runtime_id === 'string' && /^[a-f0-9]{64}$/.test(config.runtime_id)) this.pilot.runtimeId = config.runtime_id;
        this.emit();
        const stream = await this.e.getUserMedia({ audio: false, video: { width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 30 } } });
        if (!alive()) { this.dispose(stream); return; }
        this.stream = stream;
        for (const track of stream.getTracks()) track.addEventListener('ended', () => { if (alive()) this.stop('카메라 연결이 끊겼습니다. 다시 시작해 주세요.'); });
        await this.prepare(stream);
        if (!alive()) return;
        session = await this.request('/api/session', this.post(config, { client_id: this.e.uuid() }));
        if (!alive()) { this.bestStop(config, session); return; }
        if (session.boot_id !== config.boot_id || !session.session_id) { this.bestStop(config, session); throw new Error('boot'); }
        this.session = session; this.seq = 0; this.lastFrame = null; this.nextCapture = -Infinity;
        this.message = '얼굴을 화면 중앙에 두고 편안하게 앉아 주세요.';
        this.watch = this.e.setInterval(() => {
          if (!alive()) return;
          if (!this.advancePilot()) return;
          this.emit();
          if (this.e.now() - this.startedAt > 300000) this.stop('5분 측정을 마쳤습니다.');
        }, 100);
        this.startedAt = this.e.now(); this.received = new ReceivedFrames(this.startedAt); this.emit(); this.schedule(generation);
      } catch (error) {
        if (alive()) this.stop(error?.name === 'NotAllowedError' ? '카메라 권한이 허용되지 않았습니다. 브라우저 설정을 확인한 뒤 다시 시작해 주세요.' : '카메라 또는 측정 연결을 준비할 수 없습니다. 다시 시작해 주세요.');
      }
    }
    schedule(generation) {
      if (!this.active || generation !== this.generation) return;
      this.callback = this.e.frame((metadata) => { this.callback = null; this.tick(generation, metadata); });
    }
    async tick(generation, metadata) {
      const alive = () => this.active && this.generation === generation;
      if (!alive()) return;
      if (!this.advancePilot()) return;
      const now = this.e.now();
      const frameKey = metadata?.presentedFrames ?? metadata?.mediaTime ?? this.e.videoTime();
      if (this.busy || now + 1 < this.nextCapture || !finite(frameKey) || frameKey === this.lastFrame) { this.schedule(generation); return; }
      this.lastFrame = frameKey;
      const size = dimensions(...this.e.videoSize());
      if (!size) { this.schedule(generation); return; }
      this.busy = true;
      const captureAt = this.e.now(), period = 1000 / 15;
      if (!finite(this.nextCapture)) this.nextCapture = captureAt;
      // Keep elapsed deadlines rather than accumulating callback jitter or request latency.
      this.nextCapture += period;
      if (this.nextCapture <= captureAt + 1)
        this.nextCapture += (Math.floor((captureAt + 1 - this.nextCapture) / period) + 1) * period;
      this.pilot?.capture(captureAt);
      const seq = this.seq++, session = this.session, config = this.config;
      try {
        const png = await this.e.encode(size);
        if (!alive()) return;
        if (!png || png.type !== 'image/png' || png.size > 2 * 1024 * 1024) throw new Error('image');
        const data = await this.request('/api/frame', { method: 'POST', headers: {
          'Content-Type': 'image/png', 'X-RPPG-Token': config.token, 'X-Session-ID': session.session_id,
          'X-Frame-Seq': String(seq), 'X-Capture-Time': String(captureAt / 1000)
        }, body: png });
        if (!alive()) return;
        if (data.boot_id !== config.boot_id || data.session_id !== session.session_id || data.seq !== seq) throw new Error('stale');
        if (!finite(data.elapsed_s) || !finite(data.segment_elapsed_s)) throw new Error('timing');
        if (!this.advancePilot()) return;
        this.pilot?.receive(data, captureAt, this.e.now());
        this.received.record(captureAt, this.e.now());
        this.scene.receive(data, captureAt, this.e.now()); this.message = ''; this.emit();
      } catch (error) { if (alive()) this.stop('측정 연결이 끊겼습니다. 다시 시작해 주세요.'); }
      finally { if (alive()) { this.busy = false; this.schedule(generation); } }
    }
  }
  const api = { StressPilot, csvCell, Live, Scene, ReceivedFrames, dimensions, measurementInfo };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (!root.document) return;
  const $ = id => root.document.getElementById(id);
  const video = $('preview'), canvas = root.document.createElement('canvas'), overlay = $('overlay');
  const env = {
    now: () => performance.now(), fetch: (...args) => root.fetch(...args), uuid: () => root.crypto.randomUUID(),
    getUserMedia: constraints => navigator.mediaDevices.getUserMedia(constraints),
    setTimeout: root.setTimeout.bind(root), clearTimeout: root.clearTimeout.bind(root),
    setInterval: root.setInterval.bind(root), clearInterval: root.clearInterval.bind(root),
    attach: async stream => { video.srcObject = stream; if (stream) await video.play(); },
    frame: cb => video.requestVideoFrameCallback ? video.requestVideoFrameCallback((_, m) => cb(m)) : root.requestAnimationFrame(() => cb(null)),
    cancelFrame: id => video.cancelVideoFrameCallback ? video.cancelVideoFrameCallback(id) : root.cancelAnimationFrame(id),
    videoTime: () => video.currentTime, videoSize: () => [video.videoWidth, video.videoHeight],
    encode: size => { [canvas.width, canvas.height] = size; canvas.getContext('2d').drawImage(video, 0, 0, ...size); return new Promise(resolve => canvas.toBlob(resolve, 'image/png')); },
    render: state => {
      renderPilot(state);
      $('processing-location').textContent = state.processingLocation;
      $('start').disabled = state.active; $('stop').disabled = !state.active;
      $('status').textContent = state.message || (state.status === 'current' ? '측정 중 · 연속 확인 완료' : state.status === 'held' ? '이전값 · 현재 측정값이 아닙니다' : '현재 결과를 기다리고 있습니다');
      $('hr').textContent = state.hr === null ? '—' : state.hr.toFixed(1);
      $('hr-note').textContent = state.status === 'held' ? `마지막 확인 시점에서 ${state.age.toFixed(1)}초 경과` : state.status === 'current' ? '최근 두 번의 분석에서 확인했습니다.' : '유효한 결과가 연속 두 번 확인되면 표시합니다.';
      $('elapsed').textContent = `${Math.max(0, state.elapsed).toFixed(1)}초`;
      const rate = state.receivedFps;
      $('samples').textContent = state.data ? `${state.data.sample_count}회` : '—';
      $('fps').textContent = finite(rate) ? `${rate.toFixed(1)}회/초` : '집계 중';
      $('faces').textContent = state.data ? `${state.data.face_count}개` : '—';
      const measurement = measurementInfo(state);
      $('progress').value = state.progress; $('progress-label').textContent = measurement.progressLabel;
      $('analysis-update').textContent = measurement.analysisLabel;
      $('signal-quality').textContent = measurement.signalLabel;
      const reasons = state.data?.frame_reasons?.length ? state.data.frame_reasons : state.data?.analysis?.reasons || [];
      $('reason').textContent = [state.transferWarning, ...reasons.map(r => labels[r] || '측정 상태를 확인하고 있습니다.')].filter(Boolean).join(' ');
      const d = state.data; overlay.width = d?.frame_width || 640; overlay.height = d?.frame_height || 480;
      const ctx = overlay.getContext('2d'); ctx.clearRect(0, 0, overlay.width, overlay.height);
      if (d?.face_count === 1 && Array.isArray(d.face_box) && d.face_box.length === 4 && d.face_box.every(finite)) {
        ctx.strokeStyle = '#7bffd1'; ctx.lineWidth = 3; ctx.strokeRect(...d.face_box);
        const [x, y, w, h] = d.face_box; ctx.lineWidth = 2;
        for (const [rx, ry, rw, rh] of [[.25,.12,.5,.18],[.15,.5,.25,.2],[.6,.5,.25,.2]])
          ctx.strokeRect(x + rx * w, y + ry * h, rw * w, rh * h);
      }
      $('placeholder').hidden = state.active;
    }
  };
  function renderPilot(state) {
    const p = state.pilot;
    $('pilot-start').disabled = state.active || !!p;
    $('pilot-stop').disabled = !(state.active && p?.acquiring);
    $('pilot-reset').disabled = state.active || !p || p.acquiring;
    $('pilot-code').disabled = state.active || !!p; $('pilot-note').disabled = state.active || !!p;
    const terminal = p && !p.acquiring;
    $('pilot-results').hidden = !terminal;
    $('pilot-json').disabled = !terminal; $('pilot-csv').disabled = !terminal;
    $('pilot-reports').disabled = !terminal;
    for (let i = 0; i < 3; i++) {
      const visited = p && p.phases[i].start !== null;
      $('pilot-score-' + i).disabled = !terminal || !visited;
      if (!visited) $('pilot-score-' + i).value = '';
    }
    $('pilot-state').textContent = !p ? '준비 · 카메라 시작은 연속 측정, 3분 시작은 예비 실험입니다.'
      : p.status === 'preparing' ? '휴식 · 편안하게 앉아 주세요. 첫 영상부터 60초를 셉니다.'
      : p.status === 'running' ? `${phaseNames[p.phase]} · ${Math.max(0, Math.ceil((p.phase + 1) * 60 - (performance.now() - p.origin) / 1000))}초 남음. ${p.phase === 1 ? '말하지 않고 1000에서 7을 계속 빼세요.' : '말하거나 움직이지 말고 편안하게 앉아 주세요.'}`
      : p.status === 'complete' ? '완료 · 카메라를 껐습니다.' : '중단 · 부분 기록을 보존했습니다. ' + p.reason;
    if (terminal) {
      const d = p.exportData();
      $('pilot-summary').textContent = d.phases.map(x => `${x.phase}: ${x.complete ? '단계 완료' : '미완료'}, 포함 ${x.contained_count} / 유효 ${x.usable_count} / 품질 제외 ${x.quality_excluded_count}개, 중앙값 ${x.median_hr_bpm === null ? '비교 보류' : x.median_hr_bpm.toFixed(1) + ' bpm'}`).join('\n') +
        `\n단계 밖·경계 분석 ${d.unassigned_count}개. ΔHR 암산−휴식: ${d.task_minus_rest_bpm === null ? '보류' : d.task_minus_rest_bpm.toFixed(1) + ' bpm'}, 회복−휴식: ${d.recovery_minus_rest_bpm === null ? '보류' : d.recovery_minus_rest_bpm.toFixed(1) + ' bpm'}`;
    }
  }
  const live = new Live(env);
  $('pilot-start').addEventListener('click', () => live.startPilot($('pilot-code').value, $('pilot-note').value));
  $('pilot-stop').addEventListener('click', () => live.stop('실험을 중지했습니다. 부분 기록을 내려받을 수 있습니다.'));
  $('pilot-reset').addEventListener('click', () => {
    if (root.confirm('내려받지 않은 기록도 지워집니다. 현재 기록을 지우고 새로 준비할까요?')) {
      if (live.resetPilot()) for (let i = 0; i < 3; i++) $('pilot-score-' + i).value = '';
    }
  });
  for (let i = 0; i < 3; i++) $('pilot-score-' + i).addEventListener('change', () => live.pilot?.setReport(i, $('pilot-score-' + i).value));
  function downloadPilot(format) {
    const p = live.pilot; if (!p || p.acquiring) return;
    const blob = new Blob([format === 'json' ? JSON.stringify(p.exportData(), null, 2) : '\ufeff' + p.csv()], { type: format === 'json' ? 'application/json' : 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob), a = root.document.createElement('a');
    a.href = url; a.download = 'rppg-pilot.' + format; a.click(); root.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  $('pilot-json').addEventListener('click', () => downloadPilot('json'));
  $('pilot-csv').addEventListener('click', () => downloadPilot('csv'));
  $('start').addEventListener('click', () => live.start()); $('stop').addEventListener('click', () => live.stop());
  root.document.addEventListener('visibilitychange', () => { if (root.document.hidden) live.hidden(); });
  video.addEventListener('error', () => live.stop('카메라 영상을 읽을 수 없습니다. 다시 시작해 주세요.'));
  root.addEventListener('pagehide', () => live.stop());
})(typeof globalThis !== 'undefined' ? globalThis : this);
