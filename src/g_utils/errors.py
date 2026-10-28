class AppError(Exception):
    """Public, content-free error with a stable code."""

    def __init__(self, code: str, message: str, status: int = 403):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def forbidden() -> AppError:
    return AppError("forbidden", "Operation is not permitted")
