'use strict';
const $ = s => document.querySelector(s);

$('#joinBtn').addEventListener('click', join);
$('#nameInput').addEventListener('keydown', e => { if (e.key === 'Enter') join(); });

async function join() {
  const name = $('#nameInput').value.trim();
  if (!name) { $('#joinHint').textContent = 'Enter a name.'; return; }
  $('#joinBtn').disabled = true;
  try {
    const r = await (await fetch('/api/join', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name })
    })).json();
    if (!r.ok) {
      $('#joinHint').textContent = r.error || 'Could not join.';
      $('#joinBtn').disabled = false;
      return;
    }
  } catch {
    $('#joinHint').textContent = 'Could not reach the game — check you\'re on the right Wi-Fi.';
    $('#joinBtn').disabled = false;
    return;
  }
  enterWaitRoom();
}

function enterWaitRoom() {
  $('#join').classList.add('hidden');
  $('#wait').classList.remove('hidden');
  poll();
}

// If this browser's session cookie still names a real player on the current
// server (e.g. we're just back from a finished round, not a fresh visit or
// a server restart that wiped the roster), skip straight to the wait room
// instead of asking for the name again.
(async function checkExistingSession() {
  let r;
  try { r = await (await fetch('/api/me')).json(); } catch { return; }
  if (r && r.joined) enterWaitRoom();
})();

async function poll() {
  let r;
  try { r = await (await fetch('/api/live')).json(); } catch { r = null; }
  if (r && r.phase === 'running' && r.start) {
    location.href = '/wiki/' + r.start.slug;
    return;
  }
  if (r) {
    $('#waitText').textContent = r.phase === 'lobby'
      ? "You're in! Waiting for the host to start the game…"
      : 'Get ready — the round starts any second…';
  }
  setTimeout(poll, 1000);
}

