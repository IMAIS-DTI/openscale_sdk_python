"""Tests of the SDK (stdlib unittest; no network except a local HTTP server)."""

import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from openscale_sdk import (EXIT_CONFIG, EXIT_FAILURE, EXIT_OK, Automation, DryRunSkipped, OpenScaleClient,
                           OpenScaleError, mask_email, mask_phone, validate_manifest)


def app_with(env):
    out, err = io.StringIO(), io.StringIO()
    return Automation(env=env, stdout=out, stderr=err), out, err


class ConfigTests(unittest.TestCase):
    def test_missing_required_exits_2_and_names_them(self):
        app, _, err = app_with({})
        app.var("A", required=True)
        app.var("B", required=True, secret=True)
        called = []
        self.assertEqual(app.run(lambda: called.append(1)), EXIT_CONFIG)
        self.assertEqual(called, [])
        self.assertIn("A, B", err.getvalue())

    def test_default_and_cast(self):
        app, _, _ = app_with({"N": "7"})
        self.assertEqual(app.var("N", cast=int), 7)
        self.assertEqual(app.var("M", default="50", cast=int), 50)
        app2, _, err = app_with({"N": "sete"})
        app2.var("N", cast=int)
        self.assertEqual(app2.run(lambda: 0), EXIT_CONFIG)
        self.assertIn("invalid variables: N", err.getvalue())

    def test_dry_run_flags(self):
        self.assertTrue(app_with({"DRY_RUN": "1"})[0].dry_run)
        self.assertTrue(app_with({"OPENSCALE_DRY_RUN": "true"})[0].dry_run)
        self.assertFalse(app_with({"DRY_RUN": "0"})[0].dry_run)

    def test_api_error_is_one_line(self):
        app, _, err = app_with({})
        def falha():
            raise OpenScaleError(403, "sem permissão")
        self.assertEqual(app.run(falha), EXIT_FAILURE)
        self.assertEqual(err.getvalue().strip(), "[error] OpenScale HTTP 403: sem permissão")

    def test_exit_codes(self):
        self.assertEqual(app_with({})[0].run(lambda: None), EXIT_OK)
        self.assertEqual(app_with({})[0].run(lambda: 3), 3)
        app, _, err = app_with({"T": "segredo-123"})
        app.var("T", secret=True)

        def boom():
            raise RuntimeError("falhou com segredo-123")
        self.assertEqual(app.run(boom), EXIT_FAILURE)
        self.assertNotIn("segredo-123", err.getvalue())
        self.assertIn("••••••", err.getvalue())


class OutputTests(unittest.TestCase):
    def test_log_masks_secrets_and_token(self):
        app, out, _ = app_with({"OPENSCALE_URL": "http://x", "OPENSCALE_API": "ose_api_abcdef", "P": "senha!forte"})
        app.var("P", secret=True)
        app.openscale()
        app.log("token ose_api_abcdef e senha senha!forte")
        self.assertEqual(out.getvalue().strip(), "token •••••• e senha ••••••")

    def test_summary_and_artifacts_follow_the_runner_contract(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"OPENSCALE_SUMMARY": f"{d}/summary.json", "OPENSCALE_ARTIFACTS": f"{d}/artifacts", "K": "chave-secreta"}
            app, _, _ = app_with(env)
            app.var("K", secret=True)
            app.summary(processados=3)
            app.summary(falhas=0, nota="usou chave-secreta")
            self.assertEqual(json.loads(Path(d, "summary.json").read_text()), {"processados": 3, "falhas": 0, "nota": "usou ••••••"})
            p = app.artifact("relatorio.csv", "a;b\n")
            self.assertEqual(p.read_text(), "a;b\n")
            with self.assertRaises(ValueError):
                app.artifact("../fora.txt", "x")
            with self.assertRaises(ValueError):
                app.artifact(".oculto", "x")

    def test_personal_data_helpers(self):
        self.assertEqual(mask_phone("(92) 98608-1234"), "***1234")
        self.assertEqual(mask_phone("120363000000000000@g.us"), "grupo")
        self.assertEqual(mask_email("ana.souza@example.com"), "a***@example.com")


class _Handler(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *a):
        pass

    def _reply(self):
        _Handler.calls.append((self.command, self.path, self.headers.get("Authorization")))
        n = len(_Handler.calls)
        if self.path.startswith("/flaky") and n == 1:
            self.send_response(503); self.send_header("Retry-After", "0"); self.end_headers(); return
        if self.path.startswith("/forbidden"):
            body = json.dumps({"error": "forbidden", "message": "sem permissão"}).encode()
            self.send_response(403); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body); return
        length = int(self.headers.get("Content-Length") or 0)
        sent = json.loads(self.rfile.read(length)) if length else None
        body = json.dumps({"ok": True, "echo": sent}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)

    do_GET = do_POST = do_PATCH = _reply


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        _Handler.calls = []

    def test_bearer_json_and_retry(self):
        c = OpenScaleClient(self.url, "tok", sleep=lambda s: None)
        self.assertEqual(c.get("/flaky", page=2)["ok"], True)
        self.assertEqual(len(_Handler.calls), 2)
        self.assertEqual(_Handler.calls[0][2], "Bearer tok")
        self.assertEqual(c.post("/x", {"a": 1})["echo"], {"a": 1})

    def test_error_message_without_token(self):
        c = OpenScaleClient(self.url, "tok-secreto", sleep=lambda s: None)
        with self.assertRaises(OpenScaleError) as ctx:
            c.get("/forbidden")
        self.assertEqual(ctx.exception.status, 403)
        self.assertIn("sem permissão", str(ctx.exception))
        self.assertNotIn("tok-secreto", str(ctx.exception))

    def test_dry_run_skips_writes_unless_allowed(self):
        logs = []
        c = OpenScaleClient(self.url, "tok", dry_run=True, log=logs.append)
        r = c.post("/x", {"a": 1})
        self.assertIsInstance(r, DryRunSkipped)
        self.assertFalse(r)
        self.assertEqual(_Handler.calls, [])
        self.assertEqual(c.post("/x", {"dryRun": True}, allow_in_dry_run=True)["echo"], {"dryRun": True})
        self.assertEqual(c.get("/y")["ok"], True)
        self.assertIn("[dry-run] POST /x not sent", logs[0])

    def test_unreachable(self):
        c = OpenScaleClient("http://127.0.0.1:9", "tok", retries=1, sleep=lambda s: None, timeout=2)
        with self.assertRaises(OpenScaleError) as ctx:
            c.get("/x")
        self.assertEqual(ctx.exception.status, 0)


class ManifestTests(unittest.TestCase):
    """Same cases as the server (server/git-package.test.mjs)."""

    VALID = {"schema": 1, "name": "glpi-ad-sync", "runtime": {"language": "python", "entrypoint": "main.py", "requirements": "requirements.txt"},
             "execution": {"dry_run": True}, "variables": {"AD_URL": {"required": True}, "AD_PASSWORD": {"required": True, "secret": True}, "LOTE": {"default": "50"}}}

    def test_valid(self):
        m, errors = validate_manifest(self.VALID)
        self.assertEqual(errors, [])
        self.assertEqual(m["runtime"]["requirements"], "requirements.txt")
        self.assertTrue(m["execution"]["dry_run"])
        self.assertEqual(m["variables"]["AD_PASSWORD"], {"secret": True, "required": True, "default": None, "description": ""})
        self.assertEqual(m["variables"]["LOTE"]["default"], "50")

    def test_invalid(self):
        _, e = validate_manifest({"schema": 2, "name": "X", "runtime": {}})
        joined = " | ".join(e)
        for part in ("schema", "name", "runtime.language", "runtime.entrypoint"):
            self.assertIn(part, joined)
        _, e = validate_manifest({"schema": 1, "name": "a", "runtime": {"language": "python", "entrypoint": "../fora.py"}})
        self.assertTrue(any("entrypoint" in x for x in e))
        _, e = validate_manifest({"schema": 1, "name": "a", "runtime": {"language": "python", "entrypoint": "m.py"}, "variables": {"TOKEN": {"secret": True, "default": "abc"}}})
        self.assertTrue(any("cannot have a default" in x for x in e))
        self.assertEqual(validate_manifest(["lista"])[1], ["openscale.yaml must be a mapping"])


if __name__ == "__main__":
    unittest.main()
