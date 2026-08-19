"""Paging state validation tests."""

from __future__ import annotations

import pytest

from app.workers.integration.paging import (
    MalformedProviderPageError,
    next_dataset_page,
)


def test_cursor_page_requires_page_info() -> None:
    with pytest.raises(MalformedProviderPageError, match="missing pageInfo"):
        next_dataset_page(
            cursor_mode=True,
            page_info=None,
            start_row=0,
            raw_row_count=1,
            page_size=100,
        )
