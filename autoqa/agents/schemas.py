"""Structured output contract for the figure-review agent.

The model does not "reply with JSON"; it is forced to call the `record_reviews`
tool, whose input schema is generated from these pydantic models. The API
therefore guarantees well-formed JSON, and pydantic guarantees the values
(enums, lengths, one entry per scan) before anything is written to the journal.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Rating = Literal["clean", "minor", "concern", "bad"]
Panel = Literal["carpet", "coreg", "t1norm", "multiple", "none"]


class ScanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sub: str = Field(description="subject label exactly as given, e.g. sub-002S0295")
    ses: str = Field(description="session label exactly as given, e.g. ses-v28")
    rating: Rating
    panel: Panel = Field(description="which figure drove the rating; 'none' when clean")
    note: str = Field(default="", max_length=140,
                      description="specific observation, <=140 chars; empty when clean")


class ReviewBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviews: list[ScanReview] = Field(min_length=1)


REVIEW_TOOL = {
    "name": "record_reviews",
    "description": "Record one visual-QC review per scan shown. Call exactly once.",
    "input_schema": ReviewBatch.model_json_schema(),
}
