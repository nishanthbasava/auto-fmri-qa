"""QC criteria: the versioned threshold contract, validated at load time.

`criteria.yaml` is the single source of truth for every threshold in the
pipeline. It is validated with pydantic when loaded so that a typo such as
`mode: relatve` or a reversed borderline band fails immediately, rather than
silently classifying every scan INCLUDE at run time.

    from autoqa.criteria import load_criteria, default_path
    crit = load_criteria()                 # packaged default
    crit = load_criteria("my_criteria.yaml")
    crit.outlier_definition.mode           # "relative"
    crit.as_dict()                         # plain dict, as stored in state.json

Resolution order for the default: $AFQ_CRITERIA, then the copy shipped inside
the package (autoqa/data/criteria.yaml).
"""
from __future__ import annotations

import os
from importlib import resources
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Exclusion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    missing_outputs: bool = True
    mean_fd_mm: float = Field(gt=0)


class OutlierDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["absolute", "relative", "tr_scaled"]
    fd_spike_mm: float = Field(gt=0)
    dvars_abs: float = Field(gt=0)
    dvars_rel_mult: float = Field(gt=0)


class Caution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    motion_outlier_percent: float = Field(ge=0, le=100)
    min_retained_minutes: Optional[float] = Field(default=None, gt=0)


class VerifyFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")
    borderline_mean_fd_band: tuple[float, float]
    borderline_outlier_band: tuple[float, float]

    @model_validator(mode="after")
    def _ordered(self):
        for name in ("borderline_mean_fd_band", "borderline_outlier_band"):
            lo, hi = getattr(self, name)
            if not lo < hi:
                raise ValueError(f"{name}: expected [low, high] with low < high, got {lo}, {hi}")
        return self


class Multiband(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fast_tr_threshold_s: float = Field(gt=0)


class Criteria(BaseModel):
    """The whole criteria.yaml document."""
    model_config = ConfigDict(extra="forbid")
    version: str
    dated: str
    decided_by: str = ""
    exclusion: Exclusion
    outlier_definition: OutlierDefinition
    caution: Caution
    verify_flags: VerifyFlags
    multiband: Multiband

    @model_validator(mode="after")
    def _bands_bracket_thresholds(self):
        lo, hi = self.verify_flags.borderline_mean_fd_band
        if not lo <= self.exclusion.mean_fd_mm <= hi:
            raise ValueError(
                f"borderline_mean_fd_band {lo}-{hi} does not bracket exclusion.mean_fd_mm "
                f"{self.exclusion.mean_fd_mm}")
        lo, hi = self.verify_flags.borderline_outlier_band
        if not lo <= self.caution.motion_outlier_percent <= hi:
            raise ValueError(
                f"borderline_outlier_band {lo}-{hi} does not bracket "
                f"caution.motion_outlier_percent {self.caution.motion_outlier_percent}")
        return self

    def as_dict(self) -> dict:
        """Plain-dict form (what the pipeline stores in state.json)."""
        d = self.model_dump()
        d["verify_flags"] = {k: list(v) for k, v in d["verify_flags"].items()}
        return d


def default_path() -> str:
    """Path of the criteria file to use when none is given."""
    env = os.environ.get("AFQ_CRITERIA")
    if env:
        return env
    return str(resources.files("autoqa").joinpath("data", "criteria.yaml"))


def load_criteria(path: Optional[str] = None) -> Criteria:
    path = path or default_path()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}
    try:
        return Criteria.model_validate(raw)
    except Exception as e:  # re-raise with the file name so CLI errors are actionable
        raise ValueError(f"invalid criteria file {path}:\n{e}") from e
