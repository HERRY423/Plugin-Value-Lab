"""Loopback-only evaluation workbench, using the Python standard library."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import subprocess
from urllib.parse import unquote, urlsplit

from .core import ValidationError, _constant, _unique_object
from .execution import Engine, safe_file


def create_server(engine, port=8766):
    token = secrets.token_urlsafe(32)
    static = Path(__file__).with_name("static")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, status, data, content_type="application/json; charset=utf-8", download=False):
            if not isinstance(data, bytes):
                data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if download:
                self.send_header("Content-Disposition", "attachment")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def trusted(self):
            expected = f"127.0.0.1:{self.server.server_port}"
            if self.headers.get("Host") != expected:
                raise ValidationError("Invalid Host; open the printed 127.0.0.1 URL")
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                raise ValidationError("Cross-site requests are not allowed")
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + expected:
                raise ValidationError("Invalid Origin")

        def do_GET(self):
            try:
                self.trusted()
                path = unquote(urlsplit(self.path).path)
                if path == "/api/bootstrap":
                    return self.send(200, {"token": token, "data_directory": str(engine.root),
                        "backend": "Claude native eval", "real_model_calls_on_page_load": 0})
                if path == "/api/studies":
                    return self.send(200, engine.list())
                if path == "/api/research/example":
                    from .research import research_example
                    return self.send(200, research_example())
                if path == "/api/team-records":
                    return self.send(200, engine.team_records())
                if path.startswith("/api/team-records/"):
                    ident = path.rsplit("/", 1)[-1]
                    from .team_record import validate_team_record
                    target = safe_file(engine.root / "team-records", ident + "/record.json")
                    if not target.is_file():
                        raise ValidationError("Team record not found")
                    return self.send(200, validate_team_record(json.loads(target.read_text(encoding="utf-8"))))
                if path.startswith("/api/costs/"):
                    return self.send(200, engine.costs(path.split("/")[-1]))
                if path.startswith("/api/studies/"):
                    parts = path.split("/", 5)
                    job = parts[3]
                    if len(parts) == 4:
                        return self.send(200, engine.detail(job))
                    if len(parts) == 6 and parts[4] == "files":
                        relative = parts[5]
                        # Frozen plugin code and temporary agent workspaces are
                        # never exposed as executable same-origin HTML.
                        if relative not in engine.detail(job)["files"]:
                            raise ValidationError("Evidence file not listed")
                        target = safe_file(engine.directory(job), relative)
                        if not target.is_file() or target.stat().st_size > 32 * 1024 * 1024:
                            raise ValidationError("文件缺失或超过 32 MB，请在本地证据目录打开")
                        return self.send(200, target.read_bytes(), "text/plain; charset=utf-8", download=True)
                if path in ("/", "/app.js", "/analysis.js", "/research.js", "/team.js", "/style.css"):
                    filename, mime = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
                                      "/style.css": ("style.css", "text/css"), "/analysis.js": ("analysis.js", "text/javascript"),
                                      "/research.js": ("research.js", "text/javascript"),
                                      "/team.js": ("team.js", "text/javascript")}[path]
                    return self.send(200, (static / filename).read_bytes(), mime + "; charset=utf-8")
                self.send(404, {"error": "Not found"})
            except (ValidationError, OSError, ValueError) as exc:
                self.send(400, {"error": str(exc)})

        def do_POST(self):
            try:
                self.trusted()
                if not secrets.compare_digest(self.headers.get("X-Value-Lab-Token", ""), token):
                    raise ValidationError("Invalid request token; reload the workbench")
                if self.headers.get_content_type() != "application/json":
                    raise ValidationError("JSON request required")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 1024 * 1024:
                    raise ValidationError("Invalid request size")
                data = json.loads(self.rfile.read(length), parse_constant=_constant, object_pairs_hook=_unique_object)
                if not isinstance(data, dict):
                    raise ValidationError("Object required")
                path = urlsplit(self.path).path
                if path == "/api/studies":
                    return self.send(201, engine.prepare(data))
                if path == "/api/rules/check":
                    from .execution import form_suite
                    from .scoring import inspect_rules
                    return self.send(200, inspect_rules(form_suite(data), data.get("samples")))
                if path == "/api/compare":
                    return self.send(200, engine.compare(data["before"], data["after"]))
                if path == "/api/research/diagnose":
                    from .research import diagnose_research
                    return self.send(200, diagnose_research(data))
                if path == "/api/research/compare":
                    from .research import compare_research
                    if set(data) != {"before", "after"}:
                        raise ValidationError("Research comparison requires only before and after contexts")
                    return self.send(200, compare_research(data["before"], data["after"]))
                if path == "/api/research/followup":
                    from .research import assess_research_update
                    if set(data) != {"context", "update"}:
                        raise ValidationError("Research followup requires context and update")
                    return self.send(200, assess_research_update(data["context"], data["update"]))
                if path == "/api/team-records":
                    if set(data) != {"study_id", "decision", "previous_id", "research_context"}:
                        raise ValidationError("Team record needs study_id, decision, previous_id and research_context")
                    return self.send(201, engine.team_record(data["study_id"], data["decision"],
                                                              data["previous_id"], data["research_context"]))
                if path == "/api/demo":
                    return self.send(201, engine.demo())
                parts = path.split("/")
                if len(parts) == 5 and parts[1:3] == ["api", "studies"]:
                    if parts[4] == "start":
                        return self.send(202, engine.start(parts[3], data))
                    if parts[4] == "stop":
                        return self.send(202, engine.stop(parts[3]))
                    if parts[4] == "costs":
                        return self.send(201, engine.revise_costs(parts[3], data))
                self.send(404, {"error": "Not found"})
            except (ValidationError, OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
                self.send(400, {"error": str(exc)})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve(data_directory, port=8766, claude=None):
    engine = Engine(data_directory, claude)
    try:
        server = create_server(engine, port)
        print(f"Plugin Value Lab: http://127.0.0.1:{server.server_port}", flush=True)
        print(f"Local evidence: {engine.root}; opening the page does not call a model.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        engine.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="work/workbench")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--claude")
    args = parser.parse_args()
    serve(args.data, args.port, args.claude)
