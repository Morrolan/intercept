"""Static asset URLs carry the app version, so an upgrade is a new URL."""

import re

from flask import url_for

from config import VERSION


def test_url_for_static_carries_version_and_content_digest(app):
    import hashlib
    from pathlib import Path

    with app.test_request_context():
        digest = hashlib.sha256((Path(app.static_folder) / "js/modes/gps.js").read_bytes()).hexdigest()[:10]
        assert url_for("static", filename="js/modes/gps.js").endswith(f"?v={VERSION}-{digest}")
        # Different files, different digests: a deploy only changes the URLs of files that changed
        def v(filename):
            return url_for("static", filename=filename).split("?v=")[1]

        assert v("css/ami-theme.css") != v("js/modes/gps.js")
        # Never reads outside the static folder
        assert url_for("static", filename="../app.py").endswith(f"?v={VERSION}-ami")


def test_pages_version_every_app_asset(client):
    with client.session_transaction() as sess:
        sess["logged_in"] = True
    html = client.get("/").get_data(as_text=True)
    assets = re.findall(r'["\'](/static/[^"\'?]+\.(?:js|css)(?:\?[^"\']*)?)["\']', html)
    assert assets, "expected static assets on the main page"
    unversioned = [a for a in assets if f"v={VERSION}" not in a]
    assert not unversioned, unversioned
    # The lazily loaded mode scripts too (the stale gps.js case)
    assert f"js/modes/gps.js?v={VERSION}" in html
