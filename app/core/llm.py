# Optional import for ollama
try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    # Create a mock ollama module for when it's not available
    class _MockOllama:
        def __getattr__(self, name):
            # Return a mock function that returns a default response
            return lambda *args, **kwargs: {"message": {"content": "[LLM response not available - ollama not installed]"}}

    ollama = _MockOllama()


# Canonical Freya system prompt. Used as the default system message for every
# LLM call so the persona, environment, and behaviour guidance live in exactly
# one place. Per-call prompts should not restate these traits.
FREYA_SYSTEM_PROMPT = (
    "You are Freya, an autonomous AI software engineer.\n"
    "Engine focus: Windows-first, Python-first, PowerShell-first.\n"
    "Aware of: the current Git state, the active Ollama model, and the default LLM provider.\n"
    "Behave like an engineer: think briefly, act deliberately, and produce well-formed plans and clean, minimal code. "
    "Reason from the context in front of you. Prefer the smallest correct change. "
    "Skip hedging, filler, invented tools, and any step you cannot justify."
)


class LLM:

    def __init__(self, model="qwen2.5-coder:14b"):
        self.model = model

    def ask(self, prompt, system=FREYA_SYSTEM_PROMPT):
        if not OLLAMA_AVAILABLE:
            # Return a informative message when ollama is not available
            return "[LLM response not available - ollama not installed]\n\nOriginal prompt: {}\n\nSystem prompt: {}".format(
                prompt[:100] + ("..." if len(prompt) > 100 else ""),
                system[:100] + ("..." if len(system) > 100 else "")
            )

        response = ollama.chat(

            model=self.model,


            messages=[

                {

                    "role": "system",


                    "content": system,

                },

                {

                    "role": "user",


                    "content": prompt,

                },

            ],

        )

        return response["message"]["content"]
