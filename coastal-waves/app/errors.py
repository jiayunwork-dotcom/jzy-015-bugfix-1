# 领域错误：单条/批量非法输入与色散不闭合都用这些类型表达。

from __future__ import annotations


class WaveServiceError(Exception):
    code = "INTERNAL_ERROR"
    status_code = 500

    def __init__(self, message: str, *, field: str | None = None, index: int | None = None):
        super().__init__(message)
        self.message = message
        self.field = field
        self.index = index


class WaveValidationError(WaveServiceError):
    code = "INVALID_PARAMETER"
    status_code = 422


class LinearLimitExceededError(WaveServiceError):
    code = "LINEAR_LIMIT_EXCEEDED"
    status_code = 422


class DispersionError(WaveServiceError):
    code = "DISPERSION_NOT_CONVERGED"
    status_code = 422
