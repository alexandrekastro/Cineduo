"""Smoke tests: no network API key and no real user database required."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SOURCE = Path(__file__).resolve().parents[1]


class CineDuoSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="cineduo-smoke-")
        cls.folder = Path(cls.tmp.name)
        for filename in ("app.py", "app.js", "index.html", "style.css", "favicon.svg"):
            shutil.copy2(SOURCE / filename, cls.folder / filename)
        shutil.copytree(SOURCE / "config", cls.folder / "config", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        env = os.environ.copy()
        env["CINEDUO_NO_BROWSER"] = "1"
        env["CINEDUO_QUIET"] = "1"
        cls.proc = subprocess.Popen(
            [sys.executable, "-u", "app.py", "--port", str(cls.port)],
            cwd=cls.folder, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        cls.base = f"http://127.0.0.1:{cls.port}"
        for _ in range(90):
            if cls.proc.poll() is not None:
                raise RuntimeError(f"CineDuo stopped during startup: {cls.proc.stderr.read().decode()}")
            try:
                with urlopen(cls.base + "/api/movies", timeout=0.3):
                    break
            except (URLError, TimeoutError):
                time.sleep(0.1)
        else:
            raise RuntimeError("CineDuo did not become available on localhost")

    @classmethod
    def tearDownClass(cls):
        if cls.proc.poll() is None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
                cls.proc.wait(timeout=5)
        cls.proc.stderr.close()
        cls.tmp.cleanup()

    @classmethod
    def request(cls, path, data=None, method=None):
        payload = None if data is None else json.dumps(data).encode("utf-8")
        req = Request(cls.base + path, data=payload, method=method,
                      headers={"Content-Type": "application/json"} if payload else {})
        try:
            with urlopen(req, timeout=8) as response:
                raw = response.read()
                return response.status, json.loads(raw) if response.headers.get_content_type() == "application/json" else raw
        except HTTPError as ex:
            return ex.code, json.loads(ex.read())

    def test_catalog_and_ranking_without_external_services(self):
        status, movies = self.request("/api/movies")
        self.assertEqual(status, 200)
        self.assertEqual(movies, [], "A fresh installation must not include personal movie data")

        status, first = self.request("/api/movies", {
            "title": "A Órfã", "year": "2009", "imdb_id": "tt1148204",
            "personal_rating": 8, "imdb_rating": "7.0", "metascore": "42",
            "content_type": "movie"
        })
        self.assertEqual(status, 200)
        self.assertEqual(first["personal_rating"], 8)
        first_id = first["id"]

        status, second = self.request("/api/movies", {
            "title": "Orphan: First Kill", "year": "2022",
            "personal_rating": 7, "content_type": "movie"
        })
        self.assertEqual(status, 200)

        status, _ = self.request("/api/top3", {"id": first_id, "action": "add"})
        self.assertEqual(status, 200)
        status, movie = self.request(f"/api/movies/{first_id}")
        self.assertEqual(movie["top3_position"], 1)

        status, _ = self.request(f"/api/movies/{first_id}", {"notes": "A personal note"}, "PATCH")
        self.assertEqual(status, 200)
        status, movie = self.request(f"/api/movies/{first_id}")
        self.assertEqual(movie["notes"], "A personal note")

        status, duplicates = self.request("/api/movies", {
            "title": "Another copy", "imdb_id": "tt1148204"})
        self.assertEqual(status, 400)
        self.assertIn("error", duplicates)

        status, _ = self.request("/api/actors/manual", {"movie_id": first_id, "name": "Isabelle Fuhrman"})
        self.assertEqual(status, 200)
        status, people = self.request("/api/actors")
        self.assertEqual(status, 200)
        self.assertIn("Isabelle Fuhrman", [person["name"] for person in people["artists"]])

        status, sagas = self.request("/api/sagas")
        self.assertEqual(status, 200)
        orphan = [s for s in sagas["sagas"] if "órfã" in s["name"].lower()]
        self.assertTrue(orphan, "The Orphan duology should still be detected")

        status, movies = self.request("/api/movies")
        self.assertEqual(len(movies), 2)
        status, backup = self.request("/api/export.json")
        self.assertEqual(status, 200)
        self.assertEqual(backup["format"], "CineDuo")
        self.assertEqual(len(backup["movies"]), 2)
        status, settings = self.request("/api/settings")
        self.assertFalse(settings["has_key"])
        self.assertFalse(settings["has_tmdb_key"])

    def test_frontend_assets(self):
        for path in ("/", "/app.js", "/style.css", "/favicon.svg"):
            status, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertGreater(len(body), 100)


if __name__ == "__main__":
    unittest.main()
