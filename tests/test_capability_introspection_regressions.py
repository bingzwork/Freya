from types import SimpleNamespace
from app.capabilities.handlers import handle_capability_introspection


class Registry:
    def __init__(self, capabilities):
        self._capabilities = {cap.metadata.name: cap for cap in capabilities}

    def get_all(self):
        return dict(self._capabilities)


def capability(name, aliases, actions):
    metadata = SimpleNamespace(name=name, description=f'{name} capability', aliases=aliases, tags=[], supported_actions=actions, dependencies=[])
    return SimpleNamespace(metadata=metadata, state=SimpleNamespace(value='active'), is_executable=lambda: True)


def test_capability_questions_use_authoritative_aliases():
    registry = Registry([
        capability('research_capability', ['websearch', 'web search', 'deep research', 'research'], ['search_web', 'research_topic']),
        capability('image', ['image generation', 'generate image', 'create image'], ['generate']),
    ])
    cases = {
        'can you do websearch?': 'research_capability',
        'can you do web search?': 'research_capability',
        'can you do deep research?': 'research_capability',
        'can you generate an image?': 'image',
    }
    for query, expected in cases.items():
        result = handle_capability_introspection({'query': query, 'capability_registry': registry})
        assert result.data['capability'] == expected
        assert result.data['authoritative_source'] == 'CapabilityRegistry'


def test_capability_introspection_reports_unavailable_registered_capability():
    cap = capability('image', ['generate image'], ['generate'])
    cap.state = SimpleNamespace(value='inactive')
    result = handle_capability_introspection({'query': 'can you generate an image?', 'capability_registry': Registry([cap])})
    assert result.data['registered'] is True
    assert result.data['available'] is False
    assert 'registered' in result.message.lower()
