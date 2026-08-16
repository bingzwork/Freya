export const AVATAR_STATES = [
  "IDLE", "LISTENING", "THINKING", "WORKING", "SPEAKING", "SUCCESS", "WARNING", "ERROR",
  "SEARCHING", "READING", "MEMORY_RECALL", "CODING", "RUNNING_TESTS", "BROWSING", "WAITING",
  "CONFUSED", "EXCITED", "GESTURING",
] as const;

export type AvatarState = (typeof AVATAR_STATES)[number];
export type AvatarExpression = "neutral" | "happy" | "concerned" | "confused" | "focused" | "surprised" | "excited";
export type AvatarGazeTarget = "USER" | "CHAT_PANEL" | "RESULTS_PANEL" | "CODE_PANEL" | "BROWSER_PANEL" | "NOTIFICATION" | "CUSTOM_POINT";

export interface AvatarSnapshot {
  state: AvatarState;
  expression: AvatarExpression;
  expressionIntensity: number;
  gazeTarget: AvatarGazeTarget;
  speaking: boolean;
  mouthOpen: number;
  visible: boolean;
  modelStatus: "loading" | "ready" | "unavailable" | "error";
  lastEvent?: string;
  error?: string;
}

export const DEFAULT_AVATAR_SNAPSHOT: AvatarSnapshot = {
  state: "IDLE",
  expression: "neutral",
  expressionIntensity: 1,
  gazeTarget: "USER",
  speaking: false,
  mouthOpen: 0,
  visible: true,
  modelStatus: "loading",
};

export function normalizeAvatarSnapshot(value: unknown): AvatarSnapshot {
  const input = (value && typeof value === "object" ? value : {}) as Record<string, unknown>;
  const state = AVATAR_STATES.includes(input.state as AvatarState) ? input.state as AvatarState : "IDLE";
  const expression = typeof input.expression === "string" ? input.expression as AvatarExpression : "neutral";
  const gazeTarget = typeof input.gaze_target === "string"
    ? input.gaze_target as AvatarGazeTarget
    : (typeof input.gazeTarget === "string" ? input.gazeTarget as AvatarGazeTarget : "USER");
  return {
    ...DEFAULT_AVATAR_SNAPSHOT,
    ...input,
    state,
    expression,
    gazeTarget,
    expressionIntensity: Number(input.expression_intensity ?? input.expressionIntensity ?? 1),
    mouthOpen: Number(input.mouth_open ?? input.mouthOpen ?? 0),
    speaking: Boolean(input.speaking),
    visible: input.visible !== false,
    modelStatus: (input.model_status ?? input.modelStatus ?? "loading") as AvatarSnapshot["modelStatus"],
    lastEvent: typeof input.last_event === "string" ? input.last_event : typeof input.lastEvent === "string" ? input.lastEvent : undefined,
    error: typeof input.error === "string" ? input.error : undefined,
  };
}

export interface AvatarAdapter {
  setState(state: AvatarState): void;
  setExpression(expression: AvatarExpression, intensity: number): void;
  setGazeTarget(target: AvatarGazeTarget): void;
  setSpeaking(speaking: boolean): void;
  updateLipSync(openness: number): void;
  playGesture(name: string): boolean;
  update(deltaSeconds: number): void;
  dispose(): void;
}
