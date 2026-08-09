# SOP-PRC-02 — Pick Accuracy, Packing Standards, Dangerous Goods & Cold Chain

**Site:** All warehouse operations | **Applies to:** Operatives assigned to picking, packing, dangerous goods, or cold chain tasks
**Regulatory basis:** ADR (European Agreement concerning the International Carriage of Dangerous Goods by Road), applicable to §3; Reg. (EC) 852/2004 (food hygiene / temperature control), applicable to §4
**Version:** 2.3 | **Effective:** 2026-03-01 | **Review cycle:** Annual

## 1. Pick accuracy: check digits, SKU-vs-lookalike discrimination

1. Every pick location has a check digit (a short numeric code posted on the location label) that must be confirmed via RF scanner or spoken back for pick-to-voice (see SOP-EQP-02 §3) before the pick is accepted — this confirms you are at the correct physical location, not just a location that looks correct.
2. Many SKUs have visually similar "lookalike" counterparts (same packaging family, different size/variant/lot). Always confirm the full SKU code on the pick screen against the physical label, not just the product image or brand.
3. If a pick location is empty or the quantity available is less than the task requires, do not substitute a nearby lookalike SKU — flag a short pick exception (see SOP-SYS-01 §4) and move to the next task.

## 2. Packing standards

1. Void fill: all empty space in a carton must be filled to prevent movement in transit — under-filling is a packing standards failure even if the item arrives undamaged.
2. Fragile items require a visible fragile marking on the outer carton and additional cushioning beyond standard void fill.
3. Weight limits per carton are posted at each pack station by carton size — do not exceed the posted limit even if the carton has physical room remaining; this is a manual handling limit for the outbound carrier, not a volume limit.

## 3. Dangerous goods recognition

1. Dangerous goods (DG) items are identified by a DG flag on the SKU master data and a corresponding hazard label requirement. DG items must only be handled by operatives who have completed DG recognition training and must be segregated in the designated DG area (PPE per SOP-SAF-01 §2).
2. **Limited quantity (LQ)** and **excepted quantity (EQ)** are two distinct ADR exemption categories and must not be treated as interchangeable:
   - *Limited quantity*: small inner packagings within specified per-package and per-outer-packaging weight/volume limits, marked with the LQ diamond mark. Still requires DG segregation and handling awareness, but qualifies for reduced transport documentation.
   - *Excepted quantity*: an even smaller quantity threshold with its own distinct EQ diamond mark, qualifying for further-reduced regulatory requirements than LQ. An EQ-marked item is not automatically also LQ-compliant, and an LQ-marked item does not qualify for EQ treatment.
   - The most common error operatives make is assuming a package below the LQ threshold is automatically EQ, or applying LQ segregation rules to an EQ-marked item on the assumption the stricter rule always applies. Always check the actual diamond mark and the SKU master data DG classification — never infer the category from package size alone.
3. Any DG item without a corresponding SKU master data DG flag but bearing a visible hazard diamond must be treated as DG and reported to the shift supervisor for master data correction — never override the physical label based on system data.

## 4. Cold chain: temperature windows, exposure limits, breach escalation

1. Cold chain SKUs have a defined temperature window in the SKU master data (e.g. 2–8°C for chilled, ≤ -18°C for frozen). Chiller/freezer zone temperature is logged automatically but operatives must visually confirm the zone display is within window at the start of each shift.
2. Exposure limit: cold chain product may be outside its temperature window (e.g. during picking/staging) for a maximum cumulative time per SKU category, posted at the chiller entrance. Exceeding this exposure limit requires the product to be flagged for quality hold, not returned to stock as if unaffected.
3. Breach escalation: any zone temperature excursion beyond the logged window, or any product exceeding its exposure limit, must be reported to the shift supervisor immediately, not at end of shift — cold chain breaches under Reg. (EC) 852/2004 require timely disposition, and delayed reporting is itself a compliance failure independent of the breach.
