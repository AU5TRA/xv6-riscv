#!/bin/bash
# Phase 2 regression-matrix driver (docs/ROADMAP.md, Phase 2, Steps 2-8).
#
# Never edit this file while it is executing: bash reads scripts
# incrementally by byte offset and will resume inside the new text
# (docs/phase0-phase1-report.md, section 2.10).
#
# Usage:  bash tools/phase2_gate.sh <stage>
#   all           every stage below, in order
#   debugbuild    clean + build CPUS=1 VM_DEBUG=1 + fresh fs.img
#   debugtests    the full matrix in the VM_DEBUG configuration
#   releasebuild  clean + build CPUS=1 + fresh fs.img
#   releasetests  the full matrix in the release configuration
#   bigtrace      a million-event lossless capture, decoded host-side
#   smp           CPUS=3 stress only -- not a correctness claim
#
# make clean between the release and VM_DEBUG configurations is not
# optional: without it the user programs recompile without -DVM_DEBUG while
# the kernel keeps it, and the debug-only subtests silently do not run.
#
# Every step records name / duration / exit status into
# docs/phase2/gate-results.txt.  Steps do not abort the stage on failure;
# the whole matrix runs so that one pass yields the full picture.

cd /mnt/d/thesis/xv6-riscv || exit 2
. /home/ashfaq/xv6env.sh

RESULTS=docs/phase2/gate-results.txt
RUN="python3 tools/run_xv6_tests.py --cpus 1"
FAILED=0

note() { printf '%s\n' "$*" | tee -a "$RESULTS"; }

step() {
  local name="$1"; shift
  local start end rc
  start=$(date +%s)
  printf '\n===== STEP %s =====\n' "$name" >>"$RESULTS"
  printf '# cmd: %s\n' "$*" >>"$RESULTS"
  "$@" >>"$RESULTS" 2>&1
  rc=$?
  end=$(date +%s)
  if [ $rc -eq 0 ]; then
    note "RESULT PASS  $name  ($((end-start))s)"
  else
    note "RESULT FAIL  $name  ($((end-start))s)  rc=$rc"
    FAILED=$((FAILED+1))
  fi
  return 0
}

# usertests is not idempotent on a dirty image: grind leaves /a behind and
# unlinkcwd opens with an mkdir("/a") it requires to succeed.  Any step that
# needs a known filesystem state builds its own image.
freshfs() { rm -f fs.img && make fs.img >/dev/null 2>&1; }

run_debugbuild() {
  export VM_DEBUG=1
  step "debug: make clean"  make clean
  step "debug: build"       make -j"$(nproc)" CPUS=1 VM_DEBUG=1
  step "debug: fs.img"      bash -c 'rm -f fs.img && make fs.img VM_DEBUG=1'
}

run_debugtests() {
  export VM_DEBUG=1
  step "debug: vmtest baseline"         $RUN --timeout 900  "vmtest baseline"
  step "debug: vmtest data-invariance"  $RUN --timeout 900  "vmtest data-invariance"
  step "debug: vmtest all"              $RUN --timeout 2400 "vmtest all"
  step "debug: prefetchtest all"        $RUN --timeout 2400 "prefetchtest all"
  for p in fifo clock aging; do
    step "debug: vmtest all-policy $p"  $RUN --timeout 2400 "vmtest all-policy $p"
    step "debug: prefetchtest all $p"   $RUN --timeout 2400 "prefetchtest all $p"
  done
  for seed in 1 2 3 4 5 17 31 127 1024 65535; do
    step "debug: soak seed $seed"       $RUN --timeout 2400 "vmtest random $seed 100000"
  done
  step "debug: fresh fs.img (bigfile)"  freshfs
  step "debug: bigfiletest all"         $RUN --timeout 2400 "bigfiletest all"
  step "debug: fsck after bigfiletest"  python3 tools/fsck_xv6.py fs.img --fssize 100000
  step "debug: fresh fs.img (grind)"    freshfs
  step "debug: grind 200"               $RUN --timeout 2400 "grind 200"
  step "debug: fresh fs.img (usertests)" freshfs
  step "debug: usertests -q"            $RUN --timeout 5400 "usertests -q"
  step "debug: fsck after usertests"    python3 tools/fsck_xv6.py fs.img --fssize 100000
}

run_releasebuild() {
  unset VM_DEBUG
  step "release: make clean" make clean
  step "release: build"      make -j"$(nproc)" CPUS=1
  step "release: fs.img"     bash -c 'rm -f fs.img && make fs.img'
}

run_releasetests() {
  unset VM_DEBUG
  step "release: vmtest baseline"        $RUN --timeout 900  "vmtest baseline"
  step "release: vmtest data-invariance" $RUN --timeout 900  "vmtest data-invariance"
  step "release: vmtest all"             $RUN --timeout 2400 "vmtest all"
  step "release: prefetchtest all"       $RUN --timeout 2400 "prefetchtest all"
  for p in fifo clock aging; do
    step "release: vmtest all-policy $p" $RUN --timeout 2400 "vmtest all-policy $p"
    step "release: prefetchtest all $p"  $RUN --timeout 2400 "prefetchtest all $p"
  done
  for seed in 1 2 3 4 5 17 31 127 1024 65535; do
    step "release: soak seed $seed"      $RUN --timeout 2400 "vmtest random $seed 100000"
  done
  step "release: fresh fs.img (bigfile)" freshfs
  step "release: bigfiletest all"        $RUN --timeout 2400 "bigfiletest all"
  step "release: fsck after bigfiletest" python3 tools/fsck_xv6.py fs.img --fssize 100000
  step "release: fresh fs.img (grind)"   freshfs
  step "release: grind 200"              $RUN --timeout 2400 "grind 200"
  step "release: fresh fs.img (usertests)" freshfs
  step "release: usertests -q"           $RUN --timeout 5400 "usertests -q"
  step "release: fsck after usertests"   python3 tools/fsck_xv6.py fs.img --fssize 100000
}

# An overrunning capture must be REJECTED, not truncated to the part that
# survived. This step therefore passes when the run fails: it is positive
# evidence that the drop discipline fires, which is the whole basis for
# trusting any capture that does not trip it.
#
# The overrun is FORCED with a deliberately tiny ring rather than produced by
# outrunning the real one. The first version relied on the workload emitting
# faster than the drainer, and enlarging VMTRACE_CAPACITY to 262144 made the
# capture lossless -- at which point the test correctly reported that its own
# premise had gone. Forcing it keeps this independent of the ring size.
overrun_capture() {
  local log
  if $RUN --timeout 3600 "vmdrain over.bin smallring 4096 vmtest random 1 30000"
  then
    echo "UNEXPECTED: an overrunning capture was reported lossless"
    return 1
  fi
  log=$(ls -t test-logs/*vmdrain-over.bin*.log 2>/dev/null | head -1)
  [ -n "$log" ] || return 1
  grep -q "vmdrain: INVALID: dropped=" "$log" || return 1
  grep -q "capture lost records" "$log" || return 1
  echo "overrun correctly rejected; evidence: $log"
  grep -E "vmdrain: (over\.bin|kernel|INVALID)" "$log"
  return 0
}

# Trace integrity, in three parts.
#
#  1. A real guest-to-host capture that is lossless, decoded --strict.
#  2. A real guest-to-host capture that overruns, and is rejected for it.
#  3. The decoder round-tripping 1,000,000 records and detecting both a
#     removed record and a mid-record truncation.
#
# Part 3 is synthetic on purpose. A genuine 1,000,000-record in-guest
# capture is not currently reachable: vmdrain sustains about 5.3k
# records/s to the xv6 filesystem while a paging workload emits about 12k
# records/s, so any window long enough to reach a million records overruns
# first. That measurement is the finding, not a gap -- see
# docs/phase2/report.md.
run_bigtrace() {
  unset VM_DEBUG
  step "trace: fresh fs.img"        freshfs
  step "trace: capture swap-repeat" $RUN --timeout 2400 \
      "vmdrain trace.bin collect vmtest swap-repeat"
  step "trace: extract swap-repeat" \
      python3 tools/extract_file.py fs.img trace.bin /tmp/p2-trace.bin
  step "trace: decode swap-repeat" \
      python3 tools/decode_trace.py /tmp/p2-trace.bin --strict --csv /tmp/p2-trace.csv
  step "trace: fresh fs.img (overrun)" freshfs
  step "trace: overrun is rejected" overrun_capture
  step "trace: decoder selftest 1M" \
      python3 tools/decode_trace.py /tmp/p2-selftest.bin --selftest 1000000
}

# Stress only. CPUS=1 is the scientific reference configuration; no
# cross-hart TLB shootdown exists, so multicore paging correctness is not
# claimed (ROADMAP Group D).
run_smp() {
  export VM_DEBUG=1
  step "smp: make clean"   make clean
  step "smp: build CPUS=3" make -j"$(nproc)" CPUS=3 VM_DEBUG=1
  step "smp: fs.img"       bash -c 'rm -f fs.img && make fs.img VM_DEBUG=1'
  step "smp: vmtest multiproc" \
      python3 tools/run_xv6_tests.py --cpus 3 --timeout 2400 "vmtest multiproc"
  step "smp: prefetchtest worker-stress" \
      python3 tools/run_xv6_tests.py --cpus 3 --timeout 2400 "prefetchtest worker-stress"
}

stage="${1:-}"
note ""
note "########## STAGE $stage  started $(date -Is) ##########"

case "$stage" in
  debugbuild)   run_debugbuild ;;
  debugtests)   run_debugtests ;;
  releasebuild) run_releasebuild ;;
  releasetests) run_releasetests ;;
  bigtrace)     run_bigtrace ;;
  smp)          run_smp ;;
  all)
    run_debugbuild
    run_debugtests
    run_releasebuild
    run_releasetests
    run_bigtrace
    run_smp
    ;;
  *)
    echo "unknown stage: $stage" >&2
    exit 2
    ;;
esac

note "########## STAGE $stage  finished $(date -Is)  failures=$FAILED ##########"
exit $FAILED
