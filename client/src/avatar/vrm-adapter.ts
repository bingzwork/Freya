import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin } from "@pixiv/three-vrm";
import type {
  AvatarAdapter,
  AvatarExpression,
  AvatarGazeTarget,
  AvatarState,
} from "./avatar-controller";

const EXPRESSION_ALIASES: Record<AvatarExpression, string[]> = {
  neutral: ["neutral", "Neutral"],
  happy: ["happy", "joy", "Happy"],
  concerned: ["concerned", "sad", "Sad"],
  confused: ["confused", "Confused"],
  focused: ["focused", "serious", "Neutral"],
  surprised: ["surprised", "Surprised"],
  excited: ["excited", "happy", "joy", "Happy"],
};

const GAZE_POINTS: Record<AvatarGazeTarget, [number, number, number]> = {
  USER: [0, 1.45, 1.7],
  CHAT_PANEL: [-0.25, 1.35, 1.5],
  RESULTS_PANEL: [0.35, 1.25, 1.5],
  CODE_PANEL: [0.55, 1.15, 1.4],
  BROWSER_PANEL: [0.65, 1.3, 1.5],
  NOTIFICATION: [0, 1.7, 1.3],
  CUSTOM_POINT: [0, 1.45, 1.7],
};

export interface VrmLoadResult {
  renderer: any;
  vrm: any;
}

export class VrmAvatarAdapter implements AvatarAdapter {
  private THREE: any;
  private renderer: any;
  private vrm: any;
  private gazeObject: any;
  private root: HTMLElement;
  private canvas: HTMLCanvasElement | null = null;
  private raf = 0;
  private lastTime = 0;
  private elapsed = 0;
  private heavyActivity = false;
  private speaking = false;
  private currentState: AvatarState = "IDLE";
  private disposed = false;
  private blinkAt = 2.4;
  private blinkRemaining = 0;
  private gestureUntil = 0;
  private gestureName = "";

  public modelStatus: "loading" | "ready" | "unavailable" | "error" = "loading";

  private constructor(root: HTMLElement) {
    this.root = root;
  }

  static async create(root: HTMLElement, modelUrl: string): Promise<VrmAvatarAdapter> {
    const adapter = new VrmAvatarAdapter(root);
    await adapter.load(modelUrl);
    return adapter;
  }

  private async load(modelUrl: string): Promise<void> {
    try {
      this.THREE = THREE;

      const canvas = document.createElement("canvas");
      canvas.setAttribute("aria-label", "Freya avatar renderer");
      canvas.className = "avatar-canvas";
      this.canvas = canvas;
      this.root.appendChild(canvas);
      const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: false, powerPreference: "low-power" });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
      renderer.setSize(this.root.clientWidth || 320, this.root.clientHeight || 360, false);
      renderer.setClearColor(0x000000, 0);
      this.renderer = renderer;

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(22, 1, 0.1, 100);
      camera.position.set(0, 1.35, 3.6);
      camera.lookAt(0, 1.3, 0);
      scene.add(new THREE.HemisphereLight(0xbfc8ff, 0x101228, 1.35));
      const key = new THREE.DirectionalLight(0xb7a9ff, 1.1);
      key.position.set(-1.5, 2.5, 3);
      scene.add(key);

      const loader = new GLTFLoader();
      loader.register((parser: any) => new VRMLoaderPlugin(parser));
      const gltf = await loader.loadAsync(modelUrl);
      this.vrm = gltf.userData.vrm;
      if (!this.vrm) throw new Error("VRM loader returned no avatar model");
      this.vrm.scene.rotation.y = Math.PI;
      scene.add(this.vrm.scene);
      this.gazeObject = new THREE.Object3D();
      scene.add(this.gazeObject);
      this.vrm.lookAt?.target && (this.vrm.lookAt.target = this.gazeObject);
      this.root.dataset.avatarModel = "ready";
      this.modelStatus = "ready";
      this.startRenderLoop(scene, camera);
      this.resize(scene, camera);
      window.addEventListener("resize", () => this.resize(scene, camera), { passive: true });
    } catch (error) {
      this.modelStatus = "error";
      this.root.dataset.avatarModel = "error";
      throw error;
    }
  }

  setState(state: AvatarState): void {
    this.currentState = state;
  }

  setExpression(expression: AvatarExpression, intensity: number): void {
    const manager = this.vrm?.expressionManager;
    if (!manager) return;
    const names = Object.keys(manager.expressionMap || {});
    const requested = EXPRESSION_ALIASES[expression] || ["neutral"];
    const resolved = requested.find((name) => names.includes(name) || names.includes(name.toLowerCase())) || names.find((name) => name.toLowerCase() === "neutral");
    if (!resolved) return;
    for (const name of names) manager.setValue(name, 0);
    manager.setValue(resolved, Math.max(0, Math.min(1, intensity)));
  }

  setGazeTarget(target: AvatarGazeTarget): void {
    if (!this.gazeObject || !this.THREE) return;
    const [x, y, z] = GAZE_POINTS[target] || GAZE_POINTS.USER;
    this.gazeObject.position.set(x, y, z);
  }

  setSpeaking(speaking: boolean): void {
    this.speaking = speaking;
    if (!speaking) this.updateLipSync(0);
  }

  updateLipSync(openness: number): void {
    const manager = this.vrm?.expressionManager;
    if (!manager) return;
    const names = Object.keys(manager.expressionMap || {});
    const mouth = names.find((name) => ["aa", "a", "A"].includes(name)) || names.find((name) => name.toLowerCase() === "aa");
    if (mouth) manager.setValue(mouth, this.speaking ? Math.max(0, Math.min(1, openness)) : 0);
  }

  playGesture(name: string): boolean {
    const supported = ["NOD", "ACKNOWLEDGE", "CELEBRATE_SUBTLE"].includes(name);
    this.gestureName = name;
    this.gestureUntil = this.elapsed + (supported ? 0.8 : 0.45);
    return supported;
  }

  update(deltaSeconds: number): void {
    if (this.disposed || !this.vrm) return;
    this.elapsed += deltaSeconds;
    const scene = this.vrm.scene;
    const breathing = Math.sin(this.elapsed * 1.4) * 0.006;
    const sway = Math.sin(this.elapsed * 0.55) * 0.012;
    scene.position.y = breathing;
    scene.rotation.z = sway;
    if (this.gestureUntil > this.elapsed) {
      const nod = Math.sin((this.elapsed - (this.gestureUntil - 0.8)) * Math.PI * 3) * 0.035;
      scene.rotation.x = this.gestureName === "NOD" || this.gestureName === "ACKNOWLEDGE" ? nod : 0;
    } else {
      scene.rotation.x = 0;
    }
    this.updateBlink(deltaSeconds);
    this.vrm.update(deltaSeconds);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    if (this.raf) cancelAnimationFrame(this.raf);
    this.renderer?.dispose?.();
    this.renderer?.renderLists?.dispose?.();
    this.vrm?.scene?.traverse?.((object: any) => {
      object.geometry?.dispose?.();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.filter(Boolean).forEach((material: any) => {
        Object.values(material).forEach((value: any) => value?.isTexture && value.dispose?.());
        material.dispose?.();
      });
    });
    if (this.canvas?.parentElement === this.root) this.canvas.remove();
    this.canvas = null;
  }

  setHeavyActivity(heavy: boolean): void {
    this.heavyActivity = heavy;
  }

  private startRenderLoop(scene: any, camera: any): void {
    const frame = (time: number) => {
      if (this.disposed) return;
      const delta = Math.min(0.1, this.lastTime ? (time - this.lastTime) / 1000 : 1 / 60);
      this.lastTime = time;
      this.update(delta);
      this.renderer.render(scene, camera);
      this.raf = window.setTimeout(() => requestAnimationFrame(frame), this.heavyActivity ? 33 : 16);
    };
    this.raf = requestAnimationFrame(frame);
  }

  private resize(scene: any, camera: any): void {
    if (!this.renderer) return;
    const width = Math.max(1, this.root.clientWidth);
    const height = Math.max(1, this.root.clientHeight);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  private updateBlink(deltaSeconds: number): void {
    const manager = this.vrm?.expressionManager;
    if (!manager) return;
    this.blinkAt -= deltaSeconds;
    if (this.blinkAt <= 0 && this.blinkRemaining <= 0) this.blinkRemaining = 0.16;
    if (this.blinkRemaining > 0) {
      this.blinkRemaining -= deltaSeconds;
      const value = this.blinkRemaining < 0.08 ? this.blinkRemaining / 0.08 : 1;
      const names = Object.keys(manager.expressionMap || {});
      const blink = names.find((name) => name.toLowerCase() === "blink");
      if (blink) manager.setValue(blink, Math.max(0, Math.min(1, value)));
      if (this.blinkRemaining <= 0) this.blinkAt = 2.5 + Math.random() * 3.5;
    }
  }
}
