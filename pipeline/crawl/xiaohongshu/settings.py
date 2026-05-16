from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]  # pipeline/
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "data" / "xiaohongshu" / "config.yaml"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "data" / "xiaohongshu" / "config.example.yaml"


class SettingsError(RuntimeError):
    pass


class Settings:
    def __init__(self, data: dict[str, Any], root: Path = PROJECT_ROOT):
        self.data = data
        self.root = root

    def get(self, dotted_key: str, default: Any = None) -> Any:
        current: Any = self.data
        for key in dotted_key.split("."):
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

    def require_env(self, dotted_key: str) -> str:
        env_name = self.get(dotted_key)
        if not env_name:
            raise SettingsError(f"Missing config key: {dotted_key}")
        value = os.environ.get(str(env_name))
        if not value:
            raise SettingsError(f"Missing environment variable: {env_name}")
        return value

    def path(self, dotted_key: str, default: str) -> Path:
        value = self.get(dotted_key, default)
        path = Path(str(value))
        if path.is_absolute():
            return path
        return self.root / path


def load_settings(config_path: str | Path) -> Settings:
    root = PROJECT_ROOT
    load_dotenv(root.parent / "backend" / ".env")

    path = Path(config_path)
    if not path.is_absolute():
        path = root / path
    if not path.exists():
        if path == DEFAULT_CONFIG_PATH:
            raise SettingsError(
                "Config file does not exist: "
                f"{path}. Copy {EXAMPLE_CONFIG_PATH} to {DEFAULT_CONFIG_PATH} first."
            )
        raise SettingsError(f"Config file does not exist: {path}")

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise SettingsError("Config root must be a YAML object")
    return Settings(data, root=root)
