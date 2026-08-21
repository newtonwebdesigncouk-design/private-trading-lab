"""Leak-resistant chronological dataset splitting."""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict


class SplitBoundaries(BaseModel):
    model_config = ConfigDict(frozen=True)

    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    test_start: int
    test_end: int


def chronological_split[T](
    values: Sequence[T], train_fraction: float = 0.60, validation_fraction: float = 0.20
) -> tuple[tuple[T, ...], tuple[T, ...], tuple[T, ...]]:
    if not 0 < train_fraction < 1 or not 0 < validation_fraction < 1:
        raise ValueError("split fractions must lie between zero and one")
    if train_fraction + validation_fraction >= 1:
        raise ValueError("the split must leave a non-empty test fraction")
    train_end = int(len(values) * train_fraction)
    validation_end = train_end + int(len(values) * validation_fraction)
    if train_end < 2 or validation_end - train_end < 2 or len(values) - validation_end < 2:
        raise ValueError("each chronological split requires at least two observations")
    return (
        tuple(values[:train_end]),
        tuple(values[train_end:validation_end]),
        tuple(values[validation_end:]),
    )
