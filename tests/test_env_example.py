"""`.env.example` documents every setting the app reads from the environment."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_environment_setting_is_in_env_example():
    settings_source = (ROOT / "config" / "settings.py").read_text()
    read = set(re.findall(r'env(?:\.[a-z]+)?\(\s*"([A-Z_]+)"', settings_source))
    documented = set(re.findall(r"^#?\s*([A-Z_]+)=", (ROOT / ".env.example").read_text(), re.M))
    assert read, "no settings found; the pattern above needs updating"
    assert read <= documented, f"missing from .env.example: {sorted(read - documented)}"
