# SOP test corpus — `warehouse_operative`

Eight mock SOPs for the `warehouse_operative` role family. This corpus serves **two** purposes in the slice, and both depend on it being the same set of files:

1. **RAG grounding corpus** (PRD §6.1) — chunked and embedded; remediation content must cite one of these documents or the agent abstains (PRD §7).
2. **KG-authoring input** (PRD §8) — the seed 24-KC graph used by the demo conversations (PRD §9, beats 1–3) is the frozen, approved output of a run of the §8 studio pipeline over exactly these eight files. Demo beat 4 (§8.5) re-runs extraction live on a subset of them.

Regulatory citations, procedure structure, cross-references between documents, and the explicit misconception callouts (e.g. limited quantity vs. excepted quantity in doc 06) are written deliberately so that an LLM extraction pass over this corpus plausibly proposes the 24 KCs below with the graph attributes VISION.md §6.2 specifies. The mapping is not asserted as a spec the extraction pipeline is graded against turn-by-turn — it is the expected/plausible output used to sanity-check the pipeline and to seed the eval fixtures for §8's tests.

## Expected KC coverage

| # | File | Source SOP(s) | Expected KCs |
| --- | --- | --- | --- |
| 01 | [`01-ppe-manual-handling.md`](01-ppe-manual-handling.md) | SOP-SAF-01 | `SAF.001` PPE selection and correct use per zone · `SAF.002` Manual handling principles · `SAF.003` Safe lift execution *(prereq: SAF.002)* · `SAF.004` Team lift coordination *(prereq: SAF.003)* |
| 02 | [`02-mhe-pedestrian-incident-response.md`](02-mhe-pedestrian-incident-response.md) | SOP-SAF-02 | `SAF.005` Pedestrian–MHE segregation and right of way · `SAF.006` Hazard and near-miss reporting · `SAF.007` Emergency evacuation, muster point, roll call · `SAF.008` Spill response (non-hazardous vs. hazardous) |
| 03 | [`03-ppt-operation.md`](03-ppt-operation.md) | SOP-EQP-01 | `EQP.001` Pre-use inspection checklist — PPT · `EQP.002` PPT operation: load stability, gradients, cornering *(prereq: EQP.001, SAF.005)* |
| 04 | [`04-reach-truck-battery-scanner.md`](04-reach-truck-battery-scanner.md) | SOP-EQP-02 | `EQP.003` Reach truck mast/height limits and load-chart reading *(prereq: EQP.002)* · `EQP.004` Battery change / charging safety · `EQP.005` RF scanner and pick-to-voice operation, error recovery |
| 05 | [`05-inbound-receiving-putaway.md`](05-inbound-receiving-putaway.md) | SOP-PRC-01 | `PRC.001` Inbound receiving: ASN match, quantity and damage verification · `PRC.002` Putaway rules: velocity zones, weight/height, mixed-SKU prohibition *(prereq: PRC.001)* |
| 06 | [`06-picking-packing-dg-coldchain.md`](06-picking-packing-dg-coldchain.md) | SOP-PRC-02 | `PRC.003` Pick accuracy: check digits, SKU-vs-lookalike discrimination *(prereq: EQP.005)* · `PRC.004` Packing standards · `PRC.005` Dangerous goods recognition *(prereq: SAF.001; `regulation`: ADR; `known_misconceptions`: limited-quantity/excepted-quantity confusion, §3.2)* · `PRC.006` Cold chain: temperature windows, exposure limits, breach escalation *(`regulation`: Reg. (EC) 852/2004)* |
| 07 | [`07-cyclecount-returns-wms.md`](07-cyclecount-returns-wms.md) | SOP-PRC-03 / SOP-SYS-01 | `PRC.007` Cycle counting and variance reporting · `PRC.008` Returns triage and disposition coding *(prereq: PRC.001)* · `SYS.001` Core transactions: goods receipt, location transfer, stock adjustment · `SYS.002` Exception handling: short pick, damage code, blocked stock *(prereq: SYS.001, PRC.008)* |
| 08 | [`08-handover-escalation.md`](08-handover-escalation.md) | SOP-BEH-01 | `BEH.001` Shift handover: what must be communicated and to whom · `BEH.002` Escalation thresholds: what to stop for vs. report after |

**Domain tally:** Safety & regulatory 8 (docs 01–02) · Equipment 5 (docs 03–04) · Process 8 (docs 05–07) · Systems 2 (doc 07) · Behavioural 2 (doc 08) = **24 KCs**, 5 domains — matches PRD §5 and VISION.md §6.2.

**Cross-document `prerequisite_of` edges** (the interesting ones — an extraction pass confined to a single document can't find these, which is part of why this corpus, read as a whole, is a reasonable test of graph-level rather than document-level extraction):

- `EQP.002` depends on `SAF.005` (doc 03 references doc 02's right-of-way rule).
- `PRC.003` depends on `EQP.005` (doc 06 references doc 04's scanner check-digit sequence).
- `PRC.005` depends on `SAF.001` (doc 06 references doc 01's PPE-by-zone table for the DG segregation area).
- `SYS.002` depends on `SYS.001` and `PRC.008` (doc 07 states this dependency explicitly in its closing paragraph).

## Not in this corpus (by design)

No SOP version history or superseded-document example is included — `superseded_by_kc_id` (PRD §5) is exercised by the mastery-engine unit tests via a synthetic fixture, not by this corpus, since simulating a real SOP version bump would require shipping two versions of the same document and this slice only needs the invalidation *logic* tested, not a realistic authoring trigger for it.
