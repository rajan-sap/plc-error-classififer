"""Domain models for the parser layer.

These describe the *structural* output of the deterministic parser, before
any LLM judgment is applied. They're also the types every downstream layer
(classifier, eval, API) talks to — so the contract lives here.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Stage(str, Enum):
    XML_VALIDATION = "xml_validation"
    CODE_GENERATION = "code_generation"
    IEC_COMPILATION = "iec_compilation"
    C_COMPILATION = "c_compilation"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class Complexity(str, Enum):
    TRIVIAL = "trivial"
    MODERATE = "moderate"
    COMPLEX = "complex"


class SourceLocation(BaseModel):
    file: str | None = None
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None


class ParsedError(BaseModel):
    # Defaults to "" so extractors can build instances without specifying it;
    # the parser orchestrator stamps stable ids ("err_000", ...) after sorting.
    id: str = ""
    stage: Stage
    category: str
    message: str
    raw_text: str
    source_location: SourceLocation = Field(default_factory=SourceLocation)
    log_line_start: int
    log_line_end: int
    # True for known false-positives — e.g. the recurring PLCopen XSD warning that fires on every project.
    is_noise: bool = False
    context_lines: list[str] = Field(default_factory=list)


class Cascade(BaseModel):
    primary_root_ids: list[str] = Field(default_factory=list)
    downstream: dict[str, list[str]] = Field(default_factory=dict)


class ParsedLog(BaseModel):
    errors: list[ParsedError] = Field(default_factory=list)
    cascade: Cascade = Field(default_factory=Cascade)
    raw_log: str

    def primary_errors(self) -> list[ParsedError]:
        """Return the subset of ``errors`` whose ids are in the cascade's primary roots."""
        roots = set(self.cascade.primary_root_ids)
        return [e for e in self.errors if e.id in roots]
