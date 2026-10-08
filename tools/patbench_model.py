#!/usr/bin/env python3
"""Host model of user/patbench.c: the exact reference string, write count and
checksum a run must produce, and a checker for collected traces.

    python3 tools/patbench_model.py selftest
    python3 tools/patbench_model.py check <stem-or-trace> <footprint> <accesses> <seed> <mode>

`check` compares the trace file line by line (R/W and page, with the arena's
start VPN taken from the TRACEHDR in the matching .log) and, if the .log has
RESULT lines, reads / writes / checksum / word_sum.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_pat_zipf as gz  # noqa: E402

M64 = (1 << 64) - 1
MODES = ["loop", "scanhot", "scanhotlo", "zipf060", "zipf080", "zipf099", "zipf120",
         "uniform", "phase", "phaseshort", "switch"]
WRITE_PERMILLE = 100
HOT_DIV = 16
PHASE_HOT_PERMILLE = 900
CDF = {m: gz.cdf(gz.THETAS[m[4:]]) for m in MODES if m.startswith("zipf")}
CDF["switch"] = gz.cdf(0.99)


class Rng:
    def __init__(self, seed):
        self.s = (seed & M64) or 0x9E3779B97F4A7C15

    def next(self):
        x = self.s
        x ^= (x << 13) & M64
        x ^= x >> 7
        x ^= (x << 17) & M64
        self.s = x
        return x

    def below(self, bound):
        return 0 if bound == 0 else self.next() % bound


class Perm:
    def __init__(self, seed, tag, bits):
        r = Rng((seed * 0x9E3779B97F4A7C15 + tag * 0xD1B54A32D192ED03 + 1) & M64)
        self.k1 = r.next()
        self.k2 = r.next() | 1
        self.k3 = r.next() | 1
        self.mask = (1 << bits) - 1
        self.s = (bits + 1) // 2

    def __call__(self, x):
        m = self.mask
        x = (x + self.k1) & m
        x = (x * self.k2) & m
        x ^= x >> self.s
        x = (x * self.k3) & m
        x ^= x >> self.s
        return x


def zipf_rank(cdf, rng):
    draw = rng.next() & 0xFFFFFFFF
    lo, hi = 0, len(cdf) - 1
    while lo < hi:
        mid = lo + (hi - lo) // 2
        if cdf[mid] >= draw:
            hi = mid
        else:
            lo = mid + 1
    return lo


def generate(P, N, seed, mode):
    """Yield (page, is_write) for every access; returns via the generator's
    final summary in `summary()`."""
    assert P & (P - 1) == 0 and mode in MODES
    bits = P.bit_length() - 1
    H = P // HOT_DIV
    hot_permille = {"scanhot": 500, "scanhotlo": 200}.get(mode, 0)
    phase_len, loop_len = 0, P
    if mode in ("phase", "phaseshort"):
        hot_permille = PHASE_HOT_PERMILLE
        phase_len = N // (8 if mode == "phase" else 32)
    if mode == "switch":
        phase_len, loop_len = N // 8, P // 2
    phase_len = max(phase_len, 1)
    cdf = CDF.get(mode)
    pa, pb = Perm(seed, 1, bits), Perm(seed, 2, bits)
    pph = Perm(seed, 100, bits)
    rp, rw = Rng(seed * 2 + 1), Rng(seed * 2 + 2)
    scan_pos = loop_pos = 0
    phase_no = -1
    for i in range(N):
        if mode == "loop":
            page = pa(i % P)
        elif mode in ("scanhot", "scanhotlo"):
            if rp.below(1000) < hot_permille:
                page = pa(rp.below(H))
            else:
                page = pa(H + scan_pos)
                scan_pos = (scan_pos + 1) % (P - H)
        elif mode.startswith("zipf"):
            page = pa(zipf_rank(cdf, rp))
        elif mode == "uniform":
            page = rp.below(P)
        elif mode in ("phase", "phaseshort"):
            ph = i // phase_len
            if ph != phase_no:
                phase_no = ph
                pph = Perm(seed, 100 + ph, bits)
            page = pph(rp.below(H)) if rp.below(1000) < hot_permille else rp.below(P)
        else:  # switch
            if (i // phase_len) % 2 == 0:
                page = pa(loop_pos % loop_len)
                loop_pos += 1
            else:
                page = pb(zipf_rank(cdf, rp))
        yield page, rw.below(1000) < WRITE_PERMILLE


def summary(P, N, seed, mode):
    words = [0] * P
    reads = writes = 0
    checksum = 0
    for page, w in generate(P, N, seed, mode):
        if w:
            words[page] += 1
            checksum += words[page]
            writes += 1
        else:
            checksum += words[page]
            reads += 1
    return {"reads": reads, "writes": writes, "checksum": checksum & 0x7FFFFFFFFFFFFFFF,
            "word_sum": sum(words)}


def selftest():
    import random
    # permutations are bijections
    for bits in (4, 7, 10, 12):
        for seed in (0, 1, 5, 12345):
            for tag in (1, 2, 100, 101):
                p = Perm(seed, tag, bits)
                assert sorted(p(x) for x in range(1 << bits)) == list(range(1 << bits)), (bits, seed, tag)
    # the 0.99 table is the one kvbench uses
    import re
    old = [int(x) for x in re.findall(r"(\d+)u", (Path(__file__).resolve().parents[1] / "user/zipf_table.h").read_text())]
    assert gz.cdf(0.99) == old
    # the header the C program includes was generated from the same function
    hdr = (Path(__file__).resolve().parents[1] / "user/pat_zipf.h").read_text()
    for name, th in gz.THETAS.items():
        blk = re.search(rf"pat_zipf_cdf_{name}\[.*?\}};", hdr, re.S).group(0)
        assert [int(x) for x in re.findall(r"(\d+)u", blk)] == gz.cdf(th), name
    # shapes of the known answers
    P, N = 64, 4000
    loop = [pg for pg, _ in generate(P, N, 3, "loop")]
    assert all(sorted(loop[k * P:(k + 1) * P]) == list(range(P)) for k in range(N // P))
    assert loop[:P] == loop[P:2 * P]                      # a pure cycle
    assert loop[:P] != [pg for pg, _ in generate(P, P, 4, "loop")]  # seeds permute differently
    uni = [pg for pg, _ in generate(1024, 100000, 1, "uniform")]
    assert len(set(uni)) > 1000 and abs(sum(1 for x in uni if x < 512) / len(uni) - 0.5) < 0.01
    hot = [pg for pg, _ in generate(1024, 50000, 1, "zipf099")]
    top = sorted(((hot.count(p), p) for p in set(hot)), reverse=True)
    assert top[0][0] > 20 * (len(hot) / 1024)             # a few pages are very hot
    for m in MODES:
        a = list(generate(64, 3000, 2, m))
        assert a == list(generate(64, 3000, 2, m))        # deterministic
        assert a != list(generate(64, 3000, 3, m))        # seeds differ
        s = summary(64, 3000, 2, m)
        assert s["reads"] + s["writes"] == 3000 and s["word_sum"] == s["writes"]
        assert 150 < s["writes"] < 450                    # about 10%
    print("selftest OK: bijections, tables, shapes, determinism, seeds for", len(MODES), "modes")


def check(trace, P, N, seed, mode):
    trace = Path(trace)
    log = trace.with_suffix(".log")
    hdr = next(l for l in log.read_text(errors="replace").splitlines() if l.startswith("TRACEHDR"))
    base = int(hdr.split("arena_start_vpn=")[1].split()[0])
    n = bad = 0
    with open(trace) as f:
        it = generate(P, N, seed, mode)
        for line in f:
            exp = next(it, None)
            if exp is None:
                bad += 1
                break
            want = f"{'W' if exp[1] else 'R'} {base + exp[0]}\n"
            if line != want:
                bad += 1
                if bad <= 3:
                    print(f"  line {n}: got {line.strip()!r} want {want.strip()!r}")
            n += 1
        if next(it, None) is not None:
            bad += 1
            print("  trace is shorter than the model")
    ok = bad == 0 and n == N
    s = summary(P, N, seed, mode)
    res = {}
    for l in log.read_text(errors="replace").splitlines():
        if l.startswith("RESULT ") and "=" in l:
            k, v = l[7:].split("=", 1)
            res[k] = v
    for k in ("reads", "writes", "checksum", "word_sum"):
        if k in res and int(res[k]) != s[k]:
            print(f"  RESULT {k}: run {res[k]} model {s[k]}")
            ok = False
    print(f"{trace.name}: {n} refs, {bad} mismatches, results {'match' if ok else 'DIFFER'}")
    return ok


def checkdir(outdir, manifest):
    """Every patbench stream in the manifest: trace == model, -rep byte-identical,
    different seeds differ."""
    outdir = Path(outdir)
    rows = {}
    for line in open(manifest):
        if line.startswith("#") or not line.strip():
            continue
        stem, _, _, cmd = line.rstrip("\n").split("\t")
        w = cmd.split()
        if w[0] == "patbench":
            rows[stem] = (int(w[1]), int(w[3]), int(w[4]), w[5])
    ok = True
    for stem, (P, N, seed, mode) in rows.items():
        t = outdir / "pat" / f"{stem}.trace"
        if not t.exists():
            print(f"{stem}: MISSING"); ok = False; continue
        if stem.endswith("-rep"):
            same = t.read_bytes() == (outdir / "pat" / f"{stem[:-4]}.trace").read_bytes()
            print(f"{stem}: byte-identical to its original: {same}"); ok &= same
        else:
            ok &= check(t, P, N, seed, mode)
    by = {}
    for stem, (P, N, seed, mode) in rows.items():
        if not stem.endswith("-rep"):
            by.setdefault((P, N, mode), []).append((seed, (outdir / "pat" / f"{stem}.trace").read_bytes()))
    for k, v in by.items():
        if len(v) > 1 and len({b for _, b in v}) != len(v):
            print("seeds do not differ for", k); ok = False
    print("ALL OK" if ok else "FAILURES")
    return ok


if __name__ == "__main__":
    if sys.argv[1] == "selftest":
        selftest()
    elif sys.argv[1] == "checkdir":
        sys.exit(0 if checkdir(sys.argv[2], sys.argv[3]) else 1)
    else:
        t, P, N, seed, mode = sys.argv[2:7]
        sys.exit(0 if check(t, int(P), int(N), int(seed), mode) else 1)
