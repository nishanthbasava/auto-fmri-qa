"""Label taxonomy for visual QC of fMRIPrep reportlets.

Three fields per (scan, rater):
  rating        clean | minor | concern | bad          -- the review agent's scale
  panel         carpet | coreg | t1norm | multiple | none
  failure_type  what is wrong, when something is:
                truncated_fov, saturated_epi, misregistration, skull_strip,
                carpet_block, ghosting, motion, other, none

`coarse()` collapses rating to usable / needs_review / unusable -- the
"label granularity" axis of the ablation study (a 3-class problem is easier
and may be all a triage tool needs).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Rating = Literal["clean", "minor", "concern", "bad"]
Panel = Literal["carpet", "coreg", "t1norm", "multiple", "none"]
FailureType = Literal["truncated_fov", "saturated_epi", "misregistration", "skull_strip",
                      "carpet_block", "ghosting", "motion", "other", "none"]
Coarse = Literal["usable", "needs_review", "unusable"]

RATINGS: tuple[str, ...] = ("clean", "minor", "concern", "bad")
FAILURE_TYPES: tuple[str, ...] = ("truncated_fov", "saturated_epi", "misregistration",
                                  "skull_strip", "carpet_block", "ghosting", "motion",
                                  "other", "none")
COARSE: tuple[str, ...] = ("usable", "needs_review", "unusable")


def coarse(rating: str) -> str:
    return {"clean": "usable", "minor": "usable", "concern": "needs_review", "bad": "unusable"}[rating]


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(description="'<sub>|<ses>' scan key as in state.json")
    sub: str
    ses: str
    rating: Rating
    panel: Panel = "none"
    failure_type: FailureType = "none"
    note: str = Field(default="", max_length=200)
    rater: str = ""

    @property
    def coarse(self) -> str:
        return coarse(self.rating)


class Prediction(BaseModel):
    """What a predictor returns for one example (same fields, no rater)."""
    model_config = ConfigDict(extra="ignore")
    rating: Rating
    panel: Panel = "none"
    failure_type: FailureType = "none"
    note: str = ""


PREDICTION_TOOL = {
    "name": "record_review",
    "description": "Record the visual-QC review for the single scan shown.",
    "input_schema": Prediction.model_json_schema(),
}
