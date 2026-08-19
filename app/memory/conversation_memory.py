"""Conversation Memory for Freya AI.

This module provides the working conversation memory that stores the current
user/assistant dialogue with automatic context windowing (minimum 20 turns).
It supports reference resolution for recent entities like "it", "that file",
"the previous function", etc.

Integrates with the agent's prompt construction to provide relevant conversation
context without unnecessary token growth.

Also supports long-term conversation summarization to keep context manageable
across extended sessions.
"""

import hashlib
import json
import re
import threading
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Union

# Vector database imports for cross-session search
try:
    from app.vector_db import get_vector_db, VectorDB
    VECTOR_DB_AVAILABLE = True
except ImportError:
    VECTOR_DB_AVAILABLE = False
    VectorDB = None

# Embedding model for semantic search - disconnected to avoid Hugging Face dependency
SENTENCE_TRANSFORMERS_AVAILABLE = False
SentenceTransformer = None  # Type stub


@dataclass
class ConversationTurn:
    """A single turn in the conversation (user or assistant message)."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    entities: Dict[str, Any] = field(default_factory=dict)  # Extracted entities for reference resolution
    shopping_state: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationTurn":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class ConversationSummary:
    """A summary of a conversation segment.

    Summaries preserve important context from older parts of the conversation
    that have been trimmed from the active window.
    """
    summary_id: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f"))
    start_turn_index: int = 0
    end_turn_index: int = 0
    turn_count: int = 0
    summary_text: str = ""
    key_topics: List[str] = field(default_factory=list)
    key_decisions: List[str] = field(default_factory=list)
    key_facts: List[str] = field(default_factory=list)
    active_goals: List[str] = field(default_factory=list)
    unfinished_tasks: List[str] = field(default_factory=list)
    user_preferences: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationSummary":
        """Create from dictionary."""
        return cls(**data)


class ConversationMemory:
    """Stores conversation history with automatic context windowing.

    Features:
    - Minimum 20 turns retained (rolling window)
    - Automatic entity extraction for reference resolution
    - Reference resolution: "it", "that file", "the previous function", etc.
    - Integration with agent prompt construction
    - Token-aware trimming to avoid unnecessary growth
    """

    def __init__(
        self,
        workspace: str = ".",
        storage_path: str = "data/memory/conversation_memory.json",
        min_turns: int = 20,
        max_turns: int = 50,
        max_characters: int = 16000,
        summarization_threshold: int = 40,
        max_summaries: int = 10,
        _bypass_min_turns: bool = False,  # Internal: allow <20 for backward compatibility
        vector_db_name: str = "conversation_vectors",
        embedding_dim: int = 384,
        _skip_vector_db_init: bool = False,
        _skip_auto_load: bool = False,  # Internal: skip automatic loading from disk
    ):
        """Initialize Conversation Memory.

        Args:
            workspace: Project workspace directory
            storage_path: Relative path to storage file within workspace
            min_turns: Minimum turns to retain (rolling window floor)
            max_turns: Maximum turns to retain (rolling window ceiling)
            max_characters: Maximum characters in context window
            summarization_threshold: Turn count at which to auto-summarize (default 40)
            max_summaries: Maximum number of summaries to retain (default 10)
            _bypass_min_turns: (Internal) Skip minimum 20 turns enforcement for backward compat
            vector_db_name: (Internal) Vector database collection name
            embedding_dim: (Internal) Embedding dimension for vector storage
            _skip_vector_db_init: (Internal) Skip vector database initialization for testing
            _skip_auto_load: (Internal) Skip automatic loading from disk for testing
        """
        self.workspace = Path(workspace).resolve()
        self.storage_path = self.workspace / storage_path
        # Stable across process restarts; never use object identity for persisted records.
        self._conversation_id = hashlib.sha256(
            str(self.storage_path.resolve()).encode("utf-8")
        ).hexdigest()[:16]
        if _bypass_min_turns:
            self.min_turns = min_turns
        else:
            self.min_turns = max(20, min_turns)  # Enforce minimum 20
        self.max_turns = max(max_turns, self.min_turns)
        self.max_characters = max_characters

        # Summarization settings
        self.summarization_threshold = summarization_threshold
        self.max_summaries = max_summaries

        # Vector database settings
        self.vector_db_name = vector_db_name
        self.embedding_dim = embedding_dim
        self._skip_vector_db_init = _skip_vector_db_init
        self._skip_auto_load = _skip_auto_load
        self._vector_db = None  # Vector database for cross-session search

        # Embedding model for semantic search
        self.embedding_model = None
        if SENTENCE_TRANSFORMERS_AVAILABLE:
            try:
                self.embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
                self._embedding_dimension = self.embedding_model.get_sentence_embedding_dimension()
            except Exception:
                self.embedding_model = None

        # Initialize core attributes
        self._lock = threading.RLock()
        self._turns: List[ConversationTurn] = []
        self._entity_index: Dict[str, List[Tuple[int, str]]] = {}  # entity -> [(turn_index, entity_value)]
        self._summaries: List[ConversationSummary] = []
        self._summary_storage_path = self.storage_path.parent / "conversation_summaries.json"

        # Initialize vector database if available and not skipped
        if not _skip_vector_db_init and VECTOR_DB_AVAILABLE:
            self._initialize_vector_db()

        if not self._skip_auto_load:
            self._load()
            self._load_summaries()

    def _initialize_vector_db(self) -> None:
        """Initialize the vector database for cross-session conversation search."""
        try:
            # get_vector_db owns the data/vector_db path segment. Passing the
            # workspace directly keeps writes and restart-time reads aligned.
            self._vector_db = get_vector_db(
                name=self.vector_db_name,
                workspace=str(self.workspace),
                embedding_dim=self.embedding_dim,
            )
        except Exception as e:
            # Log error but don't fail initialization
            print(f"Warning: Failed to initialize vector database for conversation search: {e}")
            self._vector_db = None

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

    def _extract_entities(self, content: str, role: str) -> Dict[str, str]:
        """Extract referenceable entities from message content.

        Returns a mapping of reference keys to their values for later resolution.
        """
        entities = {}

        # File paths (with common extensions)
        file_pattern = r'\b([\w/\\.-]+\.(?:py|js|ts|jsx|tsx|java|cpp|cc|c|h|rs|go|rb|php|cs|kt|swift|scala|r|m|pl|sh|bash|zsh|fish|ps1|bat|cmd|dockerfile|makefile|cmake|gradle|xml|json|yaml|yml|toml|ini|cfg|conf|md|txt|html|css|scss|sass|less|vue|svelte))\b'
        files = re.findall(file_pattern, content, re.IGNORECASE)
        if files:
            entities["that file"] = files[-1]
            entities["the file"] = files[-1]
            for i, f in enumerate(files[-3:]):
                entities[f"file {i+1}"] = f

        # Function/method names (word followed by parentheses)
        func_pattern = r'\b(\w+)\s*\('
        funcs = re.findall(func_pattern, content)
        if funcs:
            entities["that function"] = funcs[-1]
            entities["the function"] = funcs[-1]
            entities["the previous function"] = funcs[-1]

        # Class names (capitalized words, possibly with dots)
        class_pattern = r'\b([A-Z][a-zA-Z0-9]*(?:\.[A-Z][a-zA-Z0-9]*)*)\b'
        classes = re.findall(class_pattern, content)
        if classes:
            entities["that class"] = classes[-1]
            entities["the class"] = classes[-1]

        # Variable names (snake_case or camelCase)
        var_pattern = r'\b([a-z_][a-z0-9_]*|[a-z]+[A-Z][a-zA-Z0-9]*)\b'
        vars_found = re.findall(var_pattern, content)
        if vars_found:
            entities["that variable"] = vars_found[-1]
            entities["the variable"] = vars_found[-1]

        # Error messages
        error_pattern = r'(?:Error|Exception|Failure|Traceback).*?(?:\n|$)'
        errors = re.findall(error_pattern, content, re.IGNORECASE | re.MULTILINE)
        if errors:
            entities["that error"] = errors[-1].strip()
            entities["the error"] = errors[-1].strip()

        # Code snippets in markdown
        code_pattern = r'```[\w]*\n(.*?)\n```'
        code_blocks = re.findall(code_pattern, content, re.DOTALL)
        if code_blocks:
            entities["that code"] = code_blocks[-1][:500]
            entities["the code"] = code_blocks[-1][:500]

        # Quoted strings (potential references)
        quote_pattern = r'"([^"]{3,100})"'
        quotes = re.findall(quote_pattern, content)
        if quotes:
            entities["that"] = quotes[-1]
            entities["the thing"] = quotes[-1]

        return entities

    def _update_entity_index(self, turn_index: int, entities: Dict[str, str]) -> None:
        """Update the entity index with new entities from a turn."""
        for key, value in entities.items():
            if key not in self._entity_index:
                self._entity_index[key] = []
            self._entity_index[key].append((turn_index, value))

    def _rebuild_entity_index(self) -> None:
        """Rebuild entity index from all turns."""
        self._entity_index = {}
        for i, turn in enumerate(self._turns):
            self._update_entity_index(i, turn.entities)

    def _load(self) -> None:
        """Load conversation history from disk."""
        if not self.storage_path.exists():
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._turns = [ConversationTurn.from_dict(t) for t in data.get("turns", [])]
            self._rebuild_entity_index()
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            self._turns = []
            self._entity_index = {}

    def _save(self) -> None:
        """Save conversation history to disk."""
        self._ensure_storage_dir()
        temp_path = self.storage_path.with_suffix(".tmp")
        data = {
            "turns": [t.to_dict() for t in self._turns],
            "metadata": {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "turn_count": len(self._turns),
            }
        }
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_path.replace(self.storage_path)

    # =========================================================================
    # Conversation Summarization
    # =========================================================================

    def _load_summaries(self) -> None:
        """Load conversation summaries from disk."""
        if not self._summary_storage_path.exists():
            return
        try:
            with open(self._summary_storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._summaries = [ConversationSummary.from_dict(s) for s in data.get("summaries", [])]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            self._summaries = []

    def _save_summaries(self) -> None:
        """Save conversation summaries to disk."""
        self._ensure_storage_dir()
        temp_path = self._summary_storage_path.with_suffix(".tmp")
        data = {
            "summaries": [s.to_dict() for s in self._summaries],
            "metadata": {
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "summary_count": len(self._summaries),
            }
        }
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        temp_path.replace(self._summary_storage_path)

        # Store new summaries in vector database
        # We'll store all summaries since the last save to avoid duplicates
        # For simplicity, we'll store all summaries each time (they'll be deduplicated by ID)
        if self._vector_db is not None:
            for summary in self._summaries:
                self._store_summary_in_vector_db(summary)

    # =========================================================================
    # Vector Database Methods for Cross-Session Search
    # =========================================================================

    def _compute_embedding(self, text: str):
        """Return a stable normalized embedding without requiring a process-local model.

        A sentence-transformer embedding is used when explicitly available.  The
        deterministic hashing fallback keeps the persistent FAISS contract usable
        in the supported default runtime, where the optional transformer model is
        intentionally not initialized.
        """
        if not text or not text.strip():
            return None

        if self.embedding_model is not None:
            try:
                return self.embedding_model.encode(
                    [text],
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )[0]
            except Exception:
                # A failed optional model must not disable durable retrieval.
                pass

        vector = [0.0] * self.embedding_dim
        for token in re.findall(r"[a-z0-9_]+", text.lower()):
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.embedding_dim
            vector[index] += 1.0

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return None
        return [value / norm for value in vector]

    def _store_turn_in_vector_db(self, turn: ConversationTurn, turn_index: int) -> None:
        """Store a conversation turn in the vector database for cross-session search.

        Args:
            turn: The conversation turn to store
            turn_index: The index of the turn in the conversation
        """
        if self._vector_db is None:
            return

        try:
            # Create content for vector embedding - combine role and content
            content_for_embedding = f"{turn.role}: {turn.content}"

            # Compute embedding
            embedding = self._compute_embedding(content_for_embedding)
            if embedding is None:
                return

            # Prepare metadata
            metadata = {
                "conversation_id": self._conversation_id,
                "turn_id": f"{self._conversation_id}:{turn.timestamp}:{turn_index}",
                "turn_index": turn_index,
                "role": turn.role,
                "timestamp": turn.timestamp,
                "content": turn.content,
                "entities": str(turn.entities),  # Convert dict to string for storage
                "type": "conversation_turn"
            }

            # Add to vector database
            self._vector_db.add(embedding, metadata)
        except Exception:
            # Silently fail to avoid disrupting conversation flow
            pass

    def _store_summary_in_vector_db(self, summary: ConversationSummary) -> None:
        """Store a conversation summary in the vector database for cross-session search.

        Args:
            summary: The conversation summary to store
        """
        if self._vector_db is None:
            return

        try:
            # Create content for vector embedding
            content_for_embedding = f"Summary: {summary.summary_text}\nTopics: {', '.join(summary.key_topics)}\nDecisions: {', '.join(summary.key_decisions)}\nFacts: {', '.join(summary.key_facts)}"

            # Compute embedding
            embedding = self._compute_embedding(content_for_embedding)
            if embedding is None:
                return

            # Prepare metadata
            metadata = {
                "conversation_id": self._conversation_id,
                "summary_id": summary.summary_id,
                "content": summary.summary_text,
                "start_turn_index": summary.start_turn_index,
                "end_turn_index": summary.end_turn_index,
                "turn_count": summary.turn_count,
                "timestamp": summary.updated_at,
                "key_topics": str(summary.key_topics),
                "key_decisions": str(summary.key_decisions),
                "key_facts": str(summary.key_facts),
                "active_goals": str(summary.active_goals),
                "unfinished_tasks": str(summary.unfinished_tasks),
                "user_preferences": str(summary.user_preferences),
                "type": "conversation_summary"
            }

            # Add to vector database
            self._vector_db.add(embedding, metadata)
        except Exception:
            # Silently fail to avoid disrupting conversation flow
            pass

    def search_conversations(self, query: str, max_results: int = 10, min_similarity: float = 0.3) -> List[Dict[str, Any]]:
        """Search conversation history across sessions using semantic search.

        Args:
            query: The search query
            max_results: Maximum number of results to return
            min_similarity: Minimum similarity score (0-1) for results

        Returns:
            List of matching conversation snippets with metadata
        """
        if self._vector_db is None or not query.strip():
            return []

        try:
            # Compute query embedding
            query_embedding = self._compute_embedding(query)
            if query_embedding is None:
                return []

            # Search the vector database
            results = self._vector_db.search(query_embedding, limit=max_results)

            # Process and format results
            formatted_results = []
            for item in results:
                if len(item) >= 3:
                    vector_id, score, metadata = item[0], item[1], item[2]
                else:
                    # Handle different return formats
                    vector_id, score = item[0], item[1]
                    metadata = {}

                # Convert score to similarity (assuming higher is better)
                similarity = float(score) if isinstance(score, (int, float)) else 0.0

                if similarity >= min_similarity:
                    result_item = {
                        "id": str(vector_id),
                        "similarity": similarity,
                        "content": metadata.get("content", ""),
                        "role": metadata.get("role", ""),
                        "timestamp": metadata.get("timestamp", ""),
                        "type": metadata.get("type", "unknown"),
                        "metadata": metadata
                    }

                    # Parse stringified fields back to appropriate types if needed
                    if "entities" in metadata and isinstance(metadata["entities"], str):
                        try:
                            import ast
                            result_item["entities"] = ast.literal_eval(metadata["entities"])
                        except:
                            result_item["entities"] = {}

                    for field in ["key_topics", "key_decisions", "key_facts", "active_goals", "unfinished_tasks", "user_preferences"]:
                        if field in metadata and isinstance(metadata[field], str):
                            try:
                                import ast
                                result_item[field] = ast.literal_eval(metadata[field])
                            except:
                                result_item[field] = [] if field != "user_preferences" else ""

                    formatted_results.append(result_item)

            return formatted_results
        except Exception:
            return []

    def search_conversations_by_topic(self, topic: str, max_results: int = 10,
                                    time_weight_factor: float = 0.1) -> List[Dict[str, Any]]:
        """Search conversations by topic with temporal weighting.

        Args:
            topic: The topic to search for
            max_results: Maximum number of results to return
            time_weight_factor: How much to weight recent conversations (0-1)

        Returns:
            List of matching conversation snippets with temporal weighting applied
        """
        if self._vector_db is None or not topic.strip():
            return []

        try:
            # Compute topic embedding
            topic_embedding = self._compute_embedding(topic)
            if topic_embedding is None:
                return []

            # Search for the topic
            results = self._vector_db.search(topic_embedding, limit=max_results * 2)  # Get more to filter

            # Process results with temporal weighting
            now = datetime.now(timezone.utc).timestamp()
            weighted_results = []

            for item in results:
                if len(item) >= 3:
                    vector_id, score, metadata = item[0], item[1], item[2]
                else:
                    vector_id, score = item[0], item[1]
                    metadata = {}

                similarity = float(score) if isinstance(score, (int, float)) else 0.0

                # Apply temporal weighting if weigthed_score = similarity
                if "timestamp" in metadata and metadata["timestamp"]:
                    try:
                        # Parse timestamp and calculate age in days
                        ts = datetime.fromisoformat(metadata["timestamp"].replace('Z', '+00:00'))
                        age_days = (datetime.now(timezone.utc) - ts).total_seconds() / (24 * 3600)
                        # Apply exponential decay: newer items get higher weight
                        time_weight = math.exp(-time_weight_factor * age_days)
                        weighted_score = similarity * (0.7 + 0.3 * time_weight)  # Base 70% similarity + 30% time weight
                    except:
                        weighted_score = similarity
                else:
                    weighted_score = similarity

                if weighted_score >= 0.2:  # Minimum threshold after weighting
                    result_item = {
                        "id": str(vector_id),
                        "similarity": similarity,
                        "weighted_score": weighted_score,
                        "content": metadata.get("content", ""),
                        "role": metadata.get("role", ""),
                        "timestamp": metadata.get("timestamp", ""),
                        "type": metadata.get("type", "unknown"),
                        "metadata": metadata
                    }

                    # Parse stringified fields
                    for field in ["entities", "key_topics", "key_decisions", "key_facts", "active_goals", "unfinished_tasks", "user_preferences"]:
                        if field in metadata and isinstance(metadata[field], str):
                            try:
                                import ast
                                result_item[field] = ast.literal_eval(metadata[field])
                            except:
                                result_item[field] = [] if field != "user_preferences" else ""

                    weighted_results.append(result_item)

            # Sort by weighted score and limit results
            weighted_results.sort(key=lambda x: x["weighted_score"], reverse=True)
            return weighted_results[:max_results]
        except Exception:
            return []

    def get_conversation_thread(self, target_turn_index: int, context_size: int = 2) -> List[Dict[str, Any]]:
        """Get a conversation thread around a specific turn for context.

        Args:
            target_turn_index: The index of the target turn
            context_size: Number of turns before and after to include

        Returns:
            List of conversation turns in the thread
        """
        with self._lock:
            if not self._turns:
                return []

            start_idx = max(0, target_turn_index - context_size)
            end_idx = min(len(self._turns) - 1, target_turn_index + context_size)

            thread = []
            for i in range(start_idx, end_idx + 1):
                turn = self._turns[i]
                turn_dict = {
                    "index": i,
                    "role": turn.role,
                    "content": turn.content,
                    "timestamp": turn.timestamp,
                    "entities": turn.entities
                }
                thread.append(turn_dict)

            return thread

    def _generate_summary(self, start_index: int, end_index: int) -> Optional[ConversationSummary]:
        """Generate a summary of conversation turns from start_index to end_index (inclusive).

        Extracts key topics, decisions, facts, goals, and unfinished tasks from the conversation segment.
        """
        if start_index >= end_index or start_index < 0 or end_index >= len(self._turns):
            return None

        turns_to_summarize = self._turns[start_index:end_index + 1]
        if not turns_to_summarize:
            return None

        # Extract content for summarization
        conversation_text = "\n".join(
            f"{'User' if t.role == 'user' else 'Freya'}: {t.content}"
            for t in turns_to_summarize
        )

        # Simple keyword-based extraction for key topics
        key_topics = self._extract_key_topics(conversation_text)
        key_decisions = self._extract_key_decisions(conversation_text)
        key_facts = self._extract_key_facts(conversation_text)
        active_goals = self._extract_active_goals(conversation_text)
        unfinished_tasks = self._extract_unfinished_tasks(conversation_text)
        user_preferences = self._extract_user_preferences(conversation_text)

        # Generate a concise summary text
        summary_text = self._create_summary_text(
            turns_to_summarize, key_topics, key_decisions, key_facts
        )

        return ConversationSummary(
            start_turn_index=start_index,
            end_turn_index=end_index,
            turn_count=len(turns_to_summarize),
            summary_text=summary_text,
            key_topics=key_topics,
            key_decisions=key_decisions,
            key_facts=key_facts,
            active_goals=active_goals,
            unfinished_tasks=unfinished_tasks,
            user_preferences=user_preferences,
        )

    def _extract_key_topics(self, text: str) -> List[str]:
        """Extract key topics from conversation text."""
        topics = set()
        text_lower = text.lower()

        # Technical topics
        topic_keywords = {
            "python": ["python", "py", "pip", "requirements.txt", "pyproject.toml", "setup.py"],
            "javascript": ["javascript", "js", "npm", "package.json", "node"],
            "typescript": ["typescript", "ts", "tsx", "tsconfig"],
            "api": ["api", "rest", "endpoint", "route", "fastapi", "flask", "express"],
            "database": ["database", "db", "sql", "postgres", "mysql", "sqlite", "orm", "migration"],
            "testing": ["test", "pytest", "unit test", "integration test", "mock"],
            "docker": ["docker", "container", "dockerfile", "compose"],
            "git": ["git", "commit", "push", "pull", "branch", "merge", "rebase"],
            "refactoring": ["refactor", "restructure", "cleanup", "rename", "extract"],
            "debugging": ["debug", "fix", "bug", "error", "traceback", "exception"],
            "deployment": ["deploy", "ci/cd", "pipeline", "release", "production"],
            "configuration": ["config", "settings", "env", "environment", "yaml", "toml", "json"],
        }

        for topic, keywords in topic_keywords.items():
            if any(kw in text_lower for kw in keywords):
                topics.add(topic)

        # File-based topics
        file_matches = re.findall(r'\b(\w+\.(?:py|js|ts|json|yaml|yml|toml|md|txt))\b', text, re.IGNORECASE)
        for f in file_matches[:5]:
            topics.add(f"file:{f}")

        return sorted(list(topics))

    def _extract_key_decisions(self, text: str) -> List[str]:
        """Extract key decisions from conversation text."""
        decisions = []
        text_lower = text.lower()

        # Look for decision indicators
        decision_patterns = [
            r"(?:decided|decision|agreed|will use|going to use|chose|selected)\s+([^.!?]+)",
            r"(?:we'll|we will|i'll|i will)\s+(?:use|implement|create|build|add)\s+([^.!?]+)",
        ]

        for pattern in decision_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches[:3]:
                decision = match.strip()
                if len(decision) > 5 and len(decision) < 200:
                    decisions.append(decision)

        return decisions[:5]

    def _extract_key_facts(self, text: str) -> List[str]:
        """Extract key facts from conversation text."""
        facts = []
        text_lower = text.lower()

        # Look for fact statements
        fact_patterns = [
            r"(?:note that|important|remember|key point|fact:)\s+([^.!?]+)",
            r"(?:is|was|has|have)\s+(?:configured|set|enabled|disabled|installed|available)\s+([^.!?]+)",
        ]

        for pattern in fact_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches[:3]:
                fact = match.strip()
                if len(fact) > 5 and len(fact) < 200:
                    facts.append(fact)

        return facts[:5]

    def _extract_active_goals(self, text: str) -> List[str]:
        """Extract active goals from conversation text."""
        goals = []
        text_lower = text.lower()

        goal_patterns = [
            r"(?:goal|objective|aim|target|want to|need to|trying to)\s+([^.!?]+)",
            r"(?:working on|currently|in progress)\s+([^.!?]+)",
        ]

        for pattern in goal_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches[:3]:
                goal = match.strip()
                if len(goal) > 5 and len(goal) < 200:
                    goals.append(goal)

        return goals[:5]

    def _extract_unfinished_tasks(self, text: str) -> List[str]:
        """Extract unfinished tasks from conversation text."""
        tasks = []
        text_lower = text.lower()

        task_patterns = [
            r"(?:todo|to-do|need to|still need|haven't|not yet|pending|remaining)\s+([^.!?]+)",
            r"(?:will do|plan to|later|next)\s+([^.!?]+)",
        ]

        for pattern in task_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches[:3]:
                task = match.strip()
                if len(task) > 5 and len(task) < 200:
                    tasks.append(task)

        return tasks[:5]

    def _extract_user_preferences(self, text: str) -> List[str]:
        """Extract user preferences from conversation text."""
        prefs = []
        text_lower = text.lower()

        pref_patterns = [
            r"(?:prefer|preference|like|dislike|favor|don't like|avoid)\s+([^.!?]+)",
            r"(?:always|never|usually|typically)\s+([^.!?]+)",
        ]

        for pattern in pref_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches[:3]:
                pref = match.strip()
                if len(pref) > 5 and len(pref) < 200:
                    prefs.append(pref)

        return prefs[:5]

    def _create_summary_text(self, turns: List[ConversationTurn], topics: List[str],
                             decisions: List[str], facts: List[str]) -> str:
        """Create a concise summary text from turns and extracted elements."""
        parts = []

        if topics:
            parts.append(f"Topics: {', '.join(topics[:5])}")

        if decisions:
            parts.append(f"Decisions: {'; '.join(decisions[:3])}")

        if facts:
            parts.append(f"Key facts: {'; '.join(facts[:3])}")

        # Add a brief narrative summary
        user_turns = [t for t in turns if t.role == "user"]
        assistant_turns = [t for t in turns if t.role == "assistant"]

        if user_turns:
            # Get the essence of what user asked about
            user_content = " ".join(t.content[:100] for t in user_turns[-3:])
            if len(user_content) > 200:
                user_content = user_content[:200] + "..."
            parts.append(f"User asked about: {user_content}")

        return " | ".join(parts) if parts else "Conversation segment (summary not available)"

    def _check_and_summarize(self) -> None:
        """Check if summarization is needed and create summary if threshold reached.

        This should be called after adding messages. It summarizes older turns
        that are beyond the recent window, preserving their context before they
        might be trimmed.
        """
        # Only summarize if we have enough total turns
        if len(self._turns) < self.summarization_threshold:
            return

        # Define the "recent" window that should not be summarized
        # We keep at least min_turns recent + a small buffer
        recent_window = self.min_turns + 5

        # If total turns fit in recent window, nothing to summarize yet
        if len(self._turns) <= recent_window:
            return

        # The oldest turn index that's still in the "recent" window
        recent_start = len(self._turns) - recent_window

        # Check if we already summarized up to this point
        if self._summaries:
            last_summary = self._summaries[-1]
            if last_summary.end_turn_index >= recent_start - 1:
                return  # Already summarized all non-recent turns

        # Summarize from the last summarized turn (or 0) up to just before recent window
        summarize_start = 0
        if self._summaries:
            summarize_start = self._summaries[-1].end_turn_index + 1

        summarize_end = recent_start - 1

        if summarize_start >= summarize_end:
            return

        # Generate summary
        summary = self._generate_summary(summarize_start, summarize_end)
        if summary:
            self._summaries.append(summary)

            # Trim old summaries
            if len(self._summaries) > self.max_summaries:
                self._summaries = self._summaries[-self.max_summaries:]

            self._save_summaries()

    def get_summaries(self) -> List[ConversationSummary]:
        """Get all conversation summaries."""
        with self._lock:
            return self._summaries.copy()

    def get_summary_text(self, max_summaries: Optional[int] = None) -> str:
        """Get formatted summary text for prompt injection.

        Args:
            max_summaries: Maximum number of summaries to include

        Returns:
            Formatted summary text
        """
        with self._lock:
            summaries = self._summaries[-max_summaries:] if max_summaries else self._summaries
            if not summaries:
                return ""

            lines = ["=== Conversation Summary (Previous Context) ==="]
            for summary in summaries:
                lines.append(f"\n[Summary {summary.summary_id}] ({summary.turn_count} turns)")
                lines.append(summary.summary_text)
                if summary.key_decisions:
                    lines.append(f"  Decisions: {'; '.join(summary.key_decisions)}")
                if summary.active_goals:
                    lines.append(f"  Active goals: {'; '.join(summary.active_goals)}")
                if summary.unfinished_tasks:
                    lines.append(f"  Unfinished: {'; '.join(summary.unfinished_tasks)}")
                if summary.user_preferences:
                    lines.append(f"  Preferences: {'; '.join(summary.user_preferences)}")

            lines.append("\n=== End Summary ===")
            return "\n".join(lines)

    def get_history_with_summaries(self, limit: Optional[int] = None, max_characters: Optional[int] = None) -> str:
        """Get conversation history with summaries prepended for prompt injection.

        This combines summaries of older conversation with recent history.
        """
        with self._lock:
            # Get summaries text
            summary_text = self.get_summary_text()

            # Get recent history
            turns = self._turns[-limit:] if limit else self._turns
            history_lines = []
            for turn in turns:
                role_label = "User" if turn.role == "user" else "Freya"
                history_lines.append(f"{role_label}: {turn.content}")
            history_text = "\n".join(history_lines)

            if max_characters:
                history_text = history_text[-max_characters:]

            if summary_text:
                return f"{summary_text}\n\n{history_text}"
            return history_text

    def force_summarize(self, keep_recent: int = 20) -> Optional[ConversationSummary]:
        """Force summarization of all but the most recent turns.

        Args:
            keep_recent: Number of recent turns to keep unsummarized

        Returns:
            The created summary, or None if nothing to summarize
        """
        with self._lock:
            if len(self._turns) <= keep_recent:
                return None

            summarize_end = len(self._turns) - keep_recent - 1
            summarize_start = 0
            if self._summaries:
                summarize_start = self._summaries[-1].end_turn_index + 1

            if summarize_start >= summarize_end:
                return None

            summary = self._generate_summary(summarize_start, summarize_end)
            if summary:
                self._summaries.append(summary)
                if len(self._summaries) > self.max_summaries:
                    self._summaries = self._summaries[-self.max_summaries:]
                self._save_summaries()
            return summary

    def clear_summaries(self) -> None:
        """Clear all conversation summaries."""
        with self._lock:
            self._summaries = []
            if self._summary_storage_path.exists():
                self._summary_storage_path.unlink()

    def add_message(self, role: str, content: str, shopping_state: Optional[Dict[str, Any]] = None) -> ConversationTurn:
        """Add a message to the conversation history.

        Args:
            role: "user" or "assistant"
            content: Message content
            shopping_state: Optional structured shopping state for this turn

        Returns:
            The created ConversationTurn
        """
        with self._lock:
            turn = ConversationTurn(
                role=role,
                content=content,
                entities=self._extract_entities(content, role),
                shopping_state=dict(shopping_state or {}),
            )
            self._turns.append(turn)
            self._update_entity_index(len(self._turns) - 1, turn.entities)

            # Store the turn in vector database for cross-search
            turn_index = len(self._turns) - 1
            self._store_turn_in_vector_db(turn, turn_index)

            self._check_and_summarize()  # Check if we need to summarize (before trimming)
            self._trim()
            self._save()
            return turn

    def _trim(self) -> None:
        """Trim conversation history to stay within limits.

        Keeps at least min_turns, at most max_turns, and within max_characters.
        """
        if len(self._turns) <= self.min_turns:
            return

        # Trim by turn count first
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns:]
            self._rebuild_entity_index()

        # Then trim by character count
        total_chars = sum(len(t.content) for t in self._turns)
        while total_chars > self.max_characters and len(self._turns) > self.min_turns:
            removed = self._turns.pop(0)
            total_chars -= len(removed.content)
            self._rebuild_entity_index()

    def get_history(self, limit: Optional[int] = None) -> List[ConversationTurn]:
        """Get conversation history.

        Args:
            limit: Maximum number of recent turns to return (None = all)

        Returns:
            List of ConversationTurn objects
        """
        with self._lock:
            if limit is None:
                return self._turns.copy()
            return self._turns[-limit:].copy()

    def get_history_text(self, limit: Optional[int] = None, max_characters: Optional[int] = None) -> str:
        """Get formatted conversation history for prompt injection.

        Args:
            limit: Maximum number of recent turns
            max_characters: Maximum characters to return

        Returns:
            Formatted conversation text including summaries of older context
        """
        return self.get_history_with_summaries(limit=limit, max_characters=max_characters)

    def resolve_reference(self, reference: str) -> Optional[str]:
        """Resolve a reference like "it", "that file", "the previous function".

        Args:
            reference: The reference phrase to resolve

        Returns:
            The resolved entity value, or None if not found
        """
        with self._lock:
            reference_lower = reference.lower().strip()

            # Direct match in entity index
            if reference_lower in self._entity_index:
                entries = self._entity_index[reference_lower]
                if entries:
                    return entries[-1][1]

            # Fuzzy match for common references
            reference_map = {
                "it": ["that", "the thing", "that code", "the file", "that file", "the function", "that function", "the variable", "that variable", "the error", "that error"],
                "that": ["it", "the thing", "that code", "the file", "that file"],
                "this": ["that", "it"],
                "the previous": ["the previous function", "the previous file", "the previous error"],
                "last": ["the function", "the file", "that function", "that file", "the error", "that error"],
            }

            for key, synonyms in reference_map.items():
                if reference_lower in [key] + synonyms:
                    for syn in [key] + synonyms:
                        if syn in self._entity_index and self._entity_index[syn]:
                            return self._entity_index[syn][-1][1]

            return None

    def get_recent_entities(self, category: Optional[str] = None) -> Dict[str, str]:
        """Get recent entities, optionally filtered by category.

        Args:
            category: Optional category filter (e.g., "file", "function", "error")

        Returns:
            Dictionary of entity references to their values
        """
        with self._lock:
            if category is None:
                # Return most recent value for each entity key
                return {k: v[-1][1] for k, v in self._entity_index.items() if v}

            # Filter by category prefix
            result = {}
            for key, entries in self._entity_index.items():
                if key.startswith(category) or category in key:
                    if entries:
                        result[key] = entries[-1][1]
            return result

    def clear(self) -> None:
        """Clear all conversation history."""
        with self._lock:
            self._turns = []
            self._entity_index = {}
            if self.storage_path.exists():
                self.storage_path.unlink()

    def to_dict(self) -> List[Dict[str, Any]]:
        """Convert all turns to dictionaries for serialization."""
        with self._lock:
            return [t.to_dict() for t in self._turns]

    def __len__(self) -> int:
        return len(self._turns)

    def is_empty(self) -> bool:
        return len(self._turns) == 0

    def get_last_user_message(self) -> Optional[str]:
        """Get the most recent user message content."""
        with self._lock:
            for turn in reversed(self._turns):
                if turn.role == "user":
                    return turn.content
            return None

    def get_last_assistant_message(self) -> Optional[str]:
        """Get the most recent assistant message content."""
        with self._lock:
            for turn in reversed(self._turns):
                if turn.role == "assistant":
                    return turn.content
            return None

    def save(self, path: Optional[str] = None) -> None:
        """Save conversation to file."""
        # If a different path is provided, temporarily use it
        original_path = None
        if path is not None:
            original_path = self.storage_path
            self.storage_path = Path(path).resolve()
        try:
            self._save()
        finally:
            if original_path is not None:
                self.storage_path = original_path

    def load(self, path: str) -> None:
        """Load conversation from file."""
        self.storage_path = Path(path).resolve()
        self._load()

    def new_conversation(self) -> None:
        """Start a new conversation (clear history)."""
        self.clear()

    def clear_conversation(self) -> None:
        """Clear conversation history (alias for clear)."""
        self.clear()

    def get_conversation_history(self) -> List[ConversationTurn]:
        """Get the full conversation history."""
        return self.get_history()

    def get_conversation_length(self) -> int:
        """Get the number of turns in the conversation."""
        return len(self._turns)

    # Backward compatibility properties
    @property
    def max_history(self) -> int:
        """Max history size (backward compat with ConversationState)."""
        return self.max_turns

    @property
    def _persistence_path(self) -> Optional[str]:
        """Persistence path for backward compatibility."""
        return str(self.storage_path) if self.storage_path else None

    @_persistence_path.setter
    def _persistence_path(self, value: Optional[str]) -> None:
        if value:
            self.storage_path = Path(value).resolve()

    @max_history.setter
    def max_history(self, value: int) -> None:
        """Allow setting max_history for backward compatibility.

        Note: For backward compat with old ConversationState, we allow values < 20
        even though the new system enforces a minimum of 20 turns.
        """
        self.max_turns = value


# Backwards compatibility with existing ConversationState
def create_conversation_memory(
    workspace: str = ".",
    max_history: int = 20,
    persistence_path: Optional[str] = None,
) -> ConversationMemory:
    """Create a ConversationMemory instance compatible with existing ConversationState usage.

    Args:
        workspace: Project workspace directory
        max_history: Maximum conversation history (maps to max_turns)
        persistence_path: Optional custom persistence path

    Returns:
        Configured ConversationMemory instance
    """
    storage = persistence_path or "data/memory/conversation_memory.json"
    # For backward compatibility, allow max_history < 20 (old ConversationState allowed any value)
    min_turns = min(20, max_history)
    return ConversationMemory(
        workspace=workspace,
        storage_path=storage,
        min_turns=min_turns,
        max_turns=max_history,
        max_characters=16000,
        _bypass_min_turns=True,  # Allow < 20 turns for backward compat
    )


