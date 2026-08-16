"""Pydantic models for parsed applicant records."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field
from uuid import uuid4


class AnswerStatus(str, Enum):
    answered = "answered"
    blank = "blank"
    deferred = "deferred"


class QAPair(BaseModel):
    question: str
    answer: str = ""
    status: AnswerStatus = AnswerStatus.answered


class MedicationEntry(BaseModel):
    medication: str
    dosage: str = ""
    indication: str = ""
    since: str = ""


class ConditionChecklistEntry(BaseModel):
    condition: str
    checked: bool = False


class ConsumptionEntry(BaseModel):
    substance: str
    amount: str = ""


class Identity(BaseModel):
    name: str = ""
    date: str = ""
    age: str = ""
    pronouns: str = ""
    birthdate: str = ""
    occupation: str = ""
    email: str = ""
    address: str = ""
    phone: str = ""


class ParsedSection(BaseModel):
    name: str
    taxonomy_key: str
    qa_pairs: list[QAPair] = Field(default_factory=list)
    medications: list[MedicationEntry] = Field(default_factory=list)
    condition_checklist: list[ConditionChecklistEntry] = Field(default_factory=list)
    consumption_table: list[ConsumptionEntry] = Field(default_factory=list)
    raw_text: str = ""


class ApplicantRecord(BaseModel):
    applicant_id: str = Field(default_factory=lambda: str(uuid4()))
    display_name: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    raw_form_path: str = ""
    identity: Identity = Field(default_factory=Identity)
    sections: dict[str, ParsedSection] = Field(default_factory=dict)
    unmapped_content: str = ""
