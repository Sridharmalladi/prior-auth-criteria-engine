"""Pydantic schemas for policies, criteria nodes, facts and cases.

These schemas are used for two things:

1. Structured output from the LLM during offline policy parsing / fact
   extraction (the JSON schema is handed to OpenRouter).
2. Load-time validation of anything committed under ``data/``.

The runtime evaluator (``evaluate.py``) deliberately does *not* import this
module: it works on plain dicts so that the deterministic core has zero
third-party dependencies and stays a line-for-line twin of ``docs/js/evaluator.js``.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field, field_validator, model_validator

PredicateValue = Union[bool, float, int, str, List[str]]


class NodeType(str, Enum):
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    N_OF = "N_OF"
    LEAF = "LEAF"


class Operator(str, Enum):
    GTE = ">="
    LTE = "<="
    EQ = "=="
    NEQ = "!="
    INCLUDES = "includes"
    EXCLUDES = "excludes"


NUMERIC_OPS = {Operator.GTE, Operator.LTE}
SET_OPS = {Operator.INCLUDES, Operator.EXCLUDES}


class SourceRef(BaseModel):
    section: str = Field(description="Section or paragraph label within the policy")
    url: str = Field(description="Deep link to the published policy on CMS")


class Predicate(BaseModel):
    key: str = Field(description="Fact key, snake_case, e.g. conservative_therapy_duration_months")
    op: Operator
    value: PredicateValue
    unit: Optional[str] = None

    @model_validator(mode="after")
    def _op_matches_value_type(self) -> "Predicate":
        if self.op in NUMERIC_OPS and not isinstance(self.value, (int, float)):
            raise ValueError("operator {0} requires a numeric value".format(self.op.value))
        if self.op in NUMERIC_OPS and isinstance(self.value, bool):
            raise ValueError("operator {0} requires a numeric value, got bool".format(self.op.value))
        if self.op in SET_OPS and not isinstance(self.value, (str, list)):
            raise ValueError("operator {0} requires a string or list value".format(self.op.value))
        return self


class Node(BaseModel):
    id: str
    type: NodeType
    n: Optional[int] = Field(default=None, description="Threshold for N_OF nodes")
    children: List[str] = Field(default_factory=list)
    label: str
    source_ref: SourceRef
    predicate: Optional[Predicate] = None

    @model_validator(mode="after")
    def _shape_matches_type(self) -> "Node":
        if self.type is NodeType.LEAF:
            if self.predicate is None:
                raise ValueError("leaf {0} has no predicate".format(self.id))
            if self.children:
                raise ValueError("leaf {0} must not have children".format(self.id))
        else:
            if self.predicate is not None:
                raise ValueError("operator node {0} must not carry a predicate".format(self.id))
            if self.type is NodeType.NOT and len(self.children) != 1:
                raise ValueError("NOT node {0} needs exactly 1 child".format(self.id))
            if self.type in (NodeType.AND, NodeType.OR) and len(self.children) < 2:
                raise ValueError("{0} node {1} needs at least 2 children".format(self.type.value, self.id))
            if self.type is NodeType.N_OF:
                if self.n is None:
                    raise ValueError("N_OF node {0} needs n".format(self.id))
                if self.n < 1 or self.n > len(self.children):
                    raise ValueError("N_OF node {0} has n outside 1..len(children)".format(self.id))
        if self.type is not NodeType.N_OF and self.n is not None:
            raise ValueError("n is only meaningful on N_OF nodes ({0})".format(self.id))
        return self


class SourceType(str, Enum):
    NCD = "NCD"
    LCD = "LCD"


class Policy(BaseModel):
    policy_id: str
    title: str
    source_url: str
    source_type: SourceType
    root: str
    nodes: Dict[str, Node]

    @model_validator(mode="after")
    def _root_exists(self) -> "Policy":
        if self.root not in self.nodes:
            raise ValueError("root {0} is not in nodes".format(self.root))
        for node_id, node in self.nodes.items():
            if node_id != node.id:
                raise ValueError("node key {0} does not match node.id {1}".format(node_id, node.id))
        return self


class Fact(BaseModel):
    key: str
    value: PredicateValue
    unit: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    source_span: Tuple[int, int]
    evidence_text: str

    @field_validator("source_span")
    @classmethod
    def _span_ordered(cls, span: Tuple[int, int]) -> Tuple[int, int]:
        start, end = span
        if start < 0 or end <= start:
            raise ValueError("source_span must be a non-empty forward range")
        return span


class Decision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    INDETERMINATE = "INDETERMINATE"


class Case(BaseModel):
    case_id: str
    policy_id: str
    title: str
    note_text: str
    facts: List[Fact] = Field(default_factory=list)
    gold_decision: Decision
    gold_blocking_node: Optional[str] = None

    @model_validator(mode="after")
    def _spans_index_evidence(self) -> "Case":
        for fact in self.facts:
            start, end = fact.source_span
            if self.note_text[start:end] != fact.evidence_text:
                raise ValueError(
                    "fact {0}: source_span {1} does not index evidence_text".format(fact.key, fact.source_span)
                )
        if self.gold_decision is Decision.DENY and not self.gold_blocking_node:
            raise ValueError("denied case {0} must name a gold_blocking_node".format(self.case_id))
        return self


# Schema handed to the LLM for structured policy parsing.
POLICY_JSON_SCHEMA = Policy.model_json_schema() if hasattr(Policy, "model_json_schema") else {}
