"""Forgiving article-title matching.

Players type from memory, so verification accepts more than exact slugs. Tiers,
best first:

  exact          Battle_of_Vigo_Bay / "battle of vigo bay"
  normalized     accents, punctuation and case ignored: "Stepanka Kucerova"
  redirect       any redirect alias for the article
  disambiguation the typed name is the part before a comma or bracket:
                 "Groveland" -> "Groveland, Massachusetts"
  typo           small edit distance, scaled to word length

Ambiguity is left for the caller to settle: `candidates` returns every plausible
node and the chain solver keeps whichever one is actually linked.
"""
import re, unicodedata
from collections import defaultdict

_strip = re.compile(r'[^a-z0-9 ]+')
_ws = re.compile(r'\s+')

def norm(s):
    s = unicodedata.normalize('NFKD', s.replace('_', ' '))
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    return _ws.sub(' ', _strip.sub(' ', s)).strip()

def base_of(s):
    """The part before the first comma or opening bracket."""
    return norm(re.split(r'\s*[,(]', s.replace('_', ' '))[0])

def max_edits(n):
    return 1 if n <= 8 else 2 if n <= 16 else 3

def lev(a, b, maxd):
    """Levenshtein distance, abandoned early once it exceeds maxd."""
    la, lb = len(a), len(b)
    if abs(la - lb) > maxd:
        return maxd + 1
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [maxd + 1] * lb
        lo, hi = max(1, i - maxd), min(lb, i + maxd)
        for j in range(lo, hi + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1,
                         prev[j - 1] + (a[i - 1] != b[j - 1]))
        if min(cur[lo:hi + 1], default=maxd + 1) > maxd:
            return maxd + 1
        prev = cur
    return prev[lb]

class Matcher:
    def __init__(self, G, redirects):
        self.G = G
        self.norms = [norm(t) for t in G.titles]
        self.by_norm = defaultdict(set)
        self.by_base = defaultdict(set)
        self.buckets = defaultdict(list)
        for i, nt in enumerate(self.norms):
            if not nt:
                continue
            self.by_norm[nt].add(i)
            self.buckets[(nt[0], len(nt))].append(i)
            b = base_of(G.titles[i])
            if b and b != nt:
                self.by_base[b].add(i)
        for alias, target in redirects.items():
            j = G.index.get(target)
            if j is not None:
                na = norm(alias)
                if na:
                    self.by_norm[na].add(j)
                    ba = base_of(alias)
                    if ba and ba != na:
                        self.by_base[ba].add(j)

    def candidates(self, text, limit=12):
        """[(node, score, kind)] for a typed fragment, best first."""
        raw = text.strip()
        if not raw:
            return []
        out, seen = [], set()

        def add(node, score, kind):
            if node not in seen:
                seen.add(node); out.append((node, score, kind))

        # exact title / slug, before any normalisation
        t = raw.replace(' ', '_').strip('_')
        for v in (t, t[:1].upper() + t[1:]):
            if v in self.G.index:
                add(self.G.index[v], 100, 'exact')

        nt = norm(raw)
        if not nt:
            return out[:limit]
        for i in self.by_norm.get(nt, ()):
            add(i, 92, 'exact' if self.norms[i] == nt and not out else 'normalized')
        for i in self.by_base.get(nt, ()):
            add(i, 80, 'disambiguation')

        if out:
            return out[:limit]

        # nothing matched cleanly - look for a typo, within the same first
        # letter and a narrow length window to keep the scan small
        md = max_edits(len(nt))
        hits = []
        for L in range(max(1, len(nt) - md), len(nt) + md + 1):
            for i in self.buckets.get((nt[0], L), ()):
                d = lev(nt, self.norms[i], md)
                if d <= md:
                    hits.append((d, i))
        hits.sort()
        for d, i in hits[:limit]:
            add(i, 70 - 10 * d, 'typo')
        return out[:limit]

    def best(self, text):
        c = self.candidates(text, limit=1)
        return c[0][0] if c else None
