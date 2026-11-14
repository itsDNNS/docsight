"""Gzip for text responses; neither Flask nor waitress compresses on its own."""

import gzip

from flask import request

COMPRESSIBLE_TYPES = {
    "application/javascript",
    "application/json",
    "application/manifest+json",
    "application/xml",
    "image/svg+xml",
}
MIN_SIZE = 1024
# Static files are read into memory to compress them; larger ones are sent as they are.
MAX_SIZE = 8 * 1024 * 1024


def _text_type(response) -> bool:
    mimetype = response.mimetype or ""
    return mimetype.startswith("text/") or mimetype in COMPRESSIBLE_TYPES


def _compressible(response) -> bool:
    if response.status_code != 200 or "Content-Encoding" in response.headers:
        return False
    # Generators (live streams) have no length; static files do and are read below.
    if response.is_streamed and not response.direct_passthrough:
        return False
    length = response.content_length
    return length is not None and MIN_SIZE <= length <= MAX_SIZE


def compress_response(response):
    if not _text_type(response):
        return response
    response.vary.add("Accept-Encoding")
    if request.method == "HEAD" or not request.accept_encodings["gzip"] or not _compressible(response):
        return response
    response.direct_passthrough = False
    body = gzip.compress(response.get_data(), compresslevel=6)
    response.set_data(body)
    response.headers["Content-Encoding"] = "gzip"
    etag, weak = response.get_etag()
    if etag and not weak:
        # The same tag now names two encodings, which only a weak tag allows
        response.set_etag(etag, weak=True)
    return response
