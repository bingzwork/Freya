from app.agent.executor import Executor
from app.agent.planner import Planner
from app.brain.state import ConversationState
from app.core.llm import LLM
from typing import Optional
from app.core.logger import logger
from app.core.project_index import ProjectIndex
from app.core.symbol_index import SymbolIndex
from app.core.tool_manager import ToolManager
from app.editing.patch_engine import PatchEngine
from app.editing.patch_generator import PatchGenerator
from app.intelligence.context_builder import ContextBuilder
from app.intelligence.dependency_graph import DependencyGraph
from app.intelligence.file_locator import FileLocator
from app.intelligence.lexical_search import LexicalSearch
from app.memory.project_memory import ProjectMemory
from app.verification.repair_loop import RepairLoop
from app.verification.runner import VerificationRunner
from app.rag import SimpleRetriever
try:
    from app.retrieval.enhanced_retriever import EnhancedRetriever
except ImportError:
    EnhancedRetriever = SimpleRetriever  # Fallback if enhanced version not available


class FreyaAgent:
    def __init__(self, workspace=".", max_conversation_history=20, conversation_persistence_path: Optional[str] = None):
        self.workspace = workspace
        self.llm = LLM()
        self.tools = ToolManager(workspace)
        self.memory = ProjectMemory(workspace)
        self.executor = Executor(self.llm, self.tools)
        self.patch_engine = PatchEngine()
        self.patch_generator = PatchGenerator(self.llm, self.patch_engine)
        self.verifier = VerificationRunner(workspace)
        self.planner = Planner(self.llm, self.memory)
        self.conversation = ConversationState(max_history=max_conversation_history, persistence_path=conversation_persistence_path)

        self.project_index = ProjectIndex(workspace)
        self.symbol_index = SymbolIndex(workspace)
        logger.info("Building project index...")
        self.project_index.build()
        logger.info("Building symbol index...")
        self.symbol_index.build()

        self.file_locator = FileLocator(self.symbol_index)
        self.lexical_search = LexicalSearch(self.symbol_index)
        self.dependency_graph = DependencyGraph(self.symbol_index)
        self.dependency_graph.build()
        self.context_builder = ContextBuilder(self.symbol_index, self.dependency_graph)
        self.retriever = EnhancedRetriever(self.symbol_index)
        logger.info(f"Indexed {len(self.project_index.files)} files.")
        logger.info(f"Indexed {len(self.symbol_index.symbols)} Python files.")
        logger.info("Freya Agent initialized")

    def build_context(self, task):
       matches = self.file_locator.locate(task)
       if not matches:
           for word in task.replace(",", " ").replace(".", " ").split():
               matches.extend(self.file_locator.locate(word))

       matches.extend(self.lexical_search.search(task, limit=5))
       matches.extend(self.retriever.retrieve(task, limit=5))
       unique = []
       seen = set()
       for match in matches:
           key = (match["file"], match["type"], match["name"], match["line"])
           if key not in seen:
               seen.add(key)
               unique.append(match)
       return self.context_builder.build(unique[:5]) if unique else ""

    def run(self, task, allow_mutations=True):
        """Plan, execute bounded workspace actions, and summarize the result. Mutating tools will prompt for confirmation before each use."""
        context = self.build_context(task)
        memory_context = self.memory.context()
        plan = self.planner.create_plan(task)
        allowed_tools = set(Executor.READ_ONLY_TOOLS)
        if allow_mutations:
            allowed_tools.update(Executor.MUTATING_TOOLS)
        results = self.executor.execute_plan(plan, allowed_tools)
        prompt = f"""
You are Freya, an AI software engineer.

{conversation_history}

User request:
{task}

conversation_history = self.conversation.get_history_text()

Relevant project code:
{context}

Recent project memory:
{memory_context}

Execution plan:
{plan}

Tool results:
{results}

Answer the user's request using the relevant code above.
"""
        answer = self.llm.ask(prompt)
        self.memory.record("task", {"request": task, "outcome": answer[:500]})
        self.conversation.add_message("user", task)
        self.conversation.add_message("assistant", answer)
        if self.conversation._persistence_path:
            self.conversation.save()
        return answer

    def propose_patch(self, task):
        """Return a reviewable patch proposal without changing any files."""
        operations = self.patch_generator.propose(task, self.build_context(task))
        return {"operations": operations, "preview": self.patch_engine.preview(operations)}

    def apply_patch(self, proposal, allow_mutations=False):
        if not allow_mutations:
            raise PermissionError("Patch application requires allow_mutations=True.")
        return self.patch_engine.apply(self.tools, proposal["operations"])

    def verify(self):
        """Run automated tests without giving the model a shell."""
        return self.verifier.run_tests()

    def apply_patch_and_verify(self, proposal, allow_mutations=False):
        if not allow_mutations:
            raise PermissionError("Patch application requires allow_mutations=True.")
        result = self.patch_engine.apply_and_verify(
            self.tools, proposal["operations"], self.verifier
        )
        self.memory.record(
            "patch_verification",
            {
                "preview": proposal.get("preview", ""),
                "success": result["verification"].success,
                "rolled_back": result["rolled_back"],
            },
        )
        return result

    def solve(self, task, max_iterations=5, allow_mutations=False, success_condition=None):
        """Attempt to autonomously solve a task via iterative planning, patching, and verification.

        Args:
            task (str): Description of the goal.
            max_iterations (int): Maximum number of planÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¹Ãƒâ€¦Ã¢â‚¬Å“proposeÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¹Ãƒâ€¦Ã¢â‚¬Å“apply cycles.
            allow_mutations (bool): If True, allows the agent to modify files.
            success_condition (callable, optional): A function that takes (task, iteration,
                verification_result, history) and returns True if the task is considered
                successfully completed. If not provided, success is determined by verification.

        Returns:
            dict: {
                'success': bool,
                'iterations': int,
                'history': list of dicts per iteration containing plan, proposal, verification result,
            }
        """
        if not allow_mutations:
            raise PermissionError("Autonomous solving requires allow_mutations=True.")
        context = self.build_context(task)
        history = []
        for it in range(1, max_iterations + 1):
            # 1. Plan
            plan = self.planner.create_plan(task)
            # 2. Propose patch based on plan (we treat the plan steps as the subÃƒÆ’Ã†â€™Ãƒâ€ Ã¢â‚¬â„¢ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€¦Ã‚Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã¢â‚¬Â¹Ãƒâ€¦Ã¢â‚¬Å“task)
            plan_steps = plan.get("steps", [])
            sub_task = "\n".join(plan_steps) if plan_steps else task
            try:
                proposal = self.patch_generator.propose(sub_task, context)
            except Exception as e:
                # If proposal fails, record and continue
                history.append({"iteration": it, "plan": plan, "error": str(e)})
                continue
            # 3. Apply and verify
            result = self.patch_engine.apply_and_verify(
                self.tools, proposal["operations"], self.verifier
            )
            # 4. Record outcome
            hist_entry = {
                "iteration": it,
                "plan": plan,
                "proposal": proposal,
                "verification": result["verification"],
                "rolled_back": result.get("rolled_back", False),
                "changes": result.get("changes", []),
            }
            history.append(hist_entry)
            # 5. Check success condition
            verified_success = result["verification"].success
            if success_condition is not None:
                try:
                    success = success_condition(task, it, result["verification"], history)
                except Exception:
                    success = False
            else:
                success = verified_success
            if success:
                # Success! Record a decision for learning
                self.memory.record(
                    "solved_task",
                    {
                        "task": task,
                        "iterations": it,
                        "solution_summary": f"Solved in {it} iterations.",
                        "trajectory": history,
                    },
                )
                return {
                    "success": True,
                    "iterations": it,
                    "history": history,
                }
        # Exhausted iterations
        self.memory.record(
            "unsolved_task",
            {
                "task": task,
                "max_iterations": max_iterations,
                "last_attempt": history[-1] if history else None,
                "trajectory": history,
            },
        )
        return {
            "success": False,
            "iterations": max_iterations,
            "history": history,
        }

    def remember_decision(self, decision, rationale=""):
        return self.memory.record("decision", {"decision": decision, "rationale": rationale})

    def repair(self, task, allow_mutations=False, max_attempts=2):
        if not allow_mutations:
            raise PermissionError("Autonomous repair requires allow_mutations=True.")
        context = self.build_context(task)

        def propose(feedback):
            return self.patch_generator.propose(
                f"{task}\n\nVerification feedback:\n{feedback}", context
            )

        return RepairLoop(
            self.patch_engine, self.tools, self.verifier, max_attempts
        ).run(propose)

    def new_conversation(self) -> None:
        """Start a new conversation, clearing previous message history.""" 
        self.conversation.clear()

    def get_conversation_history(self) -> list:
        """Get the current conversation message history.""" 
        return self.conversation.get_history()

    def get_conversation_length(self) -> int:
        """Get the number of messages in the current conversation.""" 
        return len(self.conversation)

    def clear_conversation(self) -> None:
        """Clear the current conversation history. Alias for new_conversation.""" 
        self.conversation.clear()

    def save_conversation(self, path: Optional[str] = None) -> None:
        """Save conversation history to a file."""
        self.conversation.save(path)

    def load_conversation(self, path: str) -> None:
        """Load conversation history from a file."""
        self.conversation.load(path)
