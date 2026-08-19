"""Browser engine adapters hidden behind a small synchronous controller contract."""
from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from queue import Queue
from threading import Event, Lock, Thread, get_ident
from typing import Any, Dict, Iterable, Optional, Protocol

from urllib.parse import urlparse


@dataclass
class BrowserObservation:
    success: bool
    action: str
    url: str = ""
    title: str = ""
    text: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "action": self.action,
            "url": self.url,
            "title": self.title,
            "text": self.text,
            "data": self.data,
            "error": self.error,
        }


class BrowserAdapter(Protocol):
    def execute(self, action: str, inputs: Dict[str, Any]) -> BrowserObservation: ...
    def close(self) -> None: ...


class PlaywrightBrowserAdapter:
    """Playwright-backed adapter. Playwright is imported only when a session starts."""

    def __init__(self, profile_dir: Optional[str | Path] = None, headless: bool = True, executable_path: Optional[str] = None) -> None:
        self.profile_dir = Path(profile_dir).expanduser().resolve() if profile_dir else None
        self.headless = headless
        self.executable_path = executable_path
        self._playwright = None
        self._context = None
        self._pages: list[Any] = []
        self._active_index = 0
        self._owner_thread_id: Optional[int] = None
        self._owner_thread: Optional[Thread] = None
        self._commands: Queue = Queue()
        self._owner_ready = Event()
        self._owner_closed = False
        self._owner_start_lock = Lock()

    def _ensure_started(self) -> None:
        if self._context is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Browser automation requires the optional 'playwright' package. "
                "Install dependencies and run 'playwright install chromium'."
            ) from exc
        self._playwright = sync_playwright().start()
        launch_options = {"headless": self.headless}
        if self.executable_path:
            launch_options["executable_path"] = self.executable_path
        if self.profile_dir:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._context = self._playwright.chromium.launch_persistent_context(
                str(self.profile_dir), **launch_options
            )
        else:
            browser = self._playwright.chromium.launch(**launch_options)
            self._context = browser.new_context()
        self._pages = list(self._context.pages)
        if not self._pages:
            self._pages = [self._context.new_page()]
        self._active_index = max(0, len(self._pages) - 1)

    @property
    def page(self) -> Any:
        self._ensure_started()
        if self._active_index >= len(self._pages):
            self._active_index = 0
        return self._pages[self._active_index]

    def _page_snapshot(self) -> Dict[str, Any]:
        """Return a cheap owner-thread snapshot for browser monitors."""
        try:
            previous_count = len(self._pages)
            if self._context is not None:
                self._pages = list(self._context.pages)
                if len(self._pages) > previous_count:
                    self._active_index = len(self._pages) - 1
                elif self._active_index >= len(self._pages):
                    self._active_index = max(0, len(self._pages) - 1)
            page = self.page
            body = ""
            try:
                body = page.locator("body").inner_text(timeout=1000)[:4000]
            except Exception:
                pass
            token_source = f"{page.url}|{page.title()}|{body}"
            return {
                "page_count": len(self._pages),
                "active_index": self._active_index,
                "state_token": hashlib.sha256(token_source.encode("utf-8", "ignore")).hexdigest()[:20],
                "body_preview": body[:500],
            }
        except Exception:
            return {"page_count": len(self._pages), "active_index": self._active_index}

    def _observation(self, action: str, data: Optional[Dict[str, Any]] = None, text: str = "", error: Optional[str] = None) -> BrowserObservation:
        if error:
            return BrowserObservation(False, action, error=error, data=data or {})
        page = self.page
        merged = self._page_snapshot()
        merged.update(data or {})
        return BrowserObservation(
            True,
            action,
            url=page.url,
            title=page.title(),
            text=text,
            data=merged,
        )

    def _owner_loop(self) -> None:
        self._owner_thread_id = get_ident()
        self._owner_ready.set()
        while True:
            command = self._commands.get()
            if command is None:
                break
            action, inputs, future = command
            if action == "__close__":
                try:
                    self._close_local()
                    future.set_result(True)
                except Exception as exc:
                    future.set_exception(exc)
                break
            if action == "__recover__":
                try:
                    future.set_result(self._recover_local())
                except Exception as exc:
                    future.set_exception(exc)
                continue
            try:
                future.set_result(self._execute_local(action, inputs))
            except Exception as exc:
                future.set_exception(exc)
        self._owner_thread_id = None

    def _ensure_owner(self) -> None:
        with self._owner_start_lock:
            if self._owner_thread is not None and self._owner_thread.is_alive():
                self._owner_ready.wait(timeout=10)
                return
            self._owner_closed = False
            self._owner_ready.clear()
            self._owner_thread = Thread(target=self._owner_loop, name="freya-playwright-owner", daemon=True)
            self._owner_thread.start()
            if not self._owner_ready.wait(timeout=10):
                raise RuntimeError("Playwright browser owner thread did not start")

    def execute(self, action: str, inputs: Dict[str, Any]) -> BrowserObservation:
        payload = dict(inputs or {})
        if self._owner_thread_id == get_ident():
            return self._execute_local(action, payload)
        try:
            self._ensure_owner()
            future: Future = Future()
            self._commands.put((action, payload, future))
            timeout_seconds = max(30.0, float(payload.get("timeout_ms", 120000)) / 1000.0 + 10.0)
            return future.result(timeout=timeout_seconds)
        except Exception as exc:
            return BrowserObservation(False, action, error=str(exc))

    def _execute_local(self, action: str, inputs: Dict[str, Any]) -> BrowserObservation:
        try:
            if action in {"open_url", "navigate"}:
                url = str(inputs.get("url", "")).strip()
                if not url or urlparse(url).scheme not in {"http", "https"}:
                    return BrowserObservation(False, action, error="A valid http(s) URL is required")
                self.page.goto(url, wait_until=inputs.get("wait_until", "domcontentloaded"), timeout=int(inputs.get("timeout_ms", 30000)))
                return self._observation(action)
            if action == "back":
                self.page.go_back()
                return self._observation(action)
            if action == "forward":
                self.page.go_forward()
                return self._observation(action)
            if action == "reload":
                self.page.reload(wait_until=inputs.get("wait_until", "domcontentloaded"))
                return self._observation(action)
            if action == "click":
                self.page.locator(str(inputs["selector"])).click(timeout=int(inputs.get("timeout_ms", 30000)))
                return self._observation(action)
            if action in {"type", "fill"}:
                locator = self.page.locator(str(inputs["selector"]))
                if action == "fill":
                    locator.fill(str(inputs.get("text", "")))
                else:
                    locator.type(str(inputs.get("text", "")))
                return self._observation(action)
            if action == "select":
                selected = self.page.locator(str(inputs["selector"])).select_option(inputs.get("value", inputs.get("label")))
                return self._observation(action, {"selected": selected})
            if action == "scroll":
                amount = int(inputs.get("amount", 700))
                self.page.mouse.wheel(0, amount)
                return self._observation(action, {"amount": amount})
            if action == "read_page":
                selector = inputs.get("selector")
                text = self.page.locator(str(selector)).inner_text() if selector else self.page.locator("body").inner_text()
                return self._observation(action, text=text[: int(inputs.get("max_chars", 20000))])
            if action == "find_element":
                selector = str(inputs["selector"])
                locator = self.page.locator(selector)
                return self._observation(action, {"count": locator.count(), "selector": selector})
            if action == "wait_for_element":
                selector = str(inputs["selector"])
                self.page.locator(selector).wait_for(state=inputs.get("state", "visible"), timeout=int(inputs.get("timeout_ms", 30000)))
                return self._observation(action, {"selector": selector})
            if action == "upload_file":
                path = str(Path(inputs["path"]).expanduser().resolve())
                self.page.locator(str(inputs["selector"])).set_input_files(path)
                return self._observation(action, {"path": path})
            if action == "extract_media":
                selector = str(inputs.get("selector") or "img, a[href], meta[property='og:image']")
                limit = max(1, min(int(inputs.get("limit", 100)), 250))
                locator = self.page.locator(selector)
                count = min(locator.count(), limit)
                elements = []
                for index in range(count):
                    element = locator.nth(index)
                    try:
                        data = element.evaluate("""element => ({
                            tag: element.tagName.toLowerCase(),
                            href: element.getAttribute('href') || '',
                            src: element.getAttribute('src') || '',
                            srcset: element.getAttribute('srcset') || '',
                            data_src: element.getAttribute('data-src') || element.getAttribute('data-lazy-src') || '',
                            content: element.getAttribute('content') || '',
                            alt: element.getAttribute('alt') || '',
                            title: element.getAttribute('title') || '',
                            text: (element.innerText || '').slice(0, 240)
                        })""")
                        if isinstance(data, dict):
                            elements.append(data)
                    except Exception:
                        continue
                return self._observation(action, {"elements": elements, "count": len(elements)})
            if action == "extract_links":
                selector = str(inputs.get("selector") or "a[href]")
                limit = max(1, min(int(inputs.get("limit", 50)), 200))
                locator = self.page.locator(selector)
                count = min(locator.count(), limit)
                links = []
                for index in range(count):
                    element = locator.nth(index)
                    try:
                        data = element.evaluate("""element => ({
                            href: element.href || element.getAttribute('href') || '',
                            text: (element.innerText || element.textContent || '').trim().slice(0, 240),
                            title: element.getAttribute('title') || '',
                            rel: element.getAttribute('rel') || ''
                        })""")
                        href = str(data.get("href") or "").strip() if isinstance(data, dict) else ""
                        if href.startswith(("http://", "https://")):
                            links.append({
                                "href": href,
                                "text": str(data.get("text") or "").strip(),
                                "title": str(data.get("title") or "").strip(),
                                "rel": str(data.get("rel") or "").strip(),
                            })
                    except Exception:
                        continue
                return self._observation(action, {"links": links, "count": len(links)})
            if action == "download_file":

                with self.page.expect_download(timeout=int(inputs.get("timeout_ms", 30000))) as download_info:
                    self.page.locator(str(inputs["selector"])).click()
                download = download_info.value
                target = Path(inputs.get("path", download.suggested_filename)).expanduser().resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                download.save_as(str(target))
                return self._observation(action, {"path": str(target), "suggested_filename": download.suggested_filename})
            if action == "open_tab":
                self._ensure_started()
                page = self._context.new_page()
                self._pages.append(page)
                self._active_index = len(self._pages) - 1

                if inputs.get("url"):
                    page.goto(str(inputs["url"]), wait_until="domcontentloaded")
                return self._observation(action, {"tab_index": self._active_index})
            if action == "close_tab":
                self.page.close()
                self._pages.pop(self._active_index)
                if not self._pages:
                    self._pages = [self._context.new_page()]
                self._active_index = min(self._active_index, len(self._pages) - 1)
                return self._observation(action, {"tab_index": self._active_index})
            if action == "switch_tab":
                index = int(inputs["tab_index"])
                if index < 0 or index >= len(self._pages):
                    return BrowserObservation(False, action, error=f"Unknown tab index: {index}")
                self._active_index = index
                return self._observation(action, {"tab_index": index})
            if action == "get_current_url":
                return self._observation(action, {"url": self.page.url})
            if action == "get_page_title":
                return self._observation(action, {"title": self.page.title()})
            if action == "take_screenshot":
                path = Path(inputs.get("path", "browser-screenshot.png")).expanduser().resolve()
                path.parent.mkdir(parents=True, exist_ok=True)
                self.page.screenshot(path=str(path), full_page=bool(inputs.get("full_page", False)))
                return self._observation(action, {"path": str(path)})
            return BrowserObservation(False, action, error=f"Unsupported browser action: {action}")
        except Exception as exc:
            return BrowserObservation(False, action, error=str(exc))

    def _close_local(self) -> None:
        try:
            if self._context is not None:
                self._context.close()
        finally:
            self._context = None
            self._pages = []
            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None
            self._owner_closed = True

    def _recover_local(self) -> bool:
        """Recreate the owned Playwright context on the owner thread only."""
        self._close_local()
        self._owner_closed = False
        self._ensure_started()
        return self._context is not None and bool(self._pages)

    def recover(self) -> bool:
        if self._owner_thread_id == get_ident():
            return self._recover_local()
        self._ensure_owner()
        future: Future = Future()
        self._commands.put(("__recover__", {}, future))
        try:
            return bool(future.result(timeout=30))
        except Exception:
            return False

    def close(self) -> None:
        if self._owner_thread_id == get_ident():
            self._close_local()
            return
        owner = self._owner_thread
        if owner is None or not owner.is_alive():
            self._close_local()
            return
        future: Future = Future()
        self._commands.put(("__close__", {}, future))
        try:
            future.result(timeout=30)
        except Exception:
            pass
        owner.join(timeout=30)
        self._owner_thread = None
        self._owner_thread_id = None


__all__ = ["BrowserAdapter", "BrowserObservation", "PlaywrightBrowserAdapter"]
