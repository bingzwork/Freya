"""
Freya - Canonical Application Entry Point.

Thin launcher that delegates to SystemInitializer for system construction.
Provides interactive chat mode or single-shot execution.
"""

import sys
import json
import signal
import argparse
from pathlib import Path

from app.core.initializer import SystemInitializer, SystemConfig
from app.core.logger import logger


class FreyaApp:
    """Main application wrapper for Freya."""

    def __init__(self, workspace: Path, config: SystemConfig = None):
        self.workspace = workspace
        self.config = config or SystemConfig()
        self.initializer = SystemInitializer(workspace, config)
        self.system = None
        self._running = False

    def start(self) -> None:
        """Initialize and start all subsystems."""
        logger.info("[FreyaApp] Starting Freya...")
        self.system = self.initializer.initialize()
        self._running = True
        logger.info("[FreyaApp] Freya started successfully")

    def shutdown(self) -> None:
        """Gracefully shutdown all subsystems."""
        if self.system:
            logger.info("[FreyaApp] Shutting down Freya...")
            self.initializer.shutdown(self.system)
            self._running = False
            logger.info("[FreyaApp] Shutdown complete")

    def chat(self, user_input: str) -> str:
        """Process a single chat message."""
        if not self.system:
            raise RuntimeError("System not initialized. Call start() first.")
        return self.system.facade.chat(user_input)

    def execute_task(self, task: str, allow_mutations: bool = True) -> str:
        """Execute an engineering task directly."""
        if not self.system:
            raise RuntimeError("System not initialized. Call start() first.")
        return self.system.facade.execute_task(task, allow_mutations)

    def run_interactive(self) -> None:
        """Run interactive chat loop."""
        print("Freya is ready. Type 'exit', 'quit', or Ctrl+C to exit.")
        print("-" * 50)

        while self._running:
            try:
                user_input = input("\n> ").strip()
                if not user_input:
                    continue
                if user_input.lower() in ('exit', 'quit'):
                    break

                response = self.chat(user_input)
                print(f"\n{response}")

            except KeyboardInterrupt:
                print("\n\nInterrupted. Shutting down...")
                break
            except EOFError:
                break
            except Exception as e:
                logger.error(f"Error processing input: {e}")
                print(f"\nError: {e}")

    def run_single_shot(self, user_input: str) -> str:
        """Process a single input and return response (for scripting)."""
        return self.chat(user_input)

    def get_health_surface(self) -> dict:
        """Return the read-only production liveness and readiness surface."""
        if self.system and self.system.infra and self.system.infra.observability:
            return self.system.infra.observability.get_health_surface(
                initialized=self._running,
            )
        return {
            "liveness": {"status": "alive", "alive": True},
            "readiness": {
                "status": "not_ready",
                "ready": False,
                "initialization": {"completed": False},
                "dependencies": [],
                "reasons": ["initialization_incomplete"],
            },
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Freya - Autonomous Software Engineering Agent")
    parser.add_argument(
        "input",
        nargs="?",
        help="Single-shot input (if omitted, runs interactive mode)",
    )
    parser.add_argument(
        "--workspace",
        "-w",
        type=Path,
        default=Path.cwd(),
        help="Workspace path (default: current directory)",
    )
    parser.add_argument(
        "--no-autonomy",
        action="store_true",
        help="Disable autonomy manager",
    )
    parser.add_argument(
        "--no-orchestrator",
        action="store_true",
        help="Disable workflow orchestrator",
    )
    parser.add_argument(
        "--no-file-watcher",
        action="store_true",
        help="Disable file watcher",
    )
    parser.add_argument(
        "--no-observability",
        action="store_true",
        help="Disable observability hub",
    )
    parser.add_argument(
        "--execute",
        "-e",
        action="store_true",
        help="Execute as engineering task (bypass router)",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Print the read-only liveness and readiness snapshot as JSON",
    )
    parser.add_argument(
        "--readiness",
        action="store_true",
        help="Print the read-only readiness snapshot as JSON and fail when unready",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Build config from CLI args
    config = SystemConfig(
        enable_autonomy=not args.no_autonomy,
        enable_orchestrator=not args.no_orchestrator,
        enable_file_watcher=not args.no_file_watcher,
        enable_observability=not args.no_observability,
        workspace=args.workspace,
    )

    app = FreyaApp(args.workspace, config)

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        print("\n\nShutdown signal received...")
        app.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        if args.health:
            print(json.dumps(app.get_health_surface(), indent=2, sort_keys=True))
            return 0
        if args.readiness:
            readiness = app.get_health_surface()["readiness"]
            print(json.dumps(readiness, indent=2, sort_keys=True))
            return 0 if readiness["ready"] else 1

        app.start()

        if args.input:
            # Single-shot mode
            if args.execute:
                response = app.execute_task(args.input)
            else:
                response = app.run_single_shot(args.input)
            print(response)
        else:
            # Interactive mode
            app.run_interactive()

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"Fatal error: {e}")
        return 1
    finally:
        app.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
