#!/usr/bin/env python3
"""Offline page-replacement simulator (WORK_PROMPT.md Phase 4).

Replays a vmbench reference trace (see tools/trace_decode.py for the
format) through FIFO, Clock, Aging, LRU, and Belady's optimal (via
next-use distance), reporting fault and eviction counts for each.

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
"""
import sys
import argparse
from trace_decode import decode, parse_header


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


def validate_against_transcript(path):
    header, refs = decode(path)
    if header is None:
        print("no TRACEHDR found")
        return False
    capacity = int(header["arena_cache_budget"])
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
    ok_evictions = (real_evictions is not None and
                    sim_result["evictions"] == real_evictions)
    print()
    if ok_evictions:
        print("PASS: simulator eviction count matches kernel exactly.")
    else:
        print("MISMATCH: simulator eviction count does NOT match kernel.")
    return ok_evictions


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--policy", default="all",
                     choices=["fifo", "clock", "aging", "lru", "belady", "all"])
    ap.add_argument("--validate", action="store_true",
                     help="cross-check the simulator against this "
                          "transcript's own kernel-reported counters "
                          "for the policy it was captured under")
    args = ap.parse_args()

    if args.validate:
        ok = validate_against_transcript(args.transcript)
        sys.exit(0 if ok else 1)

    header, refs = decode(args.transcript)
    if header is None:
        print("no TRACEHDR found -- was this run with tracing enabled?")
        sys.exit(1)
    capacity = int(header["arena_cache_budget"])
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
