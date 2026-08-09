# SOP-PRC-03 / SOP-SYS-01 — Cycle Counting, Returns Triage & WMS Core Transactions

**Site:** All warehouse operations | **Applies to:** Operatives assigned to cycle counting, returns processing, or general WMS transaction use
**Regulatory basis:** Internal process standard (no external regulatory mandate)
**Version:** 1.5 | **Effective:** 2025-12-01 | **Review cycle:** Semi-annual

## 1. Cycle counting and variance reporting

1. Cycle count tasks are assigned by the WMS on a rolling schedule weighted toward high-velocity locations. Count the physical location exactly as instructed — full unit count, not an estimate from carton count.
2. Enter the counted quantity into the WMS regardless of whether it matches the system quantity — never adjust your physical count to match what the system expects.
3. A variance (counted quantity differs from system quantity) is logged automatically once entered. Variances above the site's tolerance threshold trigger a recount by a second operative before the system quantity is adjusted — a single operative's count alone never overwrites system stock above threshold.
4. Recurring variances at the same location across multiple cycle counts should be flagged to the shift supervisor as a possible putaway or pick-accuracy issue (see SOP-PRC-01 §2, SOP-PRC-02 §1) rather than corrected in isolation each time.

## 2. Returns triage and disposition coding

Returns processing depends on the receiving discipline in SOP-PRC-01 §1 — a returned item is triaged with the same rigor as an inbound delivery, since the return's stated reason cannot be taken at face value without inspection.

1. Every return is inspected against its stated return reason (damaged, wrong item, quality complaint, unwanted) before disposition coding — the stated reason from the customer/site is a starting hypothesis, not a fact.
2. Disposition codes: **Restock** (undamaged, resaleable condition, correct item), **Quality hold** (condition uncertain, needs quality review before disposition), **Scrap** (visibly damaged or expired), **Return to vendor** (manufacturing defect within vendor claim window).
3. Restock disposition requires the item to pass the same quantity/damage checks as inbound receiving (SOP-PRC-01 §1.3–1.4) before being putaway — a returned item is never restocked without inspection regardless of stated reason.
4. Disposition coding is entered in the WMS against the original order reference where available, to preserve traceability back to the original transaction.

## 3. WMS core transactions: goods receipt, location transfer, stock adjustment

1. **Goods receipt**: posts inbound quantity against an ASN (see SOP-PRC-01 §1); requires ASN reference, SKU, quantity, and lot/batch where applicable. Cannot be posted without a matching ASN line.
2. **Location transfer**: moves stock from one location to another without changing total on-hand quantity; requires scanning source location, item, and destination location in that order (see SOP-EQP-02 §3 for scan sequence).
3. **Stock adjustment**: the only transaction type that changes total on-hand quantity without a corresponding physical movement (used for cycle count corrections, damage write-offs, scrap disposition). Requires a reason code — an adjustment with no reason code is rejected by the WMS by design, since an unexplained quantity change is not auditable.

## 4. Exception handling: short pick, damage code, blocked stock

1. **Short pick**: system quantity says stock is available but the physical location has less or none. Log a short-pick exception (do not substitute — see SOP-PRC-02 §1.3) and trigger an automatic cycle count task for that location.
2. **Damage code**: physical damage discovered outside of receiving or returns triage (e.g. racking collapse, forklift contact). Apply the damage code, which moves the affected quantity to quality hold pending disposition — never leave damaged stock in a pickable location.
3. **Blocked stock**: stock flagged unavailable for picking (quality hold, DG documentation pending, cold chain exposure hold per SOP-PRC-02 §4.2). Blocked stock is excluded from available-to-promise automatically; operatives must never manually override a block to fulfil a pick — escalate to the shift supervisor if a block appears to be in error.

Exception handling assumes working knowledge of core transactions in §3 and of the receiving/putaway/returns processes that generate these exceptions in the first place (SOP-PRC-01, SOP-PRC-03 §2) — an operative should not be assessed on exception handling before those foundations are in place.
