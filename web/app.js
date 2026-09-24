'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];

const S = {
  players: [], rounds: 5, difficulty: 'easy',
  round: 0, puzzle: null,
  t0: 0, elapsed: 0, running: false, raf: null, claim: null, lastChain: null,
  limitMs: 300000, gen: 0, walk: null
};

/* ─────────────────────────── setup ─────────────────────────── */
const seats = $('#players');
for (let i = 0; i < 6; i++) {
  const inp = document.createElement('input');
  inp.placeholder = `Player ${i + 1}`;
  inp.maxLength = 18;
  inp.addEventListener('keydown', e => { if (e.key === 'Enter') $('#start').click(); });
  seats.appendChild(inp);
}

$('#difficulty').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  $$('#difficulty button').forEach(x => x.classList.toggle('on', x === b));
  S.difficulty = b.dataset.d;
});

$('#start').addEventListener('click', () => {
  const names = $$('#players input').map(i => i.value.trim()).filter(Boolean);
  if (names.length < 1) { $('#setupHint').textContent = 'Add at least one player.'; return; }
  if (new Set(names.map(n => n.toLowerCase())).size !== names.length) {
    $('#setupHint').textContent = 'Player names must be different.'; return;
  }
  S.players = names.map(n => ({ name: n, pts: 0 }));
  S.rounds = +$('#rounds').value;
  S.limitMs = (+$('#limit').value) * 60000;
  S.round = 0;
  $('#rt').textContent = S.rounds;
  $('#diffPill').textContent = S.difficulty.toUpperCase();
  $('#setup').classList.add('hidden');
  $('#game').classList.remove('hidden');
  renderScores();
  saveGame();
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
  enterReveal("Time's up — nobody linked it.");
}
function clockStart(resume = false) {
  S.t0 = performance.now() - (resume ? S.elapsed : 0);
  if (!resume) S.elapsed = 0;
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
const PHASES = ['phReady', 'phRunning', 'phWho', 'phVerify', 'phNext', 'phReveal', 'phFinal'];
const phase = id => PHASES.forEach(p => $('#' + p).classList.toggle('hidden', p !== id));

function renderScores() {
  const max = Math.max(0, ...S.players.map(p => p.pts));
  $('#scores').innerHTML = S.players.map(p =>
    `<span class="score${p.pts === max && max > 0 ? ' lead' : ''}">${esc(p.name)}<b class="pts">${p.pts}</b></span>`
  ).join('');
}
const esc = s => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

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
  S.claim = null;
  S.lastChain = null;
  S.walk = null;
  S.gen++;
  const lab = $('#pStart .plabel');
  lab.textContent = 'START'; lab.className = 'plabel start';
  $('#rn').textContent = S.round;
  $('#verdict').innerHTML = ''; $('#revealed').innerHTML = ''; $('#pathInput').value = '';
  phase('phReady');
  $('#startRound').disabled = true;
  $('#readyTitle').textContent = '…';
  $('#readyUrl').textContent = '';
  const clk = $('#clock');
  clk.textContent = '0:00.0';
  clk.classList.remove('stopped', 'expired', 'warning');
  clk.classList.add('idle');
}

function showPuzzle(p) {
  S.puzzle = p;
  fillPanel('#pStart', p.start);
  fillPanel('#pFinish', p.finish);
  $('#readyTitle').textContent = p.start.title;
  $('#readyUrl').textContent = p.start.url;
  $('#startRound').disabled = false;
}

async function newRound() {
  S.round++;
  S.puzzle = null;
  resetRoundUI();
  saveGame();
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
  saveGame();                       // store the challenge, so a reload keeps it
}

$('#startRound').addEventListener('click', () => {
  if ($('#startRound').disabled) return;
  $('#clock').classList.remove('idle');
  phase('phRunning');
  clockStart();
});

/* ─────────────────────── linked / claiming ─────────────────────── */
$('#linked').addEventListener('click', () => {
  if (!S.running) return;
  clockStop();
  S.claim = { ms: S.elapsed, who: null };
  $('#whoButtons').innerHTML = S.players.map((p, i) =>
    `<button data-i="${i}">${i + 1}. ${esc(p.name)}</button>`).join('');
  phase('phWho');
});
$('#whoCancel').addEventListener('click', () => { phase('phRunning'); clockStart(true); });
$('#whoButtons').addEventListener('click', e => {
  const b = e.target.closest('button'); if (b) pickWinner(+b.dataset.i);
});
function pickWinner(i) {
  S.claim.who = i;
  $('#claimant').textContent = S.players[i].name;
  $('#claimTime').textContent = fmt(S.claim.ms);
  $('#verdict').innerHTML = '';
  phase('phVerify');
  $('#pathInput').focus();
}

$('#giveup').addEventListener('click', () => {
  clockStop();
  enterReveal('Nobody got it.');
});

/* ─────────────────────────── verify ─────────────────────────── */
$('#doVerify').addEventListener('click', async () => {
  const body = {
    start: S.puzzle.start.slug, finish: S.puzzle.finish.slug,
    path: $('#pathInput').value
  };
  $('#verdict').innerHTML = '<div class="small">checking…</div>';
  let r;
  try {
    r = await (await fetch('/api/verify', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    })).json();
  } catch { $('#verdict').innerHTML = '<div class="msg no">Engine unreachable.</div>'; return; }

  if (r.error) { $('#verdict').innerHTML = `<div class="msg no">${esc(r.error)}</div>`; return; }

  const chain = r.steps.map((s, i) =>
    `<span class="hop ${s.ok ? 'ok' : 'no'}">` +
    (i === 0 ? `<span class="n">${esc(s.from)}</span>` : '') +
    `<span class="lk">${s.ok ? '→' : '⊘'}</span><span class="n">${esc(s.to)}</span></span>`).join('');
  $('#verdict').innerHTML =
    `<div class="chain">${chain}</div>` +
    (r.ok
      ? `<div class="msg ok">Valid path — ${r.hops} link${r.hops > 1 ? 's' : ''}. Point to ${esc(S.players[S.claim.who].name)}.</div>`
      : `<div class="msg no">Broken link marked ⊘ — no point yet. Fix the path and verify again.</div>`) +
    ((r.corrections && r.corrections.length)
      ? `<div class="small corr">read ` + r.corrections.map(c =>
          `“${esc(c.typed)}” as <b>${esc(c.resolved)}</b>`).join(', ') + `</div>`
      : '');
  if (r.ok) { S.lastChain = chain; setTimeout(() => award(S.claim.who, r.hops), 1800); }
});

$('#skipVerify').addEventListener('click', () => { S.lastChain = null; award(S.claim.who, null); });
$('#wrongPerson').addEventListener('click', () => phase('phWho'));

function award(i, hops) {
  S.players[i].pts++;
  renderScores();
  saveGame();
  $('#roundSummary').innerHTML =
    `<div class="won"><b>${esc(S.players[i].name)}</b> takes round ${S.round} in ${fmt(S.claim.ms)}` +
    (hops ? ` — ${hops} links` : '') + `</div>` +
    (S.lastChain ? `<div class="chain">${S.lastChain}</div>` : '');
  phase('phNext');
}

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
  clearSave();
  const max = Math.max(...S.players.map(p => p.pts));
  const champs = S.players.filter(p => p.pts === max);
  const table = [...S.players].sort((a, b) => b.pts - a.pts)
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
  offerResume();
});

/* ─────────────────────────── keyboard ─────────────────────────── */
document.addEventListener('keydown', e => {
  if ($('#game').classList.contains('hidden')) return;
  const typing = ['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName);
  if (e.code === 'Space' && !typing) {
    if (S.running) { e.preventDefault(); $('#linked').click(); }
    else if (!$('#phReady').classList.contains('hidden')) { e.preventDefault(); $('#startRound').click(); }
  }
  if (!$('#phWho').classList.contains('hidden') && /^[1-6]$/.test(e.key)) {
    const i = +e.key - 1; if (i < S.players.length) pickWinner(i);
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

/* ─────────── nobody got it: step through the answer, one click at a time ─────────── */
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
  offerResume();
});

/* ───────────── keep the game across reloads ───────────── */
const SAVE_KEY = 'wikilinks.save';

function saveGame() {
  try {
    localStorage.setItem(SAVE_KEY, JSON.stringify({
      players: S.players, rounds: S.rounds, difficulty: S.difficulty,
      limitMs: S.limitMs, round: S.round, puzzle: S.puzzle
    }));
  } catch {}
}
function readSave() {
  try {
    const s = JSON.parse(localStorage.getItem(SAVE_KEY) || 'null');
    return (s && Array.isArray(s.players) && s.players.length && s.round <= s.rounds) ? s : null;
  } catch { return null; }
}
function clearSave() { try { localStorage.removeItem(SAVE_KEY); } catch {} }

function offerResume() {
  const s = readSave();
  if (!s) { $('#resumeBox').classList.add('hidden'); return; }
  $('#resumeText').innerHTML =
    `Game in progress — round ${Math.max(1, s.round)} of ${s.rounds}, ${s.difficulty}. ` +
    s.players.map(p => `${esc(p.name)} <b>${p.pts}</b>`).join(' · ') +
    (s.puzzle && s.puzzle.start
      ? `<div class="small" style="margin-top:4px">resumes ${esc(s.puzzle.start.title)} → ${esc(s.puzzle.finish.title)}</div>`
      : '');
  $('#resumeBox').classList.remove('hidden');
}

$('#resumeBtn').addEventListener('click', () => {
  const s = readSave();
  if (!s) return;
  S.players = s.players; S.rounds = s.rounds;
  S.difficulty = s.difficulty; S.limitMs = s.limitMs;
  $('#rt').textContent = S.rounds;
  $('#diffPill').textContent = S.difficulty.toUpperCase();
  $('#setup').classList.add('hidden');
  $('#game').classList.remove('hidden');
  renderScores();
  if (s.puzzle && s.puzzle.start && s.puzzle.finish) {
    S.round = s.round;                       // same round, same challenge
    resetRoundUI();
    showPuzzle(s.puzzle);
  } else {
    S.round = Math.max(0, s.round - 1);      // older save: no challenge stored
    newRound();
  }
});
$('#discardBtn').addEventListener('click', () => { clearSave(); offerResume(); });

offerResume();
