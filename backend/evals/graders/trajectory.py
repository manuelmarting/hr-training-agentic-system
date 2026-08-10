"""Rule-based grading for trajectory evals: does an observed tool/event sequence
match what's expected? No LLM judge here — trajectory checks are structural, not a
matter of quality/taste."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GraderResult:
    passed: bool
    detail: str


def check_subsequence(actual: list[str], expected: list[str]) -> GraderResult:
    """`expected` must appear, in order, as a (non-contiguous) subsequence of `actual`."""
    if not expected:
        return GraderResult(True, "nothing required")
    it = iter(actual)
    for name in expected:
        if name not in it:
            return GraderResult(
                False, f"expected {expected!r} as a subsequence of {actual!r} — missing {name!r}"
            )
    return GraderResult(True, f"{expected!r} found in order within {actual!r}")


def check_excludes(actual: list[str], forbidden: list[str]) -> GraderResult:
    present = [name for name in forbidden if name in actual]
    if present:
        return GraderResult(False, f"forbidden names present: {present!r} in {actual!r}")
    return GraderResult(True, f"none of {forbidden!r} present in {actual!r}")


def check_exact(actual: list[str], expected: list[str]) -> GraderResult:
    if actual != expected:
        return GraderResult(False, f"expected exactly {expected!r}, got {actual!r}")
    return GraderResult(True, f"matches {expected!r}")
