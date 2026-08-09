"""Dedupe near-identical KCs across documents and assign ids (plan §4, §10).

Pure and deterministic: given the same per-document proposals and the same seed-id map,
the output is byte-identical. Two guarantees matter downstream:

- **Dedupe** — a KC proposed by two documents (same normalized name) becomes one node, its
  misconceptions merged. Encounter order is document order, then within-document order.
- **Seed-id reuse** — when a proposed KC's name matches a committed seed KC, it reuses the
  seed id. This is what makes the §8.5 claim ("re-running re-derives the same ids") hold,
  and it reserves that number so freshly-assigned ids in the same domain never collide.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.kg.loader import load_kcs
from app.studio.extract_schemas import ExtractedKC
from app.studio.schemas import ProposedKC, Provenance

DOMAIN_PREFIX: dict[str, str] = {
    "safety": "SAF",
    "equipment": "EQP",
    "process": "PRC",
    "systems": "SYS",
    "behavioural": "BEH",
}


def normalize_name(name: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace — the dedupe key."""
    cleaned = re.sub(r"[^a-z0-9\s]", "", name.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def load_seed_ids(graph_path: str | Path) -> dict[str, str]:
    """normalized seed-KC name → seed id, for id reuse across re-runs."""
    return {normalize_name(kc.name): kc.id for kc in load_kcs(graph_path)}


@dataclass
class _Unique:
    kc: ExtractedKC
    doc_id: str
    misconceptions: list[str] = field(default_factory=list)


def reconcile(
    proposals: dict[str, list[ExtractedKC]],
    seed_ids: dict[str, str] | None = None,
) -> list[ProposedKC]:
    """Merge per-document proposals into a de-duplicated, id-assigned KC list."""
    seed_ids = seed_ids or {}

    # 1. Collapse to unique KCs in deterministic encounter order (doc order, then in-doc).
    order: list[str] = []
    by_norm: dict[str, _Unique] = {}
    for doc_id in sorted(proposals):
        for kc in proposals[doc_id]:
            norm = normalize_name(kc.name)
            if norm in by_norm:
                by_norm[norm].misconceptions = _dedupe(
                    by_norm[norm].misconceptions + kc.known_misconceptions
                )
                continue
            order.append(norm)
            by_norm[norm] = _Unique(
                kc=kc, doc_id=doc_id, misconceptions=list(kc.known_misconceptions)
            )

    # 2. Assign ids — reused seed ids first, so their numbers are reserved before fresh ones.
    reserved: dict[str, set[int]] = defaultdict(set)
    assigned: dict[str, str] = {}
    for norm in order:
        seed_id = seed_ids.get(norm)
        if seed_id:
            assigned[norm] = seed_id
            prefix, number = _parse_id(seed_id)
            if prefix:
                reserved[prefix].add(number)

    counters: dict[str, int] = defaultdict(lambda: 1)
    for norm in order:
        if norm in assigned:
            continue
        prefix = DOMAIN_PREFIX[by_norm[norm].kc.domain]
        number = counters[prefix]
        while number in reserved[prefix]:
            number += 1
        assigned[norm] = f"{prefix}.{number:03d}"
        reserved[prefix].add(number)
        counters[prefix] = number + 1

    # 3. Materialize ProposedKCs.
    result: list[ProposedKC] = []
    for norm in order:
        unique = by_norm[norm]
        kc = unique.kc
        result.append(
            ProposedKC(
                id=assigned[norm],
                name=kc.name,
                domain=kc.domain,
                description=kc.description,
                regulation=kc.regulation,
                known_misconceptions=unique.misconceptions,
                provenance=Provenance(doc_id=unique.doc_id, heading=kc.heading, excerpt=kc.excerpt),
                origin="extracted",
            )
        )
    return result


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _parse_id(kc_id: str) -> tuple[str | None, int]:
    match = re.fullmatch(r"([A-Z]+)\.(\d+)", kc_id)
    if not match:
        return None, 0
    return match.group(1), int(match.group(2))
