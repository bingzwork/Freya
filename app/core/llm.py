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


class LLM:

    def __init__(self, model="qwen2.5-coder:14b"):
        self.model = model

    def ask(self, prompt, system="You are Falco, an AI software engineer."):
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
