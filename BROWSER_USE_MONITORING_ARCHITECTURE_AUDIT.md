# Browser Use Monitoring Architecture Audit

## Scope and sources

Pasted25 required studying the current Browser Use source before implementation. The audit used the current public repository and source tree, especially [`CLAUDE.md`](https://github.com/browser-use/browser-use/blob/main/CLAUDE.md), [`browser_use/browser/session.py`](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/session.py), [`watchdog_base.py`](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/watchdog_base.py), [`events.py`](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/events.py), and [`dom_watchdog.py`](https://github.com/browser-use/browser-use/blob/main/browser_use/browser/watchdogs/dom_watchdog.py).

## Browser Use modules and responsibilities

| Browser Use source concept | Problem addressed | Architectural observation |
|---|---|---|
| `BrowserSession` | Canonical browser lifecycle, CDP connection, target/session state, reconnection, tab focus, watchdog ownership | Browser lifecycle is owned by one session; multiple monitors coordinate through its event bus. |
| `BaseWatchdog` | Consistent monitor lifecycle and event-handler registration | Watchdogs declare event responsibilities, attach handlers to the session bus, guard disconnected CDP state, and detach/clean up. |
| `events.py` | Typed communication between agent/tools/session/watchdogs | Browser actions, navigation, tabs, state requests, downloads, errors, and lifecycle transitions are typed events rather than raw log messages. |
| `DOMWatchdog` | DOM tree construction, selector maps, screenshots, page stability, pending-network visibility | DOM observation is a specialized service that owns cached state and refreshes it on browser-state requests. |
| Downloads/Popups/Security/CAPTCHA watchdogs | Independent download, popup, security/challenge, and access states | Independent failure domains are not collapsed into one global watchdog. |
| `SessionManager` and target lifecycle events | Multi-tab and target attachment/detachment | Target lifecycle state is tracked per target, allowing tab state and CDP sessions to recover without losing the canonical browser owner. |

Browser Use’s current design also has explicit lifecycle events for start, stop, reconnecting, reconnected, browser errors, navigation, tab creation/closure, and downloads. The watchdog base uses a circuit-breaker style guard when CDP is disconnected and bounded reconnection waits rather than allowing every handler to hang indefinitely.

## Patterns Freya should adopt

Freya should adopt the separation of browser-specific observations from the general System Watchdog; typed browser operational events; observation snapshots produced on the canonical owner thread; bounded, single-attempt browser recovery; explicit monitor start/stop; safe challenge classification; tab/popup transition reporting; DOM-state invalidation; verified download completion; and lightweight resource-pressure signals.

## Patterns deliberately rejected

Freya should not copy Browser Use’s full agent loop, cloud browser services, CDP abstraction, async event-bus library, DOM tree implementation, CAPTCHA solving, stealth/circumvention behavior, or browser-specific controller hierarchy. Freya already owns `BrowserCapability`, `PlaywrightBrowserAdapter`, `CapabilityRouter`, `SafetyGate`, `BackgroundJobService`, `EventBus`, `System Watchdog`, and the owner-thread command queue. Replacing any of those would create duplicate architecture and violate Freya’s safety and lifecycle contracts.

## Freya before Pasted25

The production flow was:

```text
CapabilityRouter
  -> BrowserCapability
      -> SafetyGate for consequential actions
      -> PlaywrightBrowserAdapter
          -> dedicated freya-playwright-owner thread
              -> Playwright context/pages
```

Freya already emitted `browser.started`, `browser.action`, `browser.navigation`, `browser.observation`, `browser.completed`, and `browser.failed`, and it already kept all Playwright calls on the owner thread. However, failures were primarily represented as generic `BrowserObservation.error` strings. There was no browser-owned classifier for session loss, navigation timeout, DOM invalidation, popup/tab transitions, challenge state, verified download state, or resource pressure.

## Freya after Pasted25

The flow remains owner-thread-first:

```text
CapabilityRouter
  -> BrowserCapability
      -> existing SafetyGate
      -> BrowserMonitorCoordinator
          -> session/crash classification + bounded recovery
          -> navigation classification
          -> page/DOM token invalidation
          -> popup/tab transition classification
          -> challenge/login/access classification
          -> download verification state
          -> lightweight resource pressure
      -> existing PlaywrightBrowserAdapter
          -> dedicated freya-playwright-owner thread
              -> Playwright context/pages
```

`BrowserMonitorCoordinator` never performs direct Playwright calls. It consumes the observation dictionary generated by the owner thread and invokes only the adapter’s explicit `recover()` boundary. The adapter’s recovery command is serialized through the same owner queue, so recovery cannot switch to a random worker thread.

## Event and lifecycle behavior

When the first browser action starts, the coordinator emits `BROWSER_MONITORS_STARTED`. Each owner-thread observation is classified and attached to the normal browser observation payload under `monitor_events` and `browser_state`. Browser-specific events are published through Freya’s existing `EventBus` under `browser.monitor.*`. Closing or replacing the adapter stops the monitor coordinator, clears previous state, and prevents listener accumulation. Recovery is bounded to one attempt per monitor lifecycle; successful recovery emits `SESSION_RECOVERED`, and unsafe or failed recovery emits `SESSION_RECOVERY_FAILED` or `SESSION_LOST`.

Navigation failures are classified as `NAVIGATION_TIMEOUT`, `REDIRECT_LOOP`, or `NAVIGATION_FAILED`; successful navigations emit `NAVIGATION_COMPLETED`. Changes in the owner-thread state token invalidate prior page observations and emit `DOM_INVALIDATED`. Page-count increases/decreases emit `POPUP_OPENED` and `TAB_CLOSED`. Challenge markers produce `BLOCKED_BY_CHALLENGE` without attempting bypass. Download actions produce `DOWNLOAD_COMPLETED` only when the adapter returned a verified saved path; failures produce `DOWNLOAD_FAILED`. Exceeding a conservative tab-count bound produces `RESOURCE_PRESSURE` without automatic process killing.

## Ownership boundary

| Concern | Owner |
|---|---|
| Freya services, workers, jobs, global health, broad recovery | Existing System Watchdog |
| Browser process/context/session health | BrowserCapability and BrowserMonitorCoordinator |
| Playwright calls, pages, tabs, context recreation | Existing PlaywrightBrowserAdapter owner thread |
| Consequential authorization | Existing SafetyGate |
| Research fallback and source selection | Existing ResearchCapability |
| Browser operational event transport | Existing EventBus |

## Verification status

Permanent tests cover monitor lifecycle, navigation timeout, DOM invalidation, popup/tab transitions, challenge classification, download states, resource pressure, bounded session recovery, SafetyGate preservation, and owner-thread isolation. Existing research, shopping, image, routing, and browser regressions must be rerun before commit. Real Chromium acceptance is required separately; when Chromium or Playwright is unavailable, the limitation must be reported rather than inferred away.

## References

[1]: https://github.com/browser-use/browser-use/blob/main/CLAUDE.md "Browser Use current architecture guidance"
[2]: https://github.com/browser-use/browser-use/blob/main/browser_use/browser/session.py "Browser Use BrowserSession source"
[3]: https://github.com/browser-use/browser-use/blob/main/browser_use/browser/watchdog_base.py "Browser Use BaseWatchdog source"
[4]: https://github.com/browser-use/browser-use/blob/main/browser_use/browser/events.py "Browser Use browser event definitions"
[5]: https://github.com/browser-use/browser-use/blob/main/browser_use/browser/watchdogs/dom_watchdog.py "Browser Use DOMWatchdog source"
