"""Errors for persisted analysis projections."""


class AnalysisNotFoundError(LookupError):
    """Raised when a requested projection has no persisted rows to serve."""


class TrendQueryError(ValueError):
    """Raised for an invalid trend query (bad engine/granularity/range)."""
