"""Gzip for text responses."""

import gzip

from flask import Flask, Response

from app.response_compression import compress_response

GZIP = {"Accept-Encoding": "gzip, deflate"}


def test_static_script_is_compressed_and_revalidates(client):
    plain = client.get("/static/js/dashboard.js")
    resp = client.get("/static/js/dashboard.js", headers=GZIP)

    assert resp.headers["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in resp.headers["Vary"]
    assert gzip.decompress(resp.data) == plain.data
    assert int(resp.headers["Content-Length"]) == len(resp.data) < len(plain.data)
    etag, weak = resp.get_etag()
    assert weak
    revalidated = client.get("/static/js/dashboard.js", headers={**GZIP, "If-None-Match": f'W/"{etag}"'})
    assert revalidated.status_code == 304


def test_page_without_gzip_support_stays_plain(client):
    resp = client.get("/static/js/dashboard.js", headers={"Accept-Encoding": "identity"})

    assert "Content-Encoding" not in resp.headers
    assert "Accept-Encoding" in resp.headers["Vary"]


def test_only_complete_text_responses_are_compressed():
    app = Flask(__name__)
    app.after_request(compress_response)
    big = "x" * 4096

    @app.route("/png")
    def png():
        return Response(b"\x89PNG" + b"0" * 4096, mimetype="image/png")

    @app.route("/small")
    def small():
        return Response("tiny", mimetype="text/plain")

    @app.route("/stream")
    def stream():
        return Response((part for part in (big, big)), mimetype="text/event-stream")

    @app.route("/text")
    def text():
        return Response(big, mimetype="text/plain")

    client = app.test_client()
    png_resp = client.get("/png", headers=GZIP)
    assert "Content-Encoding" not in png_resp.headers
    assert "Vary" not in png_resp.headers
    assert "Content-Encoding" not in client.get("/small", headers=GZIP).headers
    assert "Content-Encoding" not in client.get("/stream", headers=GZIP).headers
    assert "Content-Encoding" not in client.head("/text", headers=GZIP).headers
    assert gzip.decompress(client.get("/text", headers=GZIP).data).decode() == big
