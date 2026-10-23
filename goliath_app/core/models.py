"""Core-namespace action models shared across descendant apps."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from goliath_app.actions.base_models import ActionOutputBase


class PlanIterationsInput(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_path: str = Field(alias="projectPath")
    feature_iterations: Optional[int] = Field(default=None, alias="featureIterations")
    quality_iterations: Optional[int] = Field(default=None, alias="qualityIterations")
    seed: Optional[int] = None
    train_fraction: Optional[float] = Field(default=None, alias="trainFraction")
    layout: Optional[str] = None
    iterations: List[dict[str, object]] = Field(default_factory=list)


class PlanIterationsOutput(ActionOutputBase):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_path: str = Field(alias="projectPath")
    iterations: List[dict[str, object]] = Field(default_factory=list)
    centroid_seed_groups: List[dict[str, object]] = Field(
        default_factory=list, alias="centroidSeedGroups"
    )
