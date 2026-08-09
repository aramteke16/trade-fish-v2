"""Triple-barrier labeler (plan §5). Same barriers the execution uses."""


def label(entry: float, highs: list[float], lows: list[float], closes: list[float],
          upper: float, lower: float) -> tuple[str, float, int]:
    """Walk daily bars after entry; return (outcome, exit_price, exit_day_index).

    Outcome: 'loss' if the lower barrier is hit first, 'win' for the upper,
    'neutral' if the week's time barrier exits at the last close.
    If both barriers fall inside one bar, assume the stop hit first (conservative).
    """
    stop = entry * (1 + lower)
    take = entry * (1 + upper)

    for day, (high, low) in enumerate(zip(highs, lows)):
        if low <= stop:
            return "loss", stop, day
        if high >= take:
            return "win", take, day
    return "neutral", closes[-1], len(closes) - 1
