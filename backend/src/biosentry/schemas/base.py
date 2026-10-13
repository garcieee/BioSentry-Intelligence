"""Base model and scalar types shared by every contract schema.

Contract rules enforced here, once:
  - extra="forbid": unknown keys are errors, never silently dropped.
  - frozen=True: records are values, not mutable state.
  - allow_inf_nan=False: NaN/Infinity can never stand in for a missing value (I1).
  - numeric scalars are strict: "12" and True are not numbers.
  - no value field is given a default anywhere; optional input fields default to None only.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# Strict scalars. Strict float still accepts JSON integers (118 is a valid heart rate).
Num = Annotated[float, Field(strict=True, allow_inf_nan=False)]
NonNegNum = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0)]
Fraction = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=1)]
Percent = Annotated[float, Field(strict=True, allow_inf_nan=False, ge=0, le=100)]
NonNegInt = Annotated[int, Field(strict=True, ge=0)]
Flag = Annotated[bool, Field(strict=True)]
Age = Annotated[int, Field(strict=True, ge=0, le=150)]


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


class CamelContract(Contract):
    """Input forms keep the camelCase wire names the Station form already sends."""

    model_config = ConfigDict(alias_generator=to_camel)
