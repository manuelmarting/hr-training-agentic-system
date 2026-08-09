"""Runtime knowledge graph (workflow 1's contract, seeded by the studio).

`loader.py` owns the on-disk YAML shape: both the runtime agent's KG traversal and the
studio's `materialize.py` go through it, so a materialized graph is the same shape the
runtime loads — by construction, not by coincidence.
"""
