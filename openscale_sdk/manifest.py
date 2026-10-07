"""openscale.yaml (schema 1) — the same rules the OpenScale server applies when it saves or runs a Git script.

`validate_manifest(data)` works on an already parsed mapping (no dependency). `load_manifest(path)` parses YAML and
needs PyYAML (`pip install "openscale-sdk[manifest]"`), which CI installs; the runner never needs it.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

MANIFEST_FILE = "openscale.yaml"
LANGUAGES = ("python", "bash", "sh", "powershell")
_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_VAR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _safe_path(p: Any) -> Optional[str]:
    s = str(p or "")
    parts = [x for x in s.split("/") if x and x != "."]
    if not parts or s.startswith("/") or ".." in parts:
        return None
    return "/".join(parts)


def validate_manifest(data: Any) -> tuple[Optional[dict], list[str]]:
    """Return (normalized manifest, errors). An empty error list means valid."""
    if not isinstance(data, dict):
        return None, ["openscale.yaml must be a mapping"]
    errors: list[str] = []
    if data.get("schema") != 1:
        errors.append("schema: only version 1 is supported")
    name = str(data.get("name") or "").strip()
    if not _NAME.match(name):
        errors.append("name: required; lowercase letters, digits, '.', '-' or '_' (max 80)")
    rt = data.get("runtime") if isinstance(data.get("runtime"), dict) else {}
    language = str(rt.get("language") or "").lower()
    if language not in LANGUAGES:
        errors.append(f"runtime.language: use {', '.join(LANGUAGES)}")
    entrypoint = _safe_path(rt.get("entrypoint"))
    if not entrypoint:
        errors.append("runtime.entrypoint: required, relative to the manifest")
    requirements = None if rt.get("requirements") is None else _safe_path(rt.get("requirements"))
    if rt.get("requirements") is not None and not requirements:
        errors.append("runtime.requirements: invalid path")
    ex = data.get("execution") if isinstance(data.get("execution"), dict) else {}
    timeout = ex.get("timeout_seconds")
    if timeout is not None:
        try:
            ok = 30 <= float(timeout) <= 3600
        except (TypeError, ValueError):
            ok = False
        if not ok:
            errors.append("execution.timeout_seconds: 30 to 3600")
    variables: dict[str, dict] = {}
    vs = data.get("variables") if isinstance(data.get("variables"), dict) else {}
    for vname, spec in vs.items():
        if not _VAR.match(str(vname)):
            errors.append(f"variables.{vname}: invalid name")
            continue
        d = spec if isinstance(spec, dict) else {}
        default = d.get("default")
        variables[vname] = {"secret": d.get("secret") is True, "required": d.get("required") is True,
                            "default": None if default is None else str(default), "description": str(d.get("description") or "")[:300]}
        if variables[vname]["secret"] and variables[vname]["default"] is not None:
            errors.append(f"variables.{vname}: a secret cannot have a default in the repository")
    manifest = {
        "schema": 1, "name": name, "description": str(data.get("description") or "")[:500], "owner": str(data.get("owner") or "")[:120],
        "runtime": {"language": language, "entrypoint": entrypoint or "", "requirements": requirements or ""},
        "execution": {"timeout_seconds": timeout, "dry_run": ex.get("dry_run") is True,
                      "runner_tags": [str(t).lower() for t in (ex.get("runner_tags") or [])][:10] if isinstance(ex.get("runner_tags"), list) else []},
        "variables": variables,
        "permissions": [str(p)[:80] for p in (data.get("permissions") or [])][:40] if isinstance(data.get("permissions"), list) else [],
    }
    return manifest, errors


def load_manifest(folder: "str | Path" = ".") -> tuple[Optional[dict], list[str]]:
    """Read and validate <folder>/openscale.yaml, and check that the files it points to exist."""
    try:
        import yaml  # type: ignore
    except ImportError:
        return None, ['PyYAML is required to read openscale.yaml: pip install "openscale-sdk[manifest]"']
    root = Path(folder)
    path = root / MANIFEST_FILE
    if not path.is_file():
        return None, [f"{path} not found"]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return None, [f"openscale.yaml is not valid YAML: {exc}"]
    manifest, errors = validate_manifest(data)
    if manifest:
        if manifest["runtime"]["entrypoint"] and not (root / manifest["runtime"]["entrypoint"]).is_file():
            errors.append(f"runtime.entrypoint: {manifest['runtime']['entrypoint']} does not exist")
        if manifest["runtime"]["requirements"] and not (root / manifest["runtime"]["requirements"]).is_file():
            errors.append(f"runtime.requirements: {manifest['runtime']['requirements']} does not exist")
    return manifest, errors
