# Calibration methodology (WORK_PROMPT2.md Phase 4)

This document was supposed to report calibration of `kvbench`/`btreebench`
against real SQLite/Redis Linux traces: a distance metric, a parameter
search minimizing it, and overlaid statistics comparing native workloads
to their real counterparts. **That did not happen this pass, and this
document explains exactly why, rather than fabricating or approximating
a result.**

## The blocker

WORK_PROMPT2.md's Phase 4 explicitly depends on "the real SQLite and
Redis traces collected in Part 1 Phase 5" (WORK_PROMPT.md's own Phase
5: `tools/collect_linux_trace.sh` running real SQLite and Redis as
ordinary Linux programs under Valgrind Lackey or DynamoRIO's
`drcachesim`).

**That Phase 5 was not done.** It was explicitly dropped when reached,
under WORK_PROMPT.md's own sanctioned escape hatch ("if time is short,
this phase is the one to drop") given the time already spent on Phases
0-4 of that document.

When WORK_PROMPT2.md's Phase 4 made calibration against those traces
"the primary scientific contribution" of this continuation, the
prerequisite gap became a hard blocker rather than a scope choice, so
before writing any calibration code the environment was checked
directly:

```
$ which valgrind sqlite3 redis-server redis-cli
(nothing -- none are installed)
$ apt-cache policy valgrind redis-server sqlite3
  (all three ARE available as candidates in the standard Ubuntu 24.04
   "noble" repositories -- this is not a "doesn't exist" problem)
$ sudo -n apt-get install -y valgrind redis-server sqlite3
sudo: a password is required
```

No passwordless `sudo`, and no other package-install path was found.
**This is a real, verified environmental limitation of the sandboxed
session this work ran in** — not a time-management choice, and not
something that can be worked around by trying harder inside the same
session. The packages are ordinary, freely available Ubuntu packages;
installing them from a session with working `sudo` (or pre-installed)
would remove this blocker entirely.

## What this means for Phase 4/5 as specified

- **Phase 4 (calibration)**: cannot be executed as written. There is no
  honest way to compute a distance metric between `kvbench`/`btreebench`
  and "real Redis/SQLite" without real Redis/SQLite reference traces to
  compare against. Fabricating plausible-looking numbers here would be
  actively worse than reporting nothing — WORK_PROMPT2.md itself says
  "Do not select metrics or parameter ranges that flatter the match,"
  and inventing the comparison data entirely is a stronger version of
  exactly that failure mode.
- **Phase 5 (lock in calibrated presets, regenerate dataset)**: depends
  entirely on Phase 4's search results. Also not done, for the same
  reason.

## What was still done (Phases 1-3), and why it stands on its own

Phases 1-3 do NOT depend on real traces — they enrich the native
workloads with real database/store *mechanisms* (incremental rehashing,
heavy-tailed values, TTL, a WAL, an internal cache) and build the
statistics machinery to characterize any trace, native or real. All of
that was completed and verified this pass (see `docs/workloads.md`
SS"WORK_PROMPT2.md additions" for the measured on/off comparisons). The
statistics library itself (`tools/trace_decode.py`: reuse-distance
histogram, miss-ratio curve, working-set-over-time, phase detection,
conditional entropy) is validated against a hand-computed example
(`python3 tools/trace_decode.py --selftest <any-arg>`) and ready to run
against real traces the moment they exist — the missing piece is
specifically the real-trace *collection* step, not the analysis
pipeline that would consume it.

## To actually unblock Phase 4

Whoever has `sudo`/package-install access in an interactive session
should run once:

```
sudo apt-get install -y valgrind redis-server sqlite3
```

then implement WORK_PROMPT.md's Phase 5 (`tools/collect_linux_trace.sh`
running representative SQLite and Redis workloads under Valgrind Lackey
or `drcachesim`, `tools/trace_reduce.py` converting the byte-address
trace to the page-granularity `TRACEHDR`/`T <vpn>` format this suite
already uses). Once real traces exist in that format, `tools/sim.py`
and every function in `tools/trace_decode.py` already work on them
unmodified — Phase 4's actual calibration search (propose a distance
metric, grid-search `kvbench`/`btreebench` parameters, report the
unrelated-workload control) is a few hours of host-side Python from
there, not a re-architecture.

## Honest bottom line

This is a negative result on the specific ask ("calibrate against real
traces this pass"), for a verified environmental reason, not a swept
-under-the-rug one. Per WORK_PROMPT2.md's own instruction: "A negative
or partial result is scientifically useful and I would much rather have
it than a tuned-to-look-good number." Reporting it plainly here.
