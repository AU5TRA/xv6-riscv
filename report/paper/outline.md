# Paper outline: learned page replacement from what the kernel already sees

Target: MLSys 2027, research track. Deadline **30 Oct 2026**, official: plan for 19:00 UTC (see
paper-state.md). Body ≤10 pages, excluding references; appendix uploaded separately.

Updated 2026-10-12 on the final kernel results (week-16 report). Claim, title and framing are
**pending D2** with the collaborator. Never write "beats ARC".

Thesis sentence:
> **The kernel already sees enough.** A small whole-number score over the kernel's own signals beats
> Clock and is level with the strongest classical policy a kernel can run; bigger models do not pay.

Page-1 teaser: **Table 1**. In-kernel faults relative to Clock for FIFO, Aging, LFU, Clock,
S3-FIFO†, LHD† and ARC† (kernel forms) and the linear score, at 5/10/20% memory, plus instructions per
decision. Alternative: Fig 7 (cost against faults).

| § | Title | Pages | Claim | Figures/tables | Status |
|---|---|---|---|---|---|
| — | Abstract (192 words) | — | constraints → question → linear score → 14 workloads, 8.6% fewer than Clock at 10% [2–15%], level with ARC → heavier models 20–150× cost → 55× Clock decision cost, sampling halves it | — | pending D2 |
| 1 | Introduction | 1.5 | headroom (Belady 43–54%); kernel-form ARC ≈5%; the kernel already sees enough; C1–C5; 4 contributions; headline with intervals | Table 1 | stakes number TODO |
| 2 | Background and Motivation | 1.8 | mechanism; Obs 1 headroom; Obs 2 kernel signals informative; Obs 3 naive training fails; RQ1–RQ4 | Fig 1–3 | figures to draw/re-plot |
| 3 | Design | 2.6 | formulation; K/K+ features; decision-point data + probation; whole-number scoring (+ heavier models); guard (sim prototype); 32-sample scoring | Fig 4, Table 2, Alg 1 | Fig 4 to draw |
| 4 | Implementation | 0.75 | paging layer; policy code sizes; kernel forms of ARC/LHD/S3-FIFO; reference strings checked against program models; filled-memory simulator; exact instruction counts; cloud cross-check | — | QEMU version, bytes/page |
| 5.1 | Setup | 0.6 | 14 workloads (6 train, 8 unseen), 74/51 streams, metrics, equal-weight averaging, intervals | Table 3 | B3 missing; writes TODO |
| 5.2 | RQ1 information | 0.5 | kernel-signal capacity doesn't help; oracle inputs help only on familiar workloads, fail on real traces | Table 4 | sim; marginal fig in appendix |
| 5.3 | RQ2 in kernel | 0.8 | beats Clock at 10%; level with ARC; wins on btree/kv/heap/chase/join@20%; sim predicts kernel | Table 5 (table*, \input), Table 6 (intervals) | done |
| 5.4 | RQ3 cost | 0.5 | whole numbers lose nothing; 22,803 instr (55× Clock); sampling; break-even disk vs flash | Table 7, Fig 7 | Fig 7 to plot |
| 5.5 | RQ4 robustness | 0.4 | unseen workloads; controls; repeated failures; guard sim; noise floor | — | done |
| 5.6 | Ablations | 0.3 | capacity in kernel; training scope; data + probation (pre-refit); sample size | — | A3 rerun or label |
| 5.7 | Where it does not help | 0.2 | matmul 5%, SpMV, global graph, Bloom/app, real Redis, flash | — | done |
| 6 | Related work | 0.5 | heuristics (+LHD); learned caching; learned OS components | — | search + VERIFY |
| 7 | Discussion and limits | 0.5 | Linux not shown; why xv6; 7 limits from the week-16 report | — | done |
| 8 | Conclusion | 0.15 | restate | — | pending D2 |

Figures and tables: Fig 1 mechanism (draw), Fig 2 classical vs Belady (re-plot), Fig 3 feature correlation
(re-plot, regenerate), Fig 4 overview (draw), Fig 7 cost vs faults (plot from `cost_grid.csv`), Fig A marginal
value (appendix, regenerate); Tables 1–7 in the body; appendix tables for 5%/20%, heavier models and
trained-on-all are `\input` from `report/week_16_update/tables/`.

Challenge → technique → ablation: see paper-state.md, Spine.
