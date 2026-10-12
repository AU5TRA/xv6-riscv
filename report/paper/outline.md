# Paper outline: Glimpse (working name): learned page replacement from what the kernel already sees

Target: MLSys 2027, research track (assumed; see paper-state.md, Open questions). Body ≤10 pages,
excluding references. Deadline: 30 Oct 2026, 20:00 UTC — **unverified** (third-party trackers;
mlsys.org says the 2027 call is not out yet).

LaTeX: `main.tex` + `sections/*.tex`. Every subsection below exists in the skeleton with its claim,
`[Plan: …]` notes and red `[TODO: …]` markers.

Thesis sentence (reuse in title, introduction, design heading and conclusion):
> **The kernel already sees enough.** Accessed-bit scans and the refault bookkeeping kernels already
> keep carry nearly all the signal of a full reference trace, and a few integer multiply-adds over
> them beat Clock inside the kernel.

Page-1 teaser: **Table 1**, measured in the kernel. Faults/Clock on held-out variants for FIFO,
Aging, decayed LFU, Clock, Glimpse (global, per-family) and Belady (simulated), plus selection
ticks per eviction. Alternative: Figure 7, a scatter of decision cost against faults.

| § | Title | Pages | Claim this section makes | Figures/tables | Evidence status |
|---|---|---|---|---|---|
| — | Abstract (188 words) | — | Kernel constraints → question → Glimpse → info/integer results → in-kernel −3…−46% faults, −96% writes → cost 11–13× Clock | — | numbers exist; code link TODO |
| 1 | Introduction | 1.5 | Clock leaves 43–54% of faults; prior learned caching assumes per-access visibility; the kernel already sees enough; C1–C5 → T1–T5; 4 contributions | Table 1 (teaser) | done except stakes number, gap-closed in kernel, end-to-end |
| 2 | Background and Motivation | 2.0 | | Fig 1–3 | |
| 2.1 | Page replacement, as the kernel sees it | 0.5 | Decision = victim per eviction, on the fault path, from A/D bits only | Fig 1 mechanism | to draw |
| 2.2 | Heuristics leave large headroom (Obs 1) | 0.5 | Clock ≈ LRU; Belady −43…−54% on btree/kv/graph; fixed combinations fail somewhere → learn the combination | Fig 2 (classical.pdf) | done (sim) |
| 2.3 | The kernel's coarse signals carry the information (Obs 2) | 0.4 | sfreq ≈ freq, rdist strong, within-decision ≠ pooled → kernel features, decision-level training | Fig 3 (diagnostics.pdf) | done (sim) |
| 2.4 | A naively trained policy fails (Obs 3) | 0.4 | Uniform sampling → evicts the streamed page (97% of victims just loaded) → stratify + probation | text (fig optional) | done |
| 2.5 | Research questions | 0.2 | RQ1 information, RQ2 in-kernel effect, RQ3 cost, RQ4 robustness | — | — |
| 3 | Glimpse: learning from what the kernel already sees | 3.0 | | Fig 4 overview, Table 2, Alg 1 | |
| 3.1 | Overview and formulation | 0.5 | Imitation of Belady by regression on log next-use; offline training, frozen integer inference | Fig 4 | to draw |
| 3.2 | Features the kernel already keeps (C1→T1) | 0.5 | K and K+ tiers with Linux analogues; oracle tier as ablation only | Table 2 | done |
| 3.3 | Training on decisions, not references (C3→T3) | 0.5 | Decision-point data, recency-stratified recording, probation | — | done |
| 3.4 | Integer-only scoring (C2→T2) | 0.4 | Eq. 1, Q8 log1p tables, folded standardisation | Eq 1 | done |
| 3.5 | When the model is wrong (C4→T4) | 0.6 | Validated victim + Clock fallback; data invariance; probation; validation-only selection; **refault guard** | Alg 1 | guard **missing** |
| 3.6 | Bounding the decision cost (C5→T5) | 0.3 | Sampled/batched scoring | — | **missing** (else → §7) |
| 4 | Implementation | 0.75 | Paging layer for xv6; Glimpse in 39+63 lines; complete reference strings; validated simulator; availability; training cost | — | LOC recount, bytes/page TODO |
| 5 | Evaluation | 3.0 | | Tables 3–6, Fig 5–7 | |
| 5.1 | Setup | 0.5 | Platform, workloads (5 or 12 families), splits, memory, baselines B1–B5, metrics | Table 3 | baselines B2/B3 **missing**; QEMU version TODO |
| 5.2 | RQ1: does the kernel see enough? | 0.6 | K∪K+ beats Clock everywhere; oracle within ±1.5%; idle dominates; selection matters | Table 4, Fig 5 | done (sim) |
| 5.3 | RQ2: does it work inside the kernel? | 0.7 | −3…−46% faults on held-out; −86…−96% writes on graph/matmul; sim predicts kernel | Table 5, Fig 6 | done (10% only) |
| 5.4 | RQ3: what does a decision cost? | 0.4 | Integer = float; 11–13× Clock ticks; **break-even, cycles, end-to-end** | Table 6, Fig 7 | ticks done; rest **missing** |
| 5.5 | RQ4: robustness and generalisation | 0.4 | Held-out ≥ test; global model 8/9; capacity sensitivity; **unseen families; wrong models** | — | partly **missing** |
| 5.6 | Ablations | 0.3 | A2 model class, A3 data + probation, DAgger; **A4 guard, A5 sampling** | (table TODO) | A2/A3 done |
| 5.7 | Where Glimpse does not help | 0.2 | sort, global/matmul, graph at 5/20%, cliff stream, zero-benefit case | — | zero-benefit **missing** |
| 6 | Related work | 0.6 | Heuristics; learned caching; learned OS components — one difference sentence each | — | citations VERIFY |
| 7 | Discussion and limitations | 0.4 | Linux transfer (feature map), why xv6, workload realism, 6 limitations | — | transfer evidence **missing** |
| 8 | Conclusion | 0.15 | Restate thesis + headline + cost | — | — |
| | **Total** | **≈10.0** | | 7 figs, 6 tables, 1 alg | skeleton body today ≈ 9.5 pp |

Figure plan (≈10 figures in typical accepted papers; here 7 planned + teaser table):

| # | What | Data | Status |
|---|---|---|---|
| T1 | Teaser: in-kernel held-out faults/Clock + ticks | kernel_eval / summary_kernel | in skeleton |
| F1 | Eviction path and what the policy can see | kernel/vmpage.c | to draw |
| F2 | Classical policies vs Belady | figures2/classical.pdf | re-plot (no in-figure title, grayscale) |
| F3 | Within-decision feature correlation | figures2/diagnostics.pdf | re-plot one column |
| F4 | Overview (offline / online) | — | to draw (figure*) |
| F5 | Marginal value of each kernel feature | figures2/marginal.pdf | re-plot |
| F6 | Kernel vs simulator, per run | results2/kernel_vs_sim.csv | to plot |
| F7 | Decision cost vs faults trade-off (+ sampling curve) | results2/kernel_eval.csv | to plot; teaser candidate |
| opt | Victim-age distribution naive vs Glimpse vs Belady | needs a small replay | optional |

Challenge → technique → ablation map (the paper's spine):

| Challenge (measured where?) | Technique (§) | Ablation (figure/table) | Status |
|---|---|---|---|
| C1 The kernel never sees accesses (§2.1, §2.3) | T1 K/K+ features from A/D scans + refault bookkeeping (§3.2) | A1 tiers F / K / K∪K+ / F∪K (Table 4; kernel K-only vs K∪K+, Table 5) | done |
| C2 No floating point; per-eviction budget (§3.4) | T2 integer linear scorer, Q8 tables, folded standardisation (§3.4) | A2 float vs 4/8/12-bit; linear vs MLP/GRU/embedding (§5.4, §5.6) | done (sim) |
| C3 Decisions compound; naive data evicts the streamed page (§2.4) | T3 decision-point data, recency-stratified recording, probation (§3.3) | A3 v1 vs v2; probation 0/1/2/4; DAgger (§5.6) | done |
| C4 A wrong model can be catastrophic (≥3× Clock subsets; global loses on matmul) (§5.2, §5.7) | T4 validated victim + Clock fallback, validation-only selection, **refault guard** (§3.5) | A4 wrong-model tests, guard on/off (§5.5) | guard + test **missing** |
| C5 Full-scan selection costs 11–13× Clock (§5.4) | T5 sampled / batched scoring (§3.6) | A5 sample size k vs faults and ticks (Fig 7) | **missing** (optional) |

Contributions (each with §):
1. Glimpse, a learned page-replacement policy that runs inside a kernel: integer-only, kernel-observable
   signals, per-process weights (§3, §4).
2. A study of what a learned eviction policy needs: 3 feature tiers, 300 subsets × 6 scopes (28,800
   replays), neural/sequence/embedding/ranking models; oracle features buy almost nothing (§2, §5.2, §5.6).
3. An in-kernel evaluation on unseen seeds and variants: 231 runs, faults, writes, selection cost, and the
   simulator's prediction of each run (§5.3, §5.4).
4. A paging platform and dataset for xv6 (keep only if released anonymously) (§4, App. A).
