#!/usr/bin/env python3
"""Wikilinks game server (v1.2 — LAN multiplayer, auto-tracked routes).

Serves the shared-screen UI, the player-facing join/race page, and article
content itself (from a local Kiwix ZIM, see zimcontent.py) so every hop a
player takes is observed server-side instead of trusting a typed-in route.

Endpoints:
  GET  /api/puzzle?difficulty=easy|medium|hard  -> a start/finish pair; also
                                                    arms a new round
  POST /api/start-round                         -> flips the round to running
  POST /api/end-round                           -> stops tracking the round
  POST /api/join   {name}                       -> registers a player, sets
                                                    a session cookie
  GET  /api/me                                   -> whether this session's
                                                    cookie still names a real
                                                    player (survives a round
                                                    ending, not a restart)
  POST /api/award  {token}                      -> manual point override
  POST /api/new-game                            -> resets scores/round
  GET  /api/live                                -> current round + roster
  GET  /api/host-info                           -> {base_url} for QR join —
                                                    an ngrok tunnel if one is
                                                    running (ngrok http PORT),
                                                    else the LAN address
  GET  /api/qr?text=...                         -> an SVG QR code
  GET  /wiki/<title>                             -> a ZIM article, tracked
  GET  /api/path?start=&finish=                 -> reveals one shortest path

Run:  python3 server.py  [--port 8000]
"""
import argparse, json, os, re, secrets, socket, sys, threading, time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote
import urllib.request
import numpy as np
from wlgraph import Graph
from zimcontent import ZimContent
import qrcodegen

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, 'web')
PORT = 8000

# Difficulty -> inclusive shortest-path distance band, exactly as specified.
# Measured on this graph: every band is reachable from essentially any start,
# and no pair anywhere exceeds d=14, so d>=20 can never be offered.
BANDS = {'easy': (1, 5), 'medium': (6, 8), 'hard': (9, 19)}

print('loading graph ...', flush=True)
G = Graph()
RED = {}
with open(os.path.join(HERE, 'build', 'redirects.tsv'), encoding='utf-8') as f:
    for line in f:
        a, _, b = line.rstrip('\n').partition('\t')
        if b:
            RED[a] = b
RED_LOWER = {k.lower(): v for k, v in RED.items()}

# Pages that make dull endpoints: years, decades, and list/index articles.
_DULL = re.compile(r'^(\d{1,4}(s|_BC)?|List_of_.*|Index_of_.*|\d{1,2}_[A-Z][a-z]+)$')
_dull_mask = np.array([bool(_DULL.match(t)) for t in G.titles])
OK_START = (G.out_deg >= 10) & (G.in_deg >= 5) & ~_dull_mask
OK_TARGET = (G.in_deg >= 3) & ~_dull_mask
START_POOL = np.nonzero(OK_START)[0]
print(f'ready: {G.N:,} articles, {len(G.indices):,} links, '
      f'{len(START_POOL):,} usable starts, {len(RED):,} redirects', flush=True)

ZIM_PATH = os.path.join(HERE, 'data', 'wikipedia.zim')
if not os.path.isfile(ZIM_PATH):
    sys.exit(f'Missing {ZIM_PATH} — run ./setup.sh first '
              f'(downloads the article content, ~990 MB).')
print('loading article content ...', flush=True)
ZIM = ZimContent(ZIM_PATH)
print('content ready', flush=True)

_rng = np.random.default_rng()
_rev = None
_rev_lock = threading.Lock()


def reverse_graph():
    """Lazily build the reverse CSR, used only for revealing a shortest path."""
    global _rev
    with _rev_lock:
        if _rev is None:
            src = np.repeat(np.arange(G.N, dtype=np.int32), G.out_deg)
            order = np.argsort(G.indices, kind='stable')
            rptr = np.zeros(G.N + 1, dtype=np.int64)
            np.cumsum(np.bincount(G.indices, minlength=G.N), out=rptr[1:])
            _rev = (rptr, src[order])
    return _rev


def slug_of(i):
    return G.titles[i]


def pretty(i):
    return G.titles[i].replace('_', ' ')


def pretty_of(slug):
    return slug.replace('_', ' ')


def _esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def card(i):
    return {'slug': slug_of(i), 'title': pretty(i),
            'url': f'https://simple.wikipedia.org/wiki/{slug_of(i)}'}


# ─────────────────────────── live round state ───────────────────────────

class GameState:
    """In-memory, server-authoritative round + roster.

    Replaces the old client-only 'shout it and type your route' flow: every
    joined phone's hops are logged here as they browse ZIM-served articles,
    and the first to reach the round's finish wins automatically. Memory
    only — a server restart loses the game, same as the graph load itself.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.phase = 'lobby'          # lobby | waiting | running | ended
        self.round = 0
        self.start = None             # card dict
        self.finish = None            # card dict
        self.winner = None            # token of this round's winner, once decided
        self.limit_ms = 0             # 0 = no time limit
        self.started_at = None        # time.time() when start_round() was called
        self.players = {}             # token -> {name, pts, hops, arrived_at}

    def join(self, name):
        token = secrets.token_urlsafe(12)
        with self.lock:
            self.players[token] = {
                'name': (name or 'Player')[:24], 'pts': 0,
                'hops': 0, 'arrived_at': None,
            }
        return token

    def player_name(self, token):
        """The joined name for a session token, or None if it isn't (or is
        no longer, e.g. after a server restart wiped in-memory state) valid."""
        with self.lock:
            p = self.players.get(token)
            return p['name'] if p else None

    def reset_round(self, start, finish):
        with self.lock:
            self.round += 1
            self.phase = 'waiting'
            self.start, self.finish = start, finish
            self.winner = None
            self.started_at = None
            for p in self.players.values():
                p['hops'] = 0
                p['arrived_at'] = None

    def start_round(self, limit_ms=0):
        with self.lock:
            self.phase = 'running'
            self.limit_ms = max(0, int(limit_ms or 0))
            self.started_at = time.time()

    def end_round(self):
        with self.lock:
            self.phase = 'ended'

    def record_hop(self, token, title):
        with self.lock:
            p = self.players.get(token)
            if p is None or self.phase != 'running':
                return
            p['hops'] += 1
            # First arrival wins and is awarded immediately — record_hop and
            # award() converge on the same effect so a natural arrival and a
            # manual override behave identically to the scoreboard.
            if self.winner is None and self.finish and title == self.finish['slug']:
                p['arrived_at'] = time.time()
                p['pts'] += 1
                self.winner = token
                self.phase = 'ended'

    def award(self, token):
        with self.lock:
            p = self.players.get(token)
            if p is None or self.winner is not None:
                return False
            p['pts'] += 1
            if p['arrived_at'] is None:
                p['arrived_at'] = time.time()
            self.winner = token
            self.phase = 'ended'
            return True

    def new_game(self):
        with self.lock:
            self.round = 0
            for p in self.players.values():
                p['pts'] = 0

    def snapshot(self):
        with self.lock:
            remaining_ms = None
            if self.phase == 'running' and self.started_at and self.limit_ms:
                elapsed_ms = (time.time() - self.started_at) * 1000
                remaining_ms = max(0, int(self.limit_ms - elapsed_ms))
            return {
                'phase': self.phase, 'round': self.round,
                'start': self.start, 'finish': self.finish,
                'winner_token': self.winner,
                'limit_ms': self.limit_ms, 'remaining_ms': remaining_ms,
                'players': [{'token': t, 'name': p['name'], 'pts': p['pts'],
                             'hops': p['hops'], 'arrived': p['arrived_at'] is not None}
                            for t, p in self.players.items()],
            }


GAME = GameState()


def lan_ip():
    """The IP other devices on the LAN would use to reach this machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))   # no packet actually sent; just picks the interface
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()


def ngrok_url():
    """The public https URL of a locally running `ngrok http <port>`, if any.

    Queries ngrok's own local status API (its inspector, always on
    127.0.0.1:4040) rather than managing an ngrok subprocess ourselves — the
    host just runs ngrok in another terminal when LAN join doesn't reach a
    player's phone (e.g. a VPN or isolated Wi-Fi swallows the connection).
    """
    try:
        with urllib.request.urlopen('http://127.0.0.1:4040/api/tunnels', timeout=0.4) as r:
            tunnels = json.loads(r.read())['tunnels']
    except Exception:
        return None
    for t in tunnels:
        if t.get('proto') == 'https' and str(t.get('config', {}).get('addr', '')).endswith(str(PORT)):
            return t['public_url']
    return tunnels[0]['public_url'] if tunnels else None


def qr_svg(text, border=2):
    qr = qrcodegen.QrCode.encode_text(text, qrcodegen.QrCode.Ecc.MEDIUM)
    n = qr.get_size()
    parts = [f'M{x},{y}h1v1h-1z' for y in range(n) for x in range(n) if qr.get_module(x, y)]
    size = n + border * 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
            f'shape-rendering="crispEdges">'
            f'<rect width="100%" height="100%" fill="#fff"/>'
            f'<path d="{" ".join(parts)}" fill="#000" transform="translate({border},{border})"/>'
            f'</svg>')


def resolve(raw):
    """Resolve a user-typed title or slug to a node index, following redirects."""
    t = unquote(raw.strip()).replace(' ', '_').strip('_')
    if not t:
        return None
    variants = [t, t[0].upper() + t[1:]]
    for v in variants:
        if v in G.index:
            return G.index[v]
        if v in RED and RED[v] in G.index:
            return G.index[RED[v]]
    low = t.lower()
    if low in G.lower:
        return G.lower[low]
    if low in RED_LOWER and RED_LOWER[low] in G.index:
        return G.index[RED_LOWER[low]]
    return None


def make_puzzle(diff):
    lo, hi = BANDS[diff]
    for _ in range(400):
        s = int(_rng.choice(START_POOL))
        d = G.bfs(s)
        cand = np.nonzero((d >= lo) & (d <= hi) & OK_TARGET)[0]
        if cand.size == 0:
            continue
        f = int(_rng.choice(cand))
        if not (ZIM.has(slug_of(s)) and ZIM.has(slug_of(f))):
            continue
        return {'start': card(s), 'finish': card(f),
                'distance': int(d[f]), 'difficulty': diff}
    return None


def shortest(start, finish):
    s, f = resolve(start), resolve(finish)
    if s is None or f is None:
        return None
    d = G.bfs(s)
    if d[f] < 0:
        return None
    rptr, rsrc = reverse_graph()
    out, cur = [f], f
    while cur != s:
        preds = rsrc[rptr[cur]:rptr[cur + 1]]
        hit = preds[d[preds] == d[cur] - 1]
        if hit.size == 0:
            return None
        cur = int(hit[0]); out.append(cur)
    return [card(i) for i in reversed(out)]


MIME = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
        '.css': 'text/css; charset=utf-8', '.svg': 'image/svg+xml'}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype='application/json', extra_headers=()):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        for k, v in extra_headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get('Content-Length', 0))
        try:
            return json.loads(self.rfile.read(n) or b'{}')
        except json.JSONDecodeError:
            return {}

    def _player_token(self):
        c = SimpleCookie(self.headers.get('Cookie', ''))
        return c['pid'].value if 'pid' in c else None

    def _serve_wiki(self, raw_title):
        title = unquote(raw_title).replace('/', ' ')
        art = ZIM.get(title)
        if art is None:
            return self._send(404, 'Article not found in the local content.', 'text/plain')
        token = self._player_token()
        if token:
            GAME.record_hop(token, art['title'])
        finish = GAME.finish
        if finish and art['title'] == finish['slug']:
            banner = '<div class="wl-banner wl-win">🎉 You linked it! Tell the room.</div>'
        elif finish:
            banner = f'<div class="wl-banner">Get to: <b>{_esc(pretty_of(finish["slug"]))}</b></div>'
        else:
            banner = ''
        page = (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{art["title"].replace("_", " ")}</title>'
            '<link rel="stylesheet" href="/wiki.css"></head>'
            f'<body>{banner}<article>{art["html"]}</article>'
            f'<script src="/wiki.js"></script></body></html>'
        )
        return self._send(200, page, 'text/html; charset=utf-8')

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)

        if u.path == '/api/puzzle':
            diff = (q.get('difficulty', ['easy'])[0]).lower()
            if diff not in BANDS:
                return self._send(400, {'error': 'bad difficulty'})
            p = make_puzzle(diff)
            if p:
                GAME.reset_round(p['start'], p['finish'])
            return self._send(200 if p else 503,
                              p or {'error': 'no puzzle found, try again'})
        if u.path == '/api/path':
            p = shortest(q.get('start', [''])[0], q.get('finish', [''])[0])
            return self._send(200, {'path': p})
        if u.path == '/api/live':
            return self._send(200, GAME.snapshot())
        if u.path == '/api/me':
            name = GAME.player_name(self._player_token() or '')
            return self._send(200, {'joined': name is not None, 'name': name})
        if u.path == '/api/host-info':
            tunnel = ngrok_url()
            base = tunnel if tunnel else f'http://{lan_ip()}:{PORT}'
            return self._send(200, {'base_url': base, 'via_ngrok': bool(tunnel)})
        if u.path == '/api/qr':
            text = q.get('text', [''])[0]
            if not text:
                return self._send(400, {'error': 'missing text'})
            return self._send(200, qr_svg(text), 'image/svg+xml')
        if u.path.startswith('/wiki/'):
            return self._serve_wiki(u.path[len('/wiki/'):])

        path = {'/': '/index.html', '/play': '/play.html'}.get(u.path, u.path)
        fp = os.path.normpath(os.path.join(WEB, path.lstrip('/')))
        if not fp.startswith(WEB) or not os.path.isfile(fp):
            return self._send(404, 'not found', 'text/plain')
        with open(fp, 'rb') as f:
            self._send(200, f.read(), MIME.get(os.path.splitext(fp)[1], 'application/octet-stream'))

    def do_POST(self):
        path = urlparse(self.path).path

        if path == '/api/join':
            body = self._body()
            name = (body.get('name') or '').strip()
            if not name:
                return self._send(400, {'error': 'Enter a name.'})
            token = GAME.join(name)
            return self._send(200, {'ok': True},
                               extra_headers=[('Set-Cookie',
                                   f'pid={token}; Path=/; HttpOnly; SameSite=Lax')])
        if path == '/api/start-round':
            body = self._body()
            GAME.start_round(body.get('limit_ms', 0))
            return self._send(200, {'ok': True})
        if path == '/api/end-round':
            GAME.end_round()
            return self._send(200, {'ok': True})
        if path == '/api/award':
            body = self._body()
            ok = GAME.award(body.get('token', ''))
            return self._send(200 if ok else 404, {'ok': ok})
        if path == '/api/new-game':
            GAME.new_game()
            return self._send(200, {'ok': True})
        return self._send(404, {'error': 'not found'})


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8000)
    a = ap.parse_args()
    PORT = a.port
    print(f'\n  Wikilinks -> http://{lan_ip()}:{a.port}  (shared screen)'
          f'\n  Players join at the QR code shown there\n', flush=True)
    ThreadingHTTPServer(('0.0.0.0', a.port), Handler).serve_forever()
