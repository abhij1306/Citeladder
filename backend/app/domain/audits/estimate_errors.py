"""Errors raised while projecting audit costs from persisted inputs."""


class AuditEstimateError(ValueError):
    """The request cannot be estimated from an authorized persisted portfolio."""
