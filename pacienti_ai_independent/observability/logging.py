from __future__ import annotations

import contextvars
import logging
import re
from typing import Optional

_correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")

_CNP_RE = re.compile(r"\b\d{13}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?4)?0\d{9}(?!\d)")


def set_correlation_id(value: str) -> None:
    _correlation_id_var.set((value or "").strip())


def get_correlation_id() -> str:
    return _correlation_id_var.get("")


def _mask_pii(text: str) -> str:
    raw = str(text or "")
    raw = _CNP_RE.sub("[CNP_MASKED]", raw)
    raw = _EMAIL_RE.sub("[EMAIL_MASKED]", raw)
    raw = _PHONE_RE.sub("[PHONE_MASKED]", raw)
    return raw


class PiiMaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _mask_pii(str(record.getMessage()))
        record.args = ()
        setattr(record, "correlation_id", get_correlation_id() or "-")
        return True


_LOGGER: Optional[logging.Logger] = None


def get_app_logger(name: str = "pacienti_ai_enterprise") -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | corr=%(correlation_id)s | %(name)s | %(message)s"
            )
        )
        handler.addFilter(PiiMaskingFilter())
        logger.addHandler(handler)
    logger.propagate = False
    _LOGGER = logger
    return logger
