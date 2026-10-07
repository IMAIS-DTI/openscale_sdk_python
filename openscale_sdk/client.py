"""Small JSON client for the OpenScale API (standard library only).

- Bearer token of a service account; the token never appears in errors or logs.
- Retries 429 and 502/503/504 (and connection errors) with backoff, honoring Retry-After.
- In a test run (dry_run=True) POST/PUT/PATCH/DELETE are not sent unless the call says allow_in_dry_run=True
  (for endpoints that have their own dryRun flag and only preview).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Optional

WRITES = {"POST", "PUT", "PATCH", "DELETE"}
RETRY_STATUS = {429, 502, 503, 504}


class OpenScaleError(Exception):
    def __init__(self, status: int, message: str, body: Any = None):
        super().__init__(f"OpenScale HTTP {status}: {message}")
        self.status = status
        self.body = body


class DryRunSkipped:
    """Returned instead of a response when a write is skipped in a test run."""

    def __init__(self, method: str, path: str):
        self.method, self.path = method, path

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"<dry-run: {self.method} {self.path} not sent>"


class OpenScaleClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 60, retries: int = 3, dry_run: bool = False,
                 log: Optional[Callable[..., None]] = None, user_agent: str = "openscale-sdk",
                 sleep: Callable[[float], None] = time.sleep):
        self.base_url = str(base_url or "").rstrip("/")
        self._token = token
        self.timeout = timeout
        self.retries = max(0, retries)
        self.dry_run = dry_run
        self._log = log or (lambda *a, **k: None)
        self.user_agent = user_agent
        self._sleep = sleep

    def __repr__(self) -> str:
        return f"<OpenScaleClient {self.base_url}>"

    def request(self, method: str, path: str, *, json_body: Any = None, params: Optional[dict] = None,
                allow_in_dry_run: bool = False) -> Any:
        method = method.upper()
        if not path.startswith("/"):
            raise ValueError("path must start with '/', e.g. /manager-api/tickets/kpis")
        if self.dry_run and method in WRITES and not allow_in_dry_run:
            self._log(f"[dry-run] {method} {path} not sent")
            return DryRunSkipped(method, path)
        url = self.base_url + path + (("?" + urllib.parse.urlencode(params, doseq=True)) if params else "")
        data = None if json_body is None else json.dumps(json_body).encode("utf-8")
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json", "User-Agent": self.user_agent}
        if data is not None:
            headers["Content-Type"] = "application/json"
        attempt = 0
        while True:
            attempt += 1
            req = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    if not raw:
                        return None
                    ctype = resp.headers.get("Content-Type", "")
                    return json.loads(raw) if "json" in ctype else raw
            except urllib.error.HTTPError as exc:
                raw = exc.read()
                body: Any
                try:
                    body = json.loads(raw)
                except Exception:  # noqa: BLE001
                    body = raw.decode("utf-8", "replace")[:500]
                if exc.code in RETRY_STATUS and attempt <= self.retries:
                    self._sleep(self._wait(exc.headers.get("Retry-After"), attempt))
                    continue
                message = (body.get("message") or body.get("error")) if isinstance(body, dict) else str(body)
                raise OpenScaleError(exc.code, str(message or exc.reason)[:300], body) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt <= self.retries:
                    self._sleep(self._wait(None, attempt))
                    continue
                reason = getattr(exc, "reason", exc)
                raise OpenScaleError(0, f"cannot reach {self.base_url}: {reason}") from None

    @staticmethod
    def _wait(retry_after: Optional[str], attempt: int) -> float:
        try:
            if retry_after:
                return min(60.0, float(retry_after))
        except ValueError:
            pass
        return min(30.0, 2 ** (attempt - 1))

    def get(self, path: str, **params) -> Any:
        return self.request("GET", path, params=params or None)

    def post(self, path: str, body: Any = None, **kw) -> Any:
        return self.request("POST", path, json_body=body, **kw)

    def put(self, path: str, body: Any = None, **kw) -> Any:
        return self.request("PUT", path, json_body=body, **kw)

    def patch(self, path: str, body: Any = None, **kw) -> Any:
        return self.request("PATCH", path, json_body=body, **kw)

    def delete(self, path: str, **kw) -> Any:
        return self.request("DELETE", path, **kw)
