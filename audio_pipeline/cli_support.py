from __future__ import annotations

from typing import List, TypeVar

T = TypeVar("T")


def filter_series(series: List[T], selector: str | None) -> List[T]:
    if not selector:
        return series
    wanted = {item.strip() for item in selector.split(",") if item.strip()}
    return [item for item in series if getattr(item, "key", None) in wanted or getattr(item, "display_name", None) in wanted]
