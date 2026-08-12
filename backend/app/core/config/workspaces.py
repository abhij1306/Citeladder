"""Workspace root-allocation policy."""

from typing import Final

# A workspace is a durable tenant root with membership and billing linkage.
# Bound it independently from project/prompt occupancy so one account cannot
# allocate an unbounded number of tenant roots. The personal workspace counts.
MAX_WORKSPACES_PER_USER: Final = 10

CODE_WORKSPACE_LIMIT_EXCEEDED: Final = "workspace_limit_exceeded"
