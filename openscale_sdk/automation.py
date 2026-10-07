"""The run-time side of an OpenScale automation: configuration, dry run, logging, summary and artifacts.

A script that follows the contract (https://openscale.clickip.com.br/guias/automacoes-como-codigo/) only talks to its
environment through this object::

    app = Automation()
    token = app.var("SOME_TOKEN", required=True, secret=True)
    api = app.openscale()

    def main() -> int:
        ...
        app.summary(processed=10)
        return 0

    sys.exit(app.run(main))
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from .client import OpenScaleClient
from .masking import MASK, Masker

ARTIFACT_NAME = re.compile(r"^(?!\.)[A-Za-z0-9._-]{1,100}$")
TRUE = {"1", "true", "yes", "sim", "on"}

EXIT_OK = 0
EXIT_FAILURE = 1
EXIT_CONFIG = 2
EXIT_INTERRUPTED = 130


class ConfigError(Exception):
    """Invalid or missing configuration. `Automation.run` turns it into exit code 2."""


def _flag(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in TRUE


class Automation:
    """Configuration, dry run, masked logging, summary and artifacts for one run."""

    def __init__(self, env: Optional[Mapping[str, str]] = None, stdout=None, stderr=None):
        self.env: Mapping[str, str] = os.environ if env is None else env
        self._out = stdout or sys.stdout
        self._err = stderr or sys.stderr
        self._missing: list[str] = []
        self._invalid: list[str] = []
        self._summary: dict[str, Any] = {}
        self.masker = Masker()
        self.dry_run: bool = _flag(self.env.get("DRY_RUN")) or _flag(self.env.get("OPENSCALE_DRY_RUN"))
        self.name: str = self.env.get("OPENSCALE_AUTOMATION", "")
        self.run_id: str = self.env.get("OPENSCALE_RUN_ID", "")
        self.commit: str = self.env.get("OPENSCALE_COMMIT", "")
        self.ref: str = self.env.get("OPENSCALE_REF", "")
        tmp = self.env.get("OPENSCALE_TMP") or tempfile.gettempdir()
        self.workdir = Path(self.env.get("OPENSCALE_WORKDIR") or os.getcwd())
        self.tmp = Path(tmp)
        self.cache = Path(self.env.get("OPENSCALE_CACHE") or Path(tempfile.gettempdir()) / "openscale-cache")
        self.artifacts_dir = Path(self.env.get("OPENSCALE_ARTIFACTS") or Path(tmp) / "openscale-artifacts")
        self._summary_file = self.env.get("OPENSCALE_SUMMARY") or ""

    # ---------- configuration ----------

    def var(self, name: str, *, required: bool = False, default: Optional[str] = None, secret: bool = False,
            cast: Optional[Callable[[str], Any]] = None) -> Any:
        """Read one environment variable. Missing required variables are collected and reported by `run` (exit 2)."""
        value = self.env.get(name)
        if value is None or value == "":
            if default is not None:
                value = default
            else:
                if required:
                    self._missing.append(name)
                return None
        if secret:
            self.masker.add(value)
        if cast is not None:
            try:
                return cast(value)
            except Exception as exc:  # noqa: BLE001 - any cast error is a configuration error
                self._invalid.append(f"{name}: {exc}")
                return None
        return value

    def require(self) -> None:
        """Raise ConfigError now if any required variable is missing (`run` does it before calling main)."""
        problems = []
        if self._missing:
            problems.append("missing required variables: " + ", ".join(dict.fromkeys(self._missing)))
        if self._invalid:
            problems.append("invalid variables: " + "; ".join(self._invalid))
        if problems:
            raise ConfigError(" | ".join(problems))

    def openscale(self, token_vars: tuple[str, ...] = ("OPENSCALE_TOKEN", "OPENSCALE_API"), **kwargs) -> OpenScaleClient:
        """API client for the OpenScale this run belongs to, with the service account token from the vault."""
        url = self.env.get("OPENSCALE_URL", "")
        token = next((self.env[n] for n in token_vars if self.env.get(n)), "")
        if not url:
            self._missing.append("OPENSCALE_URL")
        if not token:
            self._missing.append(token_vars[0])
        self.masker.add(token)
        user_agent = f"openscale-sdk ({self.name or 'automation'}{f'; run {self.run_id}' if self.run_id else ''})"
        return OpenScaleClient(url, token, dry_run=self.dry_run, log=self.log, user_agent=user_agent, **kwargs)

    # ---------- output ----------

    def mask(self, text: Any) -> str:
        return self.masker.mask(str(text))

    def log(self, message: Any, level: str = "info") -> None:
        prefix = {"warn": "[warn] ", "warning": "[warn] ", "error": "[error] "}.get(level, "")
        stream = self._err if level == "error" else self._out
        print(prefix + self.mask(message), file=stream, flush=True)

    def summary(self, **fields: Any) -> dict:
        """Merge fields into the run summary. Shown as cards in the run detail (OPENSCALE_SUMMARY)."""
        self._summary.update(fields)
        self._write_summary()
        return dict(self._summary)

    def _write_summary(self) -> None:
        if not self._summary_file:
            return
        data = json.loads(self.mask(json.dumps(self._summary, ensure_ascii=False, default=str)))
        path = Path(self._summary_file)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def artifact(self, name: str, data) -> Path:
        """Save a file the run keeps (image, CSV, report). `data` is bytes, str or a path to copy."""
        if not ARTIFACT_NAME.match(name):
            raise ValueError(f"invalid artifact name {name!r}: letters, digits, '.', '-', '_' (max 100)")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        target = self.artifacts_dir / name
        if isinstance(data, (bytes, bytearray)):
            target.write_bytes(bytes(data))
        elif isinstance(data, Path):
            target.write_bytes(data.read_bytes())
        else:
            target.write_text(str(data), encoding="utf-8")
        return target

    # ---------- run ----------

    def run(self, main: Callable[[], Optional[int]]) -> int:
        """Call main() and turn the outcome into the exit code of the contract (0, 1, 2 or 130)."""
        try:
            self.require()
            if self.dry_run:
                self.log("test run (DRY_RUN=1): nothing is written")
            code = main()
            return EXIT_OK if code is None else int(code)
        except ConfigError as exc:
            self.log(f"configuration: {exc}", "error")
            return EXIT_CONFIG
        except KeyboardInterrupt:
            self.log("interrupted", "error")
            return EXIT_INTERRUPTED
        except Exception as exc:  # noqa: BLE001 - last line of defense, always masked
            frames = traceback.format_exception(type(exc), exc, exc.__traceback__)
            self.log("".join(frames[-3:]).rstrip(), "error")
            return EXIT_FAILURE
        finally:
            if self._summary and not self._summary_file:
                self.log("summary: " + json.dumps(self._summary, ensure_ascii=False, default=str))


__all__ = ["Automation", "ConfigError", "MASK", "EXIT_OK", "EXIT_FAILURE", "EXIT_CONFIG", "EXIT_INTERRUPTED"]
