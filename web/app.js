'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const S = {
  rounds: 5, difficulty: 'easy', limitMs: 300000,
  round: 0, puzzle: null,
  t0: 0, elapsed: 0, running: false, raf: null,
  gen: 0, walk: null, awarded: false, live: null
};

/* ─────────────────────────── settings persistence ─────────────────────────── */
// Only host preferences are remembered — scores/round/puzzle live on the
// server now (see GameState in server.py) and survive a shared-screen
// reload on their own; there's nothing left here to "resume".
const PREF_KEY = 'wikilinks.prefs';
function savePrefs() {
  try { localStorage.setItem(PREF_KEY, JSON.stringify({ rounds: S.rounds, difficulty: S.difficulty, limitMs: S.limitMs })); } catch {}
}
function loadPrefs() {
  try {
    const p = JSON.parse(localStorage.getItem(PREF_KEY) || 'null');
    if (!p) return;
    S.difficulty = p.difficulty || S.difficulty;
    $$('#difficulty button').forEach(x => x.classList.toggle('on', x.dataset.d === S.difficulty));
    if (p.rounds) $('#rounds').value = p.rounds;
    if (p.limitMs != null) $('#limit').value = String(p.limitMs / 60000);
  } catch {}
}
loadPrefs();

/* ─────────────────────────── setup ─────────────────────────── */
$('#difficulty').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  $$('#difficulty button').forEach(x => x.classList.toggle('on', x === b));
  S.difficulty = b.dataset.d;
});

let lastBaseUrl = null;
async function refreshJoinQrs() {
  // Re-fetched every call (not cached) so that starting `ngrok http <port>`
  // after this screen is already open still picks it up within a second or
  // two, via the same poll loop that updates the joined-players list.
  let info;
  try { info = await (await fetch('/api/host-info')).json(); } catch { info = null; }
  const base = info ? info.base_url : location.origin;
  const gameUrl = `${base}/play`;
  if (base !== lastBaseUrl) {
    lastBaseUrl = base;
    $('#gameQr').src = '/api/qr?text=' + encodeURIComponent(gameUrl);
    $('#joinUrl').textContent = gameUrl + (info && info.via_ngrok ? '  (via ngrok — works off your Wi-Fi too)' : '');
  }
}
refreshJoinQrs();

function renderJoinedList(players) {
  $('#joinedCount').textContent = players.length;
  $('#joinedList').innerHTML = players.map(p => `<span class="joinedTag">${esc(p.name)}</span>`).join('')
    || '<span class="small">nobody yet — scan the Game QR above</span>';
  const inSetup = !$('#setup').classList.contains('hidden');
  if (inSetup) $('#start').disabled = players.length === 0;
  $('#start').textContent = players.length === 0 ? 'Waiting for players…' : 'Start game';
}

$('#start').addEventListener('click', async () => {
  if ($('#start').disabled) return;
  S.rounds = +$('#rounds').value;
  S.limitMs = (+$('#limit').value) * 60000;
  S.round = 0;
  savePrefs();
  $('#rt').textContent = S.rounds;
  $('#diffPill').textContent = S.difficulty.toUpperCase();
  $('#setup').classList.add('hidden');
  $('#game').classList.remove('hidden');
  try { await fetch('/api/new-game', { method: 'POST' }); } catch {}
  newRound();
});

/* ─────────────────────────── clock ─────────────────────────── */
const fmt = ms => {
  const t = Math.floor(ms / 100);
  return `${Math.floor(t / 600)}:${String(Math.floor(t / 10) % 60).padStart(2, '0')}.${t % 10}`;
};
function tick() {
  if (!S.running) return;
  S.elapsed = performance.now() - S.t0;
  if (S.limitMs && S.elapsed >= S.limitMs) return expire();
  $('#clock').textContent = fmt(S.elapsed);
  $('#clock').classList.toggle('warning',
    !!S.limitMs && S.elapsed > S.limitMs - 30000);
  S.raf = requestAnimationFrame(tick);
}

function expire() {
  S.running = false;
  cancelAnimationFrame(S.raf);
  const c = $('#clock');
  c.textContent = fmt(S.limitMs);
  c.classList.remove('warning', 'stopped');
  c.classList.add('expired');
  fetch('/api/end-round', { method: 'POST' }).catch(() => {});
  enterReveal("Time's up — nobody linked it.");
}
function clockStart() {
  S.t0 = performance.now();
  S.elapsed = 0;
  S.running = true;
  $('#clock').classList.remove('stopped', 'expired', 'warning', 'idle');
  tick();
}
function clockStop() {
  S.running = false;
  cancelAnimationFrame(S.raf);
  $('#clock').classList.add('stopped');
}

/* ─────────────────────────── round ─────────────────────────── */
const PHASES = ['phReady', 'phRunning', 'phNext', 'phReveal', 'phFinal'];
const phase = id => PHASES.forEach(p => $('#' + p).classList.toggle('hidden', p !== id));

function renderScores(players) {
  const max = Math.max(0, ...players.map(p => p.pts));
  $('#scores').innerHTML = players.map(p =>
    `<span class="score${p.pts === max && max > 0 ? ' lead' : ''}">${esc(p.name)}<b class="pts">${p.pts}</b></span>`
  ).join('');
}

function fillPanel(sel, card) {
  const el = $(sel);
  el.querySelector('.ptitle').textContent = card.title;
  el.querySelector('.pslug').textContent = card.slug;
  el.querySelector('.popen').href = card.url;
  loadExcerpt(el, card.slug);
}

const BOILERPLATE = /^(references|related pages|other websites|notes|sources|bibliography|further reading|external links|gallery|citations)$/i;

async function loadExcerpt(panel, slug) {
  const box = panel.querySelector('.excerpt');
  box.innerHTML = '<p class="loading">loading…</p>';
  try {
    const u = new URL('https://simple.wikipedia.org/w/api.php');
    u.search = new URLSearchParams({
      action: 'query', format: 'json', origin: '*', redirects: '1',
      prop: 'extracts|pageimages', explaintext: '1', exsectionformat: 'wiki',
      piprop: 'thumbnail', pithumbsize: '320', titles: slug.replace(/_/g, ' ')
    });
    const j = await (await fetch(u)).json();
    const p = Object.values(j.query.pages)[0] || {};
    box.innerHTML = '';
    if (p.thumbnail) { const im = new Image(); im.src = p.thumbnail.source; im.alt = ''; box.appendChild(im); }

    let wrote = 0;
    for (const raw of (p.extract || '').slice(0, 14000).split('\n')) {
      const t = raw.trim();
      if (!t) continue;
      const h = t.match(/^=+\s*(.+?)\s*=+$/);      // exsectionformat=wiki marks headings
      if (h) {
        if (BOILERPLATE.test(h[1])) break;           // stop before the nav cruft
        const el = document.createElement('h3');
        el.className = 'sec'; el.textContent = h[1];
        box.appendChild(el);
      } else {
        const el = document.createElement('p');
        el.textContent = t; box.appendChild(el); wrote++;
      }
    }
    if (!wrote) box.innerHTML = '<p class="loading">No preview available.</p>';
  } catch {
    box.innerHTML = '<p class="loading">Preview unavailable — open the article link instead.</p>';
  }
}

function resetRoundUI() {
  S.walk = null;
  S.awarded = false;
  S.gen++;
  const lab = $('#pStart .plabel');
  lab.textContent = 'START'; lab.className = 'plabel start';
  $('#rn').textContent = S.round;
  $('#revealed').innerHTML = '';
  $('#liveBoard').innerHTML = '';
  phase('phReady');
  $('#startRound').disabled = true;
  const clk = $('#clock');
  clk.textContent = '0:00.0';
  clk.classList.remove('stopped', 'expired', 'warning');
  clk.classList.add('idle');
}

function showPuzzle(p) {
  S.puzzle = p;
  fillPanel('#pStart', p.start);
  fillPanel('#pFinish', p.finish);
  $('#startRound').disabled = false;
}

async function newRound() {
  S.round++;
  S.puzzle = null;
  resetRoundUI();
  for (const s of ['#pStart', '#pFinish']) {
    $(s).querySelector('.ptitle').textContent = 'finding a challenge…';
    $(s).querySelector('.excerpt').innerHTML = '';
    $(s).querySelector('.pslug').textContent = '';
  }
  let p;
  try {
    p = await (await fetch(`/api/puzzle?difficulty=${S.difficulty}`)).json();
  } catch { p = null; }
  if (!p || p.error) {
    $('#pStart').querySelector('.ptitle').textContent = 'Could not reach the engine';
    return;
  }
  showPuzzle(p);
}

$('#startRound').addEventListener('click', async () => {
  if ($('#startRound').disabled) return;
  $('#clock').classList.remove('idle');
  phase('phRunning');
  clockStart();
  try {
    await fetch('/api/start-round', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ limit_ms: S.limitMs })
    });
  } catch {}
});

/* ───────────────────── live tracking (replaces shout + type-route) ───────────────────── */
function renderBoard(players) {
  $('#liveBoard').innerHTML = players.map(p => `
    <div class="boardRow${p.arrived ? ' arrived' : ''}">
      <span class="bname">${esc(p.name)}</span>
      <span class="bhops">${p.hops} link${p.hops === 1 ? '' : 's'}</span>
      <button class="ghost tiny award" data-token="${esc(p.token)}">Award</button>
    </div>`).join('') || '<div class="small">Nobody joined this round.</div>';
}
$('#liveBoard').addEventListener('click', e => {
  const b = e.target.closest('.award'); if (!b) return;
  fetch('/api/award', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token: b.dataset.token })
  }).catch(() => {});
});

function onRoundWon(w) {
  if (S.awarded) return;
  S.awarded = true;
  clockStop();
  $('#roundSummary').innerHTML =
    `<div class="won"><b>${esc(w.name)}</b> takes round ${S.round} in ${fmt(S.elapsed)}` +
    ` — ${w.hops} link${w.hops === 1 ? '' : 's'}</div>`;
  phase('phNext');
}

$('#giveup').addEventListener('click', () => {
  clockStop();
  fetch('/api/end-round', { method: 'POST' }).catch(() => {});
  enterReveal('Nobody got it.');
});

/* ───────────────────────────── polling ───────────────────────────── */
async function pollLive() {
  let r;
  try { r = await (await fetch('/api/live')).json(); } catch { return; }
  S.live = r;
  if (!$('#setup').classList.contains('hidden')) {
    renderJoinedList(r.players);
    refreshJoinQrs();
    return;
  }
  if (!$('#phRunning').classList.contains('hidden')) {
    renderBoard(r.players);
    if (r.winner_token) {
      const w = r.players.find(p => p.token === r.winner_token);
      if (w) onRoundWon(w);
    }
  }
  renderScores(r.players);
}
setInterval(pollLive, 1000);
pollLive();

/* ───────────────────── next round / reveal / final ───────────────────── */
$('#nextRound').addEventListener('click', () => {
  if (S.round >= S.rounds) return finish();
  newRound();
});
$('#reveal').addEventListener('click', async () => {
  $('#revealed').innerHTML = '<div class="small">solving…</div>';
  const q = new URLSearchParams({ start: S.puzzle.start.slug, finish: S.puzzle.finish.slug });
  try {
    const r = await (await fetch('/api/path?' + q)).json();
    $('#revealed').innerHTML = r.path
      ? `<div class="chain">${r.path.map(n => `<span class="hop ok"><span class="n">${esc(n.title)}</span></span>`)
          .join('<span class="lk" style="color:var(--faint)">→</span>')}</div>`
      : '<div class="small">No path found.</div>';
  } catch { $('#revealed').innerHTML = '<div class="small">Engine unreachable.</div>'; }
});

function finish() {
  clockStop();
  const players = (S.live && S.live.players) || [];
  const max = Math.max(0, ...players.map(p => p.pts));
  const champs = players.filter(p => p.pts === max);
  const table = [...players].sort((a, b) => b.pts - a.pts)
    .map(p => `<span class="score${p.pts === max ? ' lead' : ''}">${esc(p.name)}<b class="pts">${p.pts}</b></span>`).join(' ');
  $('#finalText').innerHTML =
    `<h2 class="champ">${champs.length > 1 ? 'Tied: ' : ''}${champs.map(c => esc(c.name)).join(' & ')}</h2>` +
    `<div class="chain">${table}</div>`;
  phase('phFinal');
}
$('#again').addEventListener('click', () => {
  $('#game').classList.add('hidden');
  $('#setup').classList.remove('hidden');
  $('#setupHint').textContent = '';
});

/* ─────────────────────────── keyboard ─────────────────────────── */
document.addEventListener('keydown', e => {
  if ($('#game').classList.contains('hidden')) return;
  const typing = ['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName);
  if (e.code === 'Space' && !typing && !$('#phReady').classList.contains('hidden')) {
    e.preventDefault(); $('#startRound').click();
  }
  if (e.key === 'Enter' && !$('#phNext').classList.contains('hidden')) $('#nextRound').click();
  if (!$('#phReveal').classList.contains('hidden') && (e.key === 'Enter' || e.code === 'Space') && !typing) {
    e.preventDefault();
    for (const id of ['#revealNext', '#revealStart', '#nextFromReveal']) {
      const b = $(id);
      if (!b.classList.contains('hidden') && !b.disabled && !b.closest('.hidden')) { b.click(); break; }
    }
  }
});

/* ───────────── nobody got it: step through the answer, one click at a time ─────────── */
function enterReveal(headline) {
  S.walk = null;
  $('#revealHead').textContent = headline;
  const b = $('#revealStart');
  b.classList.remove('hidden'); b.disabled = false; b.textContent = 'Reveal?';
  $('#revealNext').classList.add('hidden');
  $('#walkChain').innerHTML = '';
  $('#afterReveal').classList.add('hidden');
  phase('phReveal');
}

function renderStep() {
  const { path, i } = S.walk;
  const last = path.length - 1;
  const lab = $('#pStart .plabel');
  lab.textContent = i === 0 ? 'START' : i === last ? 'ARRIVED' : `STEP ${i} / ${last}`;
  lab.className = 'plabel ' + (i === 0 ? 'start' : i === last ? 'finish' : 'walking');
  fillPanel('#pStart', path[i]);
  $('#walkChain').innerHTML = path.slice(0, i + 1).map((c, k) =>
    `<span class="hop ok"><span class="n">${esc(c.title)}</span></span>` +
    (k < i ? '<span class="lk" style="color:var(--faint)">→</span>' : '')).join('');

  if (i === last) {                       // arrived: offer the next round
    $('#revealNext').classList.add('hidden');
    $('#afterReveal').classList.remove('hidden');
  } else {
    $('#revealNext').classList.remove('hidden');
    $('#revealNext').textContent = `Next → (${i + 1} of ${last})`;
  }
}

async function revealBegin() {
  const btn = $('#revealStart');
  btn.disabled = true; btn.textContent = 'solving…';
  const mine = S.gen;
  const q = new URLSearchParams({ start: S.puzzle.start.slug, finish: S.puzzle.finish.slug });
  let path = null;
  try { path = (await (await fetch('/api/path?' + q)).json()).path; } catch {}
  if (mine !== S.gen) return;                    // a new game started meanwhile
  if (!path) { btn.textContent = 'could not solve'; btn.disabled = false; return; }
  btn.classList.add('hidden');
  S.walk = { path, i: 0 };
  renderStep();
}

function revealNext() {
  if (!S.walk || S.walk.i >= S.walk.path.length - 1) return;
  S.walk.i++;
  renderStep();
}

$('#revealStart').addEventListener('click', revealBegin);
$('#revealNext').addEventListener('click', revealNext);

const leaveReveal = () => (S.round >= S.rounds ? finish() : newRound());
$('#skipReveal').addEventListener('click', leaveReveal);
$('#nextFromReveal').addEventListener('click', leaveReveal);

$('#newGame').addEventListener('click', () => {
  const midGame = S.round > 0 && $('#phFinal').classList.contains('hidden');
  if (midGame && !confirm('Start a new game? The current scores will be lost.')) return;
  clockStop();
  S.gen++;
  S.round = 0;
  $('#game').classList.add('hidden');
  $('#setup').classList.remove('hidden');
  $('#setupHint').textContent = '';
});
