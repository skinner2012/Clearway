"""T0 acceptance tests: models import, JSON-schema smoke, extra=forbid, frozen OracleVerdict."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from clearway import schemas
from clearway.schemas import models
from clearway.schemas.models import (
    Conformance,
    Finding,
    L1Status,
    Oracle,
    OracleRegime,
    OracleVerdict,
)

# Every concrete BaseModel defined in the contract (Oracle is a Protocol, excluded).
MODEL_CLASSES = [
    obj
    for obj in vars(models).values()
    if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel
]


def test_public_names_are_importable() -> None:
    """Every name promised by clearway.schemas.__all__ resolves."""
    for name in schemas.__all__:
        assert hasattr(schemas, name), f"clearway.schemas is missing {name!r}"


@pytest.mark.parametrize("model", MODEL_CLASSES, ids=lambda m: m.__name__)
def test_json_schema_generates(model: type[BaseModel]) -> None:
    """Each model produces a valid JSON schema titled after the class."""
    js = model.model_json_schema()
    assert isinstance(js, dict)
    assert js["title"] == model.__name__


def test_extra_forbid_rejects_unknown_field() -> None:
    """Contracts are strict: an unexpected field is a validation error."""
    with pytest.raises(ValidationError):
        Finding(id="x", source_url="u", rule_id="image-alt", target="img", bogus=1)


def test_oracle_verdict_is_frozen() -> None:
    """Ground truth is immutable — assignment after construction must fail."""
    verdict = OracleVerdict(success_criteria=["1.1.1"])
    with pytest.raises(ValidationError):
        verdict.source = "axe-core"


def test_enum_wire_values_are_stable() -> None:
    """Wire strings are the contract; renaming a value is a breaking change."""
    assert Conformance.DOES_NOT_SUPPORT.value == "does_not_support"
    assert L1Status.NO_ORACLE.value == "no_oracle"
    assert OracleRegime.A_DIGITAL.value == "A-digital"


def test_oracle_protocol_is_runtime_checkable() -> None:
    """A structural implementation satisfies isinstance(..., Oracle)."""

    class DummyOracle:
        def verdict_for(self, finding):  # noqa: ANN001, ANN201
            return None

        @property
        def regime(self):  # noqa: ANN201
            return OracleRegime.A_DIGITAL

        @property
        def version(self):  # noqa: ANN201
            return "test-1"

    assert isinstance(DummyOracle(), Oracle)
