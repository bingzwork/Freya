# Freya Avatar Engine

Freya’s avatar is a **non-critical presentation subsystem**. It observes the existing Freya `EventBus` and renders a visual representation of runtime activity. It never performs reasoning, memory retrieval, routing, capability execution, safety decisions, tool execution, or speech synthesis.

## Runtime boundary

The in-process boundary is:

```text
Freya EventBus → AvatarStateMapper → AvatarController → AvatarAdapter
                                                     ├─ browser VRM adapter
                                                     └─ test/no-op adapter
```

`AvatarRuntime` is created by `SystemInitializer` immediately after the shared `EventBus` is constructed. It subscribes to existing event patterns, exposes a read-only snapshot/UI bridge, and is disposed before the EventBus shuts down. A failure in any avatar operation is caught at the presentation boundary and cannot prevent Freya startup or interrupt the core runtime.

The browser-side `AvatarPanel` is mounted directly inside `client/src/pages/Home.tsx`. It loads `/avatars/current_avatar.vrm` automatically when the primary UI mounts, uses Three.js plus `@pixiv/three-vrm`, and keeps rendering in the same browser tab and process as the primary UI. No avatar application, second window, manual command, or separate process is required.

## State mapping

| Freya activity | Event pattern | Avatar state |
| --- | --- | --- |
| User question ingress | `conversation.question.received` | `LISTENING` |
| Question routed for reasoning | `conversation.question.routed` | `THINKING` |
| Browser actions and navigation | `browser.started`, `browser.action`, `browser.navigation` | `BROWSING` |
| Browser result reading | `browser.observation` | `READING` |
| Browser success/failure | `browser.completed`, `browser.failed` | `SUCCESS` / `ERROR` |
| Memory subsystem activity | `memory.*` | `MEMORY_RECALL` |
| Plan creation and registration | `plan.created`, `plan.registered` | `THINKING` |
| Task/progress activity | `progress.*`, `task.*`, `capability.*` | `WORKING`, `SUCCESS`, or `ERROR` |
| Verification activity | `verification.*` | `RUNNING_TESTS` |
| Research and knowledge acquisition | `research.*`, `knowledge_acquisition.*` | `SEARCHING` |
| Knowledge retrieval | `knowledge_retrieval.*` | `READING` |
| TTS/speech lifecycle | `speech.*`, `tts.*` | `SPEAKING` while active |
| Warning/error families | `warning.*`, `error.*` | `WARNING` / `ERROR` |

The mapper stores only subscription handles. It does not create a second event bus or duplicate Freya state manager. The browser UI consumes the runtime snapshot through the existing host’s `/api/avatar/events` stream when available and also supports the embedded `freya:avatar-state` browser event contract for an existing UI host.

## Controller and adapter

`AvatarController` exposes model-independent commands including state transitions, expression changes, gaze targets, speaking/lip-sync lifecycle, gestures, pose reset, visibility, updates, and disposal. `AvatarAdapter` is the only model-specific boundary. Expression resolution tries aliases and falls back to `neutral`; unsupported gestures fall back to subtle state/head movement. Missing facial expressions, unavailable WebGL, failed model loading, and adapter exceptions are all isolated from Freya.

The browser adapter uses a capped device-pixel ratio, low-power WebGL settings, no post-processing, no shadows, lightweight breathing and sway, randomized blinking, restrained gaze targets, and an adaptive loop that drops from approximately 60 FPS to approximately 30 FPS while Freya is in heavy activity states. Disposing the panel cancels the render loop, removes only the adapter-owned canvas, disposes renderer resources, and releases model materials and textures.

## Visibility and disable configuration

The UI stores the user’s preference under `freya.avatar.enabled`. The in-panel eye button hides or restores the avatar without affecting the composer, conversation workspace, or core runtime. The command-line option `--no-avatar` disables the in-process observer for a Freya startup, while `--avatar-model PATH` selects a replacement model path for the host configuration.

The avatar is enabled by default. A future settings surface can map directly to the same `SystemConfig.enable_avatar` field and `AvatarRuntime.set_enabled()` method.

## Replacing the model

Replace `client/public/avatars/current_avatar.vrm` with a user-owned VRM, or provide a model through the configured host path. The controller and state mapper do not change. The replacement should have a humanoid rig and ideally VRM expressions for neutral, happy, concerned/sad, confused, focused/serious, surprised, blink, and mouth `aa`/`A`. Models without one of these expressions continue safely through fallback behavior.

## Temporary mannequin provenance

The committed development mannequin is `client/public/avatars/current_avatar.vrm`, copied from `madjin/vrm-samples` as `vroid/stable/AvatarSample_A.vrm`. The upstream repository identifies the VRoid sample models and links to the official usage conditions. The official VRoid conditions state that the sample VRM may be used in for-profit or non-profit activity and may be redistributed, but it must not be redistributed for a fee or represented as a CC0 asset. Those conditions may change, so review the official source before distributing a future product build.

References: [VRM sample repository](https://github.com/madjin/vrm-samples), [official VRoid sample-model conditions](https://vroid.pixiv.help/hc/en-us/articles/4402394424089), and [official overview of VRoid sample licenses](https://vroid.pixiv.help/hc/en-us/articles/4402614652569).

## Verification

The focused Python suite is `tests/test_avatar_engine.py`. It covers EventBus subscriptions and unsubscribe behavior, major state mappings, expression fallback, speech and mouth reset lifecycle, runtime start/stop, UI snapshot streaming, disabled startup, and adapter failure isolation. The client is checked with `./node_modules/.bin/tsc -b` and `./node_modules/.bin/vite build`. Manual browser verification confirms the actual VRM canvas is visible in the primary workspace on normal load, hide/show disposes and recreates the renderer in place, and a `conversation.question.routed` presentation event changes the visible state to `Thinking` without replacing the model.
