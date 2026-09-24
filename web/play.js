'use strict';
const $ = s => document.querySelector(s);
const JOINED_KEY = 'wikilinks.joined';

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
  try { localStorage.setItem(JOINED_KEY, '1'); } catch {}
  enterWaitRoom();
}

function enterWaitRoom() {
  $('#join').classList.add('hidden');
  $('#wait').classList.remove('hidden');
  poll();
}

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

// A previous join in this browser already carries the session cookie —
// skip straight to the wait room instead of asking for the name again.
try { if (localStorage.getItem(JOINED_KEY)) enterWaitRoom(); } catch {}
