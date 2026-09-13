"""autoqa -- automated QC for fMRIPrep outputs.

Deterministic pipeline (discover -> metrics -> classify -> render), advisory LLM
figure review, and report/app layers. Use the SDK from Python:

    import autoqa
    result = autoqa.qc("staged/adni-batch1", out="runs/qc1")
    print(result.counts)                       # {'INCLUDE': 393, 'CAUTION': 45, 'EXCLUDE': 20}
    for scan in result.scans:                  # list of dicts, one per (subject, session)
        print(scan["sub"], scan["ses"], scan["status"], scan["metrics"]["mean_fd"])

or the CLI (`autoqa --help`).
"""
from importlib.metadata import PackageNotFoundError, version

from .criteria import Criteria, load_criteria
from .pipeline.run import RunResult, qc

try:
    __version__ = version("auto-fmri-qa")
except PackageNotFoundError:  # running from a checkout without `pip install -e .`
    __version__ = "0.0.0+local"

__all__ = ["qc", "RunResult", "Criteria", "load_criteria", "__version__"]
