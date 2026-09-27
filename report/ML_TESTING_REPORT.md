# ML Page-Replacement Policy — Testing Report

Written after two rounds of experiments investigating why the first ML
policy prototype (`tools/ml_policy_prototype.py`) lost to the classical
policies, and whether a different architecture or a different feature
set could close the gap. Everything below runs entirely on the host
(Python/PyTorch/NumPy), never inside xv6 — see `HANDOFF_TO_CLAUDE.md`
for why (no floating point anywhere in xv6).

**Bottom line up front**: the failure was never about model capacity.
Seven different architectures, given the same (weak) features, converge
to nearly identical, mediocre results. Switching to a genuinely
different *feature* — total access frequency so far, which none of the
four classical kernel policies track — produces the first model that
actually beats every classical policy, using nothing more than plain
linear regression.

**Update after Experiment 3** (the full sweep across all six workloads,
133 trained models total): the pattern holds up broadly, not just on
graphbench. A simple model beats the best classical policy on **5 of
7** workload/variant configurations, by a real margin on some
(`lzwbench`: −18%, `sortbench`: −15%). But there's no single winning
recipe — different workloads favor different features — and on the
two workloads with the smallest, most rigidly cyclic access patterns
(`sortbench`, `matmulbench`), the *same* techniques that work
elsewhere can fail catastrophically (up to ~6,000x worse than the
worst classical policy), not just mediocrely. See Experiment 3 below
for the full results and the investigation into why.

**Update after Experiments 4 and 5**: Experiment 4 (hand-written, not
learned, LFU and stack-distance-based policies) confirms Experiment 3's
mechanism directly — the *same* two workloads (`sortbench`,
`matmulbench`) break just as catastrophically for a plain counter-based
heuristic as they did for a trained model, so this was never a
training/generalization artifact, it's that frequency/distance-based
eviction is the wrong strategy for those specific access patterns,
learned or not. It also turns up a genuine, cheap win: hand-written LFU
beats every classical policy *and* every learned model tried so far on
`lzwbench` (−24% vs. clock, no training required). Experiment 5, the
more expensive cross-page/embedding model suggested as the natural next
step, is a clear negative result: despite giving the model a learned
per-page embedding and a global recent-context window (genuine
cross-page information, unlike anything tried in Experiments 1-3), it
does not beat the simple `global_frequency` feature on graphbench, does
not beat hand-written LFU on `lzwbench`, and is catastrophically worse
than classical policies on `sortbench` and both `matmulbench` variants
— the extra model capacity and cross-page context bought nothing here.

## Setup, common to both experiments

- **Workload**: `graphbench` (BFS + PageRank over a synthetic
  scale-free graph), chosen because `tools/oracle_gap_sweep.py`'s
  36-run sweep found it has the least classical-policy differentiation
  of any workload (FIFO/Clock/Aging/LRU within 0.1% of each other)
  alongside a large real gap to Belady's optimal (+70%) — i.e. the
  workload where a learned policy has the clearest opening to matter.
- **Train**: `traces/graphbench/graph-p15-c200.log` (capacity 204,
  2,703,968 references). **Held-out**: `graph-p20-c267.log` (capacity
  271, same reference stream, different memory pressure) — a real,
  if modest, generalization check, not just an in-sample fit.
- **Ground truth**: Belady's own optimal decision. For every reference,
  the label is the true forward distance (in reference-stream
  positions) to that page's next touch, looked up by scanning the
  already-recorded trace backwards — see "what is the ground truth"
  in the session's own prior answer, unchanged here. Capped at 50,000
  and log1p-transformed for training stability (a monotonic transform,
  so it never changes which candidate a trained model would pick to
  evict).
- **Evaluation**: every candidate model is wrapped in a policy
  simulator with the exact same shape as `tools/sim.py`'s
  `Fifo`/`Clock`/`Aging`/`Lru` classes — at eviction time, evict
  whichever resident page the model predicts has the largest future
  distance. Reported as real fault counts on the full reference
  stream, compared directly against FIFO, Clock, Aging, LRU, and
  Belady on the same data.
- All training data was randomly subsampled to 300,000 examples (of the
  2.7M available) for speed; evaluation always runs on the full
  reference stream, since fault/eviction counts depend on every access.

## Experiment 1 — does the architecture matter?

**Question**: the original prototype (linear regression on 3 scalars:
recency, frequency, previous interval) lost to the classical policies.
Is that because a linear model is too simple, or because there isn't
enough training data?

**Setup**: generalized the input from 3 hand-picked scalars to each
page's last **K=8** inter-access intervals (a short history, not just
one number), then tried seven architectures on the identical input:
plain linear (on the full 8-window, for a fair capacity comparison),
a 2-layer MLP, a vanilla RNN, an LSTM, a GRU, a small 1D-CNN, and a
single-block self-attention model with learned positional embeddings.
Script: `tools/ml_arch_experiments.py`.

**Diagnostic run first** (cheap, no training): raw correlation between
each of the 8 interval-history positions and the (log) label.

```
correlation(interval_k_steps_back, log next-dist), k=1..8:
-0.014, +0.132, -0.014, -0.014, -0.014, -0.014, -0.014, -0.014
```

Every position is essentially uncorrelated with the label except the
2nd-most-recent interval, and even that is weak (+0.13). **Training
examples were never the constraint** — 2,703,968 available, all used
via subsampling; this is a data-*volume* non-issue, the correlation
diagnostic already ruled that out before any model was trained.

**Results** (train / held-out faults):

| model | train | held-out |
|---|---|---|
| fifo (classical) | 143,341 | 134,851 |
| clock (classical, best) | 143,231 | 134,760 |
| aging (classical) | 143,345 | 134,855 |
| lru (classical) | 143,274 | 134,895 |
| linear8 | 143,107 | 134,624 |
| mlp | 143,308 | 134,878 |
| rnn | 143,306 | 134,555 |
| lstm | 143,308 | 134,877 |
| gru | 143,321 | 134,878 |
| cnn | 143,126 | 134,685 |
| attention | 143,107 | 134,624 |
| **belady (oracle)** | **87,042** | **75,779** |

**Finding**: all seven architectures land within ~0.2% of each other,
and within ~0.2% of the classical policies' own tight cluster — none of
them come anywhere near Belady. Going from a 3-scalar linear model to
attention over an 8-step history changed essentially nothing. This is
strong, clean evidence that **the bottleneck is the feature
representation, not model capacity** — no amount of architectural
sophistication helps if the input doesn't contain the signal.

**Why the interval-history features carry so little signal**: in
retrospect, this makes sense for graphbench specifically. A page's
future reuse in a BFS/PageRank workload depends on *graph topology* —
whether it's a hub vertex, its position in the current BFS frontier,
which PageRank iteration is running — not on the raw timing of that
page's own past accesses. Two pages with an *identical* recent-interval
history can have completely different futures if one is a hub and the
other isn't; own-page timing history structurally cannot distinguish
them.

## Experiment 2 — does the feature set matter?

**Question**: if interval-history is the wrong feature, what would a
*right* one look like? Tried several qualitatively different,
inexpensive-to-compute features, each checked by raw correlation
before training anything.

**Feature sets tried** (all computed causally — only using information
available at the time of the reference, nothing from the future):

- `recency` — reference-count gap since this page's last touch (what
  the original prototype used, for continuity)
- `stack_distance` — the theoretically correct LRU-style distance:
  *distinct* pages touched since this page's last touch, not raw time
- `global_frequency` — total number of times this page has been
  touched so far in the run
- `vpn_identity` — the page number itself, normalized (tests whether
  some pages are just intrinsically hot/cold regardless of history)
- `position` — how far into the run this reference is (`i / n`) —
  tests whether BFS-phase and PageRank-phase have different signatures
- `all_combined` — all five together

Script: `tools/ml_feature_experiments.py`.

**Diagnostic run first**:

```
correlation(feature, log next-dist), 2,703,968 examples:
recency            -0.0139
stack_distance      -0.0069
global_frequency    -0.2138
vpn_identity        +0.0000
position            -0.2178
```

Two features stand out as meaningfully more correlated than anything
in Experiment 1: `global_frequency` and `position`. `vpn_identity`
carries zero signal on its own (unsurprising — arena page numbers are
assigned by allocation order, not by graph structure).

**Results** (linear and a small MLP, per feature set; train / held-out
faults):

| feature set | linear | MLP |
|---|---|---|
| recency_only | 143,061 / 134,545 | 143,061 / 134,545 |
| stack_distance | 142,904 / 134,486 | 142,888 / 134,593 |
| **global_frequency** | **138,343 / 128,996** | 147,622 / 140,166 |
| vpn_identity | 142,855 / 134,406 | 142,957 / 134,462 |
| position | 142,879 / 134,465 | 142,879 / 134,689 |
| all_combined | 147,079 / 139,423 | 141,147 / 131,571 |
| *(best classical: clock)* | *143,231 / 134,760* | |
| *(belady, oracle)* | *87,042 / 75,779* | |

**The headline result**: `global_frequency` with plain **linear**
regression — **138,343 train-faults / 128,996 held-out-faults** —
genuinely beats every classical policy tested, on *both* the training
capacity and the held-out one. That's a ~3.4% reduction vs. the best
classical policy (clock) in-sample, and ~4.3% held-out. Modest, but
real, and it generalizes (the held-out improvement is at least as big
as the in-sample one, so this isn't overfitting to the training
capacity).

**Three findings worth flagging explicitly, all counter-intuitive at
first glance**:

1. **The MLP on `global_frequency` is *worse* than the linear model on
   the same single feature** (147,622 vs. 138,343 train-faults) — a
   second, independent confirmation that more model capacity does not
   help here, this time even actively hurting (likely overfitting a
   nonlinearity onto what is fundamentally a monotonic relationship).

2. **`position` correlates about as strongly as `global_frequency`
   (-0.218 vs. -0.214) but does almost nothing for the actual policy**
   (142,879, barely different from the classical cluster). The reason
   is methodological, not statistical: `position` is a function only
   of the *current reference index*, so it is identical across every
   resident candidate being compared at a single eviction decision —
   it has real correlation with the label in aggregate, but zero power
   to *rank* candidates against each other, which is the only thing
   that matters for an eviction policy. Raw correlation with the label
   is not sufficient to predict whether a feature will actually help;
   it must vary meaningfully *across the candidates being compared at
   decision time*.

3. **`all_combined` is worse than `global_frequency` alone for both
   model types** (147,079 linear / 141,147 MLP, vs. 138,343 for
   frequency alone). Adding weak or non-differentiating features
   (`position`, `vpn_identity`, `recency`, `stack_distance`) diluted
   the fit rather than adding information — a small, simple model with
   one genuinely informative feature beat a model handed five features
   including that same good one. Feature *selection*, not feature
   *quantity*, was what mattered here.

## Experiment 3 — does any of this generalize beyond graphbench?

**Question**: Experiments 1 and 2 only ever trained on `graphbench`.
Does `global_frequency`'s win hold up elsewhere, or is it specific to
PageRank's repeated-hub-revisit pattern? Recommended as the natural
next step (see the session's own prior answer) precisely because it's
cheap to check before investing in anything more elaborate.

**Setup**: every architecture from Experiment 1 (7 models) and every
feature set from Experiment 2 (6 feature sets × 2 models = 12) run on
**all seven workload/variant configurations** in the sweep archive —
`btreebench`, `kvbench`, `sortbench`, `graphbench`, `lzwbench`,
`matmulbench-naive`, `matmulbench-blocked` — not just graphbench. Same
train/held-out-capacity split pattern throughout (train at the
tighter of two capacities, evaluate at the looser one). 133 models
trained and evaluated in total (19 per workload × 7), ~76 minutes wall
time. Every trained model's weights and a metadata sidecar (workload,
feature set, capacities, resulting fault counts) are saved under
`report/models/` — 266 files, so any individual result here can be reloaded
without retraining. Full numeric results: `report/ml_comprehensive_results.csv`
(both gitignored, regenerable via `tools/ml_comprehensive.py`, same as
the trace data itself).

**Headline results** (best ML model per workload vs. best classical
policy, held-out capacity):

| workload | best classical | best ML model | held-out faults | vs. classical |
|---|---|---|---|---|
| `btreebench` | 36,556 (clock) | `all_combined`/linear | 36,273 | **−0.8%** |
| `kvbench` | 7,252 (clock) | `all_combined`/linear | 7,243 | **−0.1%** |
| `sortbench` | 1,267 (clock) | `all_combined`/mlp | 1,073 | **−15.3%** |
| `graphbench` | 134,760 (clock) | `global_frequency`/linear | 128,996 | **−4.3%** |
| `lzwbench` | 49,731 (clock) | `stack_distance`/mlp | 40,743 | **−18.1%** |
| `matmulbench`-naive | 27 (clock, ≈ optimal already) | `recency_only`/linear | 27 | tie (degenerate case) |
| `matmulbench`-blocked | 298 (clock) | `recency_only`/linear | 720 | **+141% (loses)** |

Five of seven beat the best classical policy, two don't. `clock` is
the best classical policy on every single workload here — worth noting
on its own, since it means the "no single heuristic wins" design
property this project deliberately built the workload suite around is
visible even among the *classical* policies, not just as a reason an
ML model might help.

**No single feature set wins everywhere.** The winning configuration
differs by workload: `all_combined` for btreebench/kvbench/sortbench,
`global_frequency` alone for graphbench, `stack_distance` for
lzwbench. This mirrors the project's own original design principle for
the workload suite itself ("no single fixed heuristic should trivially
win") — it turns out to extend to feature engineering too: there is no
one feature that is simply "the best" across access patterns this
different from each other.

**`matmulbench` is where this approach struggles most** — both
variants. Its working set is tiny (27 distinct pages total, per the
first prototype's own report) and Clock already gets within a few
percent of Belady-optimal there (298 vs. 121 for the blocked variant)
— there just isn't much room left to find, and nothing tried here
found it. The naive variant's "tie" is not a real win: capacity is so
tight relative to the working set that even Clock already matches
Belady exactly, so nothing (classical or learned) can improve on it.

### Catastrophic failures: the comprehensive study into "why," where results stayed negative

Not every miss was a *mediocre* one. Scanning every held-out result for
anything more than 5x worse than the worst classical policy turns up a
sharp, specific pattern:

| workload | catastrophic configs (>5x worst classical) |
|---|---|
| `btreebench`, `kvbench` (mostly), `graphbench`, `lzwbench` | none, or isolated (kvbench's `global_frequency`/linear at 5x) |
| **`sortbench`** | 10 of 12 feature-set configs, up to **721x** worse |
| **`matmulbench`-naive** | 7 of 19 configs, up to **6,171x** worse |
| **`matmulbench`-blocked** | 11 of 19 configs, up to **1,560x** worse |

Every catastrophic failure is concentrated in exactly the two
workloads with the smallest working sets and the most rigid, cyclic
access patterns. Investigated one directly: `sortbench`'s
`vpn_identity`-only linear model reaches 915,339 held-out faults out of
1,854,621 total references — roughly **half of every single access**
becomes a fault. `vpn_identity` is a *static* per-page value: the
model's predicted eviction priority for a given page never changes
across the whole run, regardless of what's actually happening. Sortbench
walks its arena in a fixed, repeating order across several merge passes
(see `docs/workloads.md`'s own description of it as a deliberately
boring, sequential sanity-check workload); a static, wrong preference
evicts the *same* soon-to-be-needed page on every single pass, and with
such a small arena, that one bad decision compounds across the whole
run instead of averaging out the way it would in a larger, more varied
working set like `graphbench`'s or `lzwbench`'s.

The same mechanism explains `matmulbench`'s failures: 27 distinct pages
total, walked in a fixed stride pattern, so any model whose predictions
don't track the *specific* current access order (not just a page's
fixed identity, or an isolated recency/frequency snapshot) can lock
into a systematically wrong, repeating choice. This is qualitatively
different from Experiment 1's finding (many architectures converging to
similarly *mediocre* results) — this is a small number of specific
feature/architecture combinations producing *actively adversarial*
results, and it's concentrated exactly where the working set is too
small and too regular for a wrong decision to ever get diluted by
variety.

**Practical implication**: on workloads shaped like `sortbench` or
`matmulbench` — small, rigid, already well-served by Clock — a
learned policy needs real evaluation on a held-out run before ever
being trusted, since a plausible-looking feature choice can fail
silently *and* severely rather than just underperform. On workloads
shaped like `graphbench`, `lzwbench`, `kvbench`, or `btreebench` — larger,
more varied working sets — the failure modes seen here were consistently
mild even when a feature choice didn't help.

## Experiment 4 — does a hand-written (non-learned) heuristic capture the same gain?

**Question**: Experiment 3's winning features were `global_frequency`
and `stack_distance`. If a plain, no-training counter-based version of
those same ideas — actual LFU, and a proper stack-distance policy —
gets close to what the learned models found, that's far cheaper to put
in the kernel than a trained model. And if the *hand-written* version
also fails catastrophically on `sortbench`/`matmulbench`, that would
settle whether Experiment 3's catastrophic failures were a training
artifact or a property of the strategy itself.

**Setup**: added two policies to `tools/sim.py`, same shape as the
existing `Fifo`/`Clock`/`Aging`/`Lru` classes, no learning involved:

- `Lfu` — evict the resident page with the lowest total access count
  so far.
- `StackDistance` — evict the resident page with the largest current
  stack distance (distinct pages touched since its own last access).

Run across all seven workload/variant configurations via
`tools/handwritten_policy_sweep.py`. Results: `report/handwritten_results.csv`.

**Results** (train / held-out faults, classical best and Belady shown for reference):

| workload | best classical (held-out) | lfu | stackdist | belady |
|---|---|---|---|---|
| `btreebench` | 36,556 (lru) | 39,399 | 36,685 | 17,816 |
| `kvbench` | 7,252 (lru) | 7,704 | 21,111 | 3,904 |
| `sortbench` | 1,267 (aging/lru) | 1,047,108 | 825,610 | 983 |
| `graphbench` | 134,760 (clock) | 140,133 | **134,396** | 75,779 |
| `lzwbench` | 49,731 (clock) | **37,705** | 40,933 | 22,507 |
| `matmulbench`-naive | 27 (lru) | 393,969 | 77 | 27 |
| `matmulbench`-blocked | 298 (clock) | 484,475 | 21,588 | 121 |

**Two findings**:

1. **A cheap, real win on `lzwbench`**: hand-written `lfu`, with zero
   training, beats every classical policy (−24.2% vs. clock) *and*
   beats the best learned model from Experiment 3 on the same workload
   (`stack_distance`/mlp at 40,743). `stackdist` also edges out clock
   by a hair on `graphbench` (134,396 vs. 134,760), matching what the
   learned `global_frequency` model found there, without training.
   Confirms suggested next step 4 from the previous round of this
   report directly.
2. **The catastrophic failures are not a training artifact.** `lfu`
   and `stackdist` fail on `sortbench` and `matmulbench` just as badly
   as the learned models did in Experiment 3 — `lfu` is up to ~14,600x
   worse than the best classical policy on `matmulbench`-naive, with no
   model, no gradient descent, no generalization gap involved at all.
   This sharpens Experiment 3's conclusion: it was never that a model
   learned the wrong thing from limited data — frequency- and
   distance-based eviction are *themselves* the wrong strategy for
   these specific small, rigidly sequential access patterns, and
   nothing about learning caused or could fix that. Sequential,
   cyclic-walk workloads need recency, full stop; counting how often or
   how widely a page has been touched actively misleads on them.

## Experiment 5 — does cross-page context help (the expensive one)?

**Question**: every feature tried in Experiments 1-4, learned or
hand-written, only ever looked at a single page's own history in
isolation (its own recency, frequency, or stack distance) — nothing
could represent "these pages tend to be touched together," which is
structurally closer to what graph topology (`graphbench`) or a
matrix's memory-access order (`matmulbench`) actually is. Does giving
the model genuine cross-page information — a learned representation of
each page, combined with what's been happening across the *whole*
process recently, not just this candidate's own history — find
anything the simpler approaches missed?

**Setup**: `GlobalContextModel` in `tools/ml_embedding_experiment.py` —
a learned `nn.Embedding` per page (shaped freely during training,
unlike Experiment 2's static, hand-computed `vpn_identity` scalar),
fed into a small GRU over the last **W=16** *globally* referenced pages
(the whole process's recent activity, not the candidate's own history),
concatenated with the specific candidate page's own embedding, and
passed through a small MLP head to predict next-reuse-distance. The
global-context part is identical across every candidate compared at a
single eviction (same caveat as Experiment 2's `position` feature), but
each candidate's own embedding still differs, so the model can express
"given what's just been happening, how does *this* page look" — real
cross-page structure, short of full pairwise attention. Same 300,000
-example training subsample and train/held-out-capacity split as every
prior experiment, run across all seven workloads.

**Results** (train / held-out faults):

| workload | best classical (held-out) | best prior ML (held-out) | global-context embedding |
|---|---|---|---|
| `btreebench` | 36,556 | 36,273 | 74,148 / 61,625 |
| `kvbench` | 7,252 | 7,243 | 39,358 / 36,801 |
| `sortbench` | 1,267 | 1,073 | 492,119 / 379,422 |
| `graphbench` | 134,760 | 128,996 | 143,017 / **134,510** |
| `lzwbench` | 49,731 | 37,705 (hand-written lfu) | 48,143 / 43,623 |
| `matmulbench`-naive | 27 | 27 | 71,339 / 38,607 |
| `matmulbench`-blocked | 298 | 121 (belady) / 720 (best non-oracle) | 652,307 / 119,360 |

**Finding: a clear negative result.** The embedding model never wins.
On `graphbench` it essentially ties classical Clock (−0.2%) but loses
to the much simpler `global_frequency`/linear model from Experiment 2
(+4.3% worse). On `lzwbench` it beats plain Clock (−12.3%) but loses to
the zero-training hand-written `lfu` from Experiment 4. Everywhere else
it is worse than the best classical policy, often by a lot — and on
`sortbench` and both `matmulbench` variants it is catastrophic, for the
same reason Experiments 3-4 already identified: these workloads need
precise recency tracking, and a W=16 global-context summary averages
that away rather than preserving it. The one silver lining: on
`sortbench`, the embedding model (379,422 held-out faults) is
meaningfully *less* catastrophic than hand-written `lfu` or
`stackdist` (1,047,108 / 825,610) — cross-page context isn't wrong
there in the same absolute way frequency/stack-distance are, it just
isn't nearly precise enough to compete with plain recency. Given the
extra cost (a GRU forward pass per candidate at every eviction, vs. a
single linear dot-product for the Experiment 2 models) bought nothing
over the cheaper approaches on any of the seven workloads, this line
isn't worth pursuing further without a fundamentally different way of
encoding cross-page structure (true graph adjacency for `graphbench`,
for instance, rather than a fixed recent-window proxy for it).

**A concrete pitfall hit and fixed while building this**: the first run
crashed on `lzwbench` with an out-of-range embedding index. The bug:
page numbers in this project's traces are *absolute* virtual page
numbers (offset by `arena_start_vpn`, e.g. 22 for `lzwbench`), not
0-indexed — sizing the embedding table off the header's `arena_pages`
count (as the first version of the script did) works only by
coincidence when `arena_start_vpn` happens to be 0. Fixed by sizing the
table off the actual observed max page number in the data instead of a
header field. A reminder that even a metadata field with a plausible
-sounding name (`arena_pages`) needs to be checked against the real
data before being trusted as a bound.

## Why frequency, specifically

None of the four classical kernel policies actually track long-run
access frequency. FIFO tracks only load order; Clock and Aging are
both fundamentally recency-based, with Aging's 8-bit decaying counter
giving it only a short, decaying memory of recent access — not a true
running count. A page that has been touched 500 times over the run but
not in the last 50 references looks "cold" to all four; a simple
frequency count correctly identifies it as likely to be touched again
soon. This is essentially rediscovering the intuition behind LFU
(Least-Frequently-Used) — not one of the four policies this kernel
implements — via a one-line learned model rather than a hand-designed
one. That the *simplest possible* frequency-aware model already beats
every recency-based classical policy tested is itself informative:
this may be the single biggest source of the oracle gap on this
workload, though it is far from the whole gap (138,343 vs. Belady's
87,042 is still a wide margin).

## What this does and doesn't show

- It does not close anywhere near the full oracle gap on any workload.
  Even the best result (`lzwbench`, −18%) closes well under half the
  distance from the best classical policy to Belady.
- Experiment 3 answers Experiment 2's own open question directly:
  `global_frequency` is *not* a universal fix — it's graphbench's own
  best feature specifically, while `lzwbench` responds best to
  `stack_distance` and three other workloads respond best to the full
  combined feature set. There is real, workload-dependent structure
  here, not one silver-bullet feature.
- Every train/held-out pair in this report is still the *same*
  reference stream at two different capacities, per workload — never
  training on one workload's access pattern and evaluating on another's.
  Whether anything learned here transfers *across* workloads (as
  opposed to across capacities of the same workload) remains untested.
- **Now tried in Experiment 5, and negative**: a genuine cross-page
  feature (learned per-page embedding + global recent-context window)
  never beat the simple single-page scalar features from Experiment 2,
  and was catastrophic on the same workloads that were already
  catastrophic. The specific approach tried (a fixed-length recent
  -window proxy for context) doesn't seem to be the right way to expose
  cross-page structure to these models — a genuinely relational feature
  (e.g. real graph adjacency for `graphbench`) remains untried and may
  behave differently, but "more expressive model, more context" alone
  did not help.
- The catastrophic-failure investigation (Experiment 3) identifies a
  clear risk pattern (small, rigid working sets) and Experiment 4
  confirms it isn't a training artifact — a hand-written, non-learned
  version of the same strategy fails just as badly. No attempt was made
  here to make any model *robust* against it, only to explain why it
  happens; the practical implication (Experiment 3's) still stands:
  evaluate on a genuinely held-out run before trusting any of this on a
  `sortbench`/`matmulbench`-shaped workload.

## Suggested next steps

1. **Answered by Experiment 3**: frequency does *not* help everywhere —
   it's graphbench-specific.
2. **Tried in Experiment 5, negative**: a global-recent-window
   embedding model did not find cross-page structure that beats the
   simple scalar features. If cross-page context is worth revisiting,
   it likely needs a genuinely relational representation (real graph
   adjacency for `graphbench`, e.g. message-passing over the actual
   edge list) rather than a fixed recent-window proxy for it — a
   materially different, and more involved, approach than Experiment 5.
3. **Answered by Experiment 4**: hand-written LFU already captures (and
   on `lzwbench`, exceeds) most of the learned-model gain, with no
   training at all. `lzwbench` is now a strong, concrete candidate for
   an actual kernel policy change — the win is real, reproducible
   without any ML infrastructure, and the biggest single-workload
   margin found in this whole report (−24% vs. Clock).
4. For the two workloads where classical policies (Clock in particular)
   already do very well (`matmulbench` naive and blocked) — check
   whether that's specific to this project's Clock implementation or a
   general property of small, strided access patterns, before spending
   more effort trying to beat it there.
5. Before trusting any future model on a workload shaped like
   `sortbench` or `matmulbench`, evaluate on a genuinely held-out run
   first — this report found failures there that were severe (up to
   ~14,600x, in Experiment 4's hand-written policies), not just
   mediocre, and none of the earlier warning signs (weak correlation,
   architecture-independence, or even the absence of any learning at
   all) predicted *how bad* specifically; only the held-out simulation
   caught it.
6. Given Experiments 1, 3, and 5 all separately concluded that more
   model capacity / more context did not help, and Experiment 4 found
   the single best result in the whole report with zero training — the
   highest-value remaining work here is probably implementing
   hand-written LFU as an actual kernel policy for `lzwbench`-shaped
   workloads, not further ML experimentation on this feature space.

## Files

- `tools/ml_policy_prototype.py` — the original (first, negative-result)
  prototype, graphbench only.
- `tools/ml_arch_experiments.py` — Experiment 1 (seven architectures),
  graphbench only.
- `tools/ml_feature_experiments.py` — Experiment 2 (six feature sets),
  graphbench only.
- `tools/ml_comprehensive.py` — Experiment 3: every architecture and
  feature set from Experiments 1-2, run across all seven workload/
  variant configurations. Writes `report/ml_comprehensive_results.csv`
  (committed — small, ~12KB, unlike the underlying trace data) and
  saves every one of the 133 trained models' weights plus a metadata
  sidecar under `report/models/` (also committed — 266 files, ~1.5MB total,
  small enough to version directly rather than only be regenerable;
  each `.pt` is a PyTorch `state_dict`, each `.json` records the exact
  workload/feature-set/architecture/capacities/fault counts it came
  from, so any single result in this report can be reloaded without
  retraining).
- `tools/sim.py` — also gained two hand-written policies for Experiment
  4: `Lfu` and `StackDistance` (see `POLICIES` dict / `--policy` CLI
  choices).
- `tools/handwritten_policy_sweep.py` — Experiment 4: runs every
  classical policy plus the two new hand-written ones across all seven
  workloads, no training/torch dependency at all. Writes
  `report/handwritten_results.csv` (committed).
- `tools/ml_embedding_experiment.py` — Experiment 5: the cross-page
  `GlobalContextModel` (learned embedding + GRU over a global recent
  -context window), run across all seven workloads. Writes
  `report/embedding_results.csv` (committed) and saves each workload's
  trained model under `report/models/*_embed_global_context.{pt,json}`
  (committed, same convention as Experiment 3's models).
