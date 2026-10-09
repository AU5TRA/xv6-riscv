#!/usr/bin/env python3
"""Check collected runs of the new benchmarks against their host models
(GAWWY_HANDOFF_NEW_BENCHMARKS.md, rule 10 and section 8 check 1).

    python3 tools/hostmodel/check_run.py <run.log> [<run.trace>]
    python3 tools/hostmodel/check_run.py <dir> ...

With a directory, every <stem>.log in it whose program has a model is
checked, with <stem>.trace beside it if present. For each run the model is
re-run with the command the log records ("# RUN ...") and the arena VPN
from its TRACEHDR, and these must all agree:
  * every RESULT value the model predicts (parameters, counts, checksum);
  * the log's TRACEEND refs= and bytes= with the model's;
  * the trace file, if given: its size and MD5 with the model's, so it is
    byte-identical to the predicted reference string.
Exits non-zero if any run disagrees.
"""
from __future__ import annotations

import argparse
import importlib
import os
import re
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    __package__ = "hostmodel"

from .common import TraceSink

# program name -> model module in this package
MODELS = {
    "patbench": "patbench",
    "chasebench": "chasebench",
    "joinbench": "joinbench",
    "bloombench": "bloombench",
    "spmvbench": "spmvbench",
    "heapbench": "heapbench",
}


def predict(program, args, arena_vpn=0, trace_out=None, keep_pages=False):
    mod = importlib.import_module("." + MODELS[program], __package__)
    sink = TraceSink(arena_vpn, trace_out, keep_pages)
    results = mod.run(args, sink.ref)
    sink.close()
    return results, sink


def parse_log(path):
    text = Path(path).read_text(errors="replace")
    m = re.search(r"^# RUN (.+?)\s*$", text, re.M)
    if not m:
        raise SystemExit("%s: no '# RUN' line" % path)
    cmd = m.group(1).split()
    hdr = re.search(r"^TRACEHDR .*arena_start_vpn=(\d+)", text, re.M)
    end = re.search(r"^TRACEEND refs=(\d+) bytes=(\d+)", text, re.M)
    results = {k: int(v) for k, v in re.findall(r"^RESULT (\w+)=(-?\d+)\s*$", text, re.M)}
    passed = re.search(r"^PASS\s*$", text, re.M) is not None
    return {
        "cmd": cmd,
        "arena_vpn": int(hdr.group(1)) if hdr else None,
        "traceend": (int(end.group(1)), int(end.group(2))) if end else None,
        "results": results,
        "passed": passed,
    }


def file_md5(path):
    import hashlib
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check(log, trace=None, quiet=False):
    """Returns a list of problems (empty if the run matches its model)."""
    info = parse_log(log)
    program, args = info["cmd"][0], info["cmd"][1:]
    if program not in MODELS:
        return None
    problems = []
    t0 = time.time()
    try:
        want, sink = predict(program, args, info["arena_vpn"] or 0)
    except SystemExit as e:
        # The model rejects these arguments. That agrees with a run that
        # refused them too, and nothing else.
        agree = not info["passed"]
        if not quiet:
            print("%-40s %s  model rejects the arguments (%s); the run %s"
                  % (Path(log).name, "MATCH" if agree else "MISMATCH", e,
                     "failed too" if agree else "passed"))
        return [] if agree else ["model rejects arguments the run accepted"]
    if not info["passed"]:
        problems.append("run did not PASS")
    for key, value in want.items():
        got = info["results"].get(key)
        if got != value:
            problems.append("RESULT %s: run %s, model %s" % (key, got, value))
    traced = info["arena_vpn"] is not None
    if traced:
        if info["traceend"] != (sink.refs, sink.bytes):
            problems.append("TRACEEND %s, model refs=%d bytes=%d"
                            % (info["traceend"], sink.refs, sink.bytes))
        if trace is not None:
            size = os.path.getsize(trace)
            if size != sink.bytes:
                problems.append("trace file %d bytes, model %d" % (size, sink.bytes))
            elif file_md5(trace) != sink.md5.hexdigest():
                problems.append("trace file differs from the model's string")
    if not quiet:
        what = ("trace byte-identical" if traced and trace is not None and not problems
                else "TRACEEND only" if traced else "untraced run")
        print("%-40s %s  refs=%d writes=%d checksum=%s  (%s, model %.1fs)"
              % (Path(log).name, "MATCH" if not problems else "MISMATCH",
                 sink.refs, sink.writes, want.get("checksum"), what, time.time() - t0))
        for p in problems:
            print("    " + p)
    return problems


def model_main(program):
    """Command line of a model on its own (python3 tools/hostmodel/<x>.py)."""
    ap = argparse.ArgumentParser(prog=program + " model")
    ap.add_argument("args", nargs="+", help="the program's own arguments")
    ap.add_argument("--arena-vpn", type=int, default=0)
    ap.add_argument("--trace-out", help="write the predicted trace here")
    a = ap.parse_args()
    results, sink = predict(program, a.args, a.arena_vpn, a.trace_out)
    for k, v in results.items():
        print("RESULT %s=%d" % (k, v))
    print("TRACE refs=%d bytes=%d writes=%d md5=%s"
          % (sink.refs, sink.bytes, sink.writes, sink.md5.hexdigest()))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("paths", nargs="+")
    a = ap.parse_args()
    pairs = []
    if (len(a.paths) == 2 and a.paths[0].endswith(".log")
            and a.paths[1].endswith(".trace")):
        pairs.append((a.paths[0], a.paths[1]))
    else:
        for p in a.paths:
            if os.path.isdir(p):
                for log in sorted(Path(p).glob("*.log")):
                    t = log.with_suffix(".trace")
                    pairs.append((str(log), str(t) if t.exists() else None))
            else:
                t = Path(p).with_suffix(".trace")
                pairs.append((p, str(t) if t.exists() else None))
    bad = checked = 0
    for log, trace in pairs:
        problems = check(log, trace)
        if problems is None:
            continue
        checked += 1
        bad += bool(problems)
    print("%d run(s) checked, %d mismatched" % (checked, bad))
    sys.exit(1 if bad or not checked else 0)


if __name__ == "__main__":
    main()
