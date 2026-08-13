"""FreyaAgent - Application Entry Point and Lifecycle Owner.

This is the canonical application entry point. It owns the system lifecycle
and delegates all user requests to AgentFacade.
"""

import sys
import signal
import argparse
from pathlib import Path
from typing import Optional

from app.core.initializer import SystemInitializer, SystemConfig, InitializedSystem
from app.agent.facade import AgentFacade
from app.core.logger import logger


class FreyaAgent:
    """
    FreyaAgent - Application entry point and lifecycle owner.
    
    Responsibilities:
    - Owns system initialization and shutdown
    - Delegates all user requests to AgentFacade
    - Provides CLI/GUI compatible interface
    """

    def __init__(self, workspace: Path, config: Optional[SystemConfig] = None):
        self.workspace = workspace
        self.config = config or SystemConfig()
        self.initializer = SystemInitializer(workspace, self.config)
        self._system: Optional[InitializedSystem] = None
        self._running = False

    @property
    def facade(self) -> AgentFacade:
        """Access to the AgentFacade for request delegation."""
        if not self._system:
            raise RuntimeError("System not initialized. Call start() first.")
        return self._system.facade

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> None:
        """Initialize and start all subsystems."""
        logger.info("[FreyaAgent] Starting Freya...")
        self._system = self.initializer.initialize()
        self._running = True
        logger.info("[FreyaAgent] Freya started successfully")

    def shutdown(self) -> None:
        """Gracefully shutdown all subsystems."""
        if self._system:
            logger.info("[FreyaAgent] Shutting down Freya...")
            self.initializer.shutdown(self._system)
            self._system = None
            self._running = False
            logger.info("[FreyaAgent] Shutdown complete")

    # ------------------------------------------------------------
    # Request delegation to AgentFacade (the ONLY user request path)
    # ------------------------------------------------------------

    def chat(self, user_input: str) -> str:
        """Process a chat message via AgentFacade."""
        return self.facade.chat(user_input)

    def execute_task(self, task: str, allow_mutations: bool = True) -> str:
        """Execute an engineering task via AgentFacade."""
        return self.facade.execute_task(task, allow_mutations)

    def get_status(self):
        """Get agent status via AgentFacade."""
        return self.facade.get_status()

    # ------------------------------------------------------------
    # CLI interaction methods
    # ------------------------------------------------------------

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

    agent = FreyaAgent(args.workspace, config)

    # Setup signal handlers for graceful shutdown
    def signal_handler(signum, frame):
        print("\n\nShutdown signal received...")
        agent.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        agent.start()

        if args.input:
            # Single-shot mode
            if args.execute:
                response = agent.execute_task(args.input)
            else:
                response = agent.run_single_shot(args.input)
            print(response)
        else:
            # Interactive mode
            agent.run_interactive()

    except Exception as e:
        logger.error(f"Fatal error: {e}")
        print(f"Fatal error: {e}")
        return 1
    finally:
        agent.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())