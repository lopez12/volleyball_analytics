/* ===================================================================
 * Registro de Partido — Setup / Onboarding flow (Brief 2).
 *
 * Retains the Brief 1 hash navigation and adds the pre-analysis setup
 * wizard: team/roster selection (from docs/datasets.json, with a manual
 * fallback), match metadata (opponent + NN order index + type), and
 * per-set video URLs + scores. Produces a session object handed to the
 * Analysis screen (Brief 3) and autosaves the draft to IndexedDB so
 * setup survives a reload.
 *
 * In-browser validation mirrors validate_logs.py so a completed session
 * can only produce a log that passes QA: roster numbers valid (R2),
 * `@set` format V-R (R3), and `@youtube` URL rule (R6). All logic lives
 * in this one file (no frameworks, no bundler).
 * =================================================================== */
(function () {
  'use strict';

  // ---------------------------------------------------------------
  // Constants (grammar mirrors analytics.py / validate_logs.py)
  // ---------------------------------------------------------------
  var SCREENS = ['home', 'setup', 'analysis', 'review'];
  var DEFAULT_SCREEN = 'home';
  var RE_YT = /^https?:\/\/(www\.)?(youtube\.com|youtu\.be)\//i;   // R6
  var RE_OUTCOME = /^@(won|lost)(?::(re|se))?$/i;    // mirrors analytics._parse_outcome_token
  var RE_PLAY = /^(\d*)([SREADB])([#+!\-])$/i;       // mirrors analytics._RE_ANY
  var RE_TS = /^@t:(\d+(?:\.\d+)?)(?:-(\d+(?:\.\d+)?))?$/i;   // mirrors analytics._RE_TIMESTAMP
  var DATASET_CANDIDATES = ['../datasets.json', 'datasets.json'];
  var DB_NAME = 'registro-partido';
  var DB_VERSION = 1;
  var STORE = 'drafts';
  var MANUAL_KEY = '__manual__';

  // ---------------------------------------------------------------
  // Module state
  // ---------------------------------------------------------------
  var datasetIndex = {};   // 'team_slug/tournament_slug' -> manifest entry
  var draft = null;        // current in-progress setup draft (form state)
  var session = null;      // built session handed to Analysis (Brief 3)
  var analysis = null;     // in-progress tagging state (persisted on the draft)
  var sel = { player: null, action: null };  // transient entry-machine selection
  var numBuf = '';         // keyboard digit accumulator for player numbers
  var saveTimer = null;

  // YouTube IFrame Player API state (Brief 4/6). The plain <iframe> is upgraded
  // to a controllable player so rally timestamps can be captured (getCurrentTime)
  // and, later, sought (seekTo). All access goes through `videoController`.
  var ytApiState = { loading: false, callbacks: [] };
  var video = { player: null, mountedId: null, ready: false };

  // ---------------------------------------------------------------
  // Small helpers
  // ---------------------------------------------------------------
  function byId(id) { return document.getElementById(id); }
  function noop() {}

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function setError(id, msg) {
    var el = byId(id);
    if (!el) return;
    el.textContent = msg || '';
    el.style.display = msg ? 'block' : 'none';
  }

  // ---------------------------------------------------------------
  // String helpers (mirror renderer.format_title round-trip)
  // ---------------------------------------------------------------
  function slugify(name) {
    return (name || '').toString().trim().toLowerCase()
      .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '');
  }

  function titleFromSlug(slug) {
    return slug.split('_').filter(Boolean).map(function (w) {
      return w.charAt(0).toUpperCase() + w.slice(1);
    }).join(' ');
  }

  function pad2(v) {
    var n = parseInt(v, 10);
    if (isNaN(n)) return '';
    return (n < 10 ? '0' : '') + n;
  }

  // Return 'YYYY-MM-DD' for a well-formed, real calendar date, else null.
  function normalizeDate(str) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec((str || '').trim());
    if (!m) return null;
    var y = +m[1], mo = +m[2], da = +m[3];
    var dt = new Date(Date.UTC(y, mo - 1, da));
    if (dt.getUTCFullYear() !== y || dt.getUTCMonth() !== mo - 1 || dt.getUTCDate() !== da) {
      return null;
    }
    return m[1] + '-' + m[2] + '-' + m[3];
  }

  // ---------------------------------------------------------------
  // Navigation (Brief 1 behaviour, retained)
  // ---------------------------------------------------------------
  function currentScreen() {
    var name = (window.location.hash || '').replace(/^#/, '');
    return SCREENS.indexOf(name) !== -1 ? name : DEFAULT_SCREEN;
  }

  function render() {
    var active = currentScreen();

    var screens = document.querySelectorAll('.lg-screen');
    for (var i = 0; i < screens.length; i++) {
      screens[i].classList.toggle('is-active', screens[i].dataset.screen === active);
    }

    var links = document.querySelectorAll('.lg-navlink');
    for (var j = 0; j < links.length; j++) {
      links[j].classList.toggle('is-active', links[j].dataset.screen === active);
    }

    if (active === 'analysis') { ensureAnalysis(); renderAnalysis(); }
    else if (active === 'review') { ensureAnalysis(); renderReview(); }

    window.scrollTo(0, 0);
  }

  // ---------------------------------------------------------------
  // Draft model
  // ---------------------------------------------------------------
  function emptySet() { return { v: '', r: '', video: '' }; }

  function newDraft() {
    return {
      id: 'draft-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8),
      updatedAt: Date.now(),
      datasetKey: '',
      opponent: '',
      order: '',
      date: '',
      sets: [emptySet()]
    };
  }

  function normalizeDraft(d) {
    if (!d.id) d.id = newDraft().id;
    if (!Array.isArray(d.sets)) d.sets = [emptySet()];
    if (typeof d.datasetKey !== 'string') d.datasetKey = '';
    if (typeof d.date !== 'string') d.date = '';
    return d;
  }

  // ---------------------------------------------------------------
  // IndexedDB (best-effort; failures never block the UI)
  // ---------------------------------------------------------------
  function openDB() {
    return new Promise(function (resolve, reject) {
      if (!window.indexedDB) { reject(new Error('IndexedDB no disponible')); return; }
      var req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function () {
        var db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'id' });
        }
      };
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function dbPut(record) {
    return openDB().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).put(record);
        tx.oncomplete = function () { resolve(record); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function dbGetAll() {
    return openDB().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, 'readonly');
        var req = tx.objectStore(STORE).getAll();
        req.onsuccess = function () { resolve(req.result || []); };
        req.onerror = function () { reject(req.error); };
      });
    });
  }

  function dbDelete(id) {
    return openDB().then(function (db) {
      return new Promise(function (resolve, reject) {
        var tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).delete(id);
        tx.oncomplete = function () { resolve(); };
        tx.onerror = function () { reject(tx.error); };
      });
    });
  }

  function saveDraftNow() {
    if (!draft) return;
    draft.updatedAt = Date.now();
    dbPut(draft).catch(noop);
  }

  function saveDraftSoon() {
    if (saveTimer) clearTimeout(saveTimer);
    saveTimer = setTimeout(saveDraftNow, 400);
  }

  // ---------------------------------------------------------------
  // datasets.json loading (no GitHub API — published manifest only)
  // ---------------------------------------------------------------
  var MANUAL_LABEL = '➕ Nuevo equipo (próximamente)';

  function manualOption() {
    return '<option value="' + MANUAL_KEY + '">' + esc(MANUAL_LABEL) + '</option>';
  }

  function baseOptions() {
    return '<option value="">— Selecciona un equipo —</option>' + manualOption();
  }

  function fetchFirst(urls) {
    var i = 0;
    function attempt() {
      if (i >= urls.length) return Promise.reject(new Error('no manifest'));
      var url = urls[i++];
      return fetch(url, { cache: 'no-cache' }).then(function (r) {
        if (!r.ok) throw new Error('status ' + r.status);
        return r.json();
      }).catch(function () { return attempt(); });
    }
    return attempt();
  }

  // Prefer the script-injected global (works over file://); fall back to fetch.
  function getManifest() {
    if (Array.isArray(window.LOGGER_DATASETS)) {
      return Promise.resolve(window.LOGGER_DATASETS);
    }
    return fetchFirst(DATASET_CANDIDATES).catch(function () { return []; });
  }

  function loadDatasets() {
    return getManifest().then(function (data) {
      var list = Array.isArray(data) ? data : [];
      datasetIndex = {};
      var opts = ['<option value="">— Selecciona un equipo —</option>'];
      list.forEach(function (ds) {
        if (!ds || !ds.team_slug) return;
        var key = ds.team_slug + '/' + ds.tournament_slug;
        datasetIndex[key] = ds;
        var label = ds.team + (ds.tournament ? ' · ' + ds.tournament : '');
        opts.push('<option value="' + esc(key) + '">' + esc(label) + '</option>');
      });
      opts.push(manualOption());
      var sel = byId('setup-dataset');
      if (sel) sel.innerHTML = opts.join('');
    }).catch(function () {
      var sel = byId('setup-dataset');
      if (sel) sel.innerHTML = baseOptions();
    });
  }

  // ---------------------------------------------------------------
  // Validation (mirrors validate_logs.py R2/R3/R6)
  // ---------------------------------------------------------------
  function resolveTeam(d) {
    var key = d.datasetKey;
    if (key === MANUAL_KEY) {
      // Deferred to a later PR; the dropdown option shows a "coming soon" note.
      return { ok: false, error: '' };
    }
    if (key) {
      var ds = datasetIndex[key];
      if (ds) {
        return {
          ok: true, team: ds.team, tournament: ds.tournament,
          type: ds.type || 'tournament', roster: ds.roster || {},
          team_slug: ds.team_slug, tournament_slug: ds.tournament_slug
        };
      }
      return { ok: false, error: 'El equipo seleccionado no está disponible.' };
    }
    return { ok: false, error: 'Selecciona un equipo de la lista.' };
  }

  function resolveMatch(d, teamName) {
    var opponent = (d.opponent || '').trim();
    var order = (d.order == null ? '' : d.order).toString().trim();
    if (!opponent) return { ok: false, error: 'Escribe el nombre del rival.' };
    if (!/^\d{1,2}$/.test(order) || parseInt(order, 10) < 1) {
      return { ok: false, error: 'Número de partido inválido (1 o 2 dígitos, ej. 03).' };
    }
    var matchDate = null;
    var dateRaw = (d.date || '').trim();
    if (dateRaw) {
      matchDate = normalizeDate(dateRaw);      // optional; must be a real ISO date
      if (!matchDate) return { ok: false, error: 'Fecha inválida (usa formato AAAA-MM-DD).' };
    }
    var slug = slugify(opponent);
    if (!slug) return { ok: false, error: 'El nombre del rival no es válido.' };
    var nn = pad2(order);
    var stem = nn + '_' + slug;
    return {
      ok: true, order_index: nn, opponent: opponent, date: matchDate,
      filename: stem + '.txt', title: teamName + ' vs ' + titleFromSlug(slug)
    };
  }

  function resolveSets(d) {
    var sets = [], rows = [], ok = true, summary = [];
    (d.sets || []).forEach(function (s, i) {
      var no = i + 1, score = null, videoUrl = null;
      var scoreError = '', videoError = '';
      var v = String(s.v == null ? '' : s.v).trim();
      var r = String(s.r == null ? '' : s.r).trim();
      if (v || r) {
        if (!v || !r || !/^\d+$/.test(v) || !/^\d+$/.test(r)) {
          scoreError = 'Set ' + no + ': marcador incompleto (usa formato V-R, ej. 25-20).';
        } else {
          score = parseInt(v, 10) + '-' + parseInt(r, 10);   // R3: V-R
        }
      }
      var video = (s.video || '').trim();
      if (video) {
        if (RE_YT.test(video)) { videoUrl = video; }          // R6
        else { videoError = 'URL de YouTube inválida.'; }
      }
      if (scoreError) { ok = false; summary.push(scoreError); }
      if (videoError) { ok = false; }
      sets.push({ score: score, video_url: videoUrl });
      rows.push({ scoreError: scoreError, videoError: videoError });
    });
    return { ok: ok, sets: sets, rows: rows, errors: summary };
  }

  function computeValidity(d) {
    var team = resolveTeam(d);
    var match = team.ok ? resolveMatch(d, team.team) : { ok: false, error: '' };
    var sets = resolveSets(d);
    return { team: team, match: match, sets: sets, ok: team.ok && match.ok && sets.ok };
  }

  // ---------------------------------------------------------------
  // Session build + handoff to Analysis (Brief 3)
  // ---------------------------------------------------------------
  function buildSession(d, v) {
    return {
      draftId: d.id,
      team: v.team.team,
      tournament: v.team.tournament,
      type: v.team.type || 'tournament',
      team_slug: v.team.team_slug || slugify(v.team.team),
      tournament_slug: v.team.tournament_slug || slugify(v.team.tournament || ''),
      roster: v.team.roster,
      opponent: v.match.opponent,
      order_index: v.match.order_index,
      date: v.match.date,
      filename: v.match.filename,
      title: v.match.title,
      sets: v.sets.sets
    };
  }

  // ---------------------------------------------------------------
  // Analysis / tagging (Brief 3)
  //
  // The working log IS the state: analysis.sets holds per-set metadata
  // (score/video) plus committed rallies, and analysis.entry holds the
  // in-progress rally. Everything renders from this model and exports
  // straight to the canonical .txt grammar, so the log stays valid at
  // all times (validate_logs.py roster/@set/@youtube/outcome rules).
  // ---------------------------------------------------------------
  function emptyEntry() { return { tokens: [], outcome: null, start: null, end: null }; }

  function newAnalysis(s) {
    var sets = (s.sets || []).map(function (st) {
      return { score: st.score || null, video_url: st.video_url || null, rallies: [] };
    });
    if (!sets.length) sets.push({ score: null, video_url: null, rallies: [] });
    return { sets: sets, currentSet: 0, entry: emptyEntry(), date: s.date || null };
  }

  // Refresh per-set metadata from a (re)built session without losing rallies.
  function syncAnalysisMeta(s) {
    if (!analysis) return;
    analysis.date = s.date || null;
    (s.sets || []).forEach(function (st, i) {
      if (analysis.sets[i]) {
        analysis.sets[i].score = st.score || null;
        analysis.sets[i].video_url = st.video_url || null;
      } else {
        analysis.sets.push({ score: st.score || null, video_url: st.video_url || null, rallies: [] });
      }
    });
  }

  function ensureAnalysis() {
    if (!session) return;
    if (!analysis || !Array.isArray(analysis.sets) || !analysis.sets.length) {
      analysis = newAnalysis(session);
    }
    if (!analysis.entry) analysis.entry = emptyEntry();
    if (typeof analysis.currentSet !== 'number') analysis.currentSet = 0;
    if (draft) draft.analysis = analysis;
  }

  function currentSet() {
    if (!analysis) return null;
    if (analysis.currentSet < 0 || analysis.currentSet >= analysis.sets.length) analysis.currentSet = 0;
    return analysis.sets[analysis.currentSet];
  }

  function resetSelection() { sel.player = null; sel.action = null; numBuf = ''; }

  // -- roster helpers (mirror validate_logs R2: only roster numbers are valid) --
  function rosterNums() { return session ? Object.keys(session.roster || {}) : []; }
  function isRosterNumber(str) { return rosterNums().indexOf(str) !== -1; }
  function isRosterPrefix(str) {
    return rosterNums().some(function (n) { return n.indexOf(str) === 0; });
  }

  // -- outcome helpers --
  function outcomeToCode(o) {
    if (!o) return '';
    return o.result === 'lost' ? 'lost' : ('won' + (o.cause ? ':' + o.cause : ''));
  }
  function codeToOutcome(code) {
    if (code === 'lost') return { result: 'lost', cause: null };
    if (code === 'won:re') return { result: 'won', cause: 're' };
    if (code === 'won:se') return { result: 'won', cause: 'se' };
    return { result: 'won', cause: null };
  }
  function outcomeToken(o) { return '@' + outcomeToCode(o); }
  function outcomeLabel(o) {
    if (!o) return '';
    if (o.result === 'lost') return 'Perdido';
    if (o.cause === 're') return 'Error rival';
    if (o.cause === 'se') return 'Saque rival';
    return 'Ganado';
  }

  // -- rendering --
  function renderSetTabs() {
    var host = byId('analysis-set-tabs');
    if (!host || !analysis) return;
    var many = analysis.sets.length > 1;
    var html = analysis.sets.map(function (st, i) {
      var active = i === analysis.currentSet ? ' is-active' : '';
      var remove = many
        ? '<button type="button" class="lg-set-tab__remove" data-del-set="' + i +
          '" aria-label="Eliminar set ' + (i + 1) + '">✕</button>'
        : '';
      return '<span class="lg-set-tab-wrap' + active + '">' +
        '<button type="button" class="lg-set-tab' + active + '" data-set="' + i + '">Set ' + (i + 1) + '</button>' +
        remove + '</span>';
    }).join('');
    html += '<button type="button" id="analysis-add-set" class="lg-set-tab lg-set-tab--add">➕ Nuevo set</button>';
    host.innerHTML = html;
  }

  function extractYouTubeId(url) {
    var m = String(url || '').match(
      /(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|embed\/|v\/|shorts\/))([\w-]{11})/);
    return m ? m[1] : null;
  }

  function videoOpenLink(url) {
    return '<a class="lg-video__open" href="' + esc(url) +
      '" target="_blank" rel="noopener noreferrer">Abrir en YouTube ↗</a>';
  }

  // ---------------------------------------------------------------
  // Video controller (provider-agnostic seam over the YouTube IFrame API).
  // Playback/capture logic calls only these methods, never YT.* directly,
  // so a different provider could be dropped in later (Brief 6 R2).
  // ---------------------------------------------------------------
  var videoController = {
    isReady: function () { return !!(video.player && video.ready); },
    getCurrentTime: function () {
      if (!this.isReady()) return null;
      try { return video.player.getCurrentTime(); } catch (e) { return null; }
    },
    seekTo: function (seconds) {
      if (!this.isReady()) return;
      try { video.player.seekTo(seconds, true); } catch (e) {}
    },
    play: function () {
      if (!this.isReady()) return;
      try { video.player.playVideo(); } catch (e) {}
    },
    pause: function () {
      if (!this.isReady()) return;
      try { video.player.pauseVideo(); } catch (e) {}
    }
  };

  function ytApiIsReady() { return !!(window.YT && window.YT.Player); }

  // Load the IFrame API script once; fan out to any queued callbacks on ready.
  function ensureYtApi(cb) {
    if (ytApiIsReady()) { cb(); return; }
    ytApiState.callbacks.push(cb);
    if (ytApiState.loading) return;
    ytApiState.loading = true;
    var prev = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = function () {
      if (typeof prev === 'function') { try { prev(); } catch (e) {} }
      var cbs = ytApiState.callbacks.slice();
      ytApiState.callbacks = [];
      cbs.forEach(function (f) { try { f(); } catch (e) {} });
    };
    var tag = document.createElement('script');
    tag.src = 'https://www.youtube.com/iframe_api';
    document.head.appendChild(tag);
  }

  function destroyPlayer() {
    if (video.player) { try { video.player.destroy(); } catch (e) {} }
    video.player = null;
    video.mountedId = null;
    video.ready = false;
  }

  function mountPlayer(id) {
    ensureYtApi(function () {
      if (!ytApiIsReady()) return;
      var target = byId('lg-yt-player');
      if (!target) return;   // video area was re-rendered away before we mounted
      destroyPlayer();
      video.mountedId = id;
      video.player = new YT.Player('lg-yt-player', {
        videoId: id,
        playerVars: { rel: 0, modestbranding: 1, playsinline: 1, origin: window.location.origin },
        events: {
          onReady: function () { video.ready = true; }
        }
      });
    });
  }

  // Current set's embeddable YouTube id, or null when there is no usable video.
  function analysisVideoId() {
    var set = currentSet();
    var url = set && set.video_url ? set.video_url : '';
    return url ? extractYouTubeId(url) : null;
  }

  // The controllable player only works over http(s) (YT rejects a null origin).
  function videoEmbedActive() {
    return !!analysisVideoId() && /^https?:$/.test(window.location.protocol);
  }

  function renderVideo() {
    var host = byId('analysis-video');
    if (!host) return;
    var set = currentSet();
    var url = set && set.video_url ? set.video_url : '';
    var id = url ? extractYouTubeId(url) : null;
    var served = /^https?:$/.test(window.location.protocol);

    if (id && served) {
      // Reuse the live player when the set video is unchanged, so routine
      // re-renders don't tear down playback or lose the current time.
      if (video.player && video.mountedId === id && byId('lg-yt-player')) {
        host.className = 'lg-video lg-a-video lg-video--embed';
        return;
      }
      host.className = 'lg-video lg-a-video lg-video--embed';
      host.innerHTML = '<div id="lg-yt-player" class="lg-video__frame"></div>';
      mountPlayer(id);
      return;
    }

    destroyPlayer();   // leaving embed mode: release any live player
    host.className = 'lg-video lg-a-video';
    if (id && !served) {
      host.innerHTML = '<span class="lg-video__icon" aria-hidden="true">▶</span>' +
        '<span class="lg-video__hint">Abre el registro desde un servidor web (o GitHub Pages) para ver el video aquí.</span>' +
        videoOpenLink(url);
    } else if (url) {
      host.innerHTML = '<span class="lg-video__icon" aria-hidden="true">▶</span>' +
        '<span class="lg-video__hint">URL de video no reconocida.</span>' +
        videoOpenLink(url);
    } else {
      host.innerHTML = '<span class="lg-video__icon" aria-hidden="true">▶</span>' +
        '<span class="lg-video__hint">Sin video para este set</span>';
    }
  }

  // ---------------------------------------------------------------
  // Timestamp capture (Brief 4): a rally's start is stamped when its entry
  // begins (or via "Marcar inicio"); its end is stamped at "Enviar rally".
  // ---------------------------------------------------------------
  function nowVideoTime() {
    var t = videoController.getCurrentTime();
    return (typeof t === 'number' && isFinite(t) && t >= 0) ? t : null;
  }

  // Serialize seconds for the '@t:' token: whole seconds drop the decimal.
  function fmtSecs(sec) {
    var n = Math.round(sec * 10) / 10;
    return String(n);
  }

  function tsToken(start, end) {
    return '@t:' + fmtSecs(start) + (end != null ? '-' + fmtSecs(end) : '');
  }

  // Human-friendly mm:ss for on-screen capture readouts.
  function fmtClock(sec) {
    if (sec == null) return '—';
    var s = Math.max(0, Math.round(sec));
    var m = Math.floor(s / 60);
    var r = s % 60;
    return m + ':' + (r < 10 ? '0' : '') + r;
  }

  // Stamp the in-progress rally's start once, when it first gains content.
  function markStartIfNeeded() {
    if (!analysis || analysis.entry.start != null) return;
    var t = nowVideoTime();
    if (t != null) analysis.entry.start = t;
  }

  // One button drives the pre-analysis pass: the first press stamps the rally's
  // start, the next stamps its end (both re-markable). A segmenter can mark
  // start/end + result with no plays, leaving the grading for a later pass.
  function markToggle() {
    if (!analysis) return;
    var t = nowVideoTime();
    if (t == null) return;
    if (analysis.entry.start == null) analysis.entry.start = t;
    else analysis.entry.end = t;
    renderCapture();
    updateSendState();
    saveDraftSoon();
  }

  function renderCapture() {
    var bar = byId('analysis-capture');
    if (!bar) return;
    var active = videoEmbedActive();
    bar.hidden = !active;
    if (!active) return;
    var e = analysis ? analysis.entry : null;
    var s = byId('analysis-cap-start');
    var f = byId('analysis-cap-end');
    if (s) s.textContent = fmtClock(e ? e.start : null);
    if (f) f.textContent = fmtClock(e ? e.end : null);
    var btn = byId('analysis-mark');
    if (btn) btn.textContent = (e && e.start != null) ? '⏱ Marcar fin' : '⏱ Marcar inicio';
  }

  function renderRoster() {
    var host = byId('analysis-roster');
    if (!host || !session) return;
    var nums = rosterNums().sort(function (a, b) { return (+a) - (+b); });
    var html = nums.map(function (n) {
      var info = (session.roster || {})[n] || {};
      var hint = info.name ? '<small>' + esc(info.name) + '</small>' : '';
      var scls = sel.player === n ? ' is-selected' : '';
      return '<button type="button" class="lg-token-btn lg-roster-btn' + scls + '" data-player="' + esc(n) + '">' +
        '<b>' + esc(n) + '</b>' + hint + '</button>';
    }).join('');
    host.innerHTML = html;
  }

  function renderActions() {
    var btns = document.querySelectorAll('#screen-analysis [data-action]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle('is-selected', btns[i].getAttribute('data-action') === sel.action);
    }
  }

  function renderChain() {
    var el = byId('analysis-chain');
    if (!el || !analysis) return;
    var text = analysis.entry.tokens.join(' ');
    var pending = '';
    if (sel.player) pending += sel.player;
    if (sel.action) pending += sel.action;
    if (pending) text += (text ? ' ' : '') + pending + '…';
    el.textContent = text;
  }

  function renderOutcomes() {
    var code = analysis ? outcomeToCode(analysis.entry.outcome) : '';
    var btns = document.querySelectorAll('#screen-analysis [data-outcome]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle('is-selected', btns[i].getAttribute('data-outcome') === code);
    }
  }

  function renderRallies() {
    var host = byId('analysis-rallies');
    if (!host || !analysis) return;
    var set = currentSet();
    var rallies = set ? set.rallies : [];
    if (!rallies.length) {
      host.innerHTML = '<li class="lg-rally lg-rally--empty">' +
        '<span class="lg-rally__idx">·</span>' +
        '<code class="lg-rally__chain">Los rallies enviados aparecerán aquí.</code></li>';
      return;
    }
    host.innerHTML = rallies.map(function (r, i) {
      var chain = r.tokens.join(' ') || (r.outcome ? outcomeToken(r.outcome) : '—');
      var badge = '';
      if (r.outcome) {
        var cls = r.outcome.result === 'lost' ? 'result-loss' : 'result-win';
        badge = '<span class="result-badge ' + cls + ' lg-rally__outcome">' +
          esc(outcomeLabel(r.outcome)) + '</span>';
      }
      var time = (r.start != null)
        ? '<span class="lg-rally__time" title="Marca de tiempo del video">⏱ ' +
          esc(fmtClock(r.start)) + (r.end != null ? '–' + esc(fmtClock(r.end)) : '') + '</span>'
        : '';
      return '<li class="lg-rally" data-idx="' + i + '">' +
        '<span class="lg-rally__idx">' + (i + 1) + '</span>' +
        '<code class="lg-rally__chain">' + esc(chain) + '</code>' + badge + time +
        '<div class="lg-rally__actions">' +
          '<button type="button" class="lg-rally__edit" data-edit="' + i + '" aria-label="Editar rally ' + (i + 1) + '">✎</button>' +
          '<button type="button" class="lg-rally__del" data-del="' + i + '" aria-label="Eliminar rally ' + (i + 1) + '">🗑</button>' +
        '</div></li>';
    }).join('');
  }

  function updateSendState() {
    var btn = byId('analysis-send');
    if (!btn || !analysis) return;
    var e = analysis.entry;
    btn.disabled = !(e.tokens.length || e.outcome || e.start != null);
  }

  function renderAnalysis() {
    var titleEl = byId('analysis-title');
    if (titleEl) titleEl.textContent = (session && session.title) || 'Análisis del partido';
    if (!analysis) return;
    renderSetTabs();
    renderVideo();
    renderCapture();
    renderRoster();
    renderActions();
    renderChain();
    renderOutcomes();
    renderRallies();
    updateSendState();
  }

  // -- entry state machine: player -> action -> grade -> token --
  function selectPlayer(p) {
    resetSelection();
    sel.player = p;
    numBuf = p;
    renderRoster(); renderChain();
  }

  function playerDigit(d) {
    if (isRosterPrefix(numBuf + d)) { numBuf += d; }
    else if (isRosterPrefix(d)) { numBuf = d; }
    else { return; }
    sel.player = numBuf;
    sel.action = null;
    renderRoster(); renderActions(); renderChain();
  }

  function selectAction(a) {
    if (!isRosterNumber(sel.player)) return;   // need a valid player first
    sel.action = a;
    renderActions(); renderChain();
  }

  function selectGrade(g) {
    if (!sel.action) return;
    if (!isRosterNumber(sel.player)) return;
    var token = sel.player + sel.action + g;
    markStartIfNeeded();
    analysis.entry.tokens.push(token);
    resetSelection();
    renderRoster(); renderActions(); renderChain(); updateSendState(); renderCapture();
    saveDraftSoon();
  }

  function undoToken() {
    if (!analysis) return;
    if (sel.player || sel.action) { resetSelection(); }
    else if (analysis.entry.tokens.length) { analysis.entry.tokens.pop(); }
    renderRoster(); renderActions(); renderChain(); updateSendState();
    saveDraftSoon();
  }

  function selectOutcome(code) {
    if (!analysis) return;
    var cur = outcomeToCode(analysis.entry.outcome);
    analysis.entry.outcome = (cur === code) ? null : codeToOutcome(code);   // replace-on-reselect / toggle-off
    renderOutcomes(); updateSendState(); renderCapture();
    saveDraftSoon();
  }

  function sendRally() {
    if (!analysis) return;
    var e = analysis.entry;
    if (!e.tokens.length && !e.outcome && e.start == null) return;   // need plays, an outcome, or a marked segment
    var end = (e.end != null) ? e.end : nowVideoTime();   // keep an explicitly marked end
    currentSet().rallies.push({
      tokens: e.tokens.slice(), outcome: e.outcome,
      start: e.start, end: end
    });
    analysis.entry = emptyEntry();
    resetSelection();
    renderRoster(); renderActions(); renderChain(); renderOutcomes();
    renderRallies(); updateSendState(); renderCapture();
    saveDraftNow();
  }

  function deleteRally(idx) {
    var set = currentSet();
    if (!set || idx < 0 || idx >= set.rallies.length) return;
    set.rallies.splice(idx, 1);
    renderRallies();
    saveDraftNow();
  }

  function editRally(idx) {
    var set = currentSet();
    if (!set || idx < 0 || idx >= set.rallies.length) return;
    var r = set.rallies.splice(idx, 1)[0];
    // Don't lose an in-progress rally: commit it before loading the edited one.
    if (analysis.entry.tokens.length || analysis.entry.outcome) {
      set.rallies.push({
        tokens: analysis.entry.tokens.slice(), outcome: analysis.entry.outcome,
        start: analysis.entry.start, end: analysis.entry.end
      });
    }
    analysis.entry = {
      tokens: r.tokens.slice(), outcome: r.outcome,
      start: (r.start != null ? r.start : null), end: (r.end != null ? r.end : null)
    };
    resetSelection();
    renderAnalysis();
    saveDraftNow();
  }

  function addSet() {
    if (!analysis) return;
    analysis.sets.push({ score: null, video_url: null, rallies: [] });
    analysis.currentSet = analysis.sets.length - 1;
    renderAnalysis();
    saveDraftNow();
  }

  function switchSet(idx) {
    if (!analysis || idx < 0 || idx >= analysis.sets.length) return;
    analysis.currentSet = idx;
    renderSetTabs(); renderVideo(); renderCapture(); renderRallies();
    saveDraftNow();
  }

  function removeSet(idx) {
    if (!analysis || analysis.sets.length <= 1) return;   // always keep one set
    if (idx < 0 || idx >= analysis.sets.length) return;
    var set = analysis.sets[idx];
    if (set.rallies.length &&
        !window.confirm('El Set ' + (idx + 1) + ' tiene ' + set.rallies.length +
          ' rally(s). ¿Eliminarlo?')) return;
    analysis.sets.splice(idx, 1);
    if (analysis.currentSet > idx) analysis.currentSet -= 1;
    if (analysis.currentSet >= analysis.sets.length) analysis.currentSet = analysis.sets.length - 1;
    renderAnalysis();
    saveDraftNow();
  }

  // ---------------------------------------------------------------
  // Export / import / review — canonical .txt is the source of truth
  // ---------------------------------------------------------------
  function buildLog(a) {
    if (!a) return '';
    var body = a.sets.map(function (set) {
      var lines = [];
      if (set.score) lines.push('@set: ' + set.score);
      if (set.video_url) lines.push('@youtube: ' + set.video_url);
      set.rallies.forEach(function (r) {
        var parts = r.tokens.slice();
        if (r.outcome) parts.push(outcomeToken(r.outcome));
        if (r.start != null) parts.push(tsToken(r.start, r.end));
        lines.push(parts.join(' '));
      });
      return lines.join('\n');
    }).join('\n---\n');
    // Match-level date header (optional) precedes the first set block.
    return a.date ? ('@date: ' + a.date + '\n' + body) : body;
  }

  function renderReview() {
    var pre = byId('review-log');
    if (!pre) return;
    var text = analysis ? buildLog(analysis) : '';
    pre.textContent = text || 'El registro aparecerá aquí cuando etiquetes rallies.';
  }

  function downloadLog() {
    if (!analysis) return;
    var blob = new Blob([buildLog(analysis) + '\n'], { type: 'text/plain;charset=utf-8' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = (session && session.filename) || 'partido.txt';
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(url); }, 0);
  }

  function parseOutcomeToken(token) {
    var m = RE_OUTCOME.exec(token);
    if (!m) return null;
    var result = m[1].toLowerCase();
    return { result: result, cause: (result === 'lost' || !m[2]) ? null : m[2].toLowerCase() };
  }

  function parseLogToSets(text) {
    var sets = [];
    var cur = { score: null, video_url: null, rallies: [] };
    String(text || '').replace(/\r/g, '').split('\n').forEach(function (raw) {
      var line = raw.trim();
      if (line === '---') { sets.push(cur); cur = { score: null, video_url: null, rallies: [] }; return; }
      if (!line) return;
      if (line.toLowerCase().indexOf('@youtube:') === 0) {
        var url = line.slice(9).trim();
        if (RE_YT.test(url)) cur.video_url = url;
        return;
      }
      var ms = /^@set:\s*(\d+)-(\d+)$/i.exec(line);
      if (ms) { cur.score = parseInt(ms[1], 10) + '-' + parseInt(ms[2], 10); return; }
      var plays = [], outcome = null, start = null, end = null;
      line.split(/\s+/).forEach(function (tok) {
        var mt = RE_TS.exec(tok);
        if (mt) { if (start == null) { start = parseFloat(mt[1]); end = (mt[2] != null ? parseFloat(mt[2]) : null); } return; }
        var oc = parseOutcomeToken(tok);
        if (oc) { if (!outcome) outcome = oc; return; }
        if (RE_PLAY.test(tok)) plays.push(tok.toUpperCase());
      });
      if (plays.length || outcome || start != null) {
        cur.rallies.push({ tokens: plays, outcome: outcome, start: start, end: end });
      }
    });
    sets.push(cur);
    return sets;
  }

  function handleImportFile(file) {
    if (!file) return;
    if (!session) {
      window.alert('Primero configura el equipo y el partido en Configuración.');
      window.location.hash = '#setup';
      return;
    }
    var reader = new FileReader();
    reader.onload = function () {
      ensureAnalysis();
      var text = String(reader.result || '');
      analysis.sets = parseLogToSets(text);
      if (!analysis.sets.length) analysis.sets = newAnalysis(session).sets;
      var dm = /^@date:\s*(\d{4}-\d{2}-\d{2})\s*$/im.exec(text);
      analysis.date = dm ? normalizeDate(dm[1]) : null;
      analysis.currentSet = 0;
      analysis.entry = emptyEntry();
      resetSelection();
      if (draft) draft.analysis = analysis;
      saveDraftNow();
      renderAnalysis();
      renderReview();
      window.location.hash = '#analysis';
    };
    reader.readAsText(file);
  }

  // ---------------------------------------------------------------
  // Analysis event wiring (delegation + keyboard accelerators)
  // ---------------------------------------------------------------
  function onAnalysisClick(e) {
    var t = e.target, el;
    if (!t || !t.closest) return;
    if ((el = t.closest('[data-player]'))) { selectPlayer(el.getAttribute('data-player')); return; }
    if ((el = t.closest('[data-action]'))) { selectAction(el.getAttribute('data-action')); return; }
    if ((el = t.closest('[data-grade]'))) { selectGrade(el.getAttribute('data-grade')); return; }
    if ((el = t.closest('[data-outcome]'))) { selectOutcome(el.getAttribute('data-outcome')); return; }
    if ((el = t.closest('[data-del-set]'))) { removeSet(parseInt(el.getAttribute('data-del-set'), 10)); return; }
    if ((el = t.closest('[data-set]'))) { switchSet(parseInt(el.getAttribute('data-set'), 10)); return; }
    if (t.closest('#analysis-add-set')) { addSet(); return; }
    if (t.closest('#analysis-mark')) { markToggle(); return; }
    if (t.closest('#analysis-undo')) { undoToken(); return; }
    if (t.closest('#analysis-send')) { sendRally(); return; }
    if ((el = t.closest('[data-edit]'))) { editRally(parseInt(el.getAttribute('data-edit'), 10)); return; }
    if ((el = t.closest('[data-del]'))) { deleteRally(parseInt(el.getAttribute('data-del'), 10)); return; }
  }

  function onAnalysisKey(e) {
    if (currentScreen() !== 'analysis' || !analysis) return;
    var tag = (e.target && e.target.tagName) ? e.target.tagName.toLowerCase() : '';
    if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    var k = e.key;
    if (k.length === 1 && k >= '0' && k <= '9') { playerDigit(k); e.preventDefault(); return; }
    if (k.length === 1 && 'SREADB'.indexOf(k.toUpperCase()) !== -1) { selectAction(k.toUpperCase()); e.preventDefault(); return; }
    if (k === '#' || k === '+' || k === '!' || k === '-') { selectGrade(k); e.preventDefault(); return; }
    if (k === 'Enter') { sendRally(); e.preventDefault(); return; }
    if (k === 'Backspace') { undoToken(); e.preventDefault(); return; }
  }

  // ---------------------------------------------------------------
  // Setup form <-> draft
  // ---------------------------------------------------------------
  function renderSets() {
    var host = byId('setup-sets');
    if (!host) return;
    host.innerHTML = '';
    draft.sets.forEach(function (s, i) {
      var no = i + 1;
      var row = document.createElement('div');
      row.className = 'lg-set';
      row.dataset.index = String(i);
      row.innerHTML =
        '<div class="lg-set__head">' +
          '<span class="lg-set__title">Set ' + no + '</span>' +
          '<button type="button" class="lg-set__remove" aria-label="Quitar set ' + no + '">✕</button>' +
        '</div>' +
        '<div class="lg-field-row">' +
          '<div class="lg-field">' +
            '<span class="lg-field__label">Marcador (opcional)</span>' +
            '<div class="lg-score">' +
              '<input type="number" class="lg-set__score-v" min="0" inputmode="numeric" placeholder="25" aria-label="Puntos a favor set ' + no + '">' +
              '<span class="lg-score__sep" aria-hidden="true">–</span>' +
              '<input type="number" class="lg-set__score-r" min="0" inputmode="numeric" placeholder="20" aria-label="Puntos del rival set ' + no + '">' +
            '</div>' +
          '</div>' +
          '<div class="lg-field lg-field--grow">' +
            '<label>Video YouTube (opcional)</label>' +
            '<input type="url" class="lg-set__video" placeholder="https://youtu.be/…" aria-label="Video set ' + no + '">' +
            '<p class="lg-error lg-set__video-error" role="alert"></p>' +
          '</div>' +
        '</div>';
      row.querySelector('.lg-set__score-v').value = s.v || '';
      row.querySelector('.lg-set__score-r').value = s.r || '';
      row.querySelector('.lg-set__video').value = s.video || '';
      host.appendChild(row);
    });
  }

  function updateManualVisibility(key) {
    var box = byId('setup-manual');
    if (box) box.hidden = (key !== MANUAL_KEY);
  }

  function draftToForm() {
    normalizeDraft(draft);
    var sel = byId('setup-dataset');
    if (sel) {
      sel.value = draft.datasetKey || '';
      if (sel.value !== (draft.datasetKey || '')) {   // option missing (stale key)
        sel.value = '';
        draft.datasetKey = '';
      }
    }
    byId('setup-opponent').value = draft.opponent || '';
    byId('setup-order').value = draft.order || '';
    byId('setup-date').value = draft.date || '';
    updateManualVisibility(draft.datasetKey);
    renderSets();
    refresh();
  }

  function formToDraft() {
    draft.datasetKey = byId('setup-dataset').value;
    draft.opponent = byId('setup-opponent').value;
    draft.order = byId('setup-order').value;
    draft.date = byId('setup-date').value;
    draft.sets = [];
    var rows = document.querySelectorAll('#setup-sets .lg-set');
    for (var i = 0; i < rows.length; i++) {
      draft.sets.push({
        v: rows[i].querySelector('.lg-set__score-v').value,
        r: rows[i].querySelector('.lg-set__score-r').value,
        video: rows[i].querySelector('.lg-set__video').value
      });
    }
    draft.updatedAt = Date.now();
  }

  // ---------------------------------------------------------------
  // Refresh (validate + reflect in UI + persist)
  // ---------------------------------------------------------------
  function renderChips(roster) {
    var host = byId('setup-roster-preview');
    if (!host) return;
    var nums = roster ? Object.keys(roster).sort(function (a, b) { return (+a) - (+b); }) : [];
    if (!nums.length) {
      host.innerHTML = '<span class="lg-chips__empty">Selecciona un equipo para cargar el roster.</span>';
      return;
    }
    host.innerHTML = nums.map(function (n) {
      var info = roster[n] || {};
      var label = info.name ? (n + ' · ' + info.name) : n;
      return '<span class="lg-chip" title="' + esc(info.position || '') + '">' + esc(label) + '</span>';
    }).join('');
  }

  function applySetErrors(setsResult) {
    var rows = document.querySelectorAll('#setup-sets .lg-set');
    for (var i = 0; i < rows.length; i++) {
      var el = rows[i].querySelector('.lg-set__video-error');
      var msg = setsResult.rows[i] ? setsResult.rows[i].videoError : '';
      el.textContent = msg || '';
      el.style.display = msg ? 'block' : 'none';
    }
  }

  function markSteps(v) {
    var states = [v.team.ok, v.team.ok && v.match.ok, v.sets.ok];
    var steps = document.querySelectorAll('#screen-setup .lg-step');
    var activeSet = false;
    for (var i = 0; i < steps.length; i++) {
      steps[i].classList.toggle('lg-step--done', !!states[i]);
      var isActive = !states[i] && !activeSet;
      steps[i].classList.toggle('lg-step--active', isActive);
      if (isActive) activeSet = true;
    }
  }

  function refresh() {
    formToDraft();
    var v = computeValidity(draft);

    renderChips(v.team.ok ? v.team.roster : null);
    setError('setup-step1-error', v.team.ok ? '' : v.team.error);

    if (v.team.ok && v.match.ok) {
      byId('setup-filename').textContent = v.match.filename;
      byId('setup-preview-title').textContent = v.match.title;
    } else {
      byId('setup-filename').textContent = '—';
      byId('setup-preview-title').textContent = '—';
    }
    setError('setup-step2-error', v.team.ok ? (v.match.ok ? '' : v.match.error) : '');

    applySetErrors(v.sets);
    setError('setup-step3-error', v.sets.ok ? '' : v.sets.errors.join(' '));

    markSteps(v);
    byId('setup-start').disabled = !v.ok;

    saveDraftSoon();
  }

  // ---------------------------------------------------------------
  // Home drafts list (resume support)
  // ---------------------------------------------------------------
  function emptyDraftRow() {
    return '<li class="lg-draft lg-draft--empty"><div class="lg-draft__info">' +
      '<span class="lg-draft__name">Sin borradores</span>' +
      '<span class="lg-draft__meta">Los registros guardados aparecerán aquí.</span>' +
      '</div></li>';
  }

  function draftRowHtml(d) {
    var t = resolveTeam(d);
    var teamName = t.ok ? t.team : 'Equipo';
    var opp = (d.opponent || '').trim();
    var name = teamName + ' vs ' + (opp || '¿Rival?');
    var nSets = (d.sets || []).length;
    var when = d.updatedAt ? new Date(d.updatedAt).toLocaleDateString('es-MX') : '';
    return '<li class="lg-draft" data-draft-id="' + esc(d.id) + '">' +
      '<div class="lg-draft__info">' +
        '<span class="lg-draft__name">' + esc(name) + '</span>' +
        '<span class="lg-draft__meta">' + nSets + ' set(s) · ' + esc(when) + '</span>' +
      '</div>' +
      '<div class="lg-draft__actions">' +
        '<button type="button" class="lg-draft__open" data-draft-id="' + esc(d.id) + '">Abrir</button>' +
        '<button type="button" class="lg-draft__del" data-draft-id="' + esc(d.id) + '" aria-label="Eliminar borrador">🗑</button>' +
      '</div>' +
    '</li>';
  }

  function renderDrafts() {
    var host = byId('lg-drafts');
    if (!host) return;
    dbGetAll().then(function (list) {
      if (!list || !list.length) { host.innerHTML = emptyDraftRow(); return; }
      list.sort(function (a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); });
      host.innerHTML = list.map(draftRowHtml).join('');
    }).catch(function () { host.innerHTML = emptyDraftRow(); });
  }

  function openDraft(id) {
    dbGetAll().then(function (list) {
      var found = (list || []).filter(function (d) { return d.id === id; })[0];
      if (!found) return;
      draft = normalizeDraft(found);
      session = draft.session || null;
      analysis = draft.analysis || null;
      draftToForm();
      window.location.hash = '#setup';
    }).catch(noop);
  }

  function deleteDraft(id) {
    dbDelete(id).then(function () {
      if (draft && draft.id === id) {
        draft = newDraft();
        session = null;
        analysis = null;
        draftToForm();
      }
      renderDrafts();
    }).catch(noop);
  }

  // ---------------------------------------------------------------
  // Event wiring
  // ---------------------------------------------------------------
  function onDatasetPicked() {
    var key = byId('setup-dataset').value;
    updateManualVisibility(key);
  }

  function wire() {
    var setupScreen = byId('screen-setup');
    if (setupScreen) {
      var onChange = function (e) {
        if (e.target && e.target.id === 'setup-dataset') onDatasetPicked();
        refresh();
      };
      setupScreen.addEventListener('input', onChange);
      setupScreen.addEventListener('change', onChange);
    }

    var addBtn = byId('setup-add-set');
    if (addBtn) {
      addBtn.addEventListener('click', function () {
        formToDraft();
        draft.sets.push(emptySet());
        renderSets();
        refresh();
      });
    }

    var setsHost = byId('setup-sets');
    if (setsHost) {
      setsHost.addEventListener('click', function (e) {
        var btn = e.target.closest ? e.target.closest('.lg-set__remove') : null;
        if (!btn) return;
        formToDraft();
        var idx = parseInt(btn.closest('.lg-set').dataset.index, 10);
        if (!isNaN(idx)) draft.sets.splice(idx, 1);
        renderSets();
        refresh();
      });
    }

    var resetBtn = byId('setup-reset');
    if (resetBtn) {
      resetBtn.addEventListener('click', function () {
        draft = newDraft();
        session = null;
        analysis = null;
        draftToForm();
        saveDraftNow();
      });
    }

    var startBtn = byId('setup-start');
    if (startBtn) {
      startBtn.addEventListener('click', function () {
        formToDraft();
        var v = computeValidity(draft);
        if (!v.ok) { refresh(); return; }
        session = buildSession(draft, v);
        window.RegistroSession = session;    // handoff for Analysis (Brief 3)
        draft.session = session;
        ensureAnalysis();
        syncAnalysisMeta(session);
        draft.analysis = analysis;
        saveDraftNow();
        renderDrafts();
        renderAnalysis();
        window.location.hash = '#analysis';
      });
    }

    var newBtn = byId('home-new');
    if (newBtn) {
      newBtn.addEventListener('click', function () {
        draft = newDraft();
        session = null;
        analysis = null;
        draftToForm();
        saveDraftNow();
        // the anchor's href="#setup" performs the navigation
      });
    }

    // Analysis screen: one delegated click handler + keyboard accelerators.
    var analysisScreen = byId('screen-analysis');
    if (analysisScreen) analysisScreen.addEventListener('click', onAnalysisClick);
    document.addEventListener('keydown', onAnalysisKey);

    // Review export + Import (Home / Review share one hidden file input).
    var exportBtn = byId('review-export');
    if (exportBtn) exportBtn.addEventListener('click', downloadLog);
    var importFile = byId('lg-import-file');
    function pickImport() { if (importFile) importFile.click(); }
    var homeImport = byId('home-import');
    if (homeImport) homeImport.addEventListener('click', pickImport);
    var reviewImport = byId('review-import');
    if (reviewImport) reviewImport.addEventListener('click', pickImport);
    if (importFile) {
      importFile.addEventListener('change', function () {
        var f = importFile.files && importFile.files[0];
        importFile.value = '';
        handleImportFile(f);
      });
    }

    var drafts = byId('lg-drafts');
    if (drafts) {
      drafts.addEventListener('click', function (e) {
        var open = e.target.closest ? e.target.closest('.lg-draft__open') : null;
        var del = e.target.closest ? e.target.closest('.lg-draft__del') : null;
        if (open) { openDraft(open.dataset.draftId); }
        else if (del) { deleteDraft(del.dataset.draftId); }
      });
    }
  }

  // ---------------------------------------------------------------
  // Init
  // ---------------------------------------------------------------
  function init() {
    render();
    if (navigator.storage && navigator.storage.persist) {
      navigator.storage.persist().catch(noop);
    }
    wire();
    loadDatasets().catch(noop).then(function () {
      return dbGetAll().catch(function () { return []; });
    }).then(function (list) {
      if (list && list.length) {
        list.sort(function (a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); });
        draft = normalizeDraft(list[0]);
        session = draft.session || null;
        analysis = draft.analysis || null;
      } else {
        draft = newDraft();
      }
      draftToForm();
      renderDrafts();
    });
  }

  window.addEventListener('hashchange', render);
  window.addEventListener('DOMContentLoaded', init);
})();
