"""The checks the install and update scripts rely on (deploy/, app/ops.py)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from conftest import TEST_DB

from app import ops


def test_busy_counts_open_bills(client, owner, menu):
    assert ops.busy(TEST_DB) == {"open_shifts": 0, "open_bills": 0}
    client.post("/api/bills", json={"quick": True}, headers=owner)
    assert ops.busy(TEST_DB)["open_bills"] == 1


def test_revision_is_the_latest_migration():
    assert ops.revision(TEST_DB).startswith("0008")


def test_set_up_prints_the_business_id(monkeypatch, capsys, business):
    monkeypatch.setenv("FAIDA_DATABASE_URL", TEST_DB)
    monkeypatch.setenv("FAIDA_PIN_SECRET", "x")
    ops.get_config.cache_clear()
    try:
        ops.main(["set-up"])
    finally:
        ops.get_config.cache_clear()
    assert str(business.id) in capsys.readouterr().out


@pytest.fixture
def health_server():
    answer = {"version": "0.2.0", "mode": "local"}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(answer).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/api/health"
    server.shutdown()


def test_health_check_wants_the_new_version(health_server):
    assert ops.healthy(health_server, "0.2.0")[0]
    ok, detail = ops.healthy(health_server, "0.3.0")
    assert not ok and "expected 0.3.0" in detail
    assert not ops.healthy("http://127.0.0.1:9/api/health", None)[0]
    with pytest.raises(SystemExit, match="Not healthy"):
        ops.main(["wait-healthy", "--url", health_server, "--version", "9.9.9", "--seconds", "0"])


def test_installed_counter_serves_the_screens_and_icons(config, printers, tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "counter.js").write_text("// app")
    (tmp_path / "index.html").write_text("<title>Faida POS</title>")
    (tmp_path / "favicon.png").write_bytes(b"\x89PNG icon")
    app = create_app(config.model_copy(update={"static_dir": str(tmp_path)}), printers=printers)
    with TestClient(app) as c:
        assert c.get("/favicon.png").content == b"\x89PNG icon"
        assert c.get("/assets/counter.js").text == "// app"
        assert "Faida POS" in c.get("/tables/anything").text  # app screens get the page
        assert "Faida POS" in c.get("/../backend/.env").text  # never a file outside the build
        # The page is never kept: after an update it must name the new build's scripts.
        assert c.get("/").headers["cache-control"] == "no-cache"
        assert c.get("/index.html").headers["cache-control"] == "no-cache"
        assert "cache-control" not in c.get("/favicon.png").headers
        assert c.get("/api/health").json()["mode"] == "local"
