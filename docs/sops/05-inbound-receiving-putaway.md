# SOP-PRC-01 — Inbound Receiving & Putaway

**Site:** All warehouse operations | **Applies to:** Operatives assigned to receiving and putaway tasks
**Regulatory basis:** Internal process standard (no external regulatory mandate)
**Version:** 1.7 | **Effective:** 2025-10-01 | **Review cycle:** Semi-annual

## 1. Inbound receiving: ASN match, quantity and damage verification

1. Every inbound delivery must have an Advance Shipping Notice (ASN) in the WMS before goods are accepted at the dock. Do not accept a delivery with no matching ASN — hold it in the dock quarantine area and notify the shift supervisor.
2. Match the delivery against the ASN line by line: SKU, quantity, and lot/batch number where applicable.
3. Inspect packaging for visible damage before opening — crushed corners, wet packaging, or a damaged pallet must be logged as a damage exception even if the contents later prove undamaged.
4. Count quantity by full case/pallet count first, then by unit count for any part-case. A quantity mismatch (over or under) is logged as a variance exception in the WMS, not silently corrected on the ASN.
5. Only once ASN match, quantity, and damage checks pass does a delivery move from "receiving" to "putaway-ready" status in the WMS.

## 2. Putaway rules: velocity zones, weight/height, mixed-SKU prohibition

1. Every SKU has an assigned velocity zone (fast/medium/slow-moving) in the WMS master data — the putaway task will direct you to the correct zone. Do not putaway to a zone other than the one the task specifies, even if a closer empty location is visible.
2. Weight/height rule: heavier and bulkier items are putaway to lower rack levels; lighter items to upper levels. This is enforced by the WMS task but operatives must visually confirm the destination location can physically accommodate the load before placing it — do not force a placement into an undersized location.
3. Mixed-SKU prohibition: a single pallet location may never contain more than one SKU, even temporarily. If a partial pallet needs to be combined with existing stock of the same SKU, the WMS task will direct a consolidation; do not combine different SKUs at the same location under any circumstance — this is the leading cause of pick errors traced back to putaway.
4. Confirm putaway completion by scanning the location barcode, then the item barcode (see SOP-EQP-02 §3 for scanner sequence) — this closes the putaway task and makes the stock available for picking.

Putaway of a SKU into a new zone is only teachable to an operative who is already competent in the ASN-match and quantity-verification steps in §1 — an operative who has not internalized the receiving checks tends to putaway unverified or exception-flagged stock as if it were clean, propagating the error into pick locations.
