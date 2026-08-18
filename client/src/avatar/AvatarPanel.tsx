import { useEffect, useRef, useState } from "react";
import { RotateCcw } from "lucide-react";
import { DEFAULT_AVATAR_SNAPSHOT, normalizeAvatarSnapshot, type AvatarSnapshot } from "./avatar-controller";
import type { VrmAvatarAdapter } from "./vrm-adapter";

const MODEL_URL = "/avatars/current_avatar.vrm";
const AVATAR_EVENT_NAME = "freya:avatar-state";

function titleCaseState(state: string): string {
  return state.toLowerCase().replace(/_/g, " ").replace(/(^| )([a-z])/g, (_match, prefix, letter) => prefix + letter.toUpperCase());
}

export default function AvatarPanel() {
  const mountRef = useRef<HTMLDivElement>(null);
  const adapterRef = useRef<VrmAvatarAdapter | null>(null);
  const [snapshot, setSnapshot] = useState<AvatarSnapshot>(DEFAULT_AVATAR_SNAPSHOT);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const apply = (value: unknown) => {
      const next = normalizeAvatarSnapshot(value);
      setSnapshot(next);
      const adapter = adapterRef.current;
      if (!adapter) return;
      adapter.setState(next.semanticState);
      adapter.setLocomotion(next.locomotionState);
      adapter.setGazeTarget(next.gazeTarget);
      adapter.setSpeaking(next.speaking);
      adapter.updateLipSync(next.mouthOpen);
      adapter.setTargetPosition(next.targetPosition);
      if (next.action) adapter.playGesture(next.action);
      (adapter as any).setHeavyActivity?.(["THINKING", "WORKING", "RUNNING_TESTS", "SEARCHING", "READING"].includes(next.semanticState));
    };

    const onCustom = (event: Event) => apply((event as CustomEvent).detail);
    window.addEventListener(AVATAR_EVENT_NAME, onCustom);
    const source = new EventSource("/api/avatar-events");
    source.onmessage = (event) => {
      try { apply(JSON.parse(event.data)); } catch { /* keep renderer alive on malformed data */ }
    };
    return () => {
      window.removeEventListener(AVATAR_EVENT_NAME, onCustom);
      source.close();
    };
  }, [reloadKey]);

  useEffect(() => {
    let cancelled = false;
    const mount = async () => {
      if (!mountRef.current) return;
      setSnapshot((current) => ({ ...current, modelStatus: "loading" }));
      try {
        const { VrmAvatarAdapter: Adapter } = await import("./vrm-adapter");
        const adapter = await Adapter.create(mountRef.current, MODEL_URL);
        if (cancelled) { adapter.dispose(); return; }
        adapterRef.current = adapter;
        setSnapshot((current) => ({ ...current, modelStatus: adapter.modelStatus }));
      } catch (error) {
        if (!cancelled) setSnapshot((current) => ({ ...current, modelStatus: "error", error: error instanceof Error ? error.message : "Avatar failed to load" }));
      }
    };
    mount();
    return () => { cancelled = true; adapterRef.current?.dispose(); adapterRef.current = null; };
  }, [reloadKey]);

  const retry = () => setReloadKey((value) => value + 1);
  return <div className="avatar-panel">
    <div className="avatar-stage" ref={mountRef} aria-label="Freya avatar world" />
    <div className="avatar-overlay"><div className="avatar-overlay__footer"><span className={`avatar-state-dot avatar-state-dot--${snapshot.semanticState}`} /><strong>{titleCaseState(snapshot.semanticState)}</strong>{snapshot.locomotionState !== "STANDING" && <span>· {titleCaseState(snapshot.locomotionState)}</span>}<button className="avatar-toggle" type="button" aria-label="Reload avatar" title="Reload avatar" onClick={retry}><RotateCcw size={13} /></button></div></div>
    {snapshot.modelStatus !== "ready" && <div className="avatar-fallback"><div className="avatar-fallback__head"><span>{snapshot.modelStatus === "loading" ? "Loading Freya…" : "Freya could not load"}</span>{snapshot.modelStatus === "error" && <button className="avatar-retry" type="button" onClick={retry}><RotateCcw size={13} /> Retry</button>}</div></div>}
  </div>;
}
