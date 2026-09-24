# Wikilinks

A party game for a room with one screen and several phones.

Two Wikipedia articles are put up side by side. Everyone races from the first to
the second **using only links inside the articles** — no search box, no URL bar.
First to arrive shouts **"Linked!"**

This app is the referee. It picks a pair that is provably connected, shows both
ends, runs the clock, keeps score, and checks the winner's route against the
real link graph so nobody can bluff.

Players race on **simple.wikipedia.org** in their own browsers. The app itself
is only ever on the shared screen.

---

## Requirements

* Python 3.9 or newer (tested on 3.11)
* numpy (the only third-party package)
* About 200 MB of disk and an internet connection for the one-time setup
* Any modern browser for the shared screen

## Install

```bash
pip3 install -r requirements.txt
./setup.sh
```

`setup.sh` downloads four Simple English Wikipedia SQL dumps (~150 MB) and
builds the link graph. It takes under a minute and is only needed once. Already
downloaded dumps are skipped, so it is safe to re-run.

If you were given a copy that already contains a `build/` folder, you can skip
`setup.sh` entirely — that folder is the whole dataset, about 23 MB.

## Run

```bash
python3 server.py            # http://localhost:8000
python3 server.py --port 9000
```

Give it about 30 seconds on startup: it loads 13 million links into memory and
indexes every title for fuzzy matching. It binds to `127.0.0.1` only.

The game engine is fully offline. The article previews on screen are fetched
live from simple.wikipedia.org, so without internet you get the puzzle and the
verification but no preview text.

---

## Playing a round

1. **Setup** — up to 6 player names, number of rounds (default 5), difficulty,
   and a time limit (default 5 minutes, or none).
2. **On your marks** — both articles appear, each with a clipped intro. The
   clock sits idle and the start article's full URL is displayed so everyone
   can load it on their phones. Nothing on screen hints at how long the answer
   is.
3. **Go** — press **Start round** (or the spacebar). Now the clock runs,
   turning amber for the last 30 seconds.
4. **Linked!** — when someone arrives they shout; the referee hits the
   **LINKED!** button or the spacebar, which stops the clock immediately. Then
   pick who got it — click their name or press **1**–**6**.
5. **Proof** — the winner types the route they took. The engine checks every
   hop against the link graph. A valid route scores 1 point; a broken hop is
   marked ⊘ so everyone can see exactly where the claim falls apart.

If nobody makes it — the referee presses **Nobody got it**, or the clock runs
out — the round ends with a **Reveal?** button. It puts the start article back
on the left, and each **Next →** click walks one hop along a shortest path, so
the table can work through the answer together and argue about it. The last
click lands on the finish article, now sitting on the left beside itself.

Two escape hatches: **Award without checking** gives the point anyway, and
**Skip to next round** abandons a reveal.

### Keyboard

| Key | Does |
|-----|------|
| `Space` | start the round, then stop it as **LINKED!** |
| `1`–`6` | pick the player who got it |
| `Enter` | next round, or advance the reveal |

## Difficulty

Bands are the shortest-path distance from start to finish, inclusive:

| Level | Links apart |
|-------|-------------|
| Easy | 1–5 |
| Medium | 6–8 |
| Hard | 9–19 |

Every offered pair is guaranteed to be connected, and the distance is exact —
it is a real breadth-first search over the whole graph, not an estimate. No
pair anywhere in this dataset exceeds 14, so a 20-link challenge can never
appear. Edit `BANDS` at the top of `server.py` to retune.

Be warned that hop count is a rough proxy for difficulty. A 4-link path to a
famous article is easy; a 4-link path to an obscure one can be brutal, because
players cannot see the shortest route from where they are standing.

## Typing the route

Comma separated (`Spain, Madrid, Prado`) or one article per line. The start and
finish may be left out. Matching is deliberately forgiving:

| Accepts | Example |
|---------|---------|
| exact title or slug | `Battle_of_Vigo_Bay` or `Battle of Vigo Bay` |
| any case, punctuation, accents | `stepanka kucerova` |
| redirects | clicked *USA*, typed `USA` |
| dropped disambiguators | `Chilton` → **Chilton, Wisconsin** |
| small typos | 1 edit up to 8 characters, 2 up to 16, 3 beyond |

Ambiguity is settled by the graph rather than by guessing: a candidate is only
accepted if the *previous* article actually links to it. So `Chilton` resolves
to whichever Chilton was reachable from where the player was, and a route that
only works under a wrong reading is still rejected. Anything the engine had to
interpret is reported back — *read "Chilton" as Chilton, Wisconsin*.

Titles containing commas are handled by trying to rejoin adjacent fragments;
put one article per line if you want to be certain. A typo in a title's first
letter will not be caught, as the typo search is bucketed by first character.

## Scores survive a reload

The game autosaves to browser local storage after every point and every round.
Close the tab or reload by accident and the setup screen offers to resume, next
to a **Discard** button. It names the challenge it will restore, and brings back
the scores, the round number **and the same pair of articles** — the clock
simply returns to the line so you can press **Start round** when everyone is
ready again. **New game**, top right, is available at all times and asks before
throwing a game away.

---

## Files

| Path | Purpose |
|------|---------|
| `setup.sh` | downloads the dumps and builds everything |
| `build_graph.py` | dumps → `build/graph.npz` (CSR adjacency) and `titles.txt` |
| `build_redirects.py` | dumps → `build/redirects.tsv` (alias → canonical title) |
| `wlgraph.py` | graph loading, vectorised BFS, shortest-path reconstruction |
| `matching.py` | forgiving title matching |
| `server.py` | HTTP server and game engine |
| `calibrate.py` | measures the distance distribution; how the bands were chosen |
| `web/` | the interface (no build step, no dependencies) |
| `data/` | downloaded dumps — disposable |
| `build/` | the generated graph — this *is* the dataset |

### HTTP endpoints

| Endpoint | Returns |
|----------|---------|
| `GET /api/puzzle?difficulty=easy\|medium\|hard` | a connected pair and its exact distance |
| `POST /api/verify` `{start, finish, path}` | per-hop validity, plus any fuzzy corrections |
| `GET /api/path?start=&finish=` | one shortest path as article cards |

## The dataset

Simple English Wikipedia, namespace 0, redirects resolved:

* **284,808 articles**, **12,952,908 links**
* mean out-degree 45.5, median 15, only 1,672 dead ends
* 114,654 redirect aliases accepted during verification
* 13.2% of ordered pairs have no path at all; only reachable pairs are ever offered

Shortest-path distances, sampled over 57 million pairs:

| Links apart | Share | | Links apart | Share |
|---|---|---|---|---|
| 3 | 9.5% | | 7 | 1.98% |
| 4 | 38.9% | | 8 | 0.43% |
| 5 | 37.3% | | 9–14 | 0.19% |
| 6 | 11.1% | | 20+ | none |

**Why not full English Wikipedia?** It was considered and rejected. The dumps
are 9.1 GB and take hours to process, and its far denser graph collapses almost
every pair into 3–5 hops, leaving no room for three distinct difficulty levels.
Simple English is sparser, which spreads the distances out and makes Hard
genuinely hard, while fitting in 23 MB.

## Refreshing the data

The graph is a snapshot, so live Wikipedia may grow links it does not know
about. If verification ever rejects a hop a player really clicked, use **Award
without checking** and refresh when convenient:

```bash
rm -rf data && ./setup.sh
```

## Troubleshooting

**`ModuleNotFoundError: No module named 'numpy'`** — `pip3 install -r requirements.txt`

**`FileNotFoundError: build/graph.npz`** — run `./setup.sh` first.

**Port already in use** — `python3 server.py --port 9000`.

**Startup takes ~30 seconds** — expected. It is loading the graph and indexing
284,808 titles. It only happens once per launch.

**Previews say "unavailable"** — no internet, or Wikipedia is unreachable. The
game still works; use the `open ↗` links.

**A hop was rejected that really exists** — almost always a snapshot that
predates a newly added link. Award the point manually and refresh the data.

## Licence and attribution

The graph is derived from Wikipedia, whose content is licensed
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). If you
redistribute the `build/` folder you are redistributing a derived database, so
keep this attribution with it. Dumps come from
[dumps.wikimedia.org](https://dumps.wikimedia.org/), which asks that you not
hammer it — `setup.sh` downloads each file once.

The game code carries no licence yet; add one before handing it out publicly.
