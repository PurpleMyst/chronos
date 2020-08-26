import typing as t
from datetime import timezone, timedelta


def utc(offset: int) -> timezone:
    return timezone(timedelta(hours=offset))


class HasId(t.Protocol):
    id: int


T = t.TypeVar("T", bound=HasId)


def by_id(needle_id: int, haystack: t.Iterable[T]) -> T:
    "Find an item by its ID in an iterable"
    return next(item for item in haystack if item.id == needle_id)