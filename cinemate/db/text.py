"""Fit strings from external sources into the length of their database column."""

from sqlalchemy.orm import InstrumentedAttribute

ELLIPSIS = "…"


def fit[T](column: InstrumentedAttribute, value: T) -> T:
    """``value`` cut to the length of ``column`` with an ellipsis at the end.

    The length comes from the model (``String(n)``), so no numbers live in the callers. Values
    that are not strings, columns without a length (``Text``) and strings that fit stay as they
    are.
    """
    if not isinstance(value, str):
        return value
    length = getattr(column.type, "length", None)
    if length is None or len(value) <= length:
        return value
    if length <= len(ELLIPSIS):
        return value[:length]  # type: ignore[return-value]
    return value[: length - len(ELLIPSIS)] + ELLIPSIS  # type: ignore[return-value]
