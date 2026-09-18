"""全局异常类。禁止裸 raise/except，统一走这里。"""

from typing import Any


class AppError(Exception):
    """应用错误基类。所有业务异常都继承。"""

    code: str = "app_error"
    status_code: int = 500

    def __init__(self, message: str = "", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


# ====== LLM 相关 ======
class LLMError(AppError):
    code = "llm_error"
    status_code = 502


class LLMAllProvidersFailedError(LLMError):
    """所有 provider 都调用失败。"""

    code = "llm_all_providers_failed"
    status_code = 503


# ====== 知识库相关 ======
class KnowledgeBaseError(AppError):
    code = "knowledge_base_error"
    status_code = 500


class StandardNotFoundError(KnowledgeBaseError):
    code = "standard_not_found"
    status_code = 404


# ====== 问诊相关 ======
class ConsultationError(AppError):
    code = "consultation_error"
    status_code = 400


class InvalidStateTransitionError(ConsultationError):
    """问诊状态机非法跳转。"""

    code = "invalid_state_transition"
    status_code = 400


# ====== 文档相关 ======
class DocumentParseError(AppError):
    code = "document_parse_error"
    status_code = 422


class DocumentValidationError(AppError):
    """文档校验失败（如文件过大、类型不支持）。"""

    code = "document_validation_error"
    status_code = 422


# ====== 认证相关 ======
class AuthError(AppError):
    code = "auth_error"
    status_code = 401


class InvalidCredentialsError(AuthError):
    code = "invalid_credentials"
    status_code = 401


class PermissionDeniedError(AuthError):
    code = "permission_denied"
    status_code = 403
