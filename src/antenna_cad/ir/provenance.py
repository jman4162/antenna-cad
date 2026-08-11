"""Design revision provenance.

Each revision records what produced it and the hashes needed to reproduce or diff it.
The MVP regenerates designs deterministically from specs, so the chain is short; the
transform/patch system planned for later appends to the same structure.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class DesignRevision(BaseModel):
    """One node in a design's revision history."""

    model_config = ConfigDict(frozen=True)

    id: str
    parent: str | None = None
    created_by: Literal["human", "agent", "optimizer", "compiler", "import"] = "compiler"
    design_hash: str
    tool_versions: dict[str, str] = {}
    note: str | None = None
