#!/usr/bin/env python3
"""Export redirect-title -> canonical-title so verification accepts either form."""
import gzip, re, os, time
HERE = os.path.dirname(os.path.abspath(__file__))
DATA, OUT = os.path.join(HERE, 'data'), os.path.join(HERE, 'build')

_ESCB = {b'n': b'\n', b't': b'\t', b'r': b'\r', b'0': b'\x00', b'\\': b'\\',
         b"'": b"'", b'"': b'"', b'Z': b'\x1a', b'b': b'\x08'}
_esc = re.compile(rb"\\(.)")
def unesc(b):
    if b'\\' in b:
        b = _esc.sub(lambda m: _ESCB.get(m.group(1), m.group(1)), b)
    return b.decode('utf-8', 'replace')

def lines(n):
    with gzip.open(os.path.join(DATA, n), 'rb') as f:
        for ln in f:
            if ln.startswith(b'INSERT INTO'):
                yield ln

PAGE = re.compile(rb"\((\d+),(\d+),'((?:[^'\\]|\\.)*)',([01])")
RED = re.compile(rb"\((\d+),(\d+),'((?:[^'\\]|\\.)*)'")

art, red, t2id, id2t = set(), set(), {}, {}
for ln in lines('simplewiki-page.sql.gz'):
    for m in PAGE.finditer(ln):
        if m.group(2) != b'0':
            continue
        pid, t = int(m.group(1)), unesc(m.group(3))
        t2id[t] = pid; id2t[pid] = t
        (red if m.group(4) == b'1' else art).add(pid)

tgt = {}
for ln in lines('simplewiki-redirect.sql.gz'):
    for m in RED.finditer(ln):
        if m.group(2) == b'0':
            tgt[int(m.group(1))] = unesc(m.group(3))

def canon(pid):
    seen = set()
    for _ in range(5):
        if pid in art:
            return pid
        if pid not in red or pid in seen:
            return None
        seen.add(pid)
        nxt = t2id.get(tgt.get(pid, ''))
        if nxt is None:
            return None
        pid = nxt
    return None

n = 0
with open(os.path.join(OUT, 'redirects.tsv'), 'w', encoding='utf-8') as f:
    for pid in red:
        c = canon(pid)
        if c is not None:
            f.write(f'{id2t[pid]}\t{id2t[c]}\n'); n += 1
print(f'wrote {n:,} redirect mappings')
