class NewsletterError(Exception):
    """Base error with a stable stage-oriented meaning."""


class ConfigurationError(NewsletterError):
    pass


class LockError(NewsletterError):
    pass


class StageError(NewsletterError):
    def __init__(self, stage: str, message: str):
        self.stage = stage
        super().__init__(f"[{stage}] {message}")


class OpenCodeError(NewsletterError):
    pass


class SchemaError(NewsletterError):
    pass
