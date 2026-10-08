"""Shared pieces of the host-side benchmark models (tools/hostmodel/).

A model re-implements one xv6 benchmark in Python closely enough to predict
its exact reference string and its RESULT lines from the same arguments
(GAWWY_HANDOFF_NEW_BENCHMARKS.md, rule 10). Everything here mirrors code in
user/vmbench.[ch] or a benchmark's own C, operation for operation, with
64-bit wraparound made explicit.
"""
from __future__ import annotations

import bisect
import hashlib
import re
from pathlib import Path

MASK64 = (1 << 64) - 1
ROOT = Path(__file__).resolve().parents[2]
PGSIZE = 4096


class Rng:
    """user/vmbench.c: vmbench_rng_seed/next/below (xorshift64)."""

    def __init__(self, seed: int):
        self.state = seed & MASK64 if seed else 0x9E3779B97F4A7C15

    def next(self) -> int:
        x = self.state
        x ^= (x << 13) & MASK64
        x ^= x >> 7
        x ^= (x << 17) & MASK64
        self.state = x
        return x

    def below(self, bound: int) -> int:
        return 0 if bound == 0 else self.next() % bound


def load_cdf(name: str) -> list[int]:
    """The table in user/zipf_table_<name>.h (or user/zipf_table.h for
    name None), read from the header itself so the model cannot drift from
    what the C compiled."""
    path = ROOT / "user" / ("zipf_table.h" if name is None else
                            "zipf_table_%s.h" % name)
    text = path.read_text()
    body = text[text.index("{") + 1:text.index("}")]
    table = [int(v) for v in re.findall(r"(\d+)u", body)]
    n = int(re.search(r"#define VMBENCH_ZIPF_N\w* (\d+)", text).group(1))
    if len(table) != n:
        raise SystemExit("%s: %d entries, header says %d" % (path, len(table), n))
    return table


def zipf_sample(rng: Rng, cdf: list[int]) -> int:
    """vmbench_zipf_sample_cdf(): the lowest rank whose CDF entry is at
    least a 32-bit draw (the low half of one PRNG output)."""
    draw = rng.next() & 0xFFFFFFFF
    return bisect.bisect_left(cdf, draw, 0, len(cdf) - 1)


def load_bucketed(name: str) -> tuple[list[int], list[int], int]:
    """(cdf, start, n_ranks) from a bucketed user/zipf_table_<name>.h."""
    path = ROOT / "user" / ("zipf_table_%s.h" % name)
    text = path.read_text()
    arrays = re.findall(r"\] = \{(.*?)\};", text, re.S)
    if len(arrays) != 2:
        raise SystemExit("%s: not a bucketed table" % path)
    cdf, start = ([int(v) for v in re.findall(r"(\d+)u", a)] for a in arrays)
    nb = int(re.search(r"#define VMBENCH_ZIPF_B_\w+ (\d+)", text).group(1))
    n = int(re.search(r"#define VMBENCH_ZIPF_N_\w+ (\d+)", text).group(1))
    if len(cdf) != nb or len(start) != nb + 1 or start[-1] != n:
        raise SystemExit("%s: inconsistent bucketed table" % path)
    return cdf, start, n


def zipf_sample_bucketed(rng: Rng, cdf: list[int], start: list[int]) -> int:
    """vmbench_zipf_sample_bucketed(): a bucket, then a rank inside it."""
    b = zipf_sample(rng, cdf)
    return start[b] + rng.below(start[b + 1] - start[b])


def mix64(z: int) -> int:
    """splitmix64's finalizer, as mix64() in the benchmarks."""
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
    return z ^ (z >> 31)


class Perm:
    """struct perm / perm_init / perm_fwd / perm_inv: a four-round Feistel
    permutation of [0, n), cycle-walked into range."""

    GOLDEN = 0x9E3779B97F4A7C15

    def __init__(self, n: int, key: int):
        bits = 2
        while (1 << bits) < n:
            bits += 1
        bits += bits & 1
        self.n = n
        self.key = key & MASK64
        self.half = bits // 2
        self.mask = (1 << self.half) - 1
        self.rk = [(self.key + (r + 1) * self.GOLDEN) & MASK64 for r in range(4)]

    def _f(self, v: int, r: int) -> int:
        return mix64((v + self.rk[r]) & MASK64) & self.mask

    def fwd(self, x: int) -> int:
        half, mask = self.half, self.mask
        while True:
            l, r = x >> half, x & mask
            for i in range(4):
                l, r = r, l ^ self._f(r, i)
            x = (l << half) | r
            if x < self.n:
                return x

    def inv(self, x: int) -> int:
        half, mask = self.half, self.mask
        while True:
            l, r = x >> half, x & mask
            for i in (3, 2, 1, 0):
                l, r = r ^ self._f(l, i), l
            x = (l << half) | r
            if x < self.n:
                return x


class TraceSink:
    """Consumes a model's references and keeps what the run would print
    and write: the reference count, the trace's byte count and checksum,
    and optionally the trace itself (absolute VPNs, as the kernel writes
    them) or the page sequence (arena-relative, for simulation)."""

    def __init__(self, arena_vpn: int = 0, path: str | None = None,
                 keep_pages: bool = False):
        self.arena_vpn = arena_vpn
        self.refs = 0
        self.writes = 0
        self.bytes = 0
        self.md5 = hashlib.md5()
        self.out = open(path, "wb") if path else None
        self.pages = [] if keep_pages else None
        self.wflags = [] if keep_pages else None
        self._buf = []

    def ref(self, page: int, write: bool):
        self._buf.append(b"%c %d\n" % (87 if write else 82, self.arena_vpn + page))
        self.refs += 1
        self.writes += write
        if self.pages is not None:
            self.pages.append(page)
            self.wflags.append(write)
        if len(self._buf) >= 65536:
            self._flush()

    def _flush(self):
        chunk = b"".join(self._buf)
        self._buf.clear()
        self.bytes += len(chunk)
        self.md5.update(chunk)
        if self.out:
            self.out.write(chunk)

    def close(self):
        self._flush()
        if self.out:
            self.out.close()
            self.out = None
        return self
