class PropUpkeepError(Exception):
    """Base application error."""


class UserVisibleError(PropUpkeepError):
    """Errors safe to show directly in the UI."""

    def __init__(self, user_message: str, detail: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


class ConfigurationError(UserVisibleError):
    """Configuration is invalid or missing."""


class AIFormattingError(UserVisibleError):
    """AI response could not be validated."""


class PersistenceError(UserVisibleError):
    """Storage operation failed."""
