"""Compatibility shim — delivery lives in sentinel.notify."""
from sentinel.notify import deliver, sms, flush_outbox, remember_sent, OUTBOX, SENT_LOG  # noqa: F401
