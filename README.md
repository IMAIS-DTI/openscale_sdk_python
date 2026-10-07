# openscale-sdk

Helpers for scripts that run as **OpenScale automations** on the OpenScale runner: configuration from the
environment, test runs (dry run), masked logs, a run summary, artifacts and a small API client. Standard library
only (Python 3.9+).

The run-time contract (environment, folders, limits, `openscale.yaml`) is described in the OpenScale guide
[Automações como código](https://openscale.clickip.com.br/guias/automacoes-como-codigo/).

## Install

Pin a tag in the automation's `requirements.txt`:

```
openscale-sdk @ git+https://github.com/IMAIS-DTI/openscale_sdk_python@v0.1.1
```

The runner builds a virtual environment from `requirements.txt` and reuses it between runs.

## Use

```python
import sys
from openscale_sdk import Automation

app = Automation()                                   # reads OPENSCALE_* and DRY_RUN
ad_url = app.var("AD_URL", required=True)
ad_password = app.var("AD_PASSWORD", required=True, secret=True)
batch = app.var("BATCH", default="50", cast=int)
api = app.openscale()                                # OPENSCALE_URL + OPENSCALE_TOKEN (or OPENSCALE_API)

def main() -> int:
    current = api.get("/manager-api/some/resource")
    changes = plan(current)                          # pure function, unit-tested
    app.log(f"{len(changes)} planned change(s)")
    for c in changes:
        api.post("/manager-api/some/resource", c)    # not sent in a test run
    app.summary(planned=len(changes), applied=0 if app.dry_run else len(changes))
    app.artifact("changes.csv", to_csv(changes))
    return 0

sys.exit(app.run(main))
```

| API | Behavior |
|---|---|
| `app.var(name, required=, default=, secret=, cast=)` | Reads an environment variable. Missing required or invalid values are reported together and `run` exits with **2** before calling `main`. `secret=True` masks the value in every log line. |
| `app.dry_run` | `True` when OpenScale runs the routine as a test (`DRY_RUN=1` / `OPENSCALE_DRY_RUN=1`). |
| `app.openscale()` | `OpenScaleClient` with the service-account token from the vault. In a test run, `post`/`put`/`patch`/`delete` are **not sent** (they return a falsy `DryRunSkipped`) unless the call passes `allow_in_dry_run=True`. Retries 429/502/503/504. |
| `app.log(msg, level="info")` | Prints with secrets replaced by `••••••`; `level="error"` goes to stderr. |
| `app.summary(**fields)` | Merges fields into the run summary; OpenScale shows them as cards in the run detail. |
| `app.artifact(name, data)` | Saves a file (bytes, text or a `Path`) that OpenScale attaches to the run: up to 10 files, 10 MB each. |
| `app.run(main)` | Runs `main` and returns the exit code: `0` success, `1` failure (masked traceback), `2` configuration, `130` interrupted. |
| `mask_phone`, `mask_email` | Personal data in logs: `***1234`, `a***@example.com`. |

Never print a secret in a transformed form (split, encoded): masking only recognizes the exact value.

## Validate `openscale.yaml` in CI

```bash
pip install "openscale-sdk[manifest] @ git+https://github.com/IMAIS-DTI/openscale_sdk_python@v0.1.1"
python -m openscale_sdk validate .
```

The rules are the same the OpenScale server applies when it saves or runs a Git script.

## Develop

```bash
python -m unittest discover -s tests -v
```

## License

Apache-2.0.
