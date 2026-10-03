"""Loads config.yaml (or the example) and the .env file."""

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def load_dotenv(path: Path = ROOT / ".env") -> None:
    """Minimal .env reader so users don't need another dependency.

    Values already set in the real environment win over the file.
    """
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ.setdefault(key.strip(), value)


def load_config(path: str | None = None) -> dict:
    load_dotenv()
    if path:
        config_path = Path(path)
    elif (ROOT / "config.yaml").exists():
        config_path = ROOT / "config.yaml"
    else:
        config_path = ROOT / "config.example.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)
    config["_path"] = str(config_path)
    return config


def has_anthropic_credentials() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    # `ant auth login` stores a profile the SDK picks up automatically.
    return (Path.home() / ".config" / "anthropic").exists()


def has_openai_credentials() -> bool:
    return bool(os.environ.get("OPENAI_API_KEY"))


def has_printify_credentials() -> bool:
    return bool(os.environ.get("PRINTIFY_API_TOKEN"))
