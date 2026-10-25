"""Errors that retain actionable failure categories without provider response bodies."""


class CapabilityError(Exception):
    def __init__(self, code, message, retryable=False, retry_after=None):
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after
