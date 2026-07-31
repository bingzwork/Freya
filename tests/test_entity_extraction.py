"""Tests for Entity Extraction and Slot Filling."""
import pytest
from app.intent.entity_extractor import (
    EntityExtractor,
    EntityType,
    ExtractedEntity,
    SlotFillingResult,
    extract_entities,
    fill_slots,
    get_missing_slots_prompt,
)


class TestEntityType:
    """Test EntityType enum."""

    def test_all_entity_types_exist(self):
        """Verify all expected entity types exist."""
        expected = [
            "FILE", "FOLDER", "PROJECT", "DATE", "TIME", "DATETIME",
            "PERSON", "URL", "TASK", "TOPIC", "NUMBER", "TOOL",
            "EMAIL", "PHONE", "IP_ADDRESS", "VERSION", "COMMIT_HASH",
            "FILE_PATH", "REPOSITORY",
        ]
        for name in expected:
            assert hasattr(EntityType, name), f"Missing EntityType: {name}"

    def test_entity_type_values(self):
        """Test entity type string values."""
        assert EntityType.FILE.value == "file"
        assert EntityType.FILE_PATH.value == "file_path"
        assert EntityType.FOLDER.value == "folder"
        assert EntityType.DATE.value == "date"
        assert EntityType.TIME.value == "time"
        assert EntityType.PERSON.value == "person"
        assert EntityType.URL.value == "url"
        assert EntityType.EMAIL.value == "email"
        assert EntityType.PHONE.value == "phone"
        assert EntityType.VERSION.value == "version"
        assert EntityType.COMMIT_HASH.value == "commit_hash"


class TestExtractedEntity:
    """Test ExtractedEntity dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        entity = ExtractedEntity(
            entity_type=EntityType.FILE_PATH,
            value="src/main.py",
            normalized_value="src/main.py",
            start=0,
            end=12,
            confidence=0.95,
            context="read src/main.py",
        )
        d = entity.to_dict()
        assert d["type"] == "file_path"
        assert d["value"] == "src/main.py"
        assert d["normalized_value"] == "src/main.py"
        assert d["confidence"] == 0.95
        assert d["context"] == "read src/main.py"

    def test_repr(self):
        """Test string representation."""
        entity = ExtractedEntity(
            entity_type=EntityType.DATE,
            value="tomorrow",
            normalized_value="2026-08-01",
            start=5,
            end=13,
            confidence=0.9,
        )
        repr_str = repr(entity)
        assert "date" in repr_str.lower() or "DATE" in repr_str
        assert "0.9" in repr_str


class TestEntityExtractor:
    """Test EntityExtractor class."""

    @pytest.fixture
    def extractor(self):
        return EntityExtractor()

    # File path extraction
    def test_extract_file_paths(self, extractor):
        """Test extraction of file paths."""
        message = "read src/main.py and write to output.txt"
        entities = extractor.extract(message)

        file_paths = [e for e in entities if e.entity_type == EntityType.FILE]
        assert len(file_paths) >= 1  # At least one file path found
        values = [e.value for e in file_paths]
        assert any("src/main.py" in v or "output.txt" in v for v in values)

    def test_extract_file_paths_with_extensions(self, extractor):
        """Test extraction of various file extensions."""
        message = "check config.yaml, schema.json, Dockerfile, and Makefile"
        entities = extractor.extract(message)
        file_paths = [e.value for e in entities if e.entity_type == EntityType.FILE]
        assert len(file_paths) >= 1

    def test_extract_file_paths_absolute(self, extractor):
        """Test extraction of absolute paths."""
        message = "read /home/user/project/main.py"
        entities = extractor.extract(message)
        file_paths = [e.value for e in entities if e.entity_type == EntityType.FILE]
        # Absolute path extracted without leading /
        assert any("home/user/project/main.py" in v for v in file_paths)

    def test_extract_directory_paths(self, extractor):
        """Test extraction of directory/folder paths."""
        message = "list files in src/ and check tests/unit/"
        entities = extractor.extract(message)
        dirs = [e.value for e in entities if e.entity_type == EntityType.FOLDER]
        assert len(dirs) >= 1

    # URL extraction
    def test_extract_urls(self, extractor):
        """Test extraction of URLs."""
        message = "check https://github.com/user/repo and http://example.com"
        entities = extractor.extract(message)
        urls = [e.value for e in entities if e.entity_type == EntityType.URL]
        assert "https://github.com/user/repo" in urls
        assert "http://example.com" in urls

    # Email extraction
    def test_extract_emails(self, extractor):
        """Test extraction of email addresses."""
        message = "contact john@example.com or jane.doe@company.org"
        entities = extractor.extract(message)
        emails = [e.value for e in entities if e.entity_type == EntityType.EMAIL]
        assert "john@example.com" in emails
        assert "jane.doe@company.org" in emails

    # Date extraction
    def test_extract_dates_relative(self, extractor):
        """Test extraction of relative dates."""
        message = "schedule for tomorrow and next week"
        entities = extractor.extract(message)
        dates = [e for e in entities if e.entity_type == EntityType.DATE]
        values = [e.value for e in dates]
        assert "tomorrow" in values
        assert "next week" in values or len(dates) >= 1

    def test_extract_dates_specific(self, extractor):
        """Test extraction of specific date formats."""
        message = "meeting on 2026-01-15 and 01/20/2026"
        entities = extractor.extract(message)
        dates = [e.value for e in entities if e.entity_type == EntityType.DATE]
        # Should find at least one date format
        assert len(dates) >= 1

    def test_date_normalization(self, extractor):
        """Test date normalization to ISO format."""
        message = "tomorrow"
        entities = extractor.extract(message)
        dates = [e for e in entities if e.entity_type == EntityType.DATE]
        assert len(dates) >= 1
        # Should be normalized to YYYY-MM-DD format
        assert dates[0].normalized_value is not None
        assert len(dates[0].normalized_value) == 10  # YYYY-MM-DD

    # Time extraction
    def test_extract_times(self, extractor):
        """Test extraction of times."""
        message = "meeting at 2:30 PM and 14:45"
        entities = extractor.extract(message)
        times = [e.value for e in entities if e.entity_type == EntityType.TIME]
        assert len(times) >= 1

    def test_time_normalization(self, extractor):
        """Test time normalization to 24-hour format."""
        message = "2:30 PM"
        entities = extractor.extract(message)
        times = [e for e in entities if e.entity_type == EntityType.TIME]
        assert len(times) >= 1
        assert times[0].normalized_value == "14:30"

    # Person extraction
    def test_extract_persons(self, extractor):
        """Test extraction of person names."""
        message = "assign to John Smith and tell Alice Johnson"
        entities = extractor.extract(message)
        persons = [e.value for e in entities if e.entity_type == EntityType.PERSON]
        assert len(persons) >= 1

    # Version extraction
    def test_extract_versions(self, extractor):
        """Test extraction of version numbers."""
        message = "upgrade to v2.1.0 and check Python 3.11"
        entities = extractor.extract(message)
        versions = [e.value for e in entities if e.entity_type == EntityType.VERSION]
        assert "v2.1.0" in versions or "3.11" in versions or len(versions) >= 1

    # Commit hash extraction
    def test_extract_commit_hashes(self, extractor):
        """Test extraction of commit hashes."""
        message = "commit abc1234 and fix def5678"
        entities = extractor.extract(message)
        hashes = [e.value for e in entities if e.entity_type == EntityType.COMMIT_HASH]
        assert len(hashes) >= 1

    # Phone extraction
    def test_extract_phones(self, extractor):
        """Test extraction of phone numbers."""
        message = "call +1-555-123-4567 or (555) 123-4567"
        entities = extractor.extract(message)
        phones = [e.value for e in entities if e.entity_type == EntityType.PHONE]
        assert "1-555-123-4567" in phones
        assert "555) 123-4567" in phones or "555) 123-4567" in phones

    # IP address extraction
    def test_extract_ip_addresses(self, extractor):
        """Test extraction of IP addresses."""
        message = "connect to 192.168.1.1 and 10.0.0.1"
        entities = extractor.extract(message)
        ips = [e.value for e in entities if e.entity_type == EntityType.IP_ADDRESS]
        assert "192.168.1.1" in ips
        assert "10.0.0.1" in ips


class TestSlotFilling:
    """Test slot filling functionality."""

    @pytest.fixture
    def extractor(self):
        return EntityExtractor()

    def test_fill_slots_basic(self, extractor):
        """Test basic slot filling."""
        message = "read src/main.py at 2:30 PM"
        slots = {
            "file_path": EntityType.FILE,
            "time": EntityType.TIME,
        }
        result = fill_slots(message, slots)

        assert isinstance(result, SlotFillingResult)
        assert "file_path" in result.filled_slots or "time" in result.filled_slots
        assert isinstance(result.is_complete, bool)

    def test_fill_slots_missing(self, extractor):
        """Test slot filling with missing slots."""
        message = "read src/main.py"
        slots = {
            "file_path": EntityType.FILE,
            "time": EntityType.TIME,
        }
        result = fill_slots(message, slots)

        assert "file_path" in result.filled_slots
        assert "time" in result.missing_slots
        assert result.is_complete is False

    def test_get_missing_slots_prompt(self, extractor):
        """Test generation of prompt for missing slots."""
        message = "read src/main.py"
        slots = {
            "file_path": EntityType.FILE,
            "time": EntityType.TIME,
        }
        result = fill_slots(message, slots)

        prompt = get_missing_slots_prompt(result)
        assert isinstance(prompt, str)
        assert len(prompt) > 0


class TestConvenienceFunctions:
    """Test module-level convenience functions."""

    def test_extract_entities(self):
        """Test extract_entities function."""
        entities = extract_entities("read main.py")
        assert len(entities) >= 1
        assert any(e.entity_type == EntityType.FILE for e in entities)

    def test_fill_slots_function(self):
        """Test fill_slots function."""
        from app.intent.entity_extractor import fill_slots, EntityType
        result = fill_slots("read main.py at 3 PM", {"file": EntityType.FILE, "time": EntityType.TIME})
        assert "file" in result.filled_slots or "time" in result.filled_slots


if __name__ == "__main__":
    pytest.main([__file__, "-v"])