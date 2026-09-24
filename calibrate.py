#!/usr/bin/env python3
"""Measure the real shortest-path distance distribution of the graph."""
import time, numpy as np
from wlgraph import Graph

g = Graph()
rng = np.random.default_rng(7)
# sample sources weighted toward real articles (skip dead ends)
live = np.nonzero(g.out_deg > 0)[0]
srcs = rng.choice(live, size=200, replace=False)

hist = np.zeros(64, dtype=np.int64)
unreach = 0
t0 = time.time()
for n, s in enumerate(srcs, 1):
    d = g.bfs(int(s))
    unreach += int((d < 0).sum())
    b = np.bincount(d[d >= 0], minlength=64)
    hist += b[:64]
    if n % 50 == 0:
        print(f'  {n}/200 sources, {time.time()-t0:.1f}s', flush=True)

tot = hist.sum()
print(f'\n{200} sources x {g.N:,} targets = {200*g.N:,} pairs, {time.time()-t0:.1f}s')
print(f'unreachable: {unreach/(200*g.N)*100:.2f}%\n')
print(' d      pairs      share    cumulative')
cum = 0
for d in range(1, 64):
    if hist[d] == 0:
        continue
    cum += hist[d]
    print(f'{d:2d}  {hist[d]:12,}  {hist[d]/tot*100:6.2f}%  {cum/tot*100:7.2f}%')
