"""CLI entry point for streamforge."""
from streamforge.cli import app

# Backward-compatible re-exports: existing tests patch these on
# ``streamforge.__main__``, so they must remain importable here.
from streamforge.topic_config import load_topic_config as load_topic_config  # noqa: F401

if __name__ == "__main__":
    app()
