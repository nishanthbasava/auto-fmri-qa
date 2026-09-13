"""Analyses that turn a finished run into reportable numbers.

    autoqa audit pooling RUN_DIR   -- per-scan vs subject-pooled labels (the session-pooling bug)
    autoqa audit surface RUN_DIR   -- how much of the cohort still needs human eyes

Each is deterministic, reads only the run's state.json (+ the confounds files
it points at), and writes its table under RUN_DIR/analysis/.
"""
from __future__ import annotations

import os


def resolve_input_path(path: str, state_input: str | None, override: str | None) -> str:
    """Map a path recorded in state.json onto this machine.

    Runs record absolute input paths; when a run is analysed on a different
    machine (or the tree moved), `--input` re-roots them. Relative paths are
    tried as-is, then under the override.
    """
    candidates = [path]
    if override:
        if state_input and path.startswith(state_input):
            candidates.append(os.path.join(override, os.path.relpath(path, state_input)))
        if not os.path.isabs(path):
            # e.g. "staged/adni-full/sub-.../x.tsv" with override ".../staged/adni-full"
            parts = path.split(os.sep)
            base = os.path.basename(override.rstrip(os.sep))
            if base in parts:
                candidates.append(os.path.join(override, *parts[parts.index(base) + 1:]))
            candidates.append(os.path.join(override, path))
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(f"cannot locate {path!r}; pass --input to re-root the staged tree")
