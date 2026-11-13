from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class AuthFlowConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    login_attempt_limit: int = 5
    login_attempt_window_seconds: int = 300
    login_attempt_cache_prefix: str = "login_attempt"
    password_reset_request_limit: int = 3
    password_reset_request_window_seconds: int = 300
    reset_request_cache_prefix: str = "reset_request"
    verification_resend_limit: int = 3
    verification_resend_window_seconds: int = 300
    verification_resend_cache_prefix: str = "verification_resend"
