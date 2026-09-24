#!/usr/bin/env python3
"""Build the Simple English Wikipedia article link graph from SQL dumps.

Reads the four dumps in data/ and writes build/graph.npz (CSR adjacency over
canonical namespace-0 articles) plus build/titles.txt (dense index -> title).

Redirects are resolved so that a link to a redirect counts as a link to its
target, and redirect pages themselves never appear as nodes.
"""
import gzip, re, os, time, warnings
import numpy as np
warnings.filterwarnings('ignore')

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
OUT = os.path.join(HERE, 'build')
os.makedirs(OUT, exist_ok=True)

def log(*a): print(f'[{time.strftime("%H:%M:%S")}]', *a, flush=True)

_ESCB = {b'n': b'\n', b't': b'\t', b'r': b'\r', b'0': b'\x00', b'\\': b'\\',
         b"'": b"'", b'"': b'"', b'Z': b'\x1a', b'b': b'\x08'}
_esc_re = re.compile(rb"\\(.)")
def unesc(b):
    if b'\\' in b:
        b = _esc_re.sub(lambda m: _ESCB.get(m.group(1), m.group(1)), b)
    return b.decode('utf-8', 'replace')

def parse_ints(buf):
    """Parse a comma-separated integer blob into an int64 array.

    np.fromstring's text mode is deprecated and may vanish in a future numpy,
    so fall back to a split-based parse if it is gone.
    """
    try:
        return np.fromstring(buf, dtype=np.int64, sep=',')
    except (AttributeError, DeprecationWarning, ValueError):
        return np.array(buf.split(b','), dtype=np.int64)

def insert_lines(name):
    with gzip.open(os.path.join(DATA, name), 'rb') as f:
        for line in f:
            if line.startswith(b'INSERT INTO'):
                yield line

PAGE_RE = re.compile(rb"\((\d+),(\d+),'((?:[^'\\]|\\.)*)',([01])")
RED_RE  = re.compile(rb"\((\d+),(\d+),'((?:[^'\\]|\\.)*)'")
LT_RE   = re.compile(rb"\((\d+),(\d+),'((?:[^'\\]|\\.)*)'\)")

# ---------------------------------------------------------------- page
log('parsing page ...')
art_title, red_pages, title2id = {}, set(), {}
for line in insert_lines('simplewiki-page.sql.gz'):
    for m in PAGE_RE.finditer(line):
        if m.group(2) != b'0':
            continue
        pid = int(m.group(1)); t = unesc(m.group(3))
        title2id[t] = pid
        if m.group(4) == b'1':
            red_pages.add(pid)
        else:
            art_title[pid] = t
log(f'  ns-0 articles {len(art_title):,}   redirect pages {len(red_pages):,}')

# ---------------------------------------------------------------- redirect
log('parsing redirect ...')
red_target = {}
for line in insert_lines('simplewiki-redirect.sql.gz'):
    for m in RED_RE.finditer(line):
        if m.group(2) != b'0':
            continue
        red_target[int(m.group(1))] = unesc(m.group(3))
log(f'  ns-0 redirects {len(red_target):,}')

def canon(pid, _max_hops=5):
    seen = set()
    for _ in range(_max_hops):
        if pid in art_title:
            return pid
        if pid not in red_pages:
            return None
        t = red_target.get(pid)
        if t is None:
            return None
        nxt = title2id.get(t)
        if nxt is None or nxt in seen:
            return None
        seen.add(nxt); pid = nxt
    return None

# ---------------------------------------------------------------- index
ids = sorted(art_title)
idx = {pid: i for i, pid in enumerate(ids)}
titles = [art_title[pid] for pid in ids]
N = len(ids)
log(f'  {N:,} nodes')

maxpid = ids[-1]
from_map = np.full(maxpid + 1, -1, dtype=np.int32)
for pid, i in idx.items():
    from_map[pid] = i

# ---------------------------------------------------------------- linktarget
log('parsing linktarget ...')
lt2node = {}
for line in insert_lines('simplewiki-linktarget.sql.gz'):
    for m in LT_RE.finditer(line):
        if m.group(2) != b'0':
            continue
        pid = title2id.get(unesc(m.group(3)))
        if pid is None:
            continue
        c = canon(pid)
        if c is not None:
            lt2node[int(m.group(1))] = idx[c]
log(f'  resolved link targets {len(lt2node):,}')

maxlt = max(lt2node)
lt_map = np.full(maxlt + 1, -1, dtype=np.int32)
for k, v in lt2node.items():
    lt_map[k] = v

# ---------------------------------------------------------------- pagelinks
log('parsing pagelinks ...')
eu, ev, raw = [], [], 0
for line in insert_lines('simplewiki-pagelinks.sql.gz'):
    p = line.find(b'VALUES ')
    if p < 0:
        continue
    s = line[p + 7:].rstrip().rstrip(b';').replace(b'(', b'').replace(b')', b'')
    a = parse_ints(s)
    if a.size % 3:
        continue
    a = a.reshape(-1, 3)
    raw += len(a)
    keep = (a[:, 1] == 0) & (a[:, 0] <= maxpid) & (a[:, 2] <= maxlt)
    a = a[keep]
    u = from_map[a[:, 0]]
    v = lt_map[a[:, 2]]
    k = (u >= 0) & (v >= 0) & (u != v)
    eu.append(u[k]); ev.append(v[k])
log(f'  raw rows {raw:,}')

U = np.concatenate(eu); V = np.concatenate(ev)
del eu, ev
log(f'  article->article edges {len(U):,} (pre-dedupe)')

key = np.unique(U.astype(np.int64) * N + V.astype(np.int64))
U = (key // N).astype(np.int32)
V = (key % N).astype(np.int32)
log(f'  unique edges {len(U):,}')

indptr = np.zeros(N + 1, dtype=np.int64)
np.cumsum(np.bincount(U, minlength=N), out=indptr[1:])
np.savez_compressed(os.path.join(OUT, 'graph.npz'), indptr=indptr, indices=V)
with open(os.path.join(OUT, 'titles.txt'), 'w', encoding='utf-8') as f:
    f.write('\n'.join(titles))

out_deg = np.diff(indptr)
log(f'done. nodes {N:,}  edges {len(V):,}  '
    f'mean out-degree {out_deg.mean():.1f}  median {int(np.median(out_deg))}  '
    f'dead ends {(out_deg == 0).sum():,}')
