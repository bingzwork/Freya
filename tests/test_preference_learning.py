"""Tests for Preference Learning."""
import pytest
import shutil
import os
from app.memory import (
    PreferenceLearner,
    PreferenceApplier,
    PreferenceCategory,
    PreferenceSource,
    UserPreference,
    create_long_term_memory,
    get_preference_learner,
    get_preference_applier,
    learn_from_interaction,
    get_preference,
    set_preference,
    apply_preferences,
    reset_global_learner,
)
import app.memory.preference_learning as preference_learning_module


class TestUserPreference:
    """Test UserPreference dataclass."""

    def test_to_long_term_entry(self):
        """Test conversion to LongTermEntry."""
        pref = UserPreference(
            key="indent_size",
            category=PreferenceCategory.CODING_STYLE,
            value=4,
            confidence=0.9,
            source=PreferenceSource.EXPLICIT,
            description="User prefers 4 spaces",
        )
        entry = pref.to_long_term_entry()
        assert entry.category == "preference"
        assert entry.key == "coding_style.indent_size"
        assert entry.value == 4
        assert entry.confidence == 0.9
        assert entry.source == "explicit"
        assert "pref_category:coding_style" in entry.tags

    def test_from_long_term_entry(self):
        """Test creation from LongTermEntry."""
        from app.memory.long_term_memory import LongTermEntry
        from datetime import datetime, timezone

        entry = LongTermEntry(
            entry_id="preference.coding_style.indent_size",
            category="preference",
            key="coding_style.indent_size",
            value=4,
            confidence=0.9,
            source="explicit",
            tags=["pref_category:coding_style"],
            description="User prefers 4 spaces",
            created_at=datetime.now(timezone.utc).isoformat(),
            updated_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "learned_at": "2024-01-01T00:00:00Z",
                "application_count": 5,
            },
        )
        pref = UserPreference.from_long_term_entry(entry)
        assert pref.key == "indent_size"
        assert pref.category == PreferenceCategory.CODING_STYLE
        assert pref.value == 4
        assert pref.confidence == 0.9
        assert pref.source == PreferenceSource.EXPLICIT


class TestPreferenceLearner:
    """Test PreferenceLearner class."""

    @pytest.fixture
    def ltm(self):
        """Create a temporary LongTermMemory."""
        test_dir = "test_pref_learner"
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
        ltm = create_long_term_memory(workspace=test_dir, storage_path="prefs.json")
        yield ltm
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

    @pytest.fixture
    def learner(self, ltm):
        return PreferenceLearner(ltm)

    def test_learn_explicit_indent_size(self, learner):
        """Test learning indent size from explicit statement."""
        prefs = learner.learn_from_message("I prefer 4-space indentation")
        assert len(prefs) >= 1
        indent_pref = next((p for p in prefs if p.key == "indent_size"), None)
        assert indent_pref is not None
        assert indent_pref.value == 4
        assert indent_pref.category == PreferenceCategory.CODING_STYLE
        assert indent_pref.source == PreferenceSource.EXPLICIT

    def test_learn_explicit_tabs(self, learner):
        """Test learning indent style as tabs."""
        prefs = learner.learn_from_message("I prefer tabs for indentation")
        indent_pref = next((p for p in prefs if p.key == "indent_style"), None)
        assert indent_pref is not None
        assert indent_pref.value == "tabs"
        assert indent_pref.source == PreferenceSource.EXPLICIT

    def test_learn_explicit_test_framework(self, learner):
        """Test learning test framework preference."""
        prefs = learner.learn_from_message("Use pytest for testing")
        test_pref = next((p for p in prefs if "test" in p.key), None)
        assert test_pref is not None
        assert test_pref.value == "pytest"
        assert test_pref.source == PreferenceSource.EXPLICIT

    def test_learn_explicit_editor(self, learner):
        """Test learning editor preference."""
        prefs = learner.learn_from_message("My preferred editor is VS Code")
        editor_pref = next((p for p in prefs if p.key == "preferred_editor"), None)
        assert editor_pref is not None
        assert editor_pref.value == "vscode"
        assert editor_pref.source == PreferenceSource.EXPLICIT

    def test_learn_explicit_formatter(self, learner):
        """Test learning formatter preference."""
        prefs = learner.learn_from_message("Use black for formatting")
        fmt_pref = next((p for p in prefs if "format" in p.key or "formatter" in p.key), None)
        assert fmt_pref is not None
        assert fmt_pref.value == "black"
        assert fmt_pref.source == PreferenceSource.EXPLICIT

    def test_learn_explicit_want(self, learner):
        """Test learning from 'I want' statements."""
        prefs = learner.learn_from_message("I want concise responses")
        assert len(prefs) >= 1

    def test_get_preference(self, learner):
        """Test retrieving a learned preference."""
        learner.learn_from_message("I prefer 4-space indentation")
        value = learner.get_preference("indent_size")
        assert value == 4

    def test_get_nonexistent_preference(self, learner):
        """Test retrieving non-existent preference returns default."""
        value = learner.get_preference("nonexistent", default="default")
        assert value == "default"

    def test_get_all_preferences(self, learner):
        """Test getting all preferences."""
        learner.learn_from_message("I prefer 4-space indentation")
        learner.learn_from_message("Use pytest for testing")
        all_prefs = learner.get_all_preferences()
        assert len(all_prefs) >= 2

    def test_get_preferences_by_category(self, learner):
        """Test getting preferences by category."""
        learner.learn_from_message("I prefer 4-space indentation")
        learner.learn_from_message("Use pytest for testing")
        coding = learner.get_preferences_by_category(PreferenceCategory.CODING_STYLE)
        tools = learner.get_preferences_by_category(PreferenceCategory.TOOLS)
        assert "indent_size" in coding
        assert "preferred_test_framework" in tools or "testing_tool" in tools

    def test_set_preference_explicit(self, learner):
        """Test explicitly setting a preference."""
        pref = learner.set_preference("custom_key", "custom_value", category=PreferenceCategory.GENERAL)
        assert pref.key == "custom_key"
        assert pref.value == "custom_value"
        assert pref.category == PreferenceCategory.GENERAL
        assert pref.source == PreferenceSource.EXPLICIT
        assert learner.get_preference("custom_key") == "custom_value"

    def test_delete_preference(self, learner):
        """Test deleting a preference."""
        learner.set_preference("to_delete", "value")
        assert learner.get_preference("to_delete") == "value"
        result = learner.delete_preference("to_delete")
        assert result is True
        assert learner.get_preference("to_delete") is None

    def test_get_stats(self, learner):
        """Test getting statistics."""
        learner.learn_from_message("I prefer 4-space indentation")
        learner.learn_from_message("Use pytest for testing")
        stats = learner.get_stats()
        assert stats["total_preferences"] >= 2
        assert "coding_style" in stats["categories"]
        assert "tools" in stats["categories"]
        assert stats["avg_confidence"] > 0


class TestPreferenceApplier:
    """Test PreferenceApplier class."""

    @pytest.fixture
    def learner(self):
        test_dir = "test_pref_applier"
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)
        ltm = create_long_term_memory(workspace=test_dir, storage_path="prefs.json")
        learner = PreferenceLearner(ltm)
        yield learner
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)

    @pytest.fixture
    def applier(self, learner):
        return PreferenceApplier(learner)

    def test_apply_to_code_generation(self, learner, applier):
        """Test applying preferences to code generation context."""
        learner.learn_from_message("I prefer 4-space indentation")
        learner.learn_from_message("Use tabs for indentation")
        context = {}
        context = applier.apply_to_code_generation(context)
        assert "indent_size" in context or "indent_style" in context

    def test_apply_to_communication(self, learner, applier):
        """Test applying communication preferences."""
        learner.set_preference("verbose_output", True, category=PreferenceCategory.COMMUNICATION)
        learner.set_preference("concise_responses", True, category=PreferenceCategory.COMMUNICATION)
        context = {}
        context = applier.apply_to_communication(context)
        assert "comm_verbose_output" in context
        assert "comm_concise_responses" in context

    def test_apply_all(self, learner, applier):
        """Test applying all preferences."""
        learner.learn_from_message("I prefer 4-space indentation")
        learner.learn_from_message("Use pytest for testing")
        learner.set_preference("preferred_editor", "vscode", category=PreferenceCategory.ENVIRONMENT)
        context = {}
        context = applier.apply_all(context)
        assert len(context) > 0


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    @pytest.fixture(autouse=True)
    def isolated_global_learner(self, tmp_path, monkeypatch):
        """Use an explicitly allowed temporary workspace for global helpers."""
        learner = PreferenceLearner(
            create_long_term_memory(workspace=str(tmp_path), storage_path="prefs.json")
        )
        monkeypatch.setattr(
            preference_learning_module,
            "get_preference_learner",
            lambda: learner,
        )
        monkeypatch.setattr(preference_learning_module, "_applier", None)
        yield
        reset_global_learner()

    def test_learn_from_interaction(self):
        """Test learn_from_interaction function."""
        prefs = learn_from_interaction("I prefer 4-space indentation")
        assert len(prefs) >= 1

    def test_get_preference_function(self):
        """Test get_preference function."""
        value = get_preference("indent_size", default=2)
        assert value == 2  # Default since not learned yet

    def test_set_preference_function(self):
        """Test set_preference function."""
        pref = set_preference("test_key", "test_value", category=PreferenceCategory.GENERAL)
        assert pref.key == "test_key"
        assert pref.value == "test_value"

    def test_apply_preferences_function(self):
        """Test apply_preferences function."""
        context = {}
        context = apply_preferences(context)
        # Should at least add something if preferences exist


if __name__ == "__main__":
    pytest.main([__file__, "-v"])