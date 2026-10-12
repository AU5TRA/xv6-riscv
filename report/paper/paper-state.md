# Paper state

Running memory of the writing process (skill: `mlsys-ml-for-os-paper`). Update at the end of every step.
Created 2026-10-11 at Steps 0–4 (intake, positioning, spine, evaluation plan, outline), in skeleton form.
Next step in the skill's order: **Step 5.1, draft Background and Motivation**, while the experiments
in "Experiment priority" run in parallel.

## Basics
- **Working title:** Glimpse: Learned Page Replacement from What the Kernel Already Sees.
  "Glimpse" is a working name (`\sys` in `macros.tex`; one edit renames it everywhere). Check name
  collisions; there is an old file-search tool called Glimpse. Alternatives:
  - *Can the Kernel Learn to Evict? Learned Page Replacement Under Kernel Constraints*
  - *The Kernel Already Sees Enough: Integer-Only Learned Page Replacement Inside an OS Kernel*
  - *Enough to Evict: …*
- **Target:** MLSys 2027, research track. *Assumed; the author named the MLSys template but not the year.*
- **Deadline:** 30 Oct 2026, 20:00 UTC. Source: **unverified**, from third-party trackers
  (beri.net, mldeadlines.com). mlsys.org/Conferences/2027/CallForPapers says "Details for MLSys 2027
  have not been announced yet". Checked by Claude on 2026-10-11. Confirm, including any abstract-registration date.
  That is **~18 days away**. The 2027 style file may differ from the copied `mlsys2025.sty`.
- **Authors:** academic → research track (double-blind). No names in this file.
- **OS mechanism and decision:** page replacement. At each eviction (a process at its resident
  limit faults), choose which of its resident pages to evict.
- **Decision frequency and latency budget:** once per eviction, synchronously on the fault path
  (`reclaim_frame` → `choose_policy_victim` → `choose_ml`). Budget: small next to the fault it avoids (a
  disk read, often a write). Measured: 400–452 emulated timer ticks per eviction (10 MHz, so about
  40–45 µs emulated), 11–13× Clock and about 2× Aging. No real-hardware number yet.
- **ML technique and where inference runs:** supervised imitation of Belady. Weighted ridge regression
  (closed form) on log(1+next-use distance), trained on eviction decisions recorded from LRU replays,
  with feature subset and probation selected on validation. Training is offline on the host. Inference
  runs **in the kernel**, integer-only, with frozen per-process weights (`vmctl`).
- **Prototype platform:** xv6-riscv (upstream `7d01506`) plus a paging layer of about 3.4k kernel lines;
  QEMU, one hart.

## Positioning (Step 1)
- **Stakes:** [TODO: one supportable number with a citation. Do not invent it.]
- **Why heuristics fail:** Belady needs 43–54% fewer faults than Clock on btree/kv/graph (38% matmul,
  10–17% sort). Clock is within 1–2% of exact LRU on 4 of 5 families. Exact LFU is the only classical
  policy that beats Clock anywhere, and it is catastrophic elsewhere. (ML_REPORT §6.1)
- **Why ML, and which kind:** the best way to combine recency, frequency, dirtiness and refaults differs per
  workload (255-subset sweep: the best subset and weights change by family, and many subsets are worse than
  Clock). Complete reference strings give exact labels offline, so supervised imitation of Belady fits
  (as in Parrot). RL would need exploration inside a kernel. DAgger was tried and did not help.
- **Closest work and delta:**
  - Learned cache replacement (Hawkeye, Glider, Parrot; LRB; LeCaR, CACHEUS) observes every access, uses
    floating point and is judged per request. Glimpse uses only A/D-bit scans and refaults, runs in
    integers and is evaluated inside a kernel.
  - LinnOS is an in-kernel NN, but for I/O latency, not paging.
  - MLSys ML-for-OS papers (VM allocation, LAVA, ProtoRAIL, storage placement, Catur) all sit above the kernel.
  - Closest by topic: the 2026 MLSys Young Professional Symposium poster on perceptron eviction for the
    Linux page cache via eBPF. It is non-archival and cannot be cited as a paper.
  - **VERIFY:** in-kernel learned eviction work at OSDI/SOSP/ATC/ASPLOS/EuroSys (eBPF page-cache
    policies). No "first" claim before this search.
- **Biggest reviewer risks and the plan for each:**
  1. *"Teaching OS, does it transfer?"* Plan: a feature map to MGLRU/DAMON/workingset (done in text),
     Valgrind Redis/SQLite traces in the simulator (cheap), and a limitations paragraph. A Linux
     prototype is out of reach for this deadline.
  2. *"Is the cost acceptable?"* Today there are only emulated ticks. Plan: cycles, a break-even
     analysis, end-to-end runtime, sampled scoring.
  3. *"What if the model is wrong?"* Today: validated victim with Clock fallback, data invariance,
     probation, validation-only selection. Plan: a refault guard plus a wrong-model test.
  4. *"Weak baselines."* The kernel's Clock is not textbook Clock (it walks the owned-list order), but it
     is within 1–2% of exact LRU. Plan: add ARC, CLOCK-Pro/LIRS, a WSClock-style dirty-aware Clock and an
     MGLRU-like policy in simulation. **The dirty-aware Clock is critical**: it decides how much of the
     write reduction is just "prefer clean pages".
  5. *"A linear model isn't ML."* Answer with the model-class ablation: MLP, GRU, embedding and ranking
     loss do not pay. Frame the contribution as what information and training data the policy needs.
- **Framing (author, 2026-10-11):** the paper is **not** about trace collection. It asks whether an
  ML-based eviction policy is implementable at OS level, using xv6 as the vehicle. So far the answer is
  yes, with decision time as the cost.

## Spine (Step 2)
- **Thesis sentence:** "The kernel already sees enough." Long form: accessed-bit scans and the refault
  bookkeeping kernels already keep carry nearly all the signal of a full reference trace, and a few
  integer multiply-adds over them beat Clock inside the kernel. Used in the title, the intro (Move 4),
  the §3 heading and the conclusion.
- **Challenges → techniques → ablations:**

| Challenge | Technique | Ablation | Status |
|---|---|---|---|
| C1 kernel never sees accesses | T1 K/K+ features (§3.2) | A1 tiers F/K/K∪K+/F∪K (Table 4; kernel K-only) | done |
| C2 no FP; per-eviction budget | T2 integer linear scorer (§3.4) | A2 float vs 4/8/12-bit; linear vs MLP/GRU/embedding | done (sim) |
| C3 decisions compound; naive data evicts the streamed page | T3 decision-point data, recency stratum, probation (§3.3) | A3 v1 vs v2; probation 0/1/2/4; DAgger | done |
| C4 wrong model can be catastrophic | T4 validated victim + fallback, validation-only selection, **refault guard** (§3.5) | A4 wrong-model test, guard on/off | **missing** |
| C5 full scan costs 11–13× Clock | T5 sampled scoring (§3.6) | A5 k sweep | **missing**, optional |

- **Contributions:** see outline.md (system; information study; in-kernel evaluation; platform + dataset).

## Evaluation matrix (Step 3)
Status per row: done / running / missing / n.a.

| Item | Status | Notes / numbers |
|---|---|---|
| Q list | done | RQ1 information, RQ2 in-kernel, RQ3 cost, RQ4 robustness (§2.5) |
| B1 default OS policy | done | Clock (xv6's best) + FIFO, Aging, decayed LFU, all in kernel (231 runs) |
| B2 best heuristics | partial | LRU and exact LFU (sim). **Missing:** ARC, CLOCK-Pro/LIRS, WSClock-style dirty-aware Clock, MGLRU-like. ARC/MRU exist in `tools/sim.py` (Python), not in `tools/ml2/pagesim.c` |
| B3 prior learned work | missing | e.g. LeCaR or CACHEUS with kernel-observable inputs; Parrot-style as an oracle-feature learned baseline |
| B4 no-model ablation | done | single-feature scorers are part of the 255-subset sweep (e.g. `idle` alone ≈ recency) |
| B5 oracle | done | Belady, every cell |
| B6 perfect predictor | n.a. | Belady is the perfect next-use predictor; say so |
| Held-out workloads | done | unseen variants (kv-F, btree-scan, graph-bfs2000, sort-n60000, matmul-*128). **Missing:** unseen *families* (7 new benchmarks) |
| End-to-end metric | missing | workload-phase runtime; break-even analysis |
| Ablation per technique | partial | A1–A3 done; A4, A5 missing |
| Sensitivity sweeps | partial | memory 5/10/20% (sim), probation. Missing: ridge, candidates/decision, recency stratum, label cap; kernel at 5%/20% |
| Generalisation / drift | partial | seeds, variants, global vs per-family. Missing: unseen families, leave-one-family-out |
| Overhead | partial | ticks/eviction, candidates/eviction, multiply-adds, training time. Missing: cycles (p50/p99), bytes per page and per swap slot, model bytes |
| Fallback / OOD behaviour | partial | Clock fallback on invalid victim (`policy_fallbacks`; report the count). Missing: refault guard, wrong-model test |
| Runs and spread; statistical test | missing | kernel counters are deterministic (a repeat gave identical counters); add bootstrap CI over streams and a Wilcoxon test vs Clock from existing CSVs |
| Code release (anonymized link) | missing | anonymous mirror; the history must not identify the authors |

## Numbers (single source; abstract = body)
Every number in the abstract and intro, with its source. Change it here first.

| Number | Where used | Source |
|---|---|---|
| 89 streams, 123M refs, 5 families | abstract, §5.1 | ML_REPORT §3; SPLITS.tsv (5 old families sum to 123.4M) |
| oracle within 1.5% on 3 families | abstract, §5.2 | ML_REPORT §6.5 (btree, graph, kv) |
| 8-bit integer within 0.002 | abstract, §5.4 | ML_REPORT §8 quant table (max \|Δ\| 0.002; 4-bit 0.018) |
| −3…−46% faults vs Clock, held-out, in kernel | abstract, intro, §5.3, §8 | kernel_heldout per-family: matmul 0.973, sort 0.933, kv 0.875, btree 0.854, graph 0.541 |
| up to 96% fewer writes | abstract, intro, §5.3 | kernel_writes_heldout matmul 0.035 (graph test 0.045) |
| 11–13× Clock selection; 40–45 µs emulated | abstract, intro, §5.4 | kernel_cost: 400.6–451.7 vs 35.3 ticks at 10 MHz |
| Belady 43–54% fewer faults than Clock | intro, §2.2 | classical_test: 0.550 / 0.571 / 0.456 |
| Clock within 1–2% of LRU on 4 of 5 | intro, §2.2 | classical tables (LRU 0.98–1.01) |
| 231 runs = 33 streams × 7 | intro, §5.3 | kernel_eval.csv (231 data rows) |
| 300 subsets × 6 scopes = 28,800 replays | intro | ML_REPORT §5.4 |
| 4.73M rows / 357K decisions | §3.3 | ML_REPORT §5.2 |
| 22–38% (test) / 23–73% (held-out) gap closed, sim | §5.2 | headline_workload tables |
| new data: 221 streams, 450.5M refs, 12 families, 13 held-out variants | comments only | traces/streams/ml/SPLITS.tsv (2026-10-11) |

## Outline (Step 4)
`report/paper/outline.md`. The LaTeX skeleton is in `report/paper/` (`main.tex`, `sections/`, `macros.tex`,
`references.bib`). Build with `latexmk -pdf main.tex`. It compiles cleanly (MiKTeX, 2026-10-11): 13 pages, of
which ≈9.5 are body before references and the appendix is pp. 12–13.

## Experiment priority (deadline < 4 weeks: start now, in parallel with writing)
Ranked by how hard a reviewer would hit the gap (skill Step 3 order). Effort is in working days.

1. **Headroom against the strongest heuristics (go/no-go for the write claims).** In `pagesim.c`: a
   WSClock-style dirty-aware Clock, ARC, CLOCK-Pro or LIRS, and an MGLRU-like generational policy, on the
   same cells. ~1–2 d. If dirty-aware Clock already gets most of the write reduction, reframe §5.3.
2. **Decision cost and end-to-end effect.**
   (a) Cycle counts (rdcycle/rdtime) around `choose_*`, as p50/p99. Real RISC-V hardware if available.
   (b) Break-even: faults avoided × fault service time against evictions × extra selection time.
   (c) Workload-phase runtime in the kernel runs.
   (d) Zero-benefit overhead on `pat-uniform`.
   (e) Optionally, sampled scoring with k ∈ {8, 16, 32, 64, all}, first in sim, then one kernel run per family.
   ~2–4 d.
3. **Misprediction handling.** Refault guard (fall back to Clock for T evictions when recent victims refault
   too often) in sim, then the kernel. Wrong-model tests: negated weights, random weights, the
   catastrophic subsets. Report the worst per-stream ratio and how often the guard fires. ~2 d.
4. **Unseen families.** Run the existing five-family global model, unchanged, on the 7 new families'
   streams in sim (no retraining, no GPU). Then a leave-one-family-out linear refit. ~1 d.
5. **Ablation gaps.** Hyperparameter sensitivity (ridge, 32 candidates, recency stratum 4, label cap) in
   sim. ~0.5 d.
6. **Spread.** Bootstrap CIs over streams and a Wilcoxon test against Clock, from the existing CSVs. ~0.5 d.
7. **Breadth.**
   - Kernel runs at 5% and 20% (`kernel_eval.py --fracs 0.05,0.2`; hours of QEMU). Use ≤6 lanes and a
     Task Scheduler launch: WSL crashed under 8–12 lanes.
   - Replay the Valgrind Redis/SQLite traces in sim as transfer evidence. ~0.5 d.
   - A Linux prototype is out of scope for this deadline.

## Drafting log (Step 5)
| Section | Draft status | Open TODOs |
|---|---|---|
| Abstract | first draft (188 words) | code link; dataset size if new families enter |
| 1 Introduction | skeleton: Moves 2, 4, 6, 7 drafted; 1, 3, 5 as plans | stakes number; gap closed in kernel; end-to-end |
| 2 Background | skeleton with real observations | Fig 1 to draw; Fig 2/3 re-plots |
| 3 Design | skeleton; §3.2–3.4 drafted | guard (§3.5), sampling (§3.6), Fig 4 |
| 4 Implementation | drafted | LOC recount; bytes per page; model bytes; anonymized link |
| 5 Evaluation | skeleton with all existing numbers | B2/B3, cost, robustness, spread, unseen families |
| 6 Related work | plan + difference sentences | verify citations; find in-kernel learned eviction work |
| 7 Discussion | FAQ skeleton | transfer evidence |
| 8 Conclusion | drafted | — |

## Review simulation (Step 6)
- Not yet run. Run it after Steps 5.1–5.4 are drafted.

## Submission check (Step 7)
- `check_draft.py main.tex` run on 2026-10-11. Remaining flag: 18 subsections against a median of 13.
  Merge some (e.g. fold §3.6 into §3.5 or §7; merge §2.3 and §2.4) once drafting settles. The PDF check
  is unreliable on the review-mode PDF (line-number margin).
- Anonymity check: author block anonymized, e-mail removed. Still to check: repository URLs, the commit
  history of any code link, and the person/handle names used in the repo docs.
- Numbers in abstract = body: consistent at skeleton time (see Numbers).

## Open questions for the author
1. **Venue and year.** Is the target really MLSys 2027 (deadline ≈ 30 Oct 2026, unverified, about 18 days)?
   Or is this thesis-first with a later venue? This decides how many experiments in the priority list are realistic.
2. **Authorship and framing with your collaborator.** The work spans two people's parts (platform and
   traces; ML study and in-kernel policy). The handoff's §0.2 questions ("is the thesis about learned
   replacement with the platform as foundation?") are still unanswered in `AUSTRA_HANDOFF.md`. The
   paper's framing follows your message (feasibility of in-kernel ML). Confirm it with them and your supervisor.
3. **Dataset scope.** Keep the paper on the 5 studied families (89 streams), or bring in all 12 (221
   streams)? Retraining the neural models needs a machine with PyTorch; linear models run here.
4. **The 7 new families: training data or unseen-family test?** Recommendation: first use them as wholly
   unseen families for RQ4 (cheap, and the strongest generalisation result available), then decide on retraining.
5. **Refault guard and sampled scoring.** Will these be built before the deadline? If not, they become
   limitations, and the paper must say plainly that misprediction handling is selection and probation only.
6. **Linux transfer.** Is the Valgrind-trace replay enough, or do you plan a Linux prototype later?
7. **Real RISC-V hardware** for cycle counts, if any is available?
8. **System name and title** (Glimpse is a placeholder).
9. **Code release** as an anonymous mirror at submission?

## TODO (owner, due)
- [ ] Confirm the deadline and abstract-registration date on mlsys.org (author)
- [ ] Answer the open questions above (author)
- [ ] Experiments 1–4 of the priority list (author + collaborator)
- [ ] Verify every `% VERIFY` entry in `references.bib`; find the in-kernel learned eviction work (author)
- [ ] Verify: MGLRU merge version (ML_REPORT §9 says 5.18+; believed to be 6.1); DAMON version (author)
- [ ] Count `policy_fallbacks` over the 231 kernel runs (expected 0) (author)
- [ ] Re-plot figures 2, 3, 5 for one column, grayscale-safe, without in-figure titles; draw figures 1 and 4
- [ ] Step 5.1: draft §2 prose (next writing step)

## Decisions made (date: decision, reason)
- 2026-10-11: The paper lives in `report/paper/` (LaTeX, MLSys 2025 style files copied in). Not committed.
- 2026-10-11: Framing is the feasibility of an in-kernel learned policy, not trace collection (author's
  instruction). Platform and dataset are the 4th contribution, kept only if released.
- 2026-10-11: The page-1 teaser is a table of in-kernel held-out results; the decision-cost scatter is the alternative.
- 2026-10-11: Related work goes after the evaluation (2/3 of accepted papers do this).
- 2026-10-11: Only the author's own results (ML_REPORT, results2 CSVs) supply numbers. Each carries a
  `% src:` comment in the .tex files.
