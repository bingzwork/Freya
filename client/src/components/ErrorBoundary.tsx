import { Component, type ErrorInfo, type PropsWithChildren, type ReactNode } from "react";
interface State { hasError: boolean; message?: string; }
export default class ErrorBoundary extends Component<PropsWithChildren, State> {
  state: State = { hasError: false };
  static getDerivedStateFromError(error: Error): State { return { hasError: true, message: error.message }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) {}
  render(): ReactNode {
    return this.state.hasError
      ? <main style={{ padding: 32 }}>Freya is still available; the optional UI surface failed to render.{this.state.message ? ` (${this.state.message})` : ""}</main>
      : this.props.children;
  }
}
