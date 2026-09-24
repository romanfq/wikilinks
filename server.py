#!/usr/bin/env python3
"""Wikilinks game server.

Serves the web UI and three endpoints:
  GET  /api/puzzle?difficulty=easy|medium|hard  -> a start/finish pair with a known distance
  POST /api/verify   {start, finish, path}      -> checks every hop of a claimed path
  GET  /api/path?start=&finish=                 -> reveals one shortest path

Run:  python3 server.py  [--port 8000]
"""
import argparse, json, os, re, sys, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote
import numpy as np
from wlgraph import Graph
from matching import Matcher

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, 'web')

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

print('indexing titles for forgiving matching ...', flush=True)
M = Matcher(G, RED)
print('matcher ready', flush=True)

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

def card(i):
    return {'slug': slug_of(i), 'title': pretty(i),
            'url': f'https://simple.wikipedia.org/wiki/{slug_of(i)}'}

def make_puzzle(diff):
    lo, hi = BANDS[diff]
    for _ in range(400):
        s = int(_rng.choice(START_POOL))
        d = G.bfs(s)
        cand = np.nonzero((d >= lo) & (d <= hi) & OK_TARGET)[0]
        if cand.size == 0:
            continue
        f = int(_rng.choice(cand))
        return {'start': card(s), 'finish': card(f),
                'distance': int(d[f]), 'difficulty': diff}
    return None

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

def solve_chain(toks, s, f, max_span):
    """Find a reading of the typed tokens that forms a genuinely linked chain.

    Each token may be fuzzy ("Groveland") and may need joining with its
    neighbours ("Groveland", "Massachusetts"). Rather than guess, we search:
    a candidate is only accepted if the previous article actually links to it,
    so the graph settles the ambiguity. Returns [(node, score, kind, typed)].
    """
    n = len(toks)
    memo = {}

    def rec(i, prev):
        if i == n:
            return [] if (prev == f or G.has_edge(prev, f)) else None
        key = (i, prev)
        if key in memo:
            return memo[key]
        found = None
        for span in range(min(max_span, n - i), 0, -1):
            frag = ', '.join(toks[i:i + span])
            for node, score, kind in M.candidates(frag):
                if node != prev and not G.has_edge(prev, node):
                    continue
                rest = rec(i + span, node)
                if rest is not None:
                    found = [(node, score, kind, frag)] + rest
                    break
            if found:
                break
        memo[key] = found
        return found
    return rec(0, s)

def _dedupe(chain):
    out = [chain[0]]
    for x in chain[1:]:
        if x != out[-1]:
            out.append(x)
    return out

def _steps(chain):
    return [{'from': pretty(a), 'to': pretty(b),
             'ok': bool(G.has_edge(a, b))} for a, b in zip(chain, chain[1:])]

def verify(start, finish, raw_path):
    s = resolve(start) or M.best(start)
    f = resolve(finish) or M.best(finish)
    if s is None or f is None:
        return {'ok': False, 'error': 'Could not resolve the round endpoints.'}
    txt = (raw_path or '').strip()
    if '\n' in txt:                       # one article per line: unambiguous
        toks, max_span = [t.strip() for t in txt.split('\n') if t.strip()], 1
    else:
        toks, max_span = [t.strip() for t in txt.split(',') if t.strip()], 3
    if not toks:
        return {'ok': False, 'error': 'Enter the path you took.'}

    sol = solve_chain(toks, s, f, max_span)
    if sol is not None:
        chain = _dedupe([s] + [n for n, _, _, _ in sol] + [f])
        return {'ok': True, 'steps': _steps(chain), 'hops': len(chain) - 1,
                'chain': [pretty(n) for n in chain],
                'corrections': [{'typed': frag, 'resolved': pretty(n)}
                                for n, _, kind, frag in sol if kind != 'exact']}

    # No valid reading: resolve as best we can so the break can be shown.
    nodes, unknown, i = [], [], 0
    while i < len(toks):
        for span in range(min(max_span, len(toks) - i), 0, -1):
            c = M.candidates(', '.join(toks[i:i + span]), limit=1)
            if c:
                nodes.append(c[0][0]); i += span; break
        else:
            unknown.append(toks[i]); i += 1
    if unknown:
        return {'ok': False, 'error': 'No such article: ' + ', '.join(unknown[:5]),
                'unknown': unknown}
    chain = _dedupe([s] + nodes + [f])
    return {'ok': False, 'steps': _steps(chain), 'hops': len(chain) - 1,
            'chain': [pretty(n) for n in chain]}

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

    def _send(self, code, body, ctype='application/json'):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == '/api/puzzle':
            diff = (q.get('difficulty', ['easy'])[0]).lower()
            if diff not in BANDS:
                return self._send(400, {'error': 'bad difficulty'})
            p = make_puzzle(diff)
            return self._send(200 if p else 503,
                              p or {'error': 'no puzzle found, try again'})
        if u.path == '/api/path':
            p = shortest(q.get('start', [''])[0], q.get('finish', [''])[0])
            return self._send(200, {'path': p})
        path = '/index.html' if u.path == '/' else u.path
        fp = os.path.normpath(os.path.join(WEB, path.lstrip('/')))
        if not fp.startswith(WEB) or not os.path.isfile(fp):
            return self._send(404, 'not found', 'text/plain')
        with open(fp, 'rb') as f:
            self._send(200, f.read(), MIME.get(os.path.splitext(fp)[1], 'application/octet-stream'))

    def do_POST(self):
        if urlparse(self.path).path != '/api/verify':
            return self._send(404, {'error': 'not found'})
        n = int(self.headers.get('Content-Length', 0))
        try:
            body = json.loads(self.rfile.read(n) or b'{}')
        except json.JSONDecodeError:
            return self._send(400, {'error': 'bad json'})
        self._send(200, verify(body.get('start', ''), body.get('finish', ''),
                               body.get('path', '')))

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--port', type=int, default=8000)
    a = ap.parse_args()
    print(f'\n  Wikilinks -> http://localhost:{a.port}\n', flush=True)
    ThreadingHTTPServer(('127.0.0.1', a.port), Handler).serve_forever()
