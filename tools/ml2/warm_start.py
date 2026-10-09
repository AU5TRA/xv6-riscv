"""Does a populate phase before the workload explain the kernel / simulator gap?

The kernel runs every benchmark's populate loop (touches every page, mostly evicting) before the traced workload
starts, so the workload begins with a full, aged memory, earlier evictions and refault counts. The simulator starts empty.
`warm(s)` returns the same stream with one write sweep over its pages in address order in front;
`faults_after_prefix` runs both and subtracts the prefix's own faults."""
import copy

import numpy as np

import pagesim as ps


def warm(s, sweeps=1):
    t = copy.copy(s)
    n = s.n_pages
    pre = np.tile(np.arange(n, dtype=np.uint32), sweeps)
    t.page = np.ascontiguousarray(np.concatenate([pre, s.page[:s.n]]))
    t.write = np.ascontiguousarray(np.concatenate([np.ones(len(pre), np.uint8), s.write[:s.n]]))
    t.next_use = np.full(len(t.page), 0xFFFFFFFF, np.uint32)
    t.n = len(t.page)
    t.prefix = len(pre)
    return t


def faults_after_prefix(s, cap, policy, model=None, sweeps=1):
    t = warm(s, sweeps)
    full = ps.run(t, cap, policy, model)["faults"]
    u = copy.copy(t)
    u.n = t.prefix
    pre = ps.run(u, cap, policy, model)["faults"]
    return full - pre


def warm_order(s, order):
    """like warm(), with the populate sweep visiting the stream's pages in the given order (array of dense ids)"""
    t = copy.copy(s)
    pre = np.asarray(order, np.uint32)
    t.page = np.ascontiguousarray(np.concatenate([pre, s.page[:s.n]]))
    t.write = np.ascontiguousarray(np.concatenate([np.ones(len(pre), np.uint8), s.write[:s.n]]))
    t.next_use = np.full(len(t.page), 0xFFFFFFFF, np.uint32)
    t.n = len(t.page)
    t.prefix = len(pre)
    return t


def faults_with_order(s, cap, policy, model, order):
    t = warm_order(s, order)
    u = copy.copy(t)
    u.n = t.prefix
    return ps.run(t, cap, policy, model)["faults"] - ps.run(u, cap, policy, model)["faults"]
