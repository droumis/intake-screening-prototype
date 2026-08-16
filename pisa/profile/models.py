"""Pydantic models for the Screening Profile."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

PROFILE_SCHEMA_VERSION = "2"


class DetectionSpec(BaseModel):
    checklist_fields: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    medication_names: list[str] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)


class HardCriterion(BaseModel):
    id: str
    description: str
    detection: DetectionSpec = Field(default_factory=DetectionSpec)
    source_doc: str = ""
    source_excerpt: str = ""
    basis: Literal["regulatory", "house"] = "house"
    citation: str = ""


class CautionCriterion(BaseModel):
    id: str
    description: str
    detection: DetectionSpec = Field(default_factory=DetectionSpec)
    source_doc: str = ""
    source_excerpt: str = ""
    default_level: Literal["yellow", "red"] = "yellow"
    basis: Literal["regulatory", "house"] = "house"
    citation: str = ""
    resolution_pathway: str = ""


class MedicationClassOfConcern(BaseModel):
    class_name: str
    example_names: list[str] = Field(default_factory=list)
    why: str = ""
    criterion_ref: str = ""
    source_doc: str = ""


class ProgramDemand(BaseModel):
    id: str
    demand: str
    interacts_with: list[str] = Field(default_factory=list)


class PositiveIndicator(BaseModel):
    id: str
    description: str


class GroundRule(BaseModel):
    rule: str
    source_doc: str = ""


class ConflictWarning(BaseModel):
    criteria_involved: list[str] = Field(default_factory=list)
    description: str
    conservative_reading: str
    source_docs: list[str] = Field(default_factory=list)
    is_ground_rule_conflict: bool = False


class ScreeningProfile(BaseModel):
    hard_criteria: list[HardCriterion] = Field(default_factory=list)
    caution_criteria: list[CautionCriterion] = Field(default_factory=list)
    medication_classes_of_concern: list[MedicationClassOfConcern] = Field(default_factory=list)
    program_demands: list[ProgramDemand] = Field(default_factory=list)
    positive_indicators: list[PositiveIndicator] = Field(default_factory=list)
    ground_rules: list[GroundRule] = Field(default_factory=list)
    conflicts: list[ConflictWarning] = Field(default_factory=list)
    approved: bool = False
    profile_hash: str = ""
