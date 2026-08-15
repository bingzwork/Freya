# Freya Capability Audit

This audit records the ten requested areas against the repository state inspected before the extension work. The implementation uses the existing `CapabilityRegistry` → `CapabilityRegistrationBridge` → `CapabilityRouter` → `ToolManager` path; it does not introduce a second registry or routing framework.

| Capability | Before | After | Main implementation | Tests |
|---|---|---|---|---|
| Computer / Desktop Control | 🟡 PARTIAL: browser and automation surfaces existed, but no provider-neutral desktop contract | 🟢 MOSTLY COMPLETE: guarded provider contract and local open implementation; GUI actions remain injectable | `ComputerCapability`, `DesktopProvider`, `LocalDesktopProvider` | `test_extended_capabilities.py` |
| Audio + Podcast Processing | ⚪ NOT IMPLEMENTED as a callable capability | 🟢 MOSTLY COMPLETE: FFmpeg-backed metadata/transform primitives with unavailable-safe behavior | `MediaCapability`, `FFmpegProvider` | `test_extended_capabilities.py` |
| Video Editing | ⚪ NOT IMPLEMENTED as a callable capability | 🟢 MOSTLY COMPLETE: metadata, trim, audio, crop, resize, captions, join, and export actions | `MediaCapability`, `FFmpegProvider` | `test_extended_capabilities.py` |
| Image Generation + Editing | 🟡 PARTIAL: existing vision/OCR capability | 🟢 MOSTLY COMPLETE: provider contract, Pillow edits, metadata, and injectable generation | `ImageCapability`, `ImageProvider`, `PillowImageProvider` | `test_extended_capabilities.py` |
| Email + Calendar | ⚪ NOT IMPLEMENTED as provider-neutral callable capabilities | 🟡 PARTIAL: complete guarded adapter contracts; credentials/providers remain optional | `ExternalProviderCapability` | deterministic unavailable-provider behavior |
| Contacts / CRM | ⚪ NOT IMPLEMENTED as a provider-neutral callable capability | 🟡 PARTIAL: reusable contacts/CRM action contract with guarded mutations | `ExternalProviderCapability` | deterministic unavailable-provider behavior |
| Database | 🟡 PARTIAL: SQLite existed in storage subsystems, without a callable guarded database surface | 🟢 MOSTLY COMPLETE: SQLite connect, inspect, schema, parameterized query, and approval-gated writes | `DatabaseCapability` | query and approval tests |
| Voice | 🟡 PARTIAL: speech-oriented formatting existed, but no STT/TTS capability boundary | 🟡 PARTIAL: provider-neutral transcribe/speak contract; provider remains injectable | `VoiceCapability` | deterministic unavailable-provider behavior |
| Data Analysis | 🟡 PARTIAL: file/document and execution infrastructure existed | 🟢 MOSTLY COMPLETE: CSV/JSON summary, filtering, grouping, correlation, and chart extension point | `DataAnalysisCapability` | deterministic CSV analysis test |
| Smart Home / IoT | ⚪ NOT IMPLEMENTED | 🟡 PARTIAL: provider-neutral discovery/state/scenes contract with approval-gated mutations | `IoTCapability` | fail-closed mutation test |

## Safety and dependency decisions

Mutating actions fail closed unless the dispatch context contains an explicit approval marker. Production dispatch still remains subject to Freya's existing `SafetyGate` and approval flow. Optional providers, credentials, GUI libraries, FFmpeg, `ffprobe`, and hardware are not imported or downloaded at startup; unavailable integrations return deterministic errors.

The media layer uses safe argument-list subprocess calls and detects FFmpeg/ffprobe cleanly. The database layer uses SQLite first and parameter tuples for SQL values. Provider-specific email, calendar, contacts/CRM, voice, and IoT implementations can be injected without modifying generic routing.
