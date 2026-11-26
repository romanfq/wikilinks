'use strict';
// Runs on every ZIM-served /wiki/<title> article page. Keeps the goal banner's
// timer in sync with the server-tracked round clock, and — since a player
// sitting on an article page otherwise has no way to know the round ended —
// puts up a "New round" notice once it does. It's a non-blocking bar, not a
// modal: players often want to keep clicking around and find the solution
// themselves after the round's over, so it never intercepts navigation —
// it's just there to click whenever they're ready to move on.
(function () {
  const YELLOW_AT_FRAC = 0.5;    // of however long this round's limit is
  const RED_AT_FRAC = 0.8;
  const POLL_MS = 5000;          // network round-trip; the on-screen clock
                                  // ticks locally between polls and just
                                  // jumps to the fresh value when one lands

  let last = null;     // most recent /api/live response
  let lastAt = 0;       // Date.now() when it arrived
  let bar = null;       // the "round's over" bar, once shown

  function banner() { return document.querySelector('.wl-banner'); }

  function fmt(ms) {
    const s = Math.ceil(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  }

  function renderTimer(remainingMs, limitMs) {
    const b = banner();
    if (!b || b.classList.contains('wl-win') || !limitMs || remainingMs == null) return;
    let timer = b.querySelector('.wl-timer');
    if (!timer) {
      b.appendChild(document.createTextNode(' · '));
      timer = document.createElement('span');
      timer.className = 'wl-timer';
      b.appendChild(timer);
    }
    timer.textContent = 'in ' + fmt(remainingMs);
    const frac = (limitMs - remainingMs) / limitMs;
    timer.classList.toggle('wl-yellow', frac >= YELLOW_AT_FRAC && frac < RED_AT_FRAC);
    timer.classList.toggle('wl-red', frac >= RED_AT_FRAC);
  }

  function showRoundOverBar() {
    if (bar) return;
    const won = !!(banner() && banner().classList.contains('wl-win'));
    bar = document.createElement('div');
    bar.className = 'wl-endbar';
    bar.innerHTML = `
      <span class="wl-endbar-text">${won ? '🎉 You linked it!' : "Round's over"} — explore or</span>
      <button class="wl-endbar-btn">New round</button>`;
    bar.querySelector('.wl-endbar-btn').addEventListener('click', () => { location.href = '/play'; });
    document.body.appendChild(bar);
  }

  function hideRoundOverBar() {
    if (!bar) return;
    bar.remove();
    bar = null;
  }

  // Runs every second using only the last poll result, extrapolated by
  // however long it's been since it arrived — no network call.
  function renderTick() {
    if (!last || last.phase !== 'running') return;
    const guessed = last.remaining_ms == null ? null
      : Math.max(0, last.remaining_ms - (Date.now() - lastAt));
    renderTimer(guessed, last.limit_ms);
  }

  async function poll() {
    let r;
    try { r = await (await fetch('/api/live')).json(); } catch { return; }
    last = r; lastAt = Date.now();          // next fresh value always wins — jumps are fine
    if (r.phase !== 'running') {
      showRoundOverBar();
      return;
    }
    hideRoundOverBar();                     // a new round started while this page sat open
    renderTimer(r.remaining_ms, r.limit_ms);
  }

  setInterval(poll, POLL_MS);
  setInterval(renderTick, 1000);
  poll();
})();
