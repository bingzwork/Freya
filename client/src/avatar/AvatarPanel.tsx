import { useEffect, useRef, useState } from "react";
import { Eye, EyeOff, RotateCcw } from "lucide-react";
import {
  DEFAULT_AVATAR_SNAPSHOT,
  normalizeAvatarSnapshot,
  type AvatarSnapshot,
} from "./avatar-controller";
import type { VrmAvatarAdapter } from "./vrm-adapter";

const MODEL_URL = "/avatars/current_avatar.vrm";
const AVATAR_EVENT_NAME = "freya:avatar-state";

interface AvatarPanelProps {
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
}

function titleCaseState(state: string): string {
  return state.toLowerCase().replace(/_/g, " ").replace(/(^| )([a-z])/g, (_match: string, prefix: string, letter: string) => `${prefix}${letter.toUpperCase()}`);
}

export default function AvatarPanel({ enabled, onEnabledChange }: AvatarPanelProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const adapterRef = useRef<VrmAvatarAdapter | null>(null);
  const [snapshot, setSnapshot] = useState<AvatarSnapshot>(DEFAULT_AVATAR_SNAPSHOT);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled || !mountRef.current) {
      adapterRef.current?.dispose();
      adapterRef.current = null;
      return;
    }

    let disposed = false;
    let mountedAdapter: VrmAvatarAdapter | null = null;
    const mount = mountRef.current;
    setLoadError(null);
    setSnapshot((current) => ({ ...current, modelStatus: "loading", visible: true }));

    const handleRuntimeEvent = (event: Event) => {
      const detail = (event as CustomEvent<unknown>).detail;
      const next = normalizeAvatarSnapshot(detail);
      setSnapshot(next);
      adapterRef.current?.setState(next.state);
      adapterRef.current?.setExpression(next.expression, next.expressionIntensity);
      adapterRef.current?.setGazeTarget(next.gazeTarget);
      adapterRef.current?.setSpeaking(next.speaking);
      adapterRef.current?.updateLipSync(next.mouthOpen);
    };

    window.addEventListener(AVATAR_EVENT_NAME, handleRuntimeEvent);
    let source: EventSource | null = null;
    try {
      source = new EventSource("/api/avatar/events");
      source.onmessage = handleRuntimeEvent;
      source.onerror = () => source?.close();
    } catch {
      source = null;
    }

    const load = async () => {
      try {
        const { VrmAvatarAdapter: VrmAvatarAdapterModule } = await import("./vrm-adapter");
        const adapter = await VrmAvatarAdapterModule.create(mount, MODEL_URL);
        if (disposed) {
          adapter.dispose();
          return;
        }
        mountedAdapter = adapter;
        adapterRef.current = adapter;
        setSnapshot((current) => ({ ...current, modelStatus: "ready", visible: true }));
      } catch (error) {
        if (disposed) return;
        setLoadError(error instanceof Error ? error.message : "The VRM mannequin could not be loaded.");
        setSnapshot((current) => ({ ...current, modelStatus: "error", visible: true, error: "VRM unavailable" }));
      }
    };
    void load();

    return () => {
      disposed = true;
      window.removeEventListener(AVATAR_EVENT_NAME, handleRuntimeEvent);
      source?.close();
      mountedAdapter?.dispose();
      if (adapterRef.current === mountedAdapter) adapterRef.current = null;
    };
  }, [enabled]);

  useEffect(() => {
    const heavy = ["THINKING", "WORKING", "CODING", "RUNNING_TESTS", "SEARCHING", "BROWSING"].includes(snapshot.state);
    adapterRef.current?.setHeavyActivity(heavy);
  }, [snapshot.state]);

  if (!enabled) {
    return (
      <button className="avatar-enable-chip" type="button" onClick={() => onEnabledChange(true)}>
        <Eye size={14} /> Show avatar
      </button>
    );
  }

  return (
    <aside className={`avatar-panel avatar-panel--${snapshot.modelStatus}`} aria-label="Freya avatar">
      <div className="avatar-panel__header">
        <div>
          <span className="avatar-panel__eyebrow">Freya avatar</span>
          <strong>{titleCaseState(snapshot.state)}</strong>
        </div>
        <button className="avatar-panel__icon" type="button" onClick={() => onEnabledChange(false)} aria-label="Hide avatar" title="Hide avatar">
          <EyeOff size={15} />
        </button>
      </div>
      <div className="avatar-panel__viewport">
        <div ref={mountRef} className="avatar-render-target" />
        {snapshot.modelStatus !== "ready" && (
          <div className="avatar-fallback" role="status">
            <div className="avatar-fallback__head"><span className="avatar-fallback__eye avatar-fallback__eye--left" /><span className="avatar-fallback__eye avatar-fallback__eye--right" /></div>
            <div className="avatar-fallback__body" />
            <span>{snapshot.modelStatus === "loading" ? "Loading mannequin…" : "Avatar unavailable"}</span>
          </div>
        )}
      </div>
      <div className="avatar-panel__footer">
        <span className={`avatar-state-dot avatar-state-dot--${snapshot.state.toLowerCase()}`} />
        <span>{snapshot.lastEvent ? snapshot.lastEvent : "Observing Freya runtime"}</span>
        {loadError && <button className="avatar-retry" type="button" onClick={() => onEnabledChange(false)} title="Reload avatar"><RotateCcw size={12} /></button>}
      </div>
    </aside>
  );
}
