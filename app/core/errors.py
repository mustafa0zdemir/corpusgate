from __future__ import annotations


class AppError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, code: str = "bad_request"):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code


class DocumentNotFoundError(AppError):
    def __init__(self) -> None:
        super().__init__("Document not found.", status_code=404, code="document_not_found")


class InvalidFileError(AppError):
    def __init__(self, message: str, *, status_code: int = 415, code: str = "invalid_file"):
        super().__init__(message, status_code=status_code, code=code)


class FileTooLargeError(InvalidFileError):
    def __init__(self, max_size_mb: int) -> None:
        super().__init__(
            f"File exceeds the configured {max_size_mb} MB limit.",
            status_code=413,
            code="file_too_large",
        )


class DocumentConversionError(AppError):
    def __init__(self, message: str = "The document could not be converted.") -> None:
        super().__init__(message, status_code=422, code="conversion_failed")


class OperationBusyError(AppError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            f"The {operation} capacity is currently full.",
            status_code=503,
            code=f"{operation}_busy",
        )


class OperationTimeoutError(AppError):
    def __init__(self, operation: str) -> None:
        super().__init__(
            f"The {operation} operation exceeded its configured time limit.",
            status_code=504,
            code=f"{operation}_timeout",
        )


class InsufficientStorageError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "There is not enough storage space to complete the operation.",
            status_code=507,
            code="insufficient_storage",
        )
