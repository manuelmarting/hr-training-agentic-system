# SOP-EQP-02 — Reach Truck Operation, Battery Change & RF Scanner Use

**Site:** All warehouse operations | **Applies to:** Operatives certified for reach truck use (PPT certification is a prerequisite); all operatives for §3 (RF scanner)
**Regulatory basis:** RD 1215/1997 (minimum safety requirements for use of work equipment); practical competence additionally assessed by a certified human trainer
**Version:** 2.0 | **Effective:** 2025-09-01 | **Review cycle:** Annual

## 1. Reach truck: mast/height limits and load-chart reading

Reach trucks extend the pre-use inspection and operating principles of the powered pallet truck (SOP-EQP-01) with mast and height-specific requirements. Reach truck certification requires current PPT certification as a precondition — the pre-use inspection habits and stability principles from SOP-EQP-01 are assumed knowledge.

1. Before lifting to height, read the load chart mounted on the mast: it specifies maximum load weight at each height band. Capacity decreases as lift height increases — a load acceptable at 3m may exceed the chart's rated capacity at 8m.
2. Never rely on the load's shipping label weight alone for chart lookup — confirm against the WMS putaway task, which reflects verified weight from goods receipt.
3. Mast must be fully vertical (not tilted forward) before raising to height. Tilt is only used for load pickup/placement at the final position, never during travel.
4. Travel with the load lowered to the minimum safe travel height (forks approximately 15–20cm off the floor) — never travel with a load elevated, even at slow speed.
5. When operating above 4m, a second operative acts as ground guide/spotter for any putaway or picking location without direct sightline from the cab.

## 2. Battery change and charging safety

1. Battery changes and charging occur only in the designated battery bay (PPE per SOP-SAF-01 §2: face shield, acid-resistant apron, safety boots).
2. Before disconnecting: switch off the truck, verify the area is clear of ignition sources (batteries vent hydrogen gas while charging).
3. Use the overhead hoist to lift the battery — never manually lift a traction battery; they exceed safe manual handling limits under SOP-SAF-01 §3 by a wide margin.
4. Connect the charger to the battery before switching the charger on, and switch the charger off before disconnecting — reversing this order risks arcing.
5. Report any battery casing damage, swelling, or electrolyte leakage immediately; do not charge a damaged battery.

## 3. RF scanner and pick-to-voice operation

1. At shift start, log in to the RF scanner or pick-to-voice headset with your operator ID — every transaction is tied to this login for traceability.
2. Scan the location barcode before scanning the item barcode for every pick or putaway — scanning the item first without confirming location is the single most common cause of location-mismatch inventory errors.
3. If the scanner reports a quantity or location mismatch, do not override without investigating — a forced override without checking is how phantom stock discrepancies enter the WMS (see SOP-SYS-01 §4 for exception handling).
4. Error recovery: if the device loses connection mid-task, do not restart the task from scratch — the WMS holds the task state and will resume from the last confirmed scan on reconnect.
5. Pick-to-voice: confirm each instruction verbally using the exact confirmation phrase given (typically a check-digit readback), not a generic "yes" — the system requires the check digit to validate against SOP-PRC-02 §1 pick accuracy controls.
