from __future__ import annotations

import functools
import http.server
import shutil
import threading
from pathlib import Path

import pytest

from app.browser.adapter import PlaywrightBrowserAdapter


@pytest.mark.skipif(shutil.which("chromium") is None, reason="Chromium executable is unavailable")
def test_playwright_adapter_navigates_reads_and_interacts(tmp_path: Path):
    (tmp_path / "index.html").write_text(
        """<!doctype html><html><body><button id='next' onclick=\"document.body.dataset.clicked='yes'; document.querySelector('#message').textContent='Clicked'\">Go</button><p id='message'>Ready</p></body></html>""",
        encoding="utf-8",
    )
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    adapter = PlaywrightBrowserAdapter(
        profile_dir=tmp_path / "profile",
        headless=True,
        executable_path=shutil.which("chromium"),
    )
    try:
        opened = adapter.execute("open_url", {"url": f"http://127.0.0.1:{server.server_port}/index.html"})
        assert opened.success is True
        page = adapter.execute("read_page", {"selector": "body"})
        assert page.success is True
        assert "Ready" in page.text
        clicked = adapter.execute("click", {"selector": "#next"})
        assert clicked.success is True
        updated = adapter.execute("read_page", {"selector": "#message"})
        assert updated.text == "Clicked"
    finally:
        adapter.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
