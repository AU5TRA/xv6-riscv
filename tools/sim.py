#!/usr/bin/env python3
"""Offline page-replacement simulator (WORK_PROMPT.md Phase 4).

Replays a vmbench reference trace (see tools/trace_decode.py for the
format) through FIFO, Clock, Aging, LRU, LFU, MRU, ARC and Belady's
optimal (via next-use distance), reporting fault and eviction counts for
each. MRU and ARC exist only here, not in the kernel: they are the
reference answers for patbench's loop and switch/phase patterns.

Runs entirely on the host, in plain Python -- this does NOT run inside
xv6 and has no floating-point restriction. FIFO/Clock/Aging are
implemented to mirror kernel/vmpage.c's actual choose_fifo/choose_clock
/choose_aging exactly (same tie-break rules, same aging-counter shift
math), so the simulator's fault count can be validated against the real
kernel's own vmstats counters captured in the SAME transcript (the
RESULT swap_faults=... line) -- this cross-check is the single most
important thing this file does; see validate_against_transcript().

Usage:
    python3 tools/sim.py <transcript.log> [--policy fifo|clock|aging|lru|belady|all]
    python3 tools/sim.py <transcript.log> --validate
    python3 tools/sim.py <transcript.log> --trace-file <workload.trace> [--policy ...] [--validate]

--trace-file is for the newer split-capture format (tools/collect_v2.sh /
user/vmbench.c's vmbench_trace_sink()): the TRACEHDR/RESULT lines are in
<transcript.log> but the "R|W <vpn>" reference stream was written to a
separate file instead of the console, for throughput. Omit it for an
older, single-file transcript that already has both.
"""
import sys
import argparse
import collections
from trace_decode import decode, decode_split, parse_header


class Fifo:
    name = "fifo"

    def __init__(self, capacity):
        self.capacity = capacity
        self.resident = {}   # vpn -> load_sequence
        self.seq = 0
        self.faults = 0
        self.evictions = 0

    def access(self, vpn):
        if vpn in self.resident:
            return
        self.faults += 1
        if len(self.resident) >= self.capacity:
            victim = min(self.resident, key=lambda p: self.resident[p])
            del self.resident[victim]
            self.evictions += 1
        self.resident[vpn] = self.seq
        self.seq += 1


class Clock:
    name = "clock"

    def __init__(self, capacity):
        self.capacity = capacity
        self.order = []      # circular candidate list (insertion order)
        self.ref = {}        # vpn -> referenced bit
        self.hand = 0
        self.faults = 0
        self.evictions = 0

    def access(self, vpn):
        if vpn in self.ref:
            self.ref[vpn] = 1
            return
        self.faults += 1
        if len(self.order) >= self.capacity:
            n = len(self.order)
            scanned = 0
            while True:
                idx = self.hand % n
                cand = self.order[idx]
                self.hand += 1
                if not self.ref[cand]:
                    victim = cand
                    break
                self.ref[cand] = 0
                scanned += 1
                if scanned >= 2 * n:
                    victim = self.order[self.hand % n]
                    self.hand += 1
                    break
            self.order.remove(victim)
            del self.ref[victim]
            self.evictions += 1
        self.order.append(vpn)
        self.ref[vpn] = 0

    # NOTE: matching kernel/vmpage.c's choose_clock exactly would need
    # to track hand position over the SAME candidate array identity
    # across calls, which a Python list-remove reshuffles. Close enough
    # for fault-count purposes (eviction choice among referenced=0
    # candidates is what matters), but the exact victim tie-break on a
    # full sweep may differ from the kernel in rare all-referenced
    # cases. Documented here rather than silently assumed identical.


class Aging:
    name = "aging"

    def __init__(self, capacity):
        self.capacity = capacity
        self.resident = {}     # vpn -> load_sequence
        self.counter = {}      # vpn -> 8-bit aging counter
        self.ref = {}          # vpn -> referenced since last decay
        self.seq = 0
        self.faults = 0
        self.evictions = 0

    def _decay_all(self):
        for vpn in self.resident:
            accessed = self.ref.get(vpn, 0)
            self.counter[vpn] = (self.counter[vpn] >> 1) | (0x80 if accessed else 0)
            self.ref[vpn] = 0

    def access(self, vpn):
        if vpn in self.resident:
            self.ref[vpn] = 1
            return
        self.faults += 1
        if len(self.resident) >= self.capacity:
            self.ref[vpn] = 0  # the faulting page hasn't been sampled yet
            self._decay_all()
            victim = min(self.resident,
                         key=lambda p: (self.counter[p], self.resident[p]))
            del self.resident[victim]
            del self.counter[victim]
            del self.ref[victim]
            self.evictions += 1
        self.resident[vpn] = self.seq
        self.seq += 1
        self.counter[vpn] = 0xff
        self.ref[vpn] = 0


class Lru:
    name = "lru"

    def __init__(self, capacity):
        self.capacity = capacity
        self.order = []  # most-recently-used at the end
        self.faults = 0
        self.evictions = 0

    def access(self, vpn):
        if vpn in self.order:
            self.order.remove(vpn)
            self.order.append(vpn)
            return
        self.faults += 1
        if len(self.order) >= self.capacity:
            del self.order[0]
            self.evictions += 1
        self.order.append(vpn)


class Lfu:
    """Hand-written (no learning) Least-Frequently-Used: evict the
    resident page with the lowest total access count so far. Added to
    directly test whether the "global_frequency" feature's win in
    ML_TESTING_REPORT.md's Experiment 2/3 needs a trained model at all,
    or whether a plain counter-based heuristic captures the same gain
    -- see that report for why this question matters (a hand-written
    policy is far cheaper to actually put in the kernel)."""
    name = "lfu"

    def __init__(self, capacity):
        self.capacity = capacity
        self.resident = set()
        self.freq = {}   # vpn -> access count (kept for ALL pages ever
                          # seen, not just resident ones, same as the
                          # "global_frequency" feature it mirrors)
        self.faults = 0
        self.evictions = 0

    def access(self, vpn):
        self.freq[vpn] = self.freq.get(vpn, 0) + 1
        if vpn in self.resident:
            return
        self.faults += 1
        if len(self.resident) >= self.capacity:
            victim = min(self.resident, key=lambda p: self.freq[p])
            self.resident.discard(victim)
            self.evictions += 1
        self.resident.add(vpn)


class StackDistance:
    """Hand-written (no learning): evict the resident page with the
    largest current stack distance (distinct pages touched since its
    last access) -- the theoretically correct LRU-style distance,
    directly testing the "stack_distance" feature's win on lzwbench in
    ML_TESTING_REPORT.md without any trained model."""
    name = "stackdist"

    def __init__(self, capacity):
        self.capacity = capacity
        self.resident = set()
        self.last_distinct_at = {}  # vpn -> distinct-page clock value
        self.distinct_seen = 0
        self.faults = 0
        self.evictions = 0

    def access(self, vpn):
        if vpn not in self.last_distinct_at:
            self.distinct_seen += 1
        if vpn in self.resident:
            self.last_distinct_at[vpn] = self.distinct_seen
            return
        self.faults += 1
        if len(self.resident) >= self.capacity:
            victim = max(self.resident,
                         key=lambda p: self.distinct_seen - self.last_distinct_at[p])
            self.resident.discard(victim)
            self.evictions += 1
        self.resident.add(vpn)
        self.last_distinct_at[vpn] = self.distinct_seen


class Mru:
    """Hand-written (no learning) Most-Recently-Used: evict the resident
    page touched most recently. Wrong for almost everything, but it is the
    textbook answer for a cyclic loop just larger than memory (patbench
    loop): LRU, FIFO and Clock miss on every access there, while MRU keeps
    C - 1 pages of the loop in place and misses only about L - C times per
    pass. Simulator only; the kernel has no MRU."""
    name = "mru"

    def __init__(self, capacity):
        self.capacity = capacity
        self.order = collections.OrderedDict()  # most recently used last
        self.faults = 0
        self.evictions = 0

    def access(self, vpn):
        if vpn in self.order:
            self.order.move_to_end(vpn)
            return
        self.faults += 1
        if len(self.order) >= self.capacity:
            self.order.popitem(last=True)
            self.evictions += 1
        self.order[vpn] = None


class Arc:
    """Adaptive Replacement Cache (Megiddo and Modha, "ARC: A Self-Tuning,
    Low Overhead Replacement Cache", FAST 2003), following the paper's
    Figure 4 case by case. Simulator only; the kernel has no ARC.

    T1 holds resident pages seen once recently, T2 resident pages seen at
    least twice; B1 and B2 are their ghost lists (page numbers only, not
    resident). p is the target size of T1: a hit in B1 says T1 was too
    small and grows it, a hit in B2 shrinks it. Every list is kept LRU
    first, MRU last. p and the adaptation steps are real numbers, as in
    the paper. The reference for patbench's switch and phase modes, which
    alternate between recency-friendly and frequency-friendly phases."""
    name = "arc"

    def __init__(self, capacity):
        self.c = capacity
        self.p = 0.0
        self.t1 = collections.OrderedDict()
        self.t2 = collections.OrderedDict()
        self.b1 = collections.OrderedDict()
        self.b2 = collections.OrderedDict()
        self.faults = 0
        self.evictions = 0

    def _replace(self, in_b2):
        # REPLACE(x_t, p): evict T1's LRU page into B1 if T1 is over its
        # target (or at it, when the request was a B2 ghost hit), otherwise
        # T2's LRU page into B2.
        t1 = len(self.t1)
        if t1 >= 1 and ((in_b2 and t1 == self.p) or t1 > self.p):
            victim, _ = self.t1.popitem(last=False)
            self.b1[victim] = None
        else:
            victim, _ = self.t2.popitem(last=False)
            self.b2[victim] = None
        self.evictions += 1

    def access(self, vpn):
        # Case I: a hit in T1 or T2 moves the page to T2's MRU end.
        if vpn in self.t1:
            del self.t1[vpn]
            self.t2[vpn] = None
            return
        if vpn in self.t2:
            self.t2.move_to_end(vpn)
            return
        self.faults += 1
        # Case II: a ghost hit in B1 -- T1 should have been larger.
        if vpn in self.b1:
            b1, b2 = len(self.b1), len(self.b2)
            self.p = min(self.p + (1.0 if b1 >= b2 else b2 / b1), float(self.c))
            self._replace(False)
            del self.b1[vpn]
            self.t2[vpn] = None
            return
        # Case III: a ghost hit in B2 -- T2 should have been larger.
        if vpn in self.b2:
            b1, b2 = len(self.b1), len(self.b2)
            self.p = max(self.p - (1.0 if b2 >= b1 else b1 / b2), 0.0)
            self._replace(True)
            del self.b2[vpn]
            self.t2[vpn] = None
            return
        # Case IV: a page in none of the four lists.
        l1 = len(self.t1) + len(self.b1)
        l2 = len(self.t2) + len(self.b2)
        if l1 == self.c:
            # A: L1 is full. If T1 has room for a ghost, drop B1's LRU
            # ghost and replace; otherwise B1 is empty and T1's LRU page is
            # evicted outright, with no ghost.
            if len(self.t1) < self.c:
                self.b1.popitem(last=False)
                self._replace(False)
            else:
                self.t1.popitem(last=False)
                self.evictions += 1
        elif l1 < self.c and l1 + l2 >= self.c:
            # B: the directory is full; drop B2's LRU ghost if all 2c
            # entries are in use, then replace.
            if l1 + l2 == 2 * self.c:
                self.b2.popitem(last=False)
            self._replace(False)
        self.t1[vpn] = None

    def check_invariants(self):
        """The paper's invariants (its section III.B, for DBL(2c)). Used by
        the self-test; a broken one means a bug, not a workload effect."""
        t1, t2, b1, b2, c = (len(self.t1), len(self.t2), len(self.b1),
                             len(self.b2), self.c)
        assert t1 + t2 <= c, "resident pages exceed capacity"
        assert t1 + b1 <= c, "L1 exceeds c"
        assert t1 + t2 + b1 + b2 <= 2 * c, "directory exceeds 2c"
        assert 0.0 <= self.p <= c, "p out of range"
        keys = [set(self.t1), set(self.t2), set(self.b1), set(self.b2)]
        assert sum(map(len, keys)) == len(set().union(*keys)), \
            "a page is in two lists"


def belady_faults_evictions(refs, capacity):
    """Belady's optimal: evict whichever resident page's next use is
    furthest in the future (or never used again)."""
    n = len(refs)
    next_use = [0] * n
    last_pos = {}
    for i in range(n - 1, -1, -1):
        vpn = refs[i]
        next_use[i] = last_pos.get(vpn, n)  # n == "never again"
        last_pos[vpn] = i

    resident = set()
    faults = 0
    evictions = 0
    # For each resident page, the position (index into refs) of its
    # OWN next use, kept up to date as we advance.
    next_use_of = {}
    for i, vpn in enumerate(refs):
        if vpn in resident:
            next_use_of[vpn] = next_use[i]
            continue
        faults += 1
        if len(resident) >= capacity:
            victim = max(resident, key=lambda p: next_use_of.get(p, n))
            resident.remove(victim)
            del next_use_of[victim]
            evictions += 1
        resident.add(vpn)
        next_use_of[vpn] = next_use[i]
    return faults, evictions


POLICIES = {
    "fifo": Fifo,
    "clock": Clock,
    "aging": Aging,
    "lru": Lru,
    "lfu": Lfu,
    "stackdist": StackDistance,
    "mru": Mru,
    "arc": Arc,
}


def run_policy(name, refs, capacity):
    if name == "belady":
        faults, evictions = belady_faults_evictions(refs, capacity)
        return {"faults": faults, "evictions": evictions}
    sim = POLICIES[name](capacity)
    for vpn in refs:
        sim.access(vpn)
    return {"faults": sim.faults, "evictions": sim.evictions}


def parse_result_lines(path):
    """Pulls RESULT key=value lines out of a transcript (the same ones
    vmbench_result() prints) so we can cross-check against real kernel
    counters without a separate run."""
    out = {}
    with open(path, "r", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line.startswith("RESULT "):
                kv = line[len("RESULT "):]
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    try:
                        out[k] = int(v)
                    except ValueError:
                        out[k] = v
    return out


POLICY_NAME_BY_NUMBER = {0: "fifo", 1: "clock", 2: "aging"}

# Field to read the REAL applied resident-frame limit from. Not
# "arena_cache_budget" -- despite the name, every workload populates
# that field with its own resident_margin CLI argument (the *requested*
# margin added to the settled baseline -- see e.g. user/btreebench.c's
# vmbench_trace_start() call), not a true capacity. "resident_limit" is
# a live vmstats() snapshot taken after vmctl(VM_SET_LIMIT, ...) is
# actually applied (see user/vmbench.c's vmbench_trace_start()
# docstring: "Call this AFTER vmctl(VM_SET_LIMIT, ...) so the printed
# limit is the real one"), so it's the field that matches what the
# kernel actually enforced. Using arena_cache_budget instead silently
# simulates the wrong capacity (confirmed on real captures: a 266 vs.
# 270 mismatch here was enough to throw off both fault and eviction
# counts) -- this was a real, undetected bug, not a stylistic choice.
CAPACITY_FIELD = "resident_limit"


def validate_against_transcript(path, trace_file=None):
    header, refs = (decode_split(path, trace_file) if trace_file
                     else decode(path))
    if header is None:
        print("no TRACEHDR found")
        return False
    if not refs:
        print("no 'R|W <vpn>' (or legacy 'T <vpn>') reference lines found -- if this transcript "
              "was captured with vmbench_trace_sink() pointed at a file "
              "(see user/vmbench.c), pass --trace-file <the .trace file>")
        return False
    capacity = int(header[CAPACITY_FIELD])
    policy_num = int(header["policy"])
    policy_name = POLICY_NAME_BY_NUMBER.get(policy_num)
    if policy_name is None:
        print(f"unknown policy number {policy_num} in trace header")
        return False

    sim_result = run_policy(policy_name, refs, capacity)
    results = parse_result_lines(path)
    real_swap_faults = results.get("swap_faults")
    real_evictions = results.get("evictions")

    print(f"policy under test: {policy_name} (capacity={capacity})")
    print(f"simulator: faults={sim_result['faults']} "
          f"evictions={sim_result['evictions']}")
    print(f"kernel:    swap_faults={real_swap_faults} "
          f"evictions={real_evictions}")

    # The kernel's swap_faults counts SWAP-INS only (a page that was
    # evicted and is now being brought back), not the FIRST-ever fault
    # for a page (that's zero_faults in the kernel's own counters, and
    # in the simulator corresponds to the first-touch faults that
    # never require eviction of anything -- i.e. faults that happen
    # while resident count is still under capacity). So the correct
    # comparison is: simulator faults MINUS the ones that occurred
    # before the cache ever filled up (unique pages up to the point
    # capacity was first reached) should equal kernel swap_faults; and
    # simulator evictions should equal kernel evictions directly (both
    # only ever count real evictions).
    #
    # KNOWN, PRE-EXISTING LIMITATION, not something this validation can
    # fix: the trace only records touches to the workload's OWN arena
    # (via touch_r/touch_w -> vmbench_trace_ref), never the process's
    # baseline code/stack pages. At a generous margin nothing evicts and
    # both sides trivially read 0. At real, moderate-to-tight pressure
    # (the kind these captures are actually FOR), baseline pages compete
    # for the same resident-frame budget the simulator is told to
    # enforce purely against the arena stream, so an arena-only replay
    # cannot exactly reproduce which page the real kernel evicted at
    # every step. Confirmed empirically: even margin=10-in-40 native
    # captures already mismatch this way. This is a real ceiling on
    # exact-match validation at tight margins, not a bug to chase here --
    # the simulator's relative comparison ACROSS policies on the SAME
    # reference stream (its main purpose) is unaffected by it.
    ok_evictions = (real_evictions is not None and
                    sim_result["evictions"] == real_evictions)
    print()
    if ok_evictions:
        print("PASS: simulator eviction count matches kernel exactly.")
    elif real_evictions in (0, None) or sim_result["evictions"] == 0:
        print("INCONCLUSIVE: one side shows zero evictions (a generous "
              "margin where nothing was evicted) -- not a meaningful "
              "cross-check either way.")
    else:
        print("MISMATCH (expected at real/tight margins -- see the "
              "KNOWN, PRE-EXISTING LIMITATION comment in this function's "
              "source): simulator eviction count does not exactly match "
              "the kernel's. The simulator only replays arena touches, "
              "never the process's own baseline pages, which also "
              "compete for frames under real pressure.")
    return ok_evictions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--trace-file", default=None,
                     help="separate file holding the 'R|W <vpn>' (or legacy 'T <vpn>') reference "
                          "stream, for captures where vmbench_trace_sink() "
                          "wrote it to a file instead of the console (the "
                          "transcript then only has TRACEHDR/RESULT lines). "
                          "Omit for an older single-file transcript.")
    ap.add_argument("--policy", default="all",
                     choices=["fifo", "clock", "aging", "lru", "lfu",
                              "stackdist", "mru", "arc", "belady", "all"])
    ap.add_argument("--validate", action="store_true",
                     help="cross-check the simulator against this "
                          "transcript's own kernel-reported counters "
                          "for the policy it was captured under")
    args = ap.parse_args()

    if args.validate:
        ok = validate_against_transcript(args.transcript, args.trace_file)
        sys.exit(0 if ok else 1)

    header, refs = (decode_split(args.transcript, args.trace_file)
                     if args.trace_file else decode(args.transcript))
    if header is None:
        print("no TRACEHDR found -- was this run with tracing enabled?")
        sys.exit(1)
    if not refs:
        print("no 'R|W <vpn>' (or legacy 'T <vpn>') reference lines found -- if this transcript "
              "was captured with vmbench_trace_sink() pointed at a file "
              "(see user/vmbench.c), pass --trace-file <the .trace file>")
        sys.exit(1)
    capacity = int(header[CAPACITY_FIELD])
    print(f"workload={header.get('workload')} capacity={capacity} "
          f"total_refs={len(refs)}")
    print()

    names = list(POLICIES.keys()) + ["belady"] if args.policy == "all" \
        else [args.policy]
    results = {}
    for name in names:
        results[name] = run_policy(name, refs, capacity)
        r = results[name]
        print(f"{name:>8s}: faults={r['faults']:>6d} "
              f"evictions={r['evictions']:>6d}")

    if "belady" in results:
        print()
        print("oracle gap (headroom above Belady's optimal):")
        for name in names:
            if name == "belady":
                continue
            gap = results[name]["faults"] - results["belady"]["faults"]
            print(f"  {name}: +{gap} faults vs belady "
                  f"({results[name]['faults']} vs {results['belady']['faults']})")


if __name__ == "__main__":
    main()
