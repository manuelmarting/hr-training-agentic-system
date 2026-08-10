"""Shared by every component package that keeps its prompt(s) as sibling .md files."""

from pathlib import Path


def load_prompt(caller_file: str, name: str) -> str:
    return (Path(caller_file).parent / f"{name}.md").read_text().rstrip("\n")
