"""Purged, embargoed walk-forward splitter (plan §6).

A week's barrier label resolves within that week (5-day horizon), so training
on weeks up to test_index - embargo - 1 guarantees no label window overlaps
the predicted week.
"""


def walk_forward_splits(weeks: list, train_window: int = 52, embargo: int = 1):
    """Yield (train_weeks, test_week) over a sorted list of week identifiers."""
    for i in range(len(weeks)):
        end = i - embargo
        if end < 1:
            continue
        start = max(0, end - train_window)
        yield weeks[start:end], weeks[i]
