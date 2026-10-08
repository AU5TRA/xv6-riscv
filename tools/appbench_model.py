#!/usr/bin/env python3
"""Host model of user/appbench.c: the reference string of each mode (page, is_write),
exactly as the program touches it. tools/app_hostgen.py writes streams from it;
`check` compares a kernel-collected trace with it.

    python3 tools/appbench_model.py selftest
    python3 tools/appbench_model.py check <trace> <accesses> <seed> <mode>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import patbench_model as pm  # noqa: E402

M64 = (1 << 64) - 1
PG = 4096
MODES = ["chase", "spmv", "hashjoin", "bloom"]

CH_NODES = 16384
SP_ROWS, SP_NNZ_ROW = 16384, 8
SP_NNZ = SP_ROWS * SP_NNZ_ROW
SP_ROWPTR = 0
SP_COL = ((SP_ROWPTR + (SP_ROWS + 1) * 4 + 4095) // PG) * PG
SP_VAL = SP_COL + SP_NNZ * 4
SP_X = SP_VAL + SP_NNZ * 4
SP_Y = SP_X + SP_ROWS * 4
HJ_R_TUP, HJ_S_TUP, HJ_BUCKETS, HJ_OUT_TUP = 8192, 65536, 16384, 32768
HJ_R = 0
HJ_T = HJ_R + HJ_R_TUP * 16
HJ_S = HJ_T + HJ_BUCKETS * 16
HJ_OUT = HJ_S + HJ_S_TUP * 16
BL_PAGES, BL_K = 2048, 4
BL_BITS = BL_PAGES * PG * 8
PAGES = {"chase": CH_NODES * 64 // PG, "spmv": (SP_Y + SP_ROWS * 4 + PG - 1) // PG,
         "hashjoin": (HJ_OUT + HJ_OUT_TUP * 16 + PG - 1) // PG, "bloom": BL_PAGES}


def mix(x, salt):
    z = (x * 0x9E3779B97F4A7C15 + salt) & M64
    z ^= z >> 30
    z = (z * 0xBF58476D1CE4E5B9) & M64
    z ^= z >> 27
    z = (z * 0x94D049BB133111EB) & M64
    z ^= z >> 31
    return z


def generate(N, seed, mode):
    """Yield (page, write) for exactly N accesses."""
    out = []

    def touch(off, w):
        if len(out) >= N:
            return False
        out.append((off // PG, w))
        return True

    if mode == "chase":
        r = pm.Rng((seed * 0x9E3779B97F4A7C15 + 1 * 0xD1B54A32D192ED03 + 1) & M64)
        k1, k2, k3 = r.next(), r.next() | 1, r.next() | 1
        rw = pm.Rng(seed * 2 + 2)
        m = CH_NODES - 1
        i = 0
        while True:
            x = i % CH_NODES
            x = (x + k1) & m; x = (x * k2) & m; x ^= x >> 7; x = (x * k3) & m; x ^= x >> 7
            if not touch(x * 64, rw.below(100) < 5):
                break
            i += 1
    elif mode == "spmv":
        def col(j):
            row = j // SP_NNZ_ROW
            h = mix(j, seed)
            if h % 100 < 80:
                return (row + SP_ROWS + (h >> 8) % 2049 - 1024) % SP_ROWS
            return (h >> 8) % SP_ROWS
        done = False
        while not done:
            for r in range(SP_ROWS):
                if not touch(SP_ROWPTR + r * 4, False):
                    done = True; break
                for k in range(SP_NNZ_ROW):
                    j = r * SP_NNZ_ROW + k
                    if not (touch(SP_COL + j * 4, False) and touch(SP_VAL + j * 4, False)
                            and touch(SP_X + col(j) * 4, False)):
                        done = True; break
                if done or not touch(SP_Y + r * 4, True):
                    done = True; break
    elif mode == "hashjoin":
        outpos, q, done = 0, 0, False
        while not done:
            salt = (seed ^ (q << 32)) & M64
            for i in range(HJ_R_TUP):
                if not touch(HJ_R + i * 16, False) or not touch(HJ_T + (mix(i, salt) % HJ_BUCKETS) * 16, True):
                    done = True; break
            for i in range(HJ_S_TUP if not done else 0):
                key = mix(i, (seed + 0x51ED) & M64) % (2 * HJ_R_TUP)
                if not touch(HJ_S + i * 16, False) or not touch(HJ_T + (mix(key, salt) % HJ_BUCKETS) * 16, False):
                    done = True; break
                if key < HJ_R_TUP:
                    if not touch(HJ_OUT + (outpos % HJ_OUT_TUP) * 16, True):
                        done = True; break
                    outpos += 1
            q += 1
    else:
        rp, rw = pm.Rng(seed * 2 + 1), pm.Rng(seed * 2 + 2)
        cdf = pm.CDF["zipf099"]
        done = False
        while not done:
            rank = pm.zipf_rank(cdf, rp)
            key = rank * 64 + rp.below(64)
            ins = rw.below(100) < 5
            for k in range(BL_K):
                if not touch(mix(key, (seed + k * 0x1234567) & M64) % BL_BITS // 8, ins):
                    done = True; break
    return out


def summary(N, seed, mode):
    words = [0] * PAGES[mode]
    reads = writes = chk = 0
    for page, w in generate(N, seed, mode):
        if w:
            words[page] += 1; chk += words[page]; writes += 1
        else:
            chk += words[page]; reads += 1
    return {"reads": reads, "writes": writes, "checksum": chk & 0x7FFFFFFFFFFFFFFF, "word_sum": sum(words)}


def selftest():
    for m in MODES:
        a = generate(20000, 3, m)
        assert a == generate(20000, 3, m) and a != generate(20000, 4, m), m
        assert len(a) == 20000 and max(p for p, _ in a) < PAGES[m], m
        s = summary(20000, 3, m)
        assert s["word_sum"] == s["writes"] and s["reads"] + s["writes"] == 20000
    # shapes: chase visits every node once per cycle; spmv's first row touches rowptr then col/val/x
    c = generate(CH_NODES, 1, "chase")
    assert len({p for p, _ in c}) == CH_NODES * 64 // PG
    sp = generate(30, 1, "spmv")
    assert [p for p, _ in sp[:4]] == [0, SP_COL // PG, SP_VAL // PG, sp[3][0]] and sp[3][0] >= SP_X // PG
    assert sp[25][1] is True       # y[0] write after 8 * 3 + 1 touches
    print("selftest OK:", {m: PAGES[m] for m in MODES})


def check(trace, N, seed, mode):
    trace = Path(trace)
    hdr = next(l for l in trace.with_suffix(".log").read_text(errors="replace").splitlines() if l.startswith("TRACEHDR"))
    base = int(hdr.split("arena_start_vpn=")[1].split()[0])
    want = [f"{'W' if w else 'R'} {base + p}\n" for p, w in generate(N, seed, mode)]
    got = trace.read_text().splitlines(True)
    bad = sum(a != b for a, b in zip(got, want)) + abs(len(got) - len(want))
    print(f"{trace.name}: {len(got)} refs, {bad} mismatches")
    return bad == 0


if __name__ == "__main__":
    if sys.argv[1] == "selftest":
        selftest()
    else:
        sys.exit(0 if check(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5]) else 1)
