from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints


class ContractModel(BaseModel):
    """Base for every I/O model: immutable; unknown fields are an error, never dropped."""

    model_config = ConfigDict(frozen=True, extra="forbid")


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

# Category and assignment-group ids. The shape is checked here; membership is checked against
# config/taxonomy.yaml by `Taxonomy.violations`, because the allowed values are configuration.
TaxonomyId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
