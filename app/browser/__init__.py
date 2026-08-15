"""Browser automation capability and adapter exports."""
from app.browser.adapter import BrowserAdapter, BrowserObservation, PlaywrightBrowserAdapter
from app.browser.capability import BrowserCapability

__all__ = ["BrowserAdapter", "BrowserObservation", "PlaywrightBrowserAdapter", "BrowserCapability"]
