"""Path-safety helpers shared by the MCP tools and any future surface.

Two checks, used together where a root exists (per docs/mcp-conventions.md in
the APAB repo): traversal rejection blocks ``..`` segments, and containment
blocks absolute paths outside a declared root. antenna-cad's tools take
explicit paths per call and have no ambient workspace root, so the tools apply
traversal rejection to every path argument and callers that do have a root
(e.g. a harness driving these tools) should add ``validate_path_within``.
"""

from __future__ import annotations

from pathlib import Path


def reject_path_traversal(path: str) -> Path:
    """Refuse any path containing parent-directory traversal."""
    p = Path(path)
    if ".." in p.parts:
        raise ValueError(f"path {path!r} contains '..' traversal and is not allowed")
    return p


def validate_path_within(path: str | Path, root: str | Path) -> Path:
    """Resolve *path* and require it to live under *root*.

    Traversal rejection alone still admits absolute paths anywhere on the
    filesystem; this is the containment half of the convention.
    """
    resolved = Path(path).resolve()
    root_resolved = Path(root).resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise ValueError(f"path {str(path)!r} escapes root {str(root_resolved)!r}") from None
    return resolved
