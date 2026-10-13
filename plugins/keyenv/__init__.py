"""``/key`` — save an API key into ``~/.hermes/.env`` without the value reaching the model.

The gateway dispatches plugin slash commands before the agent turn (gateway/run_inbound.py,
``_hm_dispatch_quick_and_plugin_commands``), so the text of ``/key NAME VALUE`` is consumed by
``command()`` here and never enters a provider request. The value is never echoed, never logged,
and is registered with :mod:`agent.redact` so a later tool that prints .env cannot pull it into
model context.

Use only in a DM: anything typed in a group is visible to everyone in that group.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_USAGE = ("Usage:\n"
          "  /key NAME VALUE   save NAME=VALUE into ~/.hermes/.env\n"
          "  /key list         list saved variable names\n"
          "  /key rm NAME      remove one")


def _env_path() -> Path:
    try:
        from hermes_constants import get_hermes_home

        return Path(get_hermes_home()) / ".env"
    except Exception:  # not running inside Hermes (self-test, plain python)
        return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes")) / ".env"


def _quote(value: str) -> str:
    """Render *value* so python-dotenv reads back exactly what went in."""
    if value and not any(c in value for c in ' \t#"\''):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _write(name: str, value: str) -> str:
    path = _env_path()
    line = f"{name}={_quote(value)}"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(rf"^{re.escape(name)}=.*$", re.M)
    replaced = bool(pattern.search(old))
    if replaced:
        new = pattern.sub(lambda _m: line, old, count=1)
    else:
        new = (old if not old or old.endswith("\n") else old + "\n") + line + "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".keyenv.tmp")
    tmp.write_text(new, encoding="utf-8")
    os.chmod(tmp, 0o600)
    from utils import atomic_replace  # same atomic seam the rest of Hermes uses

    atomic_replace(tmp, path)
    os.environ[name] = value  # usable by this process immediately; others on next start
    return "updated" if replaced else "saved"


def _remove(name: str) -> bool:
    path = _env_path()
    if not path.exists():
        return False
    old = path.read_text(encoding="utf-8")
    new, n = re.subn(rf"^{re.escape(name)}=.*\n?", "", old, flags=re.M)
    if not n:
        return False
    tmp = path.with_name(path.name + ".keyenv.tmp")
    tmp.write_text(new, encoding="utf-8")
    os.chmod(tmp, 0o600)
    from utils import atomic_replace

    atomic_replace(tmp, path)
    os.environ.pop(name, None)
    return True


def _names() -> list[str]:
    path = _env_path()
    if not path.exists():
        return []
    return [m.group(1) for m in re.finditer(r"^([A-Za-z_][A-Za-z0-9_]*)=", path.read_text(encoding="utf-8"), re.M)]


def command(raw_args: str) -> str:
    """Handler for ``/key``: ``fn(raw_args) -> str``."""
    args = (raw_args or "").strip()
    if not args:
        return _USAGE

    head, _, rest = args.partition(" ")
    if head == "list":
        names = _names()
        return "In ~/.hermes/.env: " + (", ".join(names) if names else "(no keys)")
    if head == "rm":
        target = rest.strip()
        if not _NAME_RE.match(target):
            return "Usage: /key rm NAME"
        return f"Removed {target}." if _remove(target) else f"{target} is not in .env."

    name, _, value = args.partition(" ")
    value = value.strip()
    if not _NAME_RE.match(name) or not value or "\n" in value:
        return _USAGE
    value = value.replace("\r", "")

    try:
        from agent.redact import register_vault_redaction_value

        register_vault_redaction_value(value)  # keeps the bytes out of model context
    except Exception:
        pass

    action = _write(name, value)
    return f"{name} {action} in ~/.hermes/.env ({len(value)} chars). Not echoed, not logged."


def register(ctx):
    ctx.register_command(
        "key",
        command,
        description="Save an API key into .env without exposing it to the model",
        args_hint="<NAME> <value> | list | rm <NAME>",
    )


# --- self-check: python ~/.hermes/plugins/keyenv/__init__.py -------------------------------
if __name__ == "__main__":
    import tempfile

    home = tempfile.mkdtemp()
    os.environ["HERMES_HOME"] = home
    env = Path(home) / ".env"

    secret = "test-value-9f8Kq2Zz"
    out = command(f"OPENROUTER_API_KEY {secret}")
    assert "OPENROUTER_API_KEY" in out and secret not in out, out
    assert env.read_text().strip() == f"OPENROUTER_API_KEY={secret}", env.read_text()
    assert oct(env.stat().st_mode)[-3:] == "600", oct(env.stat().st_mode)

    # replacement must not duplicate the line, and must not mangle other keys
    env.write_text(env.read_text() + "OTHER_TOKEN=keepme\n")
    command(f"OPENROUTER_API_KEY {secret}-2")
    body = env.read_text()
    assert body.count("OPENROUTER_API_KEY=") == 1 and "OTHER_TOKEN=keepme" in body, body
    assert secret not in command("list"), command("list")

    # quoting round-trips through the same parser Hermes loads .env with
    weird = 'p@ss "w0rd" #1'
    command(f"WEIRD_SECRET {weird}")
    from dotenv import dotenv_values

    assert dotenv_values(env)["WEIRD_SECRET"] == weird, dotenv_values(env)["WEIRD_SECRET"]

    assert command("rm WEIRD_SECRET").startswith("Removed")
    assert "WEIRD_SECRET" not in env.read_text()
    assert command("").startswith("Usage")
    assert command("FOO").startswith("Usage")          # no value
    assert command("9BAD v").startswith("Usage")       # invalid name
    command("SPACED bar baz")                          # a value may contain spaces
    assert dotenv_values(env)["SPACED"] == "bar baz", dotenv_values(env)["SPACED"]
    print("self-check ok:", home)
