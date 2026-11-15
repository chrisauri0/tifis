import { start } from './engine.js';
import { t, setLang, getLang, detectLang } from './i18n.js';
import { parseCoords, formatRA, formatDec } from './coords.js';
import { OBJECTS, TOURS, MISSIONS, BANDS, PSEUDO, CATEGORIES, findObject, findMission, findBand, featuresReady } from './catalog.js';

// Okabe-Ito, short to long wavelength; the engine uses the same colors.
const COLORS = ['#0072B2', '#56B4E9', '#009E73', '#F0E442', '#E69F00', '#D55E00'];
const LEVELS = ['explore', 'compare', 'analyze'];
const MODES = ['epoch', 'diff', 'sum'];
// The three doors of the welcome screen and the level each one opens.
const DOORS = { learn: 'explore', discover: 'compare', analyze: 'analyze' };
// Fields for the challenge: fast movers. Only the built-in targets are
// modeled by the simulation, so the others need real data.
// Sesame mirrors that answer with CORS headers; the main CDS URL redirects
// without them, so the browser cannot follow it.
const SESAME = [
  'https://vizier.cfa.harvard.edu/viz-bin/nph-sesame/-oI/SNV?',
  'https://vizier.idia.ac.za/viz-bin/nph-sesame/-oI/SNV?',
];
const PIX = 6.15;
const CHANNEL_RANGES = [[0.75, 1.1], [1.1, 1.6], [1.6, 2.4], [2.4, 3.8], [3.8, 4.4], [4.4, 5.0]];
const SVGNS = 'http://www.w3.org/2000/svg';

const $ = (id) => document.getElementById(id);
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
// SVG drawn from JS takes its colors from the CSS theme.
const THEME = { accent: cssVar('--accent'), text: cssVar('--text'), lineStrong: cssVar('--line-strong') };
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

const state = {
  ready: false,
  targets: [],
  field: null,
  request: null,
  loaded: [],
  done: 0,
  total: 0,
  view: { band: 2, mode: 'epoch', visit: 0, ref: -1, flags: false, catalog: false, tint: false },
  level: 'explore',
  fov: 6,
  frame: null,
  selection: null,
  // What the engine made of the selection's spectrum (spherex/espectro.py).
  analysis: null,
  hover: null,
  playing: false,
  speed: 1,
  step: 'season',
  embed: false,
  specLog: true,
  // Real SPHEREx images through the proxy; false falls back to the simulation.
  real: false,
  // Wavelength of each loaded frame, [channel][visit], for season stepping.
  lambda: [],
  status: {},
  // Welcome door shown, guided tour { id, step, done, quiz } and mission
  // { mission, obj, done, answer, solved, revealed }.
  door: 'learn',
  tour: null,
  challenge: null,
  // Visits and channels shown since the field was opened, for the tasks.
  seen: { visits: new Set(), bands: new Set() },
  score: { ok: 0, n: 0 },
};

// Bilingual text from catalog.js.
const tr = (o) => (o ? o[getLang()] ?? o.es ?? '' : '');

const engine = () => globalThis.skyEngine;

// ---------- Engine events ----------

globalThis.skyUI = {
  event(kind, json) {
    const data = JSON.parse(json);
    handlers[kind]?.(data);
  },
};

const handlers = {
  async ready({ targets }) {
    state.real = await archiveAvailable;
    state.ready = true;
    state.targets = targets;
    renderBanner();
    engine().resize(Math.floor($('viewer').clientWidth), Math.floor($('viewer').clientHeight));
    renderWelcome();
    renderDatalist();
    startFromURL();
  },
  field(f) {
    state.field = f;
    state.loaded = f.channels.map((c) => c.available.map(() => false));
    state.lambda = f.channels.map((c) => c.available.map(() => 0));
    state.done = 0;
    state.total = f.channels.length * f.visits.length;
    state.view.visit = Math.min(state.view.visit, f.visits.length - 1);
    if (state.view.ref >= f.visits.length) state.view.ref = -1;
    state.selection = null;
    state.analysis = null;
    state.frame = null;
    resetSeen();
    showWelcome(false);
    renderBanner();
    renderTitle();
    renderChannels();
    renderFovCost();
    layoutTimeline();
    renderSelection();
    renderTour();
    renderChallenge();
    renderNow();
    snapVisit();
    sendView();
    if (state.embed) $('embed-open').href = shareURL().replace(/[?&]embed=1/, '');
    if (state.autoplay && !reduceMotion) setPlaying(true);
    state.autoplay = false;
  },
  loaded({ items, done, total }) {
    // Progress of the previous field can still arrive after a new open.
    if (!state.field) return;
    for (const it of items) {
      state.loaded[it.c][it.v] = true;
      state.lambda[it.c][it.v] = it.l;
      // A real cutout that could not be read turns into a gap.
      state.field.channels[it.c].available[it.v] = it.a;
    }
    state.done = done;
    state.total = total;
    schedule('timeline', renderTimeline);
    schedule('channels', renderChannelCounts);
    schedule('status', renderStatus);
  },
  frame(fr) {
    state.frame = fr;
    if (fr.loaded && state.field) {
      state.seen.visits.add(fr.visit);
      state.seen.bands.add(fr.band);
    }
    renderFrame();
    renderTimeline();
    updateGuides();
    schedule('now', renderNow);
  },
  hover(h) {
    state.hover = h;
    renderHover();
  },
  select(sel) {
    // A click somewhere else is a new source: its old interpretation goes.
    const prev = state.selection;
    if (!sel || !prev || angularSep(prev, sel) > 3) state.analysis = null;
    state.selection = sel;
    renderSelection();
    renderTimeline();
    if (sel && state.challenge) checkChallenge(sel);
    updateGuides();
    renderNow();
  },
  analysis({ n, result }) {
    if (!state.selection) return;
    state.analysis = { n, ...result };
    renderSpectrum();
    renderInterp();
    renderBands();
  },
  status(st) {
    state.status[st.stage] = st;
    if (st.stage === 'visits' && st.state === 'loading') {
      state.field = null;
      state.statusSince = performance.now();
      $('timeline-svg').replaceChildren();
    }
    renderArchiveStatus();
  },
};

const scheduled = new Set();
function schedule(key, fn) {
  if (scheduled.has(key)) return;
  scheduled.add(key);
  requestAnimationFrame(() => {
    scheduled.delete(key);
    fn();
  });
}

// ---------- State changes ----------

function effectiveView() {
  const v = { ...state.view };
  // A guided tour sets the view itself, whatever the level.
  if (state.level === 'explore' && !state.tour) {
    v.mode = 'epoch';
    v.catalog = false;
  }
  if (state.level !== 'analyze') v.flags = false;
  return v;
}

function sendView() {
  if (!state.field) return;
  engine()?.view(JSON.stringify(effectiveView()));
  renderControls();
  updateGuides();
  schedule('url', writeURL);
}

function setVisit(v) {
  if (!state.field) return;
  const n = state.field.visits.length;
  state.view.visit = ((v % n) + n) % n;
  sendView();
}

function setBand(b) {
  state.view.band = Math.max(0, Math.min(5, b));
  renderFovCost();
  snapVisit();
  sendView();
  renderChannels();
}

// Not every detector has every visit (real exposures cover two of the six);
// move to the closest visit in time that has an image in this channel.
function snapVisit() {
  const f = state.field;
  if (f && !f.channels[state.view.band].available[state.view.visit]) {
    const avail = f.channels[state.view.band].available;
    for (let d = 1; d < avail.length; d++) {
      const i = [state.view.visit - d, state.view.visit + d].find((j) => avail[j]);
      if (i !== undefined) {
        state.view.visit = i;
        break;
      }
    }
  }
}

function setMode(m) {
  if (!MODES.includes(m)) return;
  state.view.mode = m;
  if (m !== 'epoch' && state.level === 'explore' && !state.tour) setLevel('compare');
  sendView();
}

function setLevel(l) {
  if (!LEVELS.includes(l)) return;
  state.level = l;
  document.body.dataset.level = l;
  for (const b of document.querySelectorAll('.levels button')) b.setAttribute('aria-checked', b.dataset.level === l);
  sendView();
  renderSelection();
  renderTimeline();
  renderFrame();
}

function setPlaying(p) {
  state.playing = p && !!state.field;
  const btn = $('play');
  btn.setAttribute('aria-pressed', state.playing);
  btn.setAttribute('aria-label', t(state.playing ? 'play.pause' : 'play.play'));
  if (state.playing) {
    lastTick = 0;
    acc = 0;
    requestAnimationFrame(tick);
  }
  schedule('now', renderNow);
}

// nextVisit steps through visits that have an image in the current channel.
// By season, it jumps to the visit of the next season with the closest
// wavelength, so consecutive frames share the same color. Real frames only
// reveal their wavelength once loaded; until then the sub-band estimate is used.
function nextVisit(dir, step = state.step) {
  const f = state.field;
  const band = state.view.band;
  const n = f.visits.length;
  const avail = (i) => f.channels[band].available[i];
  const cur = f.visits[state.view.visit];
  if (step === 'visit') {
    for (let k = 1; k <= n; k++) {
      const i = (((state.view.visit + dir * k) % n) + n) % n;
      if (avail(i)) return i;
    }
    return state.view.visit;
  }
  const seasons = f.visits[n - 1].season + 1;
  const ch = f.channels[band];
  const color = (i) => {
    const l = state.lambda[band]?.[i];
    if (l) return ((l - ch.lo) / (ch.hi - ch.lo)) * 17;
    return f.visits[i].sub >= 0 ? f.visits[i].sub : null;
  };
  const here = color(state.view.visit);
  for (let k = 1; k <= seasons; k++) {
    const s = (((cur.season + dir * k) % seasons) + seasons) % seasons;
    let best = -1, bestD = Infinity;
    f.visits.forEach((v, i) => {
      if (v.season !== s || !avail(i)) return;
      const c = color(i);
      const dc = here == null || c == null ? 500 : Math.abs(c - here);
      const d = dc * 1000 + Math.abs(v.mjd - cur.mjd) / 1000;
      if (d < bestD) { best = i; bestD = d; }
    });
    if (best >= 0) return best;
  }
  return state.view.visit;
}

let lastTick = 0;
let acc = 0;
function tick(ts) {
  if (!state.playing) return;
  const dt = lastTick ? (ts - lastTick) / 1000 : 0;
  lastTick = ts;
  acc += dt;
  const interval = (state.step === 'season' ? 0.9 : 0.25) / state.speed;
  if (acc >= interval) {
    const next = nextVisit(1);
    // Wait for the frame instead of skipping it: the timeline shows what is loaded.
    if (state.loaded[state.view.band][next]) {
      acc = 0;
      setVisit(next);
    }
  }
  requestAnimationFrame(tick);
}

// ---------- Opening fields ----------

function open(req, opts = {}) {
  state.request = { ra: req.ra, dec: req.dec, fov: state.fov, name: req.name || '', real: state.real };
  state.autoplay = opts.autoplay ?? true;
  if (opts.view) Object.assign(state.view, opts.view);
  setPlaying(false);
  if (!state.ready) return;
  showWelcome(false);
  state.field = null;
  state.status = {};
  renderArchiveStatus();
  renderTitle();
  // The engine starts downloading right away, nearest the playhead in the
  // current channel, so it needs the view first.
  engine().view(JSON.stringify(effectiveView()));
  engine().open(JSON.stringify(state.request));
}

function openTarget(tg, opts = {}) {
  const view = { band: tg.band, visit: 0, ref: -1 };
  if (state.level !== 'explore') view.mode = tg.mode;
  open({ ra: tg.ra, dec: tg.dec, name: tg.name }, { ...opts, view: { ...view, ...opts.view } });
}

const normalize = (s) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[’'`]/g, '').replace(/\s+/g, ' ').trim();

function findTarget(q) {
  const n = normalize(q);
  return state.targets.find((tg) => [tg.id, tg.name, ...tg.aliases].some((a) => normalize(a) === n));
}

function findCatalogObject(q) {
  const n = normalize(q);
  return OBJECTS.find((o) => !o.target && [o.id, o.name, o.query].some((a) => a && normalize(a) === n));
}

async function search(q) {
  q = q.trim();
  if (!q) return;
  endGuides();
  const c = parseCoords(q);
  if (c) return open({ ...c, name: '' });
  const tg = findTarget(q);
  if (tg) return openTarget(tg);
  const obj = findCatalogObject(q);
  if (obj) return openObject(obj);

  const pos = await locate(q);
  if (pos) open({ ...pos, name: q });
}

// Position today of a named object, from Sesame; null (after a message) if
// it cannot be found.
async function locate(q) {
  toast(t('search.resolving', { q }));
  const text = await resolveName(q);
  if (text == null) {
    toast(t('search.offline'));
    return null;
  }
  const m = /%J\s+([\d.]+)\s+([+-][\d.]+)/.exec(text);
  if (!m) {
    toast(t('search.notfound', { q }));
    return null;
  }
  let ra = parseFloat(m[1]);
  let dec = parseFloat(m[2]);
  // Sesame gives J2000 positions at epoch J2000; carry fast movers to today.
  const pm = /%P\s+([+-]?[\d.]+)\s+([+-]?[\d.]+)/.exec(text);
  if (pm) {
    const yr = (Date.now() - Date.UTC(2000, 0, 1, 12)) / 3.15576e10;
    dec += (parseFloat(pm[2]) * yr) / 3.6e6;
    ra += (parseFloat(pm[1]) * yr) / 3.6e6 / Math.cos((dec * Math.PI) / 180);
  }
  hideToast();
  return { ra: ((ra % 360) + 360) % 360, dec };
}

function setFov(fov) {
  state.fov = clamp(fov, 4, 12);
  $('fov').value = state.fov;
  $('fov-value').textContent = state.fov + t('unit.arcmin');
  renderFovCost();
}

const objectName = (o) => o.name || state.targets.find((tg) => tg.id === o.target)?.name || o.id;

// Open a catalog object with its suggested channel, mode and field of view.
async function openObject(o, opts = {}) {
  if (!opts.keepGuides) endGuides();
  if (o.fov) setFov(o.fov);
  const view = { band: o.band, visit: 0, ref: -1, ...(state.level !== 'explore' ? { mode: o.mode } : {}), ...opts.view };
  const go = { autoplay: opts.autoplay ?? true, view };
  if (o.target) {
    const tg = state.targets.find((x) => x.id === o.target);
    if (tg) return openTarget(tg, go);
  }
  const pos = await locate(o.query || o.name);
  if (!pos) return;
  open({ ...pos, name: objectName(o) }, go);
  // The simulation only models the built-in targets.
  if (!state.real) toast(t('sim.generic'));
}

async function resolveName(q) {
  for (const base of SESAME) {
    try {
      const res = await fetch(base + encodeURIComponent(q), { signal: AbortSignal.timeout(5000) });
      if (res.ok) return await res.text();
    } catch {
      // Try the next mirror.
    }
  }
  return null;
}

// ---------- Archive ----------

// The proxy that relays IRSA serves the app, so /api answering means real data.
async function detectArchive() {
  if (new URLSearchParams(location.search).get('data') === 'sim') return false;
  try {
    const res = await fetch('/api/health', { signal: AbortSignal.timeout(2000) });
    // The server answers ok:false when started with --sim.
    return res.ok && (await res.json()).ok === true;
  } catch {
    return false;
  }
}

function renderBanner() {
  const real = state.real;
  $('banner').classList.toggle('real', real);
  $('banner-title').textContent = t(real ? 'real.title' : 'sim.title');
  $('banner-body').textContent = t(real ? 'real.body' : 'sim.body');
}

let archiveTimer;
let gaiaTimer;
function renderArchiveStatus() {
  const v = state.status.visits;
  const box = $('archive-status');
  clearInterval(archiveTimer);
  box.hidden = !v || v.state === 'done' || !state.real;
  if (!box.hidden) {
    const loading = v.state === 'loading';
    $('archive-spinner').hidden = !loading;
    $('archive-sim').hidden = loading;
    $('archive-text').textContent = t(`archive.${v.state}`);
    const detail = () => {
      $('archive-detail').textContent = loading
        ? t('archive.slow', { s: Math.round((performance.now() - state.statusSince) / 1000) })
        : v.error || '';
    };
    detail();
    if (loading) archiveTimer = setInterval(detail, 1000);
  }
  const c = state.status.catalog;
  clearInterval(gaiaTimer);
  const text = !state.real || !c ? ''
    : c.state === 'loading' ? t('catalog.loading')
    : c.state === 'error' ? t('catalog.error', { e: c.error })
    : c.missing?.length ? t('catalog.partial', { n: c.count, c: c.missing.join(', ') })
    : t('catalog.done', { n: c.count });
  $('catalog-status').textContent = text;
  // Gaia comes from 230 MB bulk files the first time a region is seen;
  // show how far the download has got.
  if (state.real && c?.state === 'loading') {
    const poll = async () => {
      try {
        const r = state.request;
        const files = await (await fetch(`/api/gaia/progress?ra=${r.ra}&dec=${r.dec}`)).json();
        if (state.status.catalog?.state !== 'loading') return;
        $('catalog-status').textContent = files.length
          ? t('catalog.gaia', { p: Math.round(100 * Math.max(...files.map((f) => f.fraction))), mb: Math.round(files[0].mb) })
          : text;
      } catch {
        // The plain message stays.
      }
    };
    poll();
    gaiaTimer = setInterval(poll, 2000);
  }
}

// ---------- URL ----------

function startFromURL() {
  const p = new URLSearchParams(location.search);
  state.embed = p.get('embed') === '1';
  document.body.classList.toggle('embed', state.embed);
  if (p.has('level')) setLevel(p.get('level'));
  if (p.has('fov')) state.fov = clamp(parseFloat(p.get('fov')) || 6, 4, 12);
  $('fov').value = state.fov;
  $('fov-value').textContent = state.fov + t('unit.arcmin');
  const view = {};
  if (p.has('band')) view.band = clamp(parseInt(p.get('band'), 10) - 1 || 0, 0, 5);
  if (MODES.includes(p.get('mode'))) view.mode = p.get('mode');
  if (p.has('t')) view.visit = Math.max(0, parseInt(p.get('t'), 10) || 0);
  if (p.has('ref')) view.ref = parseInt(p.get('ref'), 10);
  view.flags = p.get('flags') === '1';
  view.catalog = p.get('catalog') === '1';
  view.tint = p.get('tint') === '1';
  $('tint').checked = view.tint;
  $('flags').checked = view.flags;
  $('catalog').checked = view.catalog;
  const autoplay = p.get('play') !== '0';

  const ra = parseFloat(p.get('ra'));
  const dec = parseFloat(p.get('dec'));
  setDoor(p.has('door') ? p.get('door') : doorFor(state.level));
  if (p.has('door')) setLevel(DOORS[state.door]);
  const tour = TOURS.find((x) => x.id === p.get('tour'));
  if (tour) {
    startTour(tour.id, clamp((parseInt(p.get('step'), 10) || 1) - 1, 0, tour.steps.length - 1));
  } else if (Number.isFinite(ra) && Number.isFinite(dec)) {
    open({ ra, dec, name: p.get('name') || '' }, { view, autoplay });
  } else if (p.has('target') && findTarget(p.get('target'))) {
    openTarget(findTarget(p.get('target')), { view, autoplay });
  } else if (state.embed) {
    openTarget(state.targets[0], { view, autoplay });
  } else {
    showWelcome(true);
    renderTitle();
  }
}

function shareURL({ embed = false } = {}) {
  const r = state.request;
  const v = state.view;
  const p = new URLSearchParams();
  if (r) {
    p.set('ra', r.ra.toFixed(5));
    p.set('dec', r.dec.toFixed(5));
    p.set('fov', String(state.fov));
    if (state.field?.name) p.set('name', state.field.name);
    p.set('band', String(v.band + 1));
    p.set('mode', v.mode);
    p.set('t', String(v.visit));
    if (v.ref >= 0) p.set('ref', String(v.ref));
    if (v.flags) p.set('flags', '1');
    if (v.catalog) p.set('catalog', '1');
    if (v.tint) p.set('tint', '1');
  }
  if (state.level !== 'explore') p.set('level', state.level);
  if (state.tour && state.tour.step < tourOf().steps.length) {
    p.set('tour', state.tour.id);
    p.set('step', String(state.tour.step + 1));
  }
  if (getLang() !== detectLang()) p.set('lang', getLang());
  if (new URLSearchParams(location.search).get('data') === 'sim') p.set('data', 'sim');
  if (embed) p.set('embed', '1');
  return `${location.origin}${location.pathname}?${p}`;
}

function writeURL() {
  if (state.embed) return;
  history.replaceState(null, '', shareURL());
}

// ---------- Rendering ----------

function renderCards() {
  const ul = $('cards');
  ul.replaceChildren();
  for (const tg of state.targets) {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.className = 'card';
    b.style.setProperty('--card', COLORS[tg.band]);
    b.innerHTML = `<span class="tag"></span><strong></strong><span class="hook"></span><span class="look"></span>`;
    b.querySelector('.tag').textContent = t(`target.${tg.id}.tag`);
    b.querySelector('strong').textContent = tg.name;
    b.querySelector('.hook').textContent = t(`target.${tg.id}.hook`);
    b.querySelector('.look').textContent = t(`target.${tg.id}.look`);
    b.addEventListener('click', () => {
      endGuides();
      setLevel(DOORS[state.door]);
      openTarget(tg);
    });
    li.append(b);
    ul.append(li);
  }
}

function renderDatalist() {
  const dl = $('target-names');
  const names = [...state.targets.map((tg) => tg.name), ...OBJECTS.filter((o) => !o.target).map((o) => o.name)];
  dl.replaceChildren(...names.map((value) => Object.assign(document.createElement('option'), { value })));
}

// ---------- Welcome: doors, tours, categories, objects ----------

function renderWelcome() {
  renderCards();
  renderTours();
  renderMissions();
  renderCategories();
  renderObjectsTable();
  setDoor(state.door);
}

const doorFor = (level) => Object.keys(DOORS).find((d) => DOORS[d] === level) || 'learn';

function setDoor(d) {
  if (!DOORS[d]) return;
  state.door = d;
  for (const b of document.querySelectorAll('.door')) {
    const on = b.dataset.door === d;
    b.setAttribute('aria-selected', on);
    b.tabIndex = on ? 0 : -1;
  }
  for (const k of Object.keys(DOORS)) $(`door-${k}`).hidden = k !== d;
}

function renderTours() {
  $('tours').replaceChildren(...TOURS.map((tour) => {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.className = 'tour-card';
    b.innerHTML = '<strong></strong><span class="hook"></span><ol></ol><span class="go"></span>';
    b.querySelector('strong').textContent = tr(tour.title);
    b.querySelector('.hook').textContent = tr(tour.summary);
    b.querySelector('ol').replaceChildren(...tour.steps.map((st) => Object.assign(document.createElement('li'), { textContent: tr(st.title) })));
    b.querySelector('.go').textContent = t('learn.start', { n: tour.steps.length });
    b.addEventListener('click', () => startTour(tour.id));
    li.append(b);
    return li;
  }));
}

function objectCard(o) {
  const li = document.createElement('li');
  const b = document.createElement('button');
  b.className = 'object';
  b.style.setProperty('--card', COLORS[o.band]);
  b.innerHTML = '<strong></strong><span class="hook"></span><span class="meta"></span>';
  b.querySelector('strong').textContent = objectName(o);
  b.querySelector('.hook').textContent = tr(o.desc);
  b.querySelector('.meta').textContent = `${t('channel.n', { n: o.band + 1 })} · ${t(`mode.${o.mode}`)}${o.target ? '' : ' · Sesame'}`;
  b.addEventListener('click', () => {
    setLevel(DOORS[state.door]);
    openObject(o);
  });
  li.append(b);
  return li;
}

function renderCategories() {
  $('categories').replaceChildren(...CATEGORIES.map((c) => {
    const sec = document.createElement('section');
    sec.className = 'category';
    sec.innerHTML = '<h3><span aria-hidden="true"></span> <span></span></h3><p class="hint"></p><ul class="objects-grid"></ul>';
    sec.querySelector('h3 span[aria-hidden]').textContent = c.icon;
    sec.querySelector('h3 span:last-child').textContent = tr(c.name);
    sec.querySelector('.hint').textContent = tr(c.hint);
    sec.querySelector('ul').replaceChildren(...OBJECTS.filter((o) => o.cat.includes(c.id)).map(objectCard));
    return sec;
  }));
}

function renderObjectsTable() {
  $('objects-table').replaceChildren(...OBJECTS.map((o) => {
    const tr_ = document.createElement('tr');
    const cells = [objectName(o), o.cat.map((id) => tr(CATEGORIES.find((c) => c.id === id)?.name)).join(', '),
      `${t('channel.n', { n: o.band + 1 })} · ${fmtRange(...CHANNEL_RANGES[o.band])}`, t(`mode.${o.mode}`), `${o.fov}′`];
    cells.forEach((text, i) => {
      const td = document.createElement('td');
      if (i === 0) {
        const b = Object.assign(document.createElement('button'), { className: 'link', textContent: text });
        b.addEventListener('click', () => {
          setLevel('analyze');
          openObject(o);
        });
        td.append(b);
      } else td.textContent = text;
      tr_.append(td);
    });
    return tr_;
  }));
}

// The player, the timeline and the side panel only make sense once a field
// is open, so the start screen hides them (body.home in style.css).
function showWelcome(show) {
  $('welcome').hidden = !show;
  document.body.classList.toggle('home', show);
}

function goWelcome(door) {
  setPlaying(false);
  if (door) setDoor(door);
  showWelcome(true);
}

// ---------- Guides: tasks shared by tours and missions ----------
//
// A step or a mission lists tasks ({ do: 'play' | 'band' | 'select' |
// 'catalog' }). Each one checks itself off as the user does it, stays done
// for the rest of the step, and the first pending one gets a pulsing outline
// on the control to use (.coach).

// A click this close to the field center (arcsec, ~7 px) counts as clicking
// the object of the step, which every field is centered on.
const CENTER_TOL = 45;

function resetSeen() {
  state.seen = { visits: new Set(), bands: new Set() };
}

function nearCenter(sel) {
  const r = state.request;
  if (!sel || !r) return false;
  const cos = Math.cos((r.dec * Math.PI) / 180);
  let dra = sel.ra - r.ra;
  if (dra > 180) dra -= 360;
  if (dra < -180) dra += 360;
  return Math.hypot(dra * cos, sel.dec - r.dec) * 3600 <= CENTER_TOL;
}

function taskDone(task) {
  switch (task.do) {
    case 'play': {
      // Playing one visit per season shows as many frames as there are seasons.
      const seasons = new Set(state.field?.visits.map((v) => v.season)).size;
      return state.seen.visits.size >= Math.max(2, Math.min(3, seasons));
    }
    case 'band': return state.seen.bands.has(task.band);
    case 'select': return !!state.selection && (task.anywhere || nearCenter(state.selection));
    case 'catalog': return !!state.view.catalog;
    default: return false;
  }
}

function taskLabel(task) {
  if (task.do === 'band') return t('task.band', { n: task.band + 1, range: fmtRange(...CHANNEL_RANGES[task.band]) });
  if (task.do === 'select') return t(task.anywhere ? 'task.select.anywhere' : 'task.select');
  return t(`task.${task.do}`);
}

function setCatalog(on) {
  state.view.catalog = on;
  $('catalog').checked = on;
  sendView();
}

// One-click shortcuts next to a pending task (tours only: missions leave the
// doing to the user).
function taskHelper(task) {
  const mk = (label, run) => {
    const b = Object.assign(document.createElement('button'), { className: 'helper', textContent: label, type: 'button' });
    b.addEventListener('click', run);
    return b;
  };
  if (task.do === 'play') return mk(t('helper.play'), () => setPlaying(true));
  if (task.do === 'band') return mk(t('helper.band', { n: task.band + 1 }), () => setBand(task.band));
  if (task.do === 'catalog') return mk(t('helper.catalog'), () => setCatalog(true));
  return null;
}

function coachTarget(task, helper) {
  if (!task) return null;
  if (task.do === 'play') return $('play');
  if (task.do === 'band') return $('channels').children[task.band] ?? null;
  if (task.do === 'select') return $('viewer');
  if (task.do === 'catalog') return helper ?? $('catalog').closest('label');
  return null;
}

function coach(el) {
  for (const e of document.querySelectorAll('.coach')) if (e !== el) e.classList.remove('coach');
  el?.classList.add('coach');
}

// Draws the checklist; returns the coach target for the first pending task.
function renderTasks(ul, tasks, done, { helpers = false } = {}) {
  let target = null;
  let first = true;
  ul.replaceChildren(...tasks.map((task, i) => {
    const li = document.createElement('li');
    li.className = done[i] ? 'done' : first ? 'current' : '';
    const mark = Object.assign(document.createElement('span'), { className: 'check', textContent: done[i] ? '✓' : String(i + 1) });
    mark.setAttribute('aria-hidden', 'true');
    const text = Object.assign(document.createElement('span'), { className: 'label', textContent: taskLabel(task) });
    li.append(mark, text);
    if (done[i]) li.append(Object.assign(document.createElement('span'), { className: 'sr-only', textContent: ' ✓' }));
    if (!done[i]) {
      const h = helpers ? taskHelper(task) : null;
      if (h) li.append(h);
      if (task.do === 'select' && !task.anywhere && state.selection && !nearCenter(state.selection)) {
        li.append(Object.assign(document.createElement('span'), { className: 'note', textContent: t('task.select.off') }));
      }
      if (first) target = coachTarget(task, h);
      first = false;
    }
    return li;
  }));
  return target;
}

// The active guide: the current tour step or the mission.
function activeGuide() {
  const tour = tourOf();
  if (tour && state.tour.step < tour.steps.length) return { kind: 'tour', tasks: tour.steps[state.tour.step].tasks ?? [], done: state.tour.done };
  const m = missionOf();
  if (m && !state.challenge.revealed) return { kind: 'mission', tasks: m.tasks, done: state.challenge.done };
  return null;
}

// Called on every frame, selection and view change: checks tasks off and
// redraws the guide only when something it shows changed.
let guideSig = '';
function updateGuides() {
  const g = activeGuide();
  let checked = false;
  if (g) {
    g.tasks.forEach((task, i) => {
      if (!g.done[i] && taskDone(task)) checked = g.done[i] = true;
    });
  }
  const sel = state.selection;
  const sig = JSON.stringify([g?.kind, g?.done, !!sel, sel && nearCenter(sel), sel?.measurements?.length, state.view.band, state.view.catalog, getLang()]);
  if (sig === guideSig) return;
  guideSig = sig;
  if (state.tour) renderTour();
  if (state.challenge) renderChallenge();
  // Doing a task often scrolls the side panel (a channel button far down);
  // bring the guide back so the next task, or the question, is in view.
  if (checked) $(state.tour ? 'tour' : 'challenge').scrollIntoView({ block: 'start', behavior: reduceMotion ? 'auto' : 'smooth' });
}

// Multiple-choice question; `chosen` is the picked index (or null).
function renderQuiz(box, { title, q, options, answer, explain, chosen, onPick, after }) {
  box.hidden = false;
  const nodes = [];
  if (title) nodes.push(Object.assign(document.createElement('p'), { className: 'eyebrow', textContent: title }));
  nodes.push(Object.assign(document.createElement('p'), { className: 'quiz-q', textContent: q }));
  const list = document.createElement('div');
  list.className = 'quiz-options';
  options.forEach((label, i) => {
    const b = Object.assign(document.createElement('button'), { type: 'button', textContent: label });
    if (chosen != null) {
      b.disabled = true;
      if (i === answer) b.classList.add('right');
      else if (i === chosen) b.classList.add('wrong');
    } else b.addEventListener('click', () => onPick(i));
    list.append(b);
  });
  nodes.push(list);
  if (chosen != null && explain) {
    const p = document.createElement('p');
    p.className = `result ${chosen === answer ? 'good' : 'bad'}`;
    p.textContent = explain;
    nodes.push(p);
  }
  if (chosen != null && after) nodes.push(after);
  box.replaceChildren(...nodes);
}

// ---------- Guided tours ----------

const tourOf = () => TOURS.find((x) => x.id === state.tour?.id);

function startTour(id, step = 0) {
  state.challenge = null;
  renderChallenge();
  state.tour = { id, step, done: [], quiz: null };
  setLevel('explore');
  showStep();
}

function showStep() {
  const tour = tourOf();
  const i = state.tour.step;
  state.tour.done = (tour.steps[i]?.tasks ?? []).map(() => false);
  guideSig = '';
  renderTour();
  if (i >= tour.steps.length) return writeURL();
  const st = tour.steps[i];
  const view = { mode: 'epoch', catalog: false, ...st.view, visit: 0, ref: -1 };
  $('catalog').checked = view.catalog;
  openObject(findObject(st.object), { keepGuides: true, autoplay: false, view });
}

function renderTour() {
  const tour = tourOf();
  const box = $('tour');
  box.hidden = !tour;
  if (!tour) return;
  const i = state.tour.step;
  const n = tour.steps.length;
  const done = i >= n;
  const st = tour.steps[Math.min(i, n - 1)];
  const allDone = !done && state.tour.done.every(Boolean);
  $('tour-name').textContent = tr(tour.title);
  $('tour-progress').replaceChildren(...tour.steps.map((_, k) => Object.assign(document.createElement('li'), {
    className: k < i ? 'done' : k === i ? 'current' : '',
  })));
  $('tour-title').textContent = done ? t('tour.done') : tr(st.title);
  $('tour-text').textContent = done ? tr(tour.summary) : tr(st.text);
  $('tour-count').textContent = done ? '' : t('tour.count', { i: i + 1, n });
  $('tour-prev').disabled = i === 0;

  const tasks = done ? [] : st.tasks ?? [];
  $('tour-tasks-title').hidden = !tasks.length;
  const target = renderTasks($('tour-tasks'), tasks, state.tour.done, { helpers: true });
  const tk = $('tour-takeaway');
  tk.hidden = !allDone || !st.takeaway;
  if (!tk.hidden) {
    const b = Object.assign(document.createElement('b'), { textContent: `${t('tour.takeaway')} ` });
    tk.replaceChildren(b, document.createTextNode(tr(st.takeaway)));
  }

  const next = $('tour-next');
  next.textContent = done ? t('tour.more') : !allDone ? t('tour.skip') : i === n - 1 ? t('tour.finish') : t('tour.next');
  next.classList.toggle('primary', done || allDone);
  next.classList.toggle('ghost-next', !done && !allDone);

  const quiz = $('tour-quiz');
  if (done && tour.quiz) {
    const go = Object.assign(document.createElement('button'), { className: 'link', textContent: t('tour.discover'), type: 'button' });
    go.addEventListener('click', () => {
      endGuides();
      setLevel(DOORS.discover);
      goWelcome('discover');
    });
    const chosen = state.tour.quiz;
    renderQuiz(quiz, {
      title: t('quiz.title'),
      q: tr(tour.quiz.q),
      options: tour.quiz.options.map(tr),
      answer: tour.quiz.answer,
      chosen,
      explain: chosen == null ? '' : `${t(chosen === tour.quiz.answer ? 'quiz.right' : 'quiz.wrong')} ${tr(tour.quiz.explain)}`,
      onPick: (k) => { state.tour.quiz = k; renderTour(); },
      after: go,
    });
  } else quiz.hidden = true;

  coach(done ? null : allDone ? next : target);
}

function endGuides() {
  if (state.tour) {
    state.tour = null;
    renderTour();
    sendView();
  }
  if (state.challenge) {
    state.challenge = null;
    renderChallenge();
    renderTitle();
    renderSelection();
  }
  coach(null);
  renderNow();
}

// ---------- Missions (Discover) ----------

const missionOf = () => (state.challenge ? findMission(state.challenge.mission) : null);

function loadScore() {
  try {
    const s = JSON.parse(localStorage.getItem('sky.score'));
    if (Number.isFinite(s?.ok) && Number.isFinite(s?.n)) return s;
  } catch { /* no storage: score lives in memory */ }
  return { ok: 0, n: 0 };
}

// Counts a mission once, when it is answered or given up.
function scoreMission(ok) {
  const c = state.challenge;
  if (c.scored) return;
  c.scored = true;
  state.score.n++;
  if (ok) state.score.ok++;
  try { localStorage.setItem('sky.score', JSON.stringify(state.score)); } catch { /* ignore */ }
  renderScore();
}

function renderScore() {
  $('score').textContent = state.score.n ? t('score', state.score) : '';
}

function renderMissions() {
  $('missions').replaceChildren(...MISSIONS.map((m) => {
    const li = document.createElement('li');
    const b = document.createElement('button');
    b.className = 'mission-card';
    b.dataset.mission = m.id;
    b.innerHTML = '<span class="mission-icon" aria-hidden="true"></span><strong></strong><span class="hook"></span><span class="go"></span>';
    b.querySelector('.mission-icon').textContent = m.icon;
    b.querySelector('strong').textContent = tr(m.title);
    b.querySelector('.hook').textContent = tr(m.summary);
    b.querySelector('.go').textContent = t('missions.play');
    b.addEventListener('click', () => startMission(m.id));
    li.append(b);
    return li;
  }));
  renderScore();
}

function startMission(id) {
  const m = findMission(id);
  const pool = [...m.sim, ...(state.real ? m.real : [])];
  const others = pool.filter((x) => x !== state.challenge?.obj);
  const obj = (others.length ? others : pool)[Math.floor(Math.random() * (others.length || pool.length))];
  state.tour = null;
  renderTour();
  state.challenge = { mission: id, obj, solved: false, revealed: false, done: m.tasks.map(() => false), answer: null, result: '', hinted: false, scored: false };
  guideSig = '';
  setLevel('compare');
  $('catalog').checked = false;
  renderChallenge();
  openObject(findObject(obj), { keepGuides: true, autoplay: false, view: { ...m.view, catalog: false } });
}

const median = (xs) => {
  if (!xs.length) return NaN;
  const s = [...xs].sort((a, b) => a - b);
  const k = s.length >> 1;
  return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2;
};

// Where in the infrared the selected source is brightest, from its own
// measurements: the median of the good points of each channel. Options whose
// channels come within 10 % of the peak are all accepted, so a near tie
// between neighboring channels does not make a right answer wrong. The
// temperature is the peak of a blackbody in F_ν (λ_peak ≈ 5100 µm·K / T),
// only an order of magnitude, and a bound when the peak is at an edge.
function measurePeak(sel, options) {
  const per = [0, 1, 2, 3, 4, 5].map((c) => {
    const ms = sel.measurements.filter((x) => x.c === c);
    const ok = ms.filter((x) => x.ok);
    return { n: ms.length, ok: ok.length, f: median(ok.map((x) => x.f)), l: median(ok.map((x) => x.l)) };
  });
  const measured = per.filter((p) => p.n > 0).length;
  if (measured < 6) return { wait: measured };
  if (per.some((p) => p.ok < Math.max(3, p.n / 3))) return { saturated: true };
  const peak = Math.max(...per.map((p) => p.f));
  const c = per.findIndex((p) => p.f === peak);
  const l = per[c].l;
  const accepted = new Set(options.filter((o) => o.bands.some((b) => per[b].f >= 0.9 * peak)).map((o) => o.id));
  const bucket = options.find((o) => o.bands.includes(c)).id;
  const temp = Math.round(5100 / l / 100) * 100;
  const edge = c === 0 ? 'low' : c === 5 ? 'high' : 'mid';
  return { c, l, accepted, bucket, why: `${t(`temp.peak.${edge}`, { t: temp, l: l.toFixed(1) })} ${t(`temp.kind.${bucket}`)}` };
}

// Text of the answer of the rhythm and temperature missions.
function missionVerdict(ok) {
  const c = state.challenge;
  const m = missionOf();
  const o = findObject(c.obj);
  const verdict = ok == null ? '' : t(ok ? 'mission.right' : 'mission.wrong');
  if (m.id === 'rhythm') return t('mission.rhythm.result', { verdict, name: objectName(o), why: t(`rhythm.${o.rhythm}`) }).trim();
  const pk = c.peak;
  return t('mission.temperature.result', { verdict, c: pk.c + 1, l: pk.l.toFixed(2), why: pk.why, name: objectName(o) }).trim();
}

function answerMission(id) {
  const c = state.challenge;
  const m = missionOf();
  c.answer = id;
  const ok = m.id === 'rhythm' ? id === findObject(c.obj).rhythm : c.peak.accepted.has(id);
  c.solved = true;
  c.result = missionVerdict(ok);
  c.good = ok;
  scoreMission(ok);
  renderTitle();
  renderSelection();
  renderChallenge();
  renderNow();
}

function renderChallenge() {
  const c = state.challenge;
  $('challenge').hidden = !c;
  if (!c) return;
  const m = missionOf();
  $('challenge-title').textContent = tr(m.title);
  $('challenge-text').textContent = t(`mission.${m.id}.instructions`);
  const target = c.solved || c.revealed ? null : renderTasks($('challenge-tasks'), m.tasks, c.done);
  if (c.solved || c.revealed) renderTasks($('challenge-tasks'), m.tasks, m.tasks.map(() => true));
  const allDone = c.done.every(Boolean);

  // Question, once the tasks are done and the object in the middle is selected.
  const q = $('challenge-question');
  q.hidden = true;
  if (m.options && allDone && !c.revealed) {
    const sel = state.selection;
    let wait = '';
    if (!c.solved) {
      if (!nearCenter(sel)) wait = t('task.select');
      else if (m.id === 'temperature') {
        c.peak = measurePeak(sel, m.options);
        if (c.peak.wait != null) wait = t('mission.wait', { n: c.peak.wait });
        else if (c.peak.saturated) wait = t('mission.saturated');
      }
    }
    if (wait) {
      q.hidden = false;
      q.replaceChildren(Object.assign(document.createElement('p'), { className: 'hint', textContent: wait }));
    } else {
      const ids = m.options.map((o) => o.id);
      const answer = m.id === 'rhythm' ? ids.indexOf(findObject(c.obj).rhythm) : ids.indexOf(c.answer != null && c.peak.accepted.has(c.answer) ? c.answer : c.peak.bucket);
      renderQuiz(q, {
        q: tr(m.question),
        options: m.options.map((o) => tr(o.label)),
        answer,
        chosen: c.answer == null ? null : ids.indexOf(c.answer),
        onPick: (k) => answerMission(ids[k]),
      });
    }
  }

  const res = $('challenge-result');
  res.hidden = !c.result;
  res.textContent = c.result || '';
  res.className = `result ${c.solved ? (c.good === false ? 'bad' : 'good') : ''}`;
  $('challenge-hint').disabled = c.solved || c.revealed || c.hinted;
  $('challenge-giveup').disabled = c.solved || c.revealed;
  coach(target);
}

function catalogAgreement(sel) {
  const err = Math.hypot(sel.pmraErr, sel.pmdecErr);
  // Agreement within 3 sigma, with a floor for systematics at this pixel size.
  const dist = sel.catalog ? Math.hypot(sel.pmra - sel.catalog.pmra, sel.pmdec - sel.catalog.pmdec) : Infinity;
  return { agree: sel.moving && dist < 3 * err + 0.3, dist };
}

// The "find what moves" mission answers on every click.
function checkChallenge(sel) {
  const c = state.challenge;
  if (c.mission !== 'moving' || c.solved || c.revealed) return;
  const speed = Math.hypot(sel.pmra, sel.pmdec).toFixed(1);
  if (sel.moving && sel.catalog && catalogAgreement(sel).agree) {
    c.solved = true;
    c.good = true;
    c.result = t('challenge.found', { name: sel.catalog.name, v: speed });
    scoreMission(true);
    renderTitle();
    renderNow();
  } else if (sel.moving) {
    c.result = t('challenge.unconfirmed', { v: speed });
  } else {
    c.result = t('challenge.still');
  }
  renderChallenge();
}

function challengeHint() {
  const c = state.challenge;
  c.hinted = true;
  if (c.mission === 'moving') {
    setCatalog(true);
    c.result = t('challenge.hinted');
  } else c.result = t(`mission.${c.mission}.hint`);
  renderChallenge();
}

function challengeGiveUp() {
  const c = state.challenge;
  c.revealed = true;
  c.good = false;
  if (c.mission === 'moving') {
    setCatalog(true);
    c.result = t('challenge.revealed', { name: objectName(findObject(c.obj)) });
  } else if (c.mission === 'temperature' && !(c.peak?.c >= 0)) {
    c.result = t('challenge.revealed.plain', { name: objectName(findObject(c.obj)) });
  } else c.result = missionVerdict(null);
  scoreMission(false);
  renderTitle();
  renderSelection();
  renderChallenge();
  renderNow();
}

// ---------- What you are seeing ----------

function currentObject() {
  const name = state.field?.name || state.request?.name;
  return name ? OBJECTS.find((o) => objectName(o) === name) : null;
}

function renderNow() {
  const r = state.request;
  const f = state.field;
  if (!r) return;
  const c = state.challenge;
  const mystery = c && !c.solved && !c.revealed;
  const what = $('now-what');
  if (mystery) what.textContent = t('now.mystery');
  else {
    const name = f?.name || r.name;
    const o = currentObject();
    const tg = state.targets.find((x) => x.name === name);
    const desc = o ? tr(o.desc) : tg ? t(`target.${tg.id}.hook`) : '';
    if (name) {
      what.replaceChildren(Object.assign(document.createElement('strong'), { textContent: name }), document.createTextNode(desc ? ` — ${desc}` : ''));
    } else what.textContent = t('now.region', { coords: `${formatRA(r.ra)} ${formatDec(r.dec)}` });
  }

  const v = state.view;
  const rows = [];
  if (f) {
    const ch = f.channels[v.band];
    rows.push(['now.color', t('now.color.value', { n: v.band + 1, range: fmtRange(ch.lo, ch.hi), what: t(`channel.${v.band + 1}`) })]);
    const vis = f.visits[v.visit];
    rows.push(['now.date', t('now.date.value', { n: v.visit + 1, total: f.visits.length, date: fmtDate(vis.date) })]);
    rows.push(['now.mode', t(`now.mode.${effectiveView().mode}`)]);
  } else rows.push(['now.date', t('now.loading')]);
  fillFacts($('now-facts'), rows);

  // The next step, when no tour or mission is already saying it.
  const next = $('now-next');
  const guided = !!(state.tour || state.challenge);
  next.hidden = guided || !f;
  if (!next.hidden) {
    next.textContent = state.seen.visits.size < 2 && !state.playing ? t('now.next.play')
      : !state.selection ? t('now.next.select')
        : t(state.level === 'explore' ? 'now.next.measured.explore' : 'now.next.measured');
  }
}

function renderTitle() {
  const r = state.request;
  if (!r) {
    $('field-name').textContent = '';
    $('field-coords').textContent = '';
    return;
  }
  const c = state.challenge;
  $('field-name').textContent = c && !c.solved && !c.revealed
    ? t('challenge.mystery')
    : state.field?.name || r.name || `${formatRA(r.ra)} ${formatDec(r.dec)}`;
  $('field-coords').textContent = `${formatRA(r.ra)} ${formatDec(r.dec)} · ${state.fov}′ · 1 px = ${PIX}″`;
  document.title = `${$('field-name').textContent} · Tifis`;
}

function renderChannels() {
  const box = $('channels');
  const f = state.field;
  if (!box.children.length) {
    for (let i = 0; i < 6; i++) {
      const b = document.createElement('button');
      b.className = 'channel';
      b.setAttribute('role', 'radio');
      b.style.setProperty('--ch', COLORS[i]);
      b.innerHTML = `<span class="bar"></span><span><span class="name"></span><span class="tech"></span></span><span class="count"></span>`;
      b.addEventListener('click', () => setBand(i));
      b.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault();
          e.stopPropagation();
          setBand(i + (e.key === 'ArrowDown' ? 1 : -1));
          box.children[state.view.band].focus();
        }
      });
      box.append(b);
    }
  }
  const ranges = f ? f.channels : [[0.75, 1.1], [1.1, 1.6], [1.6, 2.4], [2.4, 3.8], [3.8, 4.4], [4.4, 5.0]].map(([lo, hi]) => ({ lo, hi }));
  [...box.children].forEach((b, i) => {
    const on = i === state.view.band;
    b.setAttribute('aria-checked', on);
    b.tabIndex = on ? 0 : -1;
    b.querySelector('.name').textContent = t(`channel.${i + 1}`);
    b.querySelector('.tech').textContent = `${t('channel.n', { n: i + 1 })} · ${fmtRange(ranges[i].lo, ranges[i].hi)}`;
  });
  renderChannelCounts();
}

function renderChannelCounts() {
  const f = state.field;
  [...$('channels').children].forEach((b, i) => {
    const c = b.querySelector('.count');
    if (!f) return (c.textContent = '');
    const avail = f.channels[i].available.filter(Boolean).length;
    const loaded = state.loaded[i].filter((x, v) => x && f.channels[i].available[v]).length;
    c.textContent = loaded < avail ? `${loaded}/${avail}` : `${avail}`;
    c.title = t('timeline.loaded', { done: loaded, total: avail });
  });
}

function renderControls() {
  const v = state.view;
  for (const b of $('modes').children) b.setAttribute('aria-checked', b.dataset.mode === v.mode);
  $('mode-hint').textContent = t(`mode.${v.mode}.hint`);
  $('ref-row').hidden = v.mode === 'epoch';
  $('ref-auto').hidden = v.ref < 0;
  renderRefLabel();
  const tl = $('timeline');
  const f = state.field;
  if (f) {
    const vis = f.visits[v.visit];
    tl.setAttribute('aria-valuemax', f.visits.length - 1);
    tl.setAttribute('aria-valuenow', v.visit);
    tl.setAttribute('aria-valuetext', t('timeline.value', { n: v.visit + 1, total: f.visits.length, date: fmtDate(vis.date), s: vis.season + 1 }));
  }
}

function renderRefLabel() {
  const fr = state.frame;
  const v = state.view;
  const el = $('ref-label');
  if (!fr || !state.field || v.mode === 'epoch') return (el.textContent = '');
  if (fr.ref < 0) return (el.textContent = t('ref.none'));
  const vis = state.field.visits[fr.ref];
  const key = v.mode === 'diff' ? 'ref.label.diff' : 'ref.label.sum';
  el.textContent = `${t(key, { n: fr.ref + 1, date: fmtDate(vis.date), k: fr.stacked ?? 0 })} ${v.ref < 0 ? t('ref.auto.tag') : ''}`;
}

function renderFrame() {
  const fr = state.frame;
  const f = state.field;
  if (!fr || !f) return;
  const ch = f.channels[fr.band];
  const chip = $('frame-channel');
  chip.style.setProperty('--chip', COLORS[fr.band]);
  chip.textContent = `${t('channel.n', { n: fr.band + 1 })} · ${fmtRange(ch.lo, ch.hi)}`;
  $('frame-label').textContent = `${t('frame.label', { date: fmtDate(fr.date), n: fr.visit + 1, total: f.visits.length })} · λ ${fr.lambda.toFixed(2)} µm`;
  $('loading').hidden = fr.loaded || (fr.mode === 'epoch' && !fr.available);
  $('missing').hidden = !(fr.loaded && !fr.available && fr.mode !== 'sum');
  renderRefLabel();

  const rows = [
    ['meta.date', `${fr.date} · MJD ${fr.mjd.toFixed(3)}`],
    ['meta.lambda', `${fr.lambda.toFixed(3)} µm${fr.refLambda ? ` (A: ${fr.refLambda.toFixed(3)} µm)` : ''}`],
    ['meta.file', fr.file],
    ['meta.bg', fr.available ? `${fr.bg.toFixed(4)} MJy/sr` : '—'],
    ['meta.sigma', fr.available ? `${fr.sigma.toFixed(4)} MJy/sr` : '—'],
    ['meta.flagged', String(fr.flagged)],
    ['meta.pixel', `${PIX}″ · ${f.npix}×${f.npix}`],
  ];
  if (fr.stacked) rows.push(['meta.stacked', String(fr.stacked)]);
  fillFacts($('meta'), rows);
}

function renderHover() {
  const h = state.hover;
  const out = $('readout');
  const tip = $('tip');
  if (!h) {
    out.textContent = '';
    tip.hidden = true;
    return;
  }
  const val = h.value == null ? '' : ` · ${t('readout.value', { v: h.value.toFixed(4) })}`;
  out.textContent = `α ${formatRA(h.ra)}  δ ${formatDec(h.dec)}\n(${h.x}, ${h.y})${val}`;
  const showFlags = h.flags?.length && state.level === 'analyze' && state.view.flags;
  tip.hidden = !showFlags;
  if (showFlags) {
    tip.replaceChildren(...h.flags.map((name) => {
      const d = document.createElement('div');
      d.innerHTML = '<b></b> <span></span>';
      d.querySelector('b').textContent = name;
      d.querySelector('span').textContent = t(`flag.${name}`);
      return d;
    }));
  }
}

function renderStatus() {
  const f = state.field;
  if (!f) return;
  const fr = state.view.visit;
  $('date-label').textContent = t('timeline.value', { n: fr + 1, total: f.visits.length, date: fmtDate(f.visits[fr].date), s: f.visits[fr].season + 1 });
  $('load-label').textContent = state.done < state.total
    ? t('timeline.loaded', { done: state.done, total: state.total })
    : t('timeline.ready', { total: state.total, date: fmtDate(f.visits[f.visits.length - 1].date) });
}

function renderFovCost() {
  const fov = parseFloat($('fov').value);
  const px = Math.round((fov * 60) / PIX);
  const f = state.field;
  const count = (c) => c.available.filter(Boolean).length;
  const all = f ? f.channels.reduce((n, c) => n + count(c), 0) : 360;
  // The engine downloads the channel on screen; the rest when the user
  // switches to them or selects a source.
  const frames = f ? count(f.channels[state.view.band]) : 60;
  // Cutouts arrive in detector orientation, so they span the field's diagonal.
  // Each has IMAGE, VARIANCE and ZODI (float32) and FLAGS (int32) plus about
  // 72 KB of headers; the proxy leaves out the PSF cube.
  const side = Math.ceil(px * Math.SQRT2 * 1.02);
  const size = (n) => {
    const mb = (n * (side * side * 16 + 72000)) / 1e6;
    return mb < 10 ? mb.toFixed(1) : Math.round(mb);
  };
  $('fov-cost').textContent = t('fov.cost', { n: frames, px, mb: size(frames), all: size(all) });
}

// ---------- Timeline ----------

let tl = { xs: [], width: 0 };

function layoutTimeline() {
  const f = state.field;
  const svg = $('timeline-svg');
  const width = svg.clientWidth || 600;
  if (!f) return;
  const n = f.visits.length;
  const seasons = f.visits[n - 1].season + 1;
  const gap = 4;
  const pad = 10;
  const unit = (width - 2 * pad) / Math.max(1, n - 1 + gap * (seasons - 1));
  tl = { width, unit, xs: f.visits.map((v, i) => pad + (i + gap * v.season) * unit) };
  renderTimeline();
  renderStatus();
}

function svgEl(name, attrs = {}, text) {
  const el = document.createElementNS(SVGNS, name);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text != null) el.textContent = text;
  return el;
}

function renderTimeline() {
  const f = state.field;
  const svg = $('timeline-svg');
  if (!f || !tl.xs.length) return svg.replaceChildren();
  const band = state.view.band;
  const col = COLORS[band];
  const nodes = [];
  const w = Math.max(2, Math.min(8, tl.unit * 0.65));

  // Seasons
  let start = 0;
  for (let i = 1; i <= f.visits.length; i++) {
    if (i === f.visits.length || f.visits[i].season !== f.visits[start].season) {
      const x0 = tl.xs[start] - w;
      const x1 = tl.xs[i - 1] + w;
      nodes.push(svgEl('rect', { x: x0, y: 14, width: x1 - x0, height: 56, rx: 4, fill: THEME.text, 'fill-opacity': 0.04 }));
      nodes.push(svgEl('text', { x: x0 + 2, y: 10 }, fmtMonth(f.visits[start].date)));
      start = i;
    }
  }

  // Reference epoch and stacked range
  const fr = state.frame;
  const mode = effectiveView().mode;
  if (fr && mode !== 'epoch' && fr.ref >= 0) {
    const xr = tl.xs[fr.ref];
    if (mode === 'sum') {
      nodes.push(svgEl('rect', { x: xr - w / 2, y: 46, width: tl.xs[state.view.visit] - xr + w, height: 22, fill: THEME.accent, 'fill-opacity': 0.15 }));
    }
    nodes.push(svgEl('line', { x1: xr, x2: xr, y1: 16, y2: 70, stroke: THEME.accent, 'stroke-dasharray': '3 3' }));
    nodes.push(svgEl('text', { x: xr + 3, y: 24, style: `fill:${THEME.accent};font-weight:600` }, 'A'));
  }

  // Visits: filled when loaded, outlined while loading, faint when missing
  f.visits.forEach((v, i) => {
    const x = tl.xs[i] - w / 2;
    if (!f.channels[band].available[i]) {
      nodes.push(svgEl('rect', { x, y: 62, width: w, height: 4, fill: THEME.lineStrong }));
    } else if (state.loaded[band][i]) {
      nodes.push(svgEl('rect', { x, y: 48, width: w, height: 18, rx: 1.5, fill: col }));
    } else {
      nodes.push(svgEl('rect', { x: x + 0.5, y: 48.5, width: w - 1, height: 17, rx: 1.5, fill: 'none', stroke: col, 'stroke-opacity': 0.45 }));
    }
  });

  // Light curve of the selected source in this channel
  let lightcurve = false;
  const sel = state.selection;
  if (sel) {
    const pts = sel.measurements.filter((m) => m.c === band);
    if (pts.length > 1) {
      const fs = pts.map((m) => m.f);
      const lo = Math.min(...fs);
      const hi = Math.max(...fs);
      const y = (v) => 42 - ((v - lo) / (hi - lo || 1)) * 24;
      nodes.push(svgEl('polyline', { points: pts.map((m) => `${tl.xs[m.v]},${y(m.f)}`).join(' '), fill: 'none', stroke: THEME.accent, 'stroke-opacity': 0.5 }));
      for (const m of pts) nodes.push(svgEl('circle', { cx: tl.xs[m.v], cy: y(m.f), r: 2.2, fill: m.ok ? THEME.accent : 'none', stroke: THEME.accent }));
      lightcurve = true;
    }
  }
  $('lc-legend').hidden = !lightcurve;

  // Playhead
  const xp = tl.xs[state.view.visit];
  nodes.push(svgEl('line', { x1: xp, x2: xp, y1: 14, y2: 74, stroke: THEME.text, 'stroke-width': 2 }));
  nodes.push(svgEl('circle', { cx: xp, cy: 76, r: 6, fill: THEME.text, stroke: col, 'stroke-width': 2 }));

  svg.replaceChildren(...nodes);
  renderStatus();
}

function visitAt(clientX) {
  const rect = $('timeline-svg').getBoundingClientRect();
  const x = clientX - rect.left;
  let best = 0;
  tl.xs.forEach((xi, i) => {
    if (Math.abs(xi - x) < Math.abs(tl.xs[best] - x)) best = i;
  });
  return best;
}

// ---------- Selection: spectrum and motion ----------

function renderSelection() {
  const sel = state.selection;
  $('sel-chip').hidden = !sel || state.level !== 'explore';
  $('spectrum-empty').hidden = !!sel;
  $('spectrum-box').hidden = !sel;
  if (!sel) return;
  renderSpectrum();

  const [pmRA, pmDec] = [sel.pmra, sel.pmdec];
  const total = Math.hypot(pmRA, pmDec);
  const err = Math.hypot(sel.pmraErr, sel.pmdecErr);
  const rows = [['motion.position', `${formatRA(sel.ra)} ${formatDec(sel.dec)}`]];
  rows.push(['motion.measured', sel.moving
    ? `${t('motion.value', { v: `${total.toFixed(1)} ± ${err.toFixed(1)}`, dir: t(`dir.${compass(pmRA, pmDec)}`) })} · ${t('motion.px', { v: (total / PIX).toFixed(2) })}`
    : t('motion.none')]);
  rows.push(['motion.components', `μα* ${pmRA.toFixed(2)} ± ${sel.pmraErr.toFixed(2)} · μδ ${pmDec.toFixed(2)} ± ${sel.pmdecErr.toFixed(2)} ″/a`]);
  // During the challenge the catalog would give the answer away.
  const hideCatalog = state.challenge && !state.challenge.solved && !state.challenge.revealed;
  if (sel.catalog && !hideCatalog) {
    const ct = Math.hypot(sel.catalog.pmra, sel.catalog.pmdec);
    const { agree, dist } = catalogAgreement(sel);
    const note = !sel.moving ? '' : agree ? ` · ✓ ${t('motion.match')}` : ` · ${t('motion.differs', { d: dist.toFixed(1) })}`;
    rows.push(['motion.catalog', `${sel.catalog.name} · ${sel.catalog.pmra.toFixed(2)}, ${sel.catalog.pmdec.toFixed(2)} (${ct.toFixed(2)}″/a)${note}`, agree]);
  }
  rows.push(['motion.points', String(sel.track?.length ?? 0)]);
  const inBand = sel.measurements.filter((m) => m.c === sel.band);
  const flagged = inBand.filter((m) => !m.ok).length;
  if (flagged > inBand.length / 3) rows.push(['motion.caveat', t('motion.saturated', { n: flagged, total: inBand.length })]);
  fillFacts($('motion'), rows);
  renderBands();
  renderInterp();
}

// The bands drawn on the spectrum, explained; those the measurements do not
// reach are marked, and those found in the selected source say so.
function renderBands() {
  const sel = state.selection;
  const found = analysisFeatures();
  $('bands').replaceChildren(...BANDS.map((b) => {
    const li = document.createElement('li');
    li.innerHTML = '<b></b> <span class="mono"></span> <span></span>';
    li.querySelector('b').textContent = b.label;
    li.querySelector('.mono').textContent = b.line ? `${b.l.toFixed(3)} µm` : `${b.lo.toFixed(2)}–${b.hi.toFixed(2)} µm`;
    li.querySelector('span:last-child').textContent = tr(b.desc);
    const covered = sel?.measurements.some((m) => m.ok && m.l >= b.lo - 0.02 && m.l <= b.hi + 0.02);
    if (sel && !covered) {
      li.classList.add('nodata');
      li.title = t('bands.nodata');
    }
    const f = found[b.id];
    if (f && HIT.has(f.estado)) {
      li.classList.add('hit');
      li.append(Object.assign(document.createElement('span'), { className: 'tag', textContent: featureVerdict(f) }));
    }
    if (b.confuses) {
      li.append(Object.assign(document.createElement('small'), { textContent: tr(b.confuses) }));
    }
    return li;
  }));
}

// ---------- Interpretation of the spectrum ----------

// Feature states worth showing in the summary, strongest first.
const HIT = new Set(['detectada', 'compatible', 'indicio']);
const STATE_ORDER = { detectada: 0, compatible: 1, indicio: 2, opuesta: 3, no: 4 };

// During a mission the interpretation would give the answer away.
const interpHidden = () => !!(state.challenge && !state.challenge.solved && !state.challenge.revealed);

function currentAnalysis() {
  const a = state.analysis;
  return a && !a.error && state.selection && !interpHidden() ? a : null;
}

function analysisFeatures() {
  const a = currentAnalysis();
  return Object.fromEntries((a?.firmas ?? []).map((f) => [f.id, f]));
}

const fmtZ = (z) => (Math.abs(z) >= 10 ? Math.abs(z).toFixed(0) : Math.abs(z).toFixed(1));
// Rule ids can carry the sign they need ("co2_427:abs").
const featName = (id) => {
  const base = id.split(':')[0];
  return findBand(base)?.label ?? (tr(PSEUDO[base]) || base);
};
const featLabel = (id) => {
  const b = findBand(id);
  if (!b) return tr(PSEUDO[id]) || id;
  return `${b.label} ${b.line ? b.l.toFixed(2) : b.l.toFixed(1)} µm`;
};

function featureVerdict(f) {
  const kind = t(f.observado === 'emisión' ? 'interp.emi' : 'interp.abs');
  return `${t(`interp.state.${f.estado}`)} · ${kind} · ${fmtZ(f.z)}σ`;
}

function renderInterp() {
  const box = $('interp');
  const body = $('interp-body');
  const sel = state.selection;
  box.hidden = !sel;
  if (!sel) return;
  if (interpHidden()) {
    body.replaceChildren(el('p', 'hint', t('interp.hidden')));
    return;
  }
  const a = state.analysis;
  if (!a) {
    body.replaceChildren(el('p', 'hint', t('interp.pending')));
    return;
  }
  if (a.error) {
    body.replaceChildren(el('p', 'hint', tr(a.error)));
    return;
  }
  const out = [];

  // 1. What it looks like: ranked families, not a verdict.
  const classes = (a.clasificacion ?? []).filter((c) => c.puntaje >= 0.15).slice(0, 3);
  if (classes.length) {
    const ol = el('ol', 'classes');
    classes.forEach((c, i) => {
      const li = el('li', i === 0 ? 'top' : '');
      const head = el('div', 'class-head');
      head.append(el('b', '', tr(c.nombre)), el('span', 'mono', `${Math.round(c.puntaje * 100)} %`));
      const bar = el('div', 'bar');
      bar.append(Object.assign(el('span'), { style: `width:${Math.round(c.puntaje * 100)}%` }));
      li.append(head, bar);
      const why = [tr(c.desc)];
      if (c.por.length) why.push(t('interp.because', { list: c.por.map(featName).join(', ') }));
      if (c.contra?.length) why.push(t('interp.against', { list: c.contra.map(featName).join(', ') }));
      li.append(el('p', 'hint', why.join(' ')));
      ol.append(li);
    });
    out.push(el('h4', '', t('interp.best')), ol);
  } else {
    out.push(el('p', 'hint', t('interp.none')));
  }

  // 2. Continuum.
  const facts = [['interp.temp', a.T_rango_K
    ? t('interp.temp.range', { lo: Math.round(a.T_rango_K[0]), hi: Math.round(a.T_rango_K[1]) })
    : t('interp.temp.value', { t: Math.round(a.T_color_K), e: Math.round(a.T_err_K), p: a.pico_wien_um })]];
  if (a.estrella_disco) facts.push(['interp.model', t('interp.disk', { s: Math.round(a.estrella_disco.T_estrella_K), d: Math.round(a.estrella_disco.T_disco_K) })]);
  if (a.exceso_ir && a.exceso_ir.z >= 3) facts.push(['interp.excess', t('interp.excess.value', { r: a.exceso_ir.cociente.toFixed(2), z: fmtZ(a.exceso_ir.z) })]);
  const dl = el('dl', 'facts');
  for (const [k, v] of facts) dl.append(el('dt', '', t(k)), el('dd', '', v));
  out.push(dl);

  // 3. Features found.
  const hits = (a.firmas ?? []).filter((f) => HIT.has(f.estado))
    .sort((x, y) => STATE_ORDER[x.estado] - STATE_ORDER[y.estado] || Math.abs(y.z) - Math.abs(x.z));
  out.push(el('h4', '', t('interp.features')));
  if (hits.length) {
    const ul = el('ul', 'found');
    for (const f of hits) {
      const b = findBand(f.id);
      const li = el('li', f.estado);
      li.append(el('b', '', featLabel(f.id)), el('span', '', ` ${featureVerdict(f)}`));
      if (b?.confuses) li.append(el('small', '', tr(b.confuses)));
      ul.append(li);
    }
    out.push(ul);
  } else {
    out.push(el('p', 'hint', t('interp.nofeatures')));
  }

  // 4. Change over time, season by season.
  if (a.cambios?.length) {
    out.push(el('h4', '', t('interp.seasons')));
    const ul = el('ul', 'seasons');
    for (const c of a.cambios) {
      const parts = [];
      if (c.T_cambia) parts.push(t('interp.season.dT', { d: (c.dT_K > 0 ? '+' : '') + Math.round(c.dT_K), e: Math.round(c.dT_err_K) }));
      for (const [k, v] of Object.entries(c.dmag ?? {})) {
        if (Math.abs(v.dmag) > 3 * v.err && Math.abs(v.dmag) > 0.05) {
          parts.push(t(v.dmag > 0 ? 'interp.season.fainter' : 'interp.season.brighter', { v: Math.abs(v.dmag).toFixed(2), l: k.replace('um', ' µm') }));
        }
      }
      if (c.cambios.length) parts.push(t('interp.season.feats', { list: c.cambios.map((x) => featName(x.id)).join(', ') }));
      const li = el('li', parts.length ? 'changed' : '');
      li.append(el('b', '', t('interp.season.pair', { a: c.temporadas[0] + 1, b: c.temporadas[1] + 1 })),
        el('span', '', ` ${parts.length ? parts.join(' · ') : t('interp.season.nochange')}`));
      ul.append(li);
    }
    out.push(ul);
  }

  // 5. Limits: warnings first, then notes.
  const notes = [...(a.avisos ?? []).map((m) => ['warn', m]), ...(a.notas ?? []).map((m) => ['note', m])];
  if (notes.length) {
    const ul = el('ul', 'notes');
    for (const [k, m] of notes) ul.append(el('li', k, tr(m)));
    out.push(ul);
  }

  // 6. Every feature, for the Analyze level.
  if (a.firmas?.length) {
    const det = Object.assign(document.createElement('details'), { className: 'interp-detail' });
    det.dataset.minLevel = 'analyze';
    det.append(el('summary', '', t('interp.detail')));
    const table = el('table', 'mono');
    const head = el('tr');
    for (const k of ['feature', 'depth', 'z', 'state']) head.append(el('th', '', t(`interp.col.${k}`)));
    table.append(head);
    for (const f of [...a.firmas].sort((x, y) => x.lo - y.lo)) {
      const row = el('tr', f.estado);
      const name = el('td', '', f.etiqueta);
      name.append(el('small', '', `${f.lo.toFixed(2)}–${f.hi.toFixed(2)} µm · ${t(`interp.method.${f.metodo}`)}`));
      row.append(name, el('td', '', `${f.d >= 0 ? '+' : ''}${f.d.toFixed(3)} ± ${f.sigma.toFixed(3)}`),
        el('td', '', f.z.toFixed(1)), el('td', '', t(`interp.state.${f.estado}`)));
      table.append(row);
    }
    det.append(table, el('p', 'hint', t('interp.legend', { n: a.puntos, c: a.puntos_continuo, chi: a.chi2_reducido })));
    out.push(det);
  }
  body.replaceChildren(...out);
}

function el(tag, className = '', text) {
  const e = document.createElement(tag);
  if (className) e.className = className;
  if (text !== undefined) e.textContent = text;
  return e;
}

// Angular distance between two selections, arcsec.
function angularSep(a, b) {
  const cos = Math.cos((a.dec * Math.PI) / 180);
  let dra = a.ra - b.ra;
  if (dra > 180) dra -= 360;
  if (dra < -180) dra += 360;
  return Math.hypot(dra * cos, a.dec - b.dec) * 3600;
}

function exportAnalysis() {
  const a = state.analysis;
  const sel = state.selection;
  const f = state.field;
  if (!a || !sel || !f) return;
  const out = { source: { name: f.name, ra: sel.ra, dec: sel.dec, real: !!f.real }, ...a };
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
  const link = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(blob),
    download: `${(f.name || 'spherex').replace(/[^\w.-]+/g, '_')}_analysis.json`,
  });
  link.click();
  setTimeout(() => URL.revokeObjectURL(link.href), 1000);
}

function exportCSV() {
  const sel = state.selection;
  const f = state.field;
  if (!sel || !f) return;
  const unit = f.fluxUnit || 'image units';
  const rows = [['channel', 'visit', 'date', 'mjd', 'lambda_um', `flux_${unit}`, `flux_err_${unit}`, 'reliable']];
  for (const m of sel.measurements) {
    rows.push([m.c + 1, m.v + 1, f.visits[m.v].date, m.t.toFixed(5), m.l.toFixed(4), m.f.toPrecision(6), m.e.toPrecision(4), m.ok ? 1 : 0]);
  }
  const head = `# Tifis (SPHEREx): ${f.name || 'field'} · RA ${sel.ra.toFixed(6)} Dec ${sel.dec.toFixed(6)} · ${f.real ? 'SPHEREx DR1/QR3 (IRSA)' : 'simulation'}\n`;
  const blob = new Blob([head + rows.map((r) => r.join(',')).join('\n') + '\n'], { type: 'text/csv' });
  const a = Object.assign(document.createElement('a'), {
    href: URL.createObjectURL(blob),
    download: `${(f.name || 'spherex').replace(/[^\w.-]+/g, '_')}_measurements.csv`,
  });
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function renderSpectrum() {
  const sel = state.selection;
  const svg = $('spectrum');
  const W = svg.clientWidth || 300;
  const H = 200;
  const m = { l: 40, r: 6, t: 40, b: 30 };
  // Points whose aperture has too many flagged pixels (saturated cores,
  // cosmic rays) are kept but drawn hollow, like the bad-pixel counts of the
  // SPHEREx Source Discovery Tool.
  const pts = sel.measurements;
  const x = (l) => m.l + ((l - 0.7) / (5.1 - 0.7)) * (W - m.l - m.r);
  const log = state.specLog;
  const vals = pts.map((p) => p.f).filter((v) => !log || v > 0);
  const nodes = [];
  if (!vals.length) return svg.replaceChildren();
  let lo = Math.min(...vals);
  let hi = Math.max(...vals);
  if (log) {
    lo = Math.log10(Math.max(lo, hi * 1e-4));
    hi = Math.log10(hi);
  }
  const span = hi - lo || 1;
  lo -= span * 0.08;
  hi += span * 0.08;
  const y = (v) => {
    const vv = log ? Math.log10(Math.max(v, 10 ** lo)) : v;
    return m.t + (1 - (vv - lo) / (hi - lo)) * (H - m.t - m.b);
  };

  // Bands are shaded and lines (unresolved) drawn as thin marks. Once the
  // spectrum is interpreted, only what was found keeps its label, highlighted.
  const found = analysisFeatures();
  const interpreted = !!currentAnalysis();
  const rows = [-Infinity, -Infinity, -Infinity];
  const sorted = [...BANDS].sort((p, q) => (found[q.id] && HIT.has(found[q.id].estado)) - (found[p.id] && HIT.has(found[p.id].estado)) || p.l - q.l);
  for (const ft of sorted) {
    const f = found[ft.id];
    const hit = f && HIT.has(f.estado);
    const g = svgEl('g', { class: `feature${ft.line ? ' line' : ''}${hit ? ` hit ${f.estado}` : ''}` });
    if (ft.line) {
      g.append(svgEl('line', { x1: x(ft.l), x2: x(ft.l), y1: m.t, y2: H - m.b }));
    } else {
      g.append(svgEl('rect', { x: x(ft.lo), y: m.t, width: Math.max(1, x(ft.hi) - x(ft.lo)), height: H - m.t - m.b }));
    }
    // Labels go in the first of three rows with room, or not at all.
    if (hit || (!interpreted && !ft.line)) {
      const cx = x(ft.l);
      const half = ft.label.length * 3.4 + 3;
      const row = rows.findIndex((end) => end < cx - half);
      if (row >= 0) {
        rows[row] = cx + half;
        g.append(svgEl('text', { x: cx, y: m.t - 3 - row * 11, 'text-anchor': 'middle' }, ft.label));
      }
    }
    const verdict = f ? ` · ${featureVerdict(f)}` : '';
    g.append(svgEl('title', {}, `${ft.label} ${ft.lo}–${ft.hi} µm${verdict}: ${tr(ft.desc)}`));
    nodes.push(g);
  }
  state.field.channels.forEach((c, i) => {
    nodes.push(svgEl('rect', { x: x(c.lo), y: H - m.b + 1, width: x(c.hi) - x(c.lo) - 1, height: 4, fill: COLORS[i] }));
  });
  nodes.push(svgEl('line', { class: 'axis', x1: m.l, x2: W - m.r, y1: H - m.b, y2: H - m.b }));
  nodes.push(svgEl('line', { class: 'axis', x1: m.l, x2: m.l, y1: m.t, y2: H - m.b }));
  for (const l of [1, 2, 3, 4, 5]) nodes.push(svgEl('text', { x: x(l), y: H - m.b + 16, 'text-anchor': 'middle' }, String(l)));
  nodes.push(svgEl('text', { x: W - m.r, y: H - 2, 'text-anchor': 'end' }, t('spectrum.x')));
  if (state.field.fluxUnit) nodes.push(svgEl('text', { x: 2, y: m.t - 13 }, state.field.fluxUnit));
  for (const v of yTicks(lo, hi, log)) {
    nodes.push(svgEl('text', { x: m.l - 4, y: y(v) + 3, 'text-anchor': 'end' }, fmtFlux(v)));
    nodes.push(svgEl('line', { class: 'axis', x1: m.l, x2: W - m.r, y1: y(v), y2: y(v), 'stroke-opacity': 0.4 }));
  }

  for (const p of pts) {
    const cx = x(p.l);
    const below = log && p.f <= 0;
    if (!below && p.e > 0) {
      nodes.push(svgEl('line', { x1: cx, x2: cx, y1: y(p.f - p.e), y2: y(p.f + p.e), stroke: COLORS[p.c], 'stroke-opacity': 0.5 }));
    }
    const dot = svgEl('circle', { cx, cy: y(p.f), r: 2.6, fill: below || !p.ok ? 'none' : COLORS[p.c], stroke: COLORS[p.c] });
    const unit = state.field.fluxUnit ? ` ${state.field.fluxUnit}` : '';
    const note = p.ok ? '' : ` · ${t('spectrum.flagged')}`;
    dot.append(svgEl('title', {}, `${p.l.toFixed(3)} µm · ${p.f.toPrecision(4)} ± ${p.e.toPrecision(2)}${unit} · ${fmtDate(state.field.visits[p.v].date)}${note}`));
    nodes.push(dot);
  }
  // Fitted continuum (black body, or star + disk), dashed, over the points.
  const an = currentAnalysis();
  if (an?.continuo?.length) {
    const cpts = an.continuo.filter(([, v]) => v !== null && (v > 0 || !log))
      .map(([l, v]) => `${x(l).toFixed(1)},${clamp(y(v), m.t - 6, H - m.b).toFixed(1)}`);
    nodes.push(svgEl('polyline', { class: 'continuum', points: cpts.join(' ') }));
  }
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.replaceChildren(...nodes);
}

function yTicks(lo, hi, log) {
  if (log) {
    const mult = hi - lo < 2.5 ? [1, 2, 5] : [1];
    const out = [];
    for (let e = Math.floor(lo); e <= Math.ceil(hi); e++) {
      for (const k of mult) {
        const v = k * 10 ** e;
        if (Math.log10(v) >= lo && Math.log10(v) <= hi) out.push(v);
      }
    }
    return out;
  }
  const step = niceStep((hi - lo) / 4);
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(v);
  return out;
}

function niceStep(raw) {
  const p = 10 ** Math.floor(Math.log10(raw));
  const r = raw / p;
  return (r < 1.5 ? 1 : r < 3.5 ? 2 : r < 7.5 ? 5 : 10) * p;
}

// ---------- Helpers ----------

function fillFacts(dl, rows) {
  dl.replaceChildren();
  for (const [k, v, good] of rows) {
    const dd = Object.assign(document.createElement('dd'), { textContent: v });
    if (good) dd.className = 'good';
    dl.append(Object.assign(document.createElement('dt'), { textContent: t(k) }), dd);
  }
}

function compass(east, north) {
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  const a = (Math.atan2(east, north) * 180) / Math.PI;
  return dirs[Math.round(((a + 360) % 360) / 45) % 8];
}

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const fmtRange = (lo, hi) => `${lo.toFixed(2)}–${hi.toFixed(2)} µm`;
const fmtDate = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString(getLang(), { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
const fmtMonth = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString(getLang(), { month: 'short', year: 'numeric', timeZone: 'UTC' });
const fmtFlux = (v) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(1) : v.toPrecision(1));

let toastTimer;
function toast(msg, action) {
  const el = $('toast');
  el.replaceChildren(document.createTextNode(msg));
  if (action) {
    const b = Object.assign(document.createElement('button'), { className: 'link', textContent: action.label });
    b.addEventListener('click', action.run);
    el.append(' ', b);
  }
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, 4000);
}

function hideToast() {
  $('toast').hidden = true;
}

async function copy(text, msg) {
  try {
    await navigator.clipboard.writeText(text);
    toast(msg);
  } catch {
    prompt('', text);
  }
}

// ---------- Wiring ----------

function wire() {
  $('search').addEventListener('submit', (e) => {
    e.preventDefault();
    search($('q').value);
    $('q').blur();
  });
  for (const b of document.querySelectorAll('.levels button')) {
    b.addEventListener('click', () => {
      setLevel(b.dataset.level);
      // On the welcome screen the level and the door are the same choice.
      if (!$('welcome').hidden) setDoor(doorFor(b.dataset.level));
    });
  }
  for (const b of $('modes').children) b.addEventListener('click', () => setMode(b.dataset.mode));

  $('play').addEventListener('click', () => setPlaying(!state.playing));
  $('prev').addEventListener('click', () => { setPlaying(false); setVisit(nextVisit(-1, 'visit')); });
  $('next').addEventListener('click', () => { setPlaying(false); setVisit(nextVisit(1, 'visit')); });
  $('speed').addEventListener('change', (e) => { state.speed = parseFloat(e.target.value); });
  $('step').addEventListener('change', (e) => { state.step = e.target.value; });

  $('tint').addEventListener('change', (e) => { state.view.tint = e.target.checked; sendView(); });
  $('flags').addEventListener('change', (e) => { state.view.flags = e.target.checked; sendView(); renderHover(); });
  $('catalog').addEventListener('change', (e) => setCatalog(e.target.checked));
  $('spec-log').addEventListener('change', (e) => { state.specLog = e.target.checked; renderSpectrum(); });
  $('ref-set').addEventListener('click', () => { state.view.ref = state.view.visit; sendView(); });
  $('ref-auto').addEventListener('click', () => { state.view.ref = -1; sendView(); });

  $('fov').addEventListener('input', (e) => {
    $('fov-value').textContent = e.target.value + t('unit.arcmin');
    renderFovCost();
  });
  $('fov').addEventListener('change', (e) => {
    state.fov = parseInt(e.target.value, 10);
    if (state.request) open(state.request, { autoplay: state.playing });
    renderTitle();
  });

  $('zoom-in').addEventListener('click', () => engine()?.zoom(1.4));
  $('zoom-out').addEventListener('click', () => engine()?.zoom(1 / 1.4));
  $('zoom-fit').addEventListener('click', () => engine()?.fit());

  $('sel-analyze').addEventListener('click', () => {
    setLevel('analyze');
    $('h-spectrum').closest('.panel').scrollIntoView({ block: 'start', behavior: reduceMotion ? 'auto' : 'smooth' });
  });
  $('sel-clear').addEventListener('click', () => engine()?.clearSelection());

  for (const b of document.querySelectorAll('.door')) {
    b.addEventListener('click', () => {
      setDoor(b.dataset.door);
      setLevel(DOORS[b.dataset.door]);
    });
    b.addEventListener('keydown', (e) => {
      if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return;
      const keys = Object.keys(DOORS);
      const next = keys[(keys.indexOf(state.door) + (e.key === 'ArrowRight' ? 1 : keys.length - 1)) % keys.length];
      setDoor(next);
      setLevel(DOORS[next]);
      document.querySelector(`.door[data-door="${next}"]`).focus();
    });
  }
  $('tour-prev').addEventListener('click', () => {
    if (state.tour.step > 0) {
      state.tour.step = Math.min(state.tour.step, tourOf().steps.length) - 1;
      showStep();
    }
  });
  $('tour-next').addEventListener('click', () => {
    if (state.tour.step >= tourOf().steps.length) return goWelcome('learn');
    state.tour.step++;
    showStep();
  });
  $('tour-exit').addEventListener('click', endGuides);
  $('challenge-next').addEventListener('click', () => startMission(state.challenge.mission));
  $('challenge-hint').addEventListener('click', challengeHint);
  $('challenge-giveup').addEventListener('click', challengeGiveUp);
  $('challenge-exit').addEventListener('click', endGuides);
  $('export-csv').addEventListener('click', exportCSV);
  // The band table comes from the server a moment after the page starts.
  featuresReady.then(() => {
    renderBands();
    if (state.selection) renderSpectrum();
  });
  $('export-analysis').addEventListener('click', exportAnalysis);

  $('share').addEventListener('click', () => copy(shareURL(), t('share.copied')).then(() => {
    toast(t('share.copied'), {
      label: '</> embed',
      run: () => copy(`<iframe src="${shareURL({ embed: true })}" width="640" height="480" style="border:0" allow="clipboard-write"></iframe>`, t('share.embedCopied')),
    });
  }));
  $('lang').addEventListener('click', () => {
    setLang(getLang() === 'es' ? 'en' : 'es');
    $('lang').textContent = getLang() === 'es' ? 'EN' : 'ES';
    $('lang').setAttribute('aria-label', getLang() === 'es' ? 'English' : 'Español');
    renderWelcome();
    renderTour();
    guideSig = '';
    renderChallenge();
    renderNow();
    renderBands();
    renderInterp();
    renderDatalist();
    renderTitle();
    renderChannels();
    renderControls();
    renderFrame();
    renderTimeline();
    renderSelection();
    renderFovCost();
    renderBanner();
    renderArchiveStatus();
    writeURL();
  });
  $('help').addEventListener('click', () => $('help-dialog').showModal());
  $('archive-sim').addEventListener('click', () => {
    state.real = false;
    renderBanner();
    if (state.request) open(state.request, { autoplay: true });
  });

  const timeline = $('timeline');
  let scrubbing = false;
  timeline.addEventListener('pointerdown', (e) => {
    if (!state.field) return;
    scrubbing = true;
    timeline.setPointerCapture(e.pointerId);
    setPlaying(false);
    setVisit(visitAt(e.clientX));
  });
  timeline.addEventListener('pointermove', (e) => {
    if (scrubbing) {
      const v = visitAt(e.clientX);
      if (v !== state.view.visit) setVisit(v);
    }
  });
  timeline.addEventListener('pointerup', () => { scrubbing = false; });

  const viewer = $('viewer');
  new ResizeObserver(() => {
    engine()?.resize(Math.floor(viewer.clientWidth), Math.floor(viewer.clientHeight));
  }).observe(viewer);
  new ResizeObserver(() => {
    layoutTimeline();
    if (state.selection) renderSpectrum();
  }).observe($('timeline'));

  viewer.addEventListener('mousemove', (e) => {
    const r = viewer.getBoundingClientRect();
    const tip = $('tip');
    tip.style.left = `${e.clientX - r.left + 14}px`;
    tip.style.top = `${e.clientY - r.top + 14}px`;
  });
  const canvas = $('canvas');
  canvas.addEventListener('pointerenter', () => engine()?.pointer(true));
  canvas.addEventListener('pointermove', () => engine()?.pointer(true), { once: true });
  canvas.addEventListener('pointerleave', () => {
    engine()?.pointer(false);
    $('tip').hidden = true;
  });

  document.addEventListener('keydown', onKey);
}

function onKey(e) {
  const tag = e.target.tagName;
  if (e.target.closest?.('dialog') || ['INPUT', 'SELECT', 'TEXTAREA'].includes(tag)) {
    if (e.key === 'Escape' && e.target.id === 'q') e.target.blur();
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (tag === 'BUTTON' && (e.key === ' ' || e.key === 'Enter')) return;

  const f = state.field;
  const k = e.key;
  let handled = true;
  if (k === '/') $('q').focus();
  else if (k === '?') $('help-dialog').showModal();
  else if (!f) handled = false;
  else if (k === ' ') setPlaying(!state.playing);
  else if (k === 'ArrowRight' || k === 'ArrowLeft') {
    setPlaying(false);
    setVisit(nextVisit(k === 'ArrowRight' ? 1 : -1, e.shiftKey ? 'season' : 'visit'));
  } else if (k === 'PageUp' || k === 'PageDown') {
    setPlaying(false);
    setVisit(nextVisit(k === 'PageDown' ? 1 : -1, 'season'));
  } else if (k === 'Home') setVisit(0);
  else if (k === 'End') setVisit(f.visits.length - 1);
  else if (k >= '1' && k <= '6') setBand(parseInt(k, 10) - 1);
  else if (k === 'e' || k === 'E') setMode('epoch');
  else if (k === 'd' || k === 'D') setMode('diff');
  else if (k === 's' || k === 'S') setMode('sum');
  else if (k === 'a' || k === 'A') { state.view.ref = state.view.visit; sendView(); }
  else if (k === 'c' || k === 'C') {
    if (state.level === 'explore') setLevel('compare');
    $('catalog').checked = state.view.catalog = !state.view.catalog;
    sendView();
  } else if (k === 'f' || k === 'F') {
    if (state.level !== 'analyze') setLevel('analyze');
    $('flags').checked = state.view.flags = !state.view.flags;
    sendView();
  } else if (k === '+' || k === '=') engine()?.zoom(1.4);
  else if (k === '-') engine()?.zoom(1 / 1.4);
  else if (k === '0') engine()?.fit();
  else if (k === '[' || k === ']') {
    const speeds = [0.5, 1, 2, 4];
    const i = clamp(speeds.indexOf(state.speed) + (k === ']' ? 1 : -1), 0, speeds.length - 1);
    state.speed = speeds[i];
    $('speed').value = String(state.speed);
  } else if (k === 'Escape') engine()?.clearSelection();
  else handled = false;
  if (handled) e.preventDefault();
}

// ---------- Boot ----------

const params = new URLSearchParams(location.search);
if (params.has('debug')) globalThis.skyState = state;
setLang(params.get('lang') || detectLang());
$('lang').textContent = getLang() === 'es' ? 'EN' : 'ES';
renderChannels();
renderControls();
renderFovCost();
state.score = loadScore();
wire();
const archiveAvailable = detectArchive();
archiveAvailable.then((real) => {
  state.real = real;
  renderBanner();
});
if (!['ra', 'target', 'embed', 'tour'].some((k) => params.has(k))) showWelcome(true);
start().catch((err) => {
  console.error(err);
  toast(String(err));
});
