"""Shared graph loading + BFS for the Wikilinks engine."""
import os, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, 'build')

class Graph:
    def __init__(self):
        z = np.load(os.path.join(BUILD, 'graph.npz'))
        self.indptr = z['indptr']
        self.indices = z['indices']
        with open(os.path.join(BUILD, 'titles.txt'), encoding='utf-8') as f:
            self.titles = f.read().split('\n')
        self.N = len(self.titles)
        self.index = {t: i for i, t in enumerate(self.titles)}
        self.lower = {t.lower(): i for i, t in enumerate(self.titles)}
        self.out_deg = np.diff(self.indptr)
        self.in_deg = np.bincount(self.indices, minlength=self.N)

    def neighbors(self, u):
        return self.indices[self.indptr[u]:self.indptr[u + 1]]

    def has_edge(self, u, v):
        nb = self.neighbors(u)
        i = np.searchsorted(nb, v)
        return bool(i < nb.size and nb[i] == v)

    def bfs(self, src):
        """Distances from src to every node (-1 = unreachable), as int16."""
        dist = np.full(self.N, -1, dtype=np.int16)
        dist[src] = 0
        frontier = np.array([src], dtype=np.int32)
        d = 0
        while frontier.size:
            d += 1
            counts = (self.indptr[frontier + 1] - self.indptr[frontier]).astype(np.int64)
            total = int(counts.sum())
            if total == 0:
                break
            cum = np.cumsum(counts)
            offs = np.arange(total, dtype=np.int64) - np.repeat(cum - counts, counts)
            nb = self.indices[np.repeat(self.indptr[frontier], counts) + offs]
            nb = nb[dist[nb] < 0]
            if nb.size == 0:
                break
            nb = np.unique(nb)
            dist[nb] = d
            frontier = nb
        return dist

    def path(self, src, dst, dist=None):
        """Reconstruct one shortest path src->dst by walking distances backwards."""
        if dist is None:
            dist = self.bfs(src)
        if dist[dst] < 0:
            return None
        out = [dst]
        cur = dst
        while cur != src:
            d = dist[cur]
            prev = None
            cand = np.nonzero(dist == d - 1)[0]
            for u in cand:
                if self.has_edge(u, cur):
                    prev = u
                    break
            if prev is None:
                return None
            out.append(int(prev)); cur = int(prev)
        return out[::-1]
