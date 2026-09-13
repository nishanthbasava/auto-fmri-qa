"""`autoqa` -- one entrypoint for every stage.

    autoqa run      --input staged/ --out runs/qc1 [--render]   discover -> metrics -> classify
    autoqa render   runs/qc1                                    SVG -> JPEG (playwright)
    autoqa review   runs/qc1 [--only flagged]                   LLM figure review (ANTHROPIC_API_KEY)
    autoqa report   deck|dashboard runs/qc1                     pptx deck / static HTML
    autoqa lists    runs/qc1 -o lists/                          include/caution/exclude CSVs
    autoqa rag      build | query "..."                         knowledge-base index
    autoqa stage    /derivatives -o staged/                     copy the light subset (on the cluster)
    autoqa serve    [--host 0.0.0.0 --port 8000]                the FastAPI backend
    autoqa criteria [path]                                      validate + print a criteria file
    autoqa demo     --out staged/demo [--subjects 24]           synthetic cohort (no real data)
    autoqa audit    pooling|surface runs/qc1                    reportable numbers from a run

Every subcommand is a thin wrapper over a module `main(argv)`, so the same code
is importable as a library (see `autoqa.qc`).
"""
from __future__ import annotations

import argparse
import sys


def _run(argv):
    from .pipeline.run import main
    return main(argv)


def _render(argv):
    from .pipeline.render import main
    return main(argv)


def _review(argv):
    from .agents.review_figures import main
    return main(argv)


def _report(argv):
    if not argv or argv[0] not in ("deck", "dashboard"):
        print("usage: autoqa report {deck,dashboard} RUN_DIR [...]", file=sys.stderr)
        return 2
    kind, rest = argv[0], argv[1:]
    if kind == "deck":
        from .report.build_decks import main
    else:
        from .report.dashboard import main
    return main(rest)


def _lists(argv):
    from .lists import main
    return main(argv)


def _rag(argv):
    from .agents.rag import main
    return main(argv)


def _stage(argv):
    from .stage import main
    return main(argv)


def _serve(argv):
    ap = argparse.ArgumentParser(prog="autoqa serve")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    a = ap.parse_args(argv)
    import uvicorn
    uvicorn.run("autoqa.api.main:app", host=a.host, port=a.port, reload=a.reload)
    return 0


def _audit(argv):
    if not argv or argv[0] not in ("pooling", "surface"):
        print("usage: autoqa audit {pooling,surface} RUN_DIR [...]", file=sys.stderr)
        return 2
    if argv[0] == "pooling":
        from .analysis.pooling_audit import main
    else:
        from .analysis.surface import main
    return main(argv[1:])


def _demo(argv):
    from .synth import main
    return main(argv)


def _criteria(argv):
    ap = argparse.ArgumentParser(prog="autoqa criteria",
                                 description="Validate a criteria file and print it.")
    ap.add_argument("path", nargs="?", default=None)
    a = ap.parse_args(argv)
    import yaml

    from .criteria import default_path, load_criteria
    path = a.path or default_path()
    try:
        crit = load_criteria(path)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"# {path}  (valid)")
    print(yaml.safe_dump(crit.as_dict(), sort_keys=False))
    return 0


COMMANDS = {
    "run": _run, "render": _render, "review": _review, "report": _report,
    "lists": _lists, "rag": _rag, "stage": _stage, "serve": _serve,
    "criteria": _criteria, "demo": _demo, "audit": _audit,
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    if argv[0] in ("-V", "--version"):
        from . import __version__
        print(f"autoqa {__version__}")
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd not in COMMANDS:
        print(f"autoqa: unknown command {cmd!r}\n", file=sys.stderr)
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return int(COMMANDS[cmd](rest) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
