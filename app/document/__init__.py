"""Document/content editing capability and format handlers."""
from app.document.capability import DocumentEditingCapability
from app.document.handlers import SUPPORTED_EXTENSIONS, handler_for

__all__ = ["DocumentEditingCapability", "SUPPORTED_EXTENSIONS", "handler_for"]
