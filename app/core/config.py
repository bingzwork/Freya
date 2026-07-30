import os
from pathlib import Path
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent.parent

ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)


class Config:

    def __init__(self):

        self.project_name = os.getenv(
            "PROJECT_NAME",
            "Freya",
        )

        self.model = os.getenv(
            "MODEL",
            "qwen3:8b",
        )

        self.workspace = os.getenv(
            "WORKSPACE",
            str(BASE_DIR),
        )

        self.memory_path = os.getenv(
            "MEMORY_PATH",
            "data/memory",
        )

        self.vector_path = os.getenv(
            "VECTOR_PATH",
            "data/vector_db",
        )


    def get(self, key, default=None):

        return os.getenv(
            key,
            default,
        )


config = Config()