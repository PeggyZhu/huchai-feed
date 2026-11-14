import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from huchai.client import USER_AGENT, UrllibTransport
from huchai.errors import SourceBlocked, SourceError


class QuietHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        return

    def _send(self, status, body, content_type):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.server.agents.append(self.headers.get("User-Agent"))
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class ChallengeHandler(QuietHandler):
    def do_GET(self):
        self.server.gets += 1
        self._send(412, "<html><script>$_ts={}</script></html>", "text/html")

    def do_POST(self):
        self.server.posts += 1
        self._send(200, "{}", "application/json")


class RetryHandler(QuietHandler):
    def do_GET(self):
        self._send(200, "<html>old house</html>", "text/html")

    def do_POST(self):
        self.server.posts += 1
        if self.server.posts < 3:
            self._send(503, "busy", "text/plain")
            return
        self._send(200, json.dumps({"sellcount": 800, "sellarea": 64000}), "application/json")


class ClientTests(unittest.TestCase):
    def serve(self, handler):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        httpd.gets = 0
        httpd.posts = 0
        httpd.agents = []
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(httpd.shutdown)
        self.addCleanup(httpd.server_close)
        self.addCleanup(thread.join, 2)
        return httpd

    def transport(self, httpd, **kwargs):
        port = httpd.server_address[1]
        sleeps = []
        client = UrllibTransport(
            interval=0,
            backoff=0,
            timeout=2,
            attempts=3,
            sleep=sleeps.append,
            page_url=f"http://127.0.0.1:{port}/old_house/old_house.html",
            api_url=f"http://127.0.0.1:{port}/oldhouse/getSHYesterdaySell.action",
            **kwargs,
        )
        return client, sleeps

    def test_challenge_stops_before_the_second_request(self):
        httpd = self.serve(ChallengeHandler)
        client, sleeps = self.transport(httpd)
        with self.assertRaises(SourceBlocked):
            client.fetch_yesterday()
        self.assertEqual(httpd.gets, 1)
        self.assertEqual(httpd.posts, 0)
        self.assertEqual(sleeps, [])
        self.assertEqual(httpd.agents, [USER_AGENT])

    def test_retries_server_errors_then_parses_json(self):
        httpd = self.serve(RetryHandler)
        client, sleeps = self.transport(httpd)
        payload = client.fetch_yesterday()
        self.assertEqual(payload["sellcount"], 800)
        self.assertEqual(httpd.posts, 3)
        self.assertEqual(len(sleeps), 3)
        self.assertTrue(all(agent == USER_AGENT for agent in httpd.agents))

    def test_exhausted_server_errors_raise(self):
        class AlwaysDown(QuietHandler):
            def do_GET(self):
                self._send(200, "ok", "text/html")

            def do_POST(self):
                self._send(502, "down", "text/plain")

        httpd = self.serve(AlwaysDown)
        client, _sleeps = self.transport(httpd)
        with self.assertRaises(SourceError):
            client.fetch_yesterday()


if __name__ == "__main__":
    unittest.main()
