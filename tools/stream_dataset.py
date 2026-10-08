#!/usr/bin/env python3
"""The seed/variant reference streams (traces/streams, collected by
tools/run_stream_lanes.sh) as an ML dataset: fixed splits, compact arrays,
Belady labels, a capacity grid, and baseline fault counts.

    python3 tools/stream_dataset.py prepare [--jobs N] [--no-baselines]
    python3 tools/stream_dataset.py summary

`prepare` writes traces/streams/ml/:
    <stem>.npz       vpn (uint32), write (bool), next_use (uint32)
    index.json       one entry per stream: workload, variant, seed, split,
                     refs, distinct pages, capacity grid, TRACEHDR/RESULT
    SPLITS.tsv       the same split assignment, readable
    baselines.tsv    FIFO / LRU / Belady faults at every grid capacity

In Python:
    from stream_dataset import streams
    for s in streams(split="train", workload="kv"):
        s.vpn, s.write, s.next_use, s.capacities, s.meta

Labels. next_use[i] is the distance, in references, from access i to the
next access of the same page -- the quantity Belady's algorithm evicts by --
or NEVER if the page is not used again. It is computed from the recorded
future, so it is a training label only, never a feature.

Splits, fixed so every experiment reports against the same data:
  * held-out variants are used only for testing (HELD_OUT below): an
    unseen behaviour, not just an unseen run;
  * within every other variant, the last seed is test, the second-to-last
    validation, and the rest training -- seeds 1-3/4/5 for five seeds,
    1/2/3 for three;
  * matmulbench has one stream per variant (its seed has no effect), so
    its variants are training data and its n=128 variants are held out;
  * lzwbench has seeds 0-5 (seed = input text), so lzw-r20 splits like the
    others -- seeds 0-3 train, 4 validation, 5 test -- and lzw-r30 is
    held out.

Capacities are fractions of the stream's own distinct pages (CAPACITY_GRID).
The streams were collected at a generous margin, so no kernel run exists at
these capacities; they are simulation capacities, which is what a reference
string is for. Baselines simulate the stream alone -- code and stack pages
are not in it -- starting from an empty memory.
"""
from __future__ import annotations

import collections
import heapq
import json
import os
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
STREAMS = ROOT / "traces" / "streams"
ML = STREAMS / "ml"

NEVER = np.uint32(0xFFFFFFFF)
CAPACITY_GRID = (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
HELD_OUT = {"kv-F", "btree-scan", "graph-bfs2000", "sort-n60000",
            "matmul-naive128", "matmul-blocked128", "lzw-r30"}
STEM_RE = re.compile(r"^(?P<variant>(?P<workload>[a-z]+)-[A-Za-z0-9]+)-s(?P<seed>\d+)$")


# ---- split rule -------------------------------------------------------------
def assign_splits(stems):
    """stem -> split, by the rule in the module docstring."""
    by_variant = collections.defaultdict(list)
    for stem in stems:
        m = STEM_RE.match(stem)
        by_variant[m["variant"]].append((int(m["seed"]), stem))
    split = {}
    for variant, seeded in by_variant.items():
        seeded.sort()
        if variant in HELD_OUT:
            for _, stem in seeded:
                split[stem] = "heldout"
            continue
        if len(seeded) == 1:
            split[seeded[0][1]] = "train"
            continue
        for k, (_, stem) in enumerate(seeded):
            split[stem] = ("test" if k == len(seeded) - 1 else
                           "val" if k == len(seeded) - 2 else "train")
    return split


def stream_file(stem, ext):
    """A collected stream's file: traces/streams/<workload>/<stem><ext>,
    the workload being the stem up to its first "-" (kv-A-s1 -> kv/)."""
    return STREAMS / stem.split("-")[0] / (stem + ext)


def collected_stems():
    """Dataset streams that were collected and verified (an .ok marker),
    without the "-rep" determinism repeats."""
    return sorted(p.stem for p in STREAMS.glob("*/*.ok")
                  if not p.stem.endswith("-rep") and STEM_RE.match(p.stem))


# ---- parsing ----------------------------------------------------------------
def read_trace(path):
    """Parse "R 123\\n" / "W 123\\n" lines straight from the bytes with numpy.
    A Python list per reference costs about 1 GB for a 6M-line graph stream;
    this keeps a few flat arrays instead."""
    buf = np.fromfile(path, dtype=np.uint8)
    ends = np.flatnonzero(buf == 10)
    starts = np.concatenate(([0], ends[:-1] + 1))
    write = buf[starts] == ord("W")
    first = starts + 2                       # after the letter and the space
    ndig = ends - first
    vpn = np.zeros(len(ends), dtype=np.uint64)
    for k in range(int(ndig.max()) if len(ndig) else 0):
        live = ndig > k
        vpn[live] = vpn[live] * 10 + (buf[first[live] + k] - 48)
    bad = ~np.isin(buf[starts], (ord("R"), ord("W"), ord("T")))
    if bad.any():
        raise SystemExit("%s: line %d is not a reference" % (path, int(np.flatnonzero(bad)[0]) + 1))
    return vpn.astype(np.uint32), write


def read_log(path):
    text = open(path, errors="replace").read()
    hdr = re.search(r"^TRACEHDR (.*)$", text, re.M).group(1)
    header = dict(kv.split("=", 1) for kv in hdr.split() if "=" in kv)
    results = {k: int(v) for k, v in re.findall(r"^RESULT (\w+)=(-?\d+)", text, re.M)}
    end = re.search(r"TRACEEND refs=(\d+) bytes=(\d+)", text)
    return header, results, (int(end[1]), int(end[2])) if end else None


def next_use(vpn):
    """Vectorised: sort positions by (page, position); each position's next
    use is the following position in that order if it is the same page."""
    n = len(vpn)
    pos = np.arange(n, dtype=np.int64)
    order = np.lexsort((pos, vpn))
    out = np.full(n, NEVER, dtype=np.uint32)
    same = vpn[order[1:]] == vpn[order[:-1]]
    here = order[:-1][same]
    out[here] = (order[1:][same] - here).astype(np.uint32)
    return out


# ---- baselines (all from an empty memory, stream pages only) ----------------
def _seq(a):
    # Callers convert a stream to Python lists once and share them across
    # every policy and capacity: converting a 6M-element array per simulation
    # held gigabytes outside PyPy's own heap, where no GC limit reaches it.
    return a.tolist() if hasattr(a, "tolist") else a


def fifo_faults(vpn, cap):
    res, q, f = set(), collections.deque(), 0
    for v in _seq(vpn):
        if v in res:
            continue
        f += 1
        if len(res) >= cap:
            res.discard(q.popleft())
        res.add(v)
        q.append(v)
    return f


def lru_faults(vpn, cap):
    od, f = collections.OrderedDict(), 0
    for v in _seq(vpn):
        if v in od:
            od.move_to_end(v)
            continue
        f += 1
        if len(od) >= cap:
            od.popitem(last=False)
        od[v] = True
    return f


def belady_faults(vpn, nxt, cap):
    # Lazy-deletion max-heap of (next use, page). Every access pushes a fresh
    # entry, so stale ones pile up; rebuilding from the resident set whenever
    # the heap outgrows it keeps memory proportional to the capacity rather
    # than to the trace -- a 6M-reference stream otherwise holds 6M tuples.
    res, heap, f = {}, [], 0
    n = len(vpn)
    never = int(NEVER)
    limit = 4 * cap + 1024
    for i, (v, d) in enumerate(zip(_seq(vpn), _seq(nxt))):
        when = n + i if d == never else i + d   # distinct "never" keys
        if v not in res:
            f += 1
            if len(res) >= cap:
                while True:
                    w, p = heapq.heappop(heap)
                    if res.get(p) == -w:
                        del res[p]
                        break
        res[v] = when
        heapq.heappush(heap, (-when, v))
        if len(heap) > limit:
            heap = [(-w, p) for p, w in res.items()]
            heapq.heapify(heap)
    return f


def capacity_grid(distinct):
    return {str(frac): max(2, round(frac * distinct)) for frac in CAPACITY_GRID}


# ---- prepare ----------------------------------------------------------------
def prepare_one(args):
    """One stream: arrays, index entry, baseline rows. Results are cached as
    <stem>.npz + <stem>.json, so an interrupted prepare resumes."""
    stem, split, with_baselines = args
    cached = ML / (stem + ".json")
    if cached.exists():
        done = json.load(open(cached))
        if done["entry"]["split"] == split and (done["rows"] or not with_baselines):
            return done["entry"], [tuple(r) for r in done["rows"]]
    header, results, end = read_log(stream_file(stem, ".log"))
    arrays = ML / (stem + ".npz")
    vpn = None
    if arrays.exists():
        # A worker killed mid-write leaves a truncated file. Open it ourselves:
        # when np.load fails on a bad file it can leave its own handle open,
        # and Windows then refuses to replace the file below.
        try:
            with open(arrays, "rb") as fh, np.load(fh) as z:
                vpn, write, nxt = z["vpn"], z["write"], z["next_use"]
            if end is None or len(vpn) != end[0] or len(nxt) != len(vpn):
                vpn = None
        except Exception:
            vpn = None
    if vpn is None:
        vpn, write = read_trace(stream_file(stem, ".trace"))
        if end is None or end[0] != len(vpn):
            raise SystemExit("%s: trace has %d references, TRACEEND says %s"
                             % (stem, len(vpn), end))
        nxt = next_use(vpn)
        tmp = ML / (stem + ".npz.tmp")
        with open(tmp, "wb") as f:
            np.savez(f, vpn=vpn, write=write, next_use=nxt)
        _replace(tmp, arrays)
    m = STEM_RE.match(stem)
    distinct = int(len(np.unique(vpn)))
    caps = capacity_grid(distinct)
    entry = {
        "stem": stem, "workload": m["workload"], "variant": m["variant"],
        "seed": int(m["seed"]), "split": split, "refs": int(len(vpn)),
        "writes": int(write.sum()), "distinct_pages": distinct,
        "capacities": caps, "header": header, "results": results,
    }
    rows = []
    if with_baselines:
        vl, nl_ = vpn.tolist(), nxt.tolist()
        for frac, cap in caps.items():
            rows.append((stem, split, frac, cap, fifo_faults(vl, cap),
                         lru_faults(vl, cap), belady_faults(vl, nl_, cap)))
    tmp = ML / (stem + ".json.tmp")
    with open(tmp, "w") as f:
        json.dump({"entry": entry, "rows": rows}, f)
    _replace(tmp, cached)
    return entry, rows


def _replace(src, dst, tries=10):
    """os.replace, retried: on Windows a file another process has open (a
    virus scanner, say) cannot be replaced for a moment."""
    import time
    for k in range(tries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if k == tries - 1:
                raise
            time.sleep(0.5 * (k + 1))


def prepare(jobs, with_baselines):
    stems = collected_stems()
    if not stems:
        sys.exit("no collected streams in %s" % STREAMS)
    split = assign_splits(stems)
    ML.mkdir(parents=True, exist_ok=True)
    work = [(s, split[s], with_baselines) for s in stems]
    # biggest first, so a long graph stream does not start last
    work.sort(key=lambda w: -stream_file(w[0], ".trace").stat().st_size)
    if jobs > 1:
        # ProcessPoolExecutor, not multiprocessing.Pool: when a worker dies
        # (out of memory, say) Pool waits forever, while the executor raises.
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(jobs) as pool:
            done = list(pool.map(prepare_one, work))
    else:
        done = [prepare_one(w) for w in work]
    done.sort(key=lambda d: d[0]["stem"])
    index = [e for e, _ in done]
    with open(ML / "index.json", "w") as f:
        json.dump({"capacity_grid": CAPACITY_GRID, "held_out": sorted(HELD_OUT),
                   "never": int(NEVER), "streams": index}, f, indent=1)
    with open(ML / "SPLITS.tsv", "w", newline="\n") as f:
        f.write("stem\tworkload\tvariant\tseed\tsplit\trefs\tdistinct_pages\n")
        for e in index:
            f.write("%s\t%s\t%s\t%d\t%s\t%d\t%d\n" % (
                e["stem"], e["workload"], e["variant"], e["seed"], e["split"],
                e["refs"], e["distinct_pages"]))
    if with_baselines:
        with open(ML / "baselines.tsv", "w", newline="\n") as f:
            f.write("stem\tsplit\tfraction\tframes\tfifo\tlru\tbelady\n")
            for _, rows in done:
                for r in rows:
                    f.write("%s\t%s\t%s\t%d\t%d\t%d\t%d\n" % r)
    print("prepared %d streams in %s" % (len(index), ML))


# ---- loading ----------------------------------------------------------------
class Stream:
    def __init__(self, entry):
        self.meta = entry
        self.stem = entry["stem"]
        self.split = entry["split"]
        self.capacities = {float(k): v for k, v in entry["capacities"].items()}
        self._arrays = None

    def _load(self):
        if self._arrays is None:
            self._arrays = np.load(ML / (self.stem + ".npz"))
        return self._arrays

    @property
    def vpn(self):
        return self._load()["vpn"]

    @property
    def write(self):
        return self._load()["write"]

    @property
    def next_use(self):
        return self._load()["next_use"]

    def dense_pages(self):
        """Page ids 0..distinct-1 in order of first use, for embedding
        tables -- vpn values are absolute and start wherever the arena did."""
        _, first, inverse = np.unique(self.vpn, return_index=True, return_inverse=True)
        order = np.argsort(np.argsort(first))
        return order[inverse].astype(np.uint32)

    def __repr__(self):
        return "Stream(%s, %s, %d refs)" % (self.stem, self.split, self.meta["refs"])


def load_index():
    return json.load(open(ML / "index.json"))


def streams(split=None, workload=None, variant=None):
    for e in load_index()["streams"]:
        if split and e["split"] != split:
            continue
        if workload and e["workload"] != workload:
            continue
        if variant and e["variant"] != variant:
            continue
        yield Stream(e)


def summary():
    idx = load_index()["streams"]
    table = collections.Counter((e["workload"], e["split"]) for e in idx)
    splits = ["train", "val", "test", "heldout"]
    print("%-8s" % "" + "".join("%9s" % s for s in splits))
    for w in sorted({e["workload"] for e in idx}):
        print("%-8s" % w + "".join("%9d" % table[(w, s)] for s in splits))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "summary"
    if cmd == "prepare":
        # Default 3: a worker on a 6M-reference graph stream holds about a
        # gigabyte, and six of them beside a running WSL sweep exhausted a
        # 16 GB machine.
        jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 3
        prepare(jobs, "--no-baselines" not in sys.argv)
    elif cmd == "summary":
        summary()
    else:
        sys.exit(__doc__)
