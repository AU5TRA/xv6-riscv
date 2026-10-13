# Related-work search (2026-10-12)

**Written for:** whoever writes the introduction's Move 3 and Section 6. This is evidence,
not paper text. Write the paragraphs in your own words; MLSys forbids AI-only text.

**How it was done:** two searches.
* **Scope:** OSDI, SOSP, ATC, EuroSys, ASPLOS, FAST, NSDI, HotOS, HotStorage, ISCA/MICRO/HPCA,
  ICML/SODA and arXiv, 2018–2026.
* **Sources:** every entry below was found on a publisher, USENIX, PMLR or arXiv page. DBLP
  blocked automated access.
* **Spot-checked by hand:** LearnedCache (arXiv page) and PageFlex (USENIX page).
* **Before submission:** re-check each one you cite on its publisher page.

## The answer to the `[verify]` note

1. **No archival OS-venue paper puts a learned page-replacement policy for process (VM)
   memory into a real kernel.**
2. **The closest work is LearnedCache** (Zejia Qi, arXiv 2605.26168, May 2026). It learns
   eviction **inside Linux**, as a per-workload perceptron in eBPF through cache_ext. It
   predicts reuse within a time horizon, for the **file page cache**, and **sees every
   page-cache access**. The MLSys 2026 Young Professional Symposium poster with the same
   title is non-archival. Cite the arXiv version, not the poster.
3. **Consequence: do not write "first learned eviction policy in a kernel".** That is false.
   * A narrower claim may hold: first for process memory, using only faults and accessed
     bits, measured in a kernel against kernel forms of ARC/LHD/S3-FIFO.
   * The safest course is no "first" claim at all. State the differences instead.

## The papers that matter most, by where they go in the paper

### Move 3 (intro) and §6: learned eviction outside the kernel

All of these see every request or access, and run in user space, a simulator or hardware.

| Work | Venue | Difference from ours (one line) |
|---|---|---|
| LFO (Berger) | HotNets 2018 | Same idea (imitate OPT with a cheap model), but for a CDN, with the full request stream |
| HALP (Song et al.) | NSDI 2023 | Heuristic picks candidates, an MLP re-ranks them, trained online; floating point, per-request features (YouTube CDN) |
| 3L-Cache (Zhou et al.) | FAST 2025 | Learned eviction with low overhead, but built on per-request statistics |
| LAH / S4-FIFO (Xia et al.) | OSDI 2026 | Learns to *tune* S3-FIFO's knobs; eviction stays a heuristic; worst case 0.8% below FIFO |
| GL-Cache (Yang et al.) | FAST 2023 | Learns over groups of objects, not individual pages |
| Mockingjay (Shah, Jain, Lin) | HPCA 2022 | Imitates Belady in hardware using program counters a kernel does not have |
| RLR (Sethumurugan et al.) | HPCA 2021 | RL used offline to *design* a cheap hardware policy; we deploy the learned model |
| Zhou & Maas | MLSys 2021 | MLSys precedent: learned cache admission from application traces the kernel lacks |

### §6, a new category: programmable and learned memory policies *inside* kernels

| Work | Venue | What it is | Difference |
|---|---|---|---|
| **LearnedCache** (Qi) | arXiv 2026 | Perceptron eviction in Linux via eBPF | Page cache, every access visible, reuse-horizon label; we do VM pages from faults and A-bits, imitating Belady |
| **cache_ext** (Zussman et al.) | SOSP 2025 | eBPF framework for page-cache eviction policies (MRU, LFU, S3-FIFO, LHD, …) | No learned policy (listed as future work); full access visibility |
| **PageFlex** (Yelam et al.) | ATC 2025 | Linux paging policies (reclaim, prefetch) delegated to eBPF + user space | Reportedly uses faults and periodic accessed-bit scans, **our observation model**, but no learned policy. **Check the PDF.** A natural Linux route for our policy (§7) |
| xTier (Ramaswamy, Chen) | arXiv 2026 | int8 MLP in eBPF ranks pages for CXL tiering | Tiering promotion from PEBS samples, not eviction |
| LAKE (Fingler et al.) | ASPLOS 2023 | GPU offload for ML in the kernel | Batched inference offload; we run small integer inference inline |
| KML (Akgun et al.) | HotStorage 2021 / TOS 2023 | In-kernel NN tunes readahead each second | Tunes a parameter, uses kernel floating point; we pick each victim, integers only |
| RMT (Qiu et al.) | HotOS 2021 | In-kernel learned swap prefetch | Prefetching, not eviction |
| Far memory (Lagar-Cavilla et al.) | ASPLOS 2019 | Google's A-bit page aging (kstaled) + zswap; ML tunes thresholds | ML tunes control knobs, not per-page choices; useful as precedent for A-bit aging at scale |
| Guardrails (Saxena et al.) | HotOS 2025 | Safety monitors for learned OS policies, in eBPF or kernel modules | Monitors only; relevant to our fallback guard (§3.5) |

### §3.5 guard, and §6 theory: paging with ML predictions

| Work | Venue | Why it matters to us |
|---|---|---|
| Lykouris & Vassilvitskii | ICML 2018 / JACM 2021 | Blindly following predictions is bad; a robust wrapper stays within O(log k) |
| Wei | APPROX 2020 | Combining "follow the predictor" with LRU as a black box is near-optimal: the theory behind a learned policy with a Clock fallback |
| Chłędowski et al. | ICML 2021 | Experimental: switching to a robust policy when the learned one falls behind is "cheap worst-case insurance", the same idea as our guard |
| Rohatgi | SODA 2020 | Tighter bounds for the same setting |

All of these assume a prediction *per request*. The kernel sees none, which is itself a
difference worth one clause.

## Medium and low relevance (in the search output; add if space allows)

* **Admission and other cache work:** Raven (CoNEXT 2022), LHR (CoNEXT 2021), Baleen (FAST 2024,
  admission), MAT (arXiv 2023), ALPS (OPODIS 2023).
* **Buffer pools and simulation-only:** sampling-based buffer management in PostgreSQL (PVLDB
  2025, not ML), MUSTACHE (arXiv, simulation).
* **Kernel-side, not eviction:** FetchBPF (ATC 2024, eBPF prefetch), P2Cache (HotStorage 2023),
  Kleio (HPDC 2019, simulated tiering), FarSight (arXiv 2025, neural prefetch in the swap path).
* **Reinforcement learning:** CHROME (HPCA 2024), LPR (Middleware 2022), deep-RL replacement
  (ICAPS 2022).
* **Surveys:** Wu & Xie (CSUR 2022), Jain & Lin (Cache Replacement Policies, 2019).

## Could not verify (do not cite)

* "Stormbird" (RL last-level-cache replacement): only a search snippet.
* A paper on learned MGLRU tuning: none found.
* The LearnedCache poster abstract: not public.
* SOL's author spelling ("Dan" vs "Daniel" Crankshaw): check the ACM DL.

## What changed in the repo

* The high-relevance entries are added to `references.bib` under "Related-work search
  2026-10-12". Uncited entries do not appear in the PDF.
* The `[verify]` notes in Move 3 and §6 now point here and name the closest work.
