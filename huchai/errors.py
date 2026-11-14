"""Errors that decide whether a crawl writes anything."""


class SourceBlocked(RuntimeError):
    """The origin returned an anti-bot challenge or a hard block.

    Callers must not treat this as an empty dataset and must not try to
    solve the challenge.
    """


class SourceError(RuntimeError):
    """The origin was reached but the payload was unusable."""
