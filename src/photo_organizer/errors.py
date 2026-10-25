"""Errors that retain actionable failure categories without provider response bodies."""
class CapabilityError(Exception):
    def __init__(self,code,message,retryable=False):
        super().__init__(message);self.code=code;self.retryable=retryable
