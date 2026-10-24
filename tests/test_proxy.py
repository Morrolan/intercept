"""Opt-in forwarded-header trust for login addresses and rate limiting."""

import pytest
from flask import Flask, request
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from app import _configure_proxy


@pytest.fixture
def proxy_client(monkeypatch):
    def make_client(value=None):
        if value is None:
            monkeypatch.delenv("INTERCEPT_TRUSTED_PROXIES", raising=False)
        else:
            monkeypatch.setenv("INTERCEPT_TRUSTED_PROXIES", value)
        application = Flask(__name__)
        _configure_proxy(application)

        @application.get("/")
        def address():
            return {
                "address": request.remote_addr,
                "limiter_key": get_remote_address(),
                "scheme": request.scheme,
                "host": request.host,
                "prefix": request.script_root,
            }

        return application.test_client()

    return make_client


def forwarded_request(client, forwarded_for="198.51.100.10, 203.0.113.20"):
    return client.get("/", environ_overrides={"REMOTE_ADDR": "172.18.0.2"}, headers={
        "X-Forwarded-For": forwarded_for,
        "X-Forwarded-Proto": "http, https",
        "X-Forwarded-Host": "spoofed.example, intercept.example.test",
        "X-Forwarded-Port": "9999",
        "X-Forwarded-Prefix": "/spoofed",
    }).get_json()


@pytest.mark.parametrize("value", [None, "0", "-1", "invalid", "", "1.5", "1,2"])
def test_proxy_trust_defaults_off_and_invalid_values_disable_it(proxy_client, value):
    client = proxy_client(value)
    assert not isinstance(client.application.wsgi_app, ProxyFix)
    assert forwarded_request(client) == {
        "address": "172.18.0.2", "limiter_key": "172.18.0.2",
        "scheme": "http", "host": "localhost", "prefix": "",
    }


def test_one_proxy_uses_rightmost_address_and_public_origin(proxy_client):
    assert forwarded_request(proxy_client("1")) == {
        "address": "203.0.113.20", "limiter_key": "203.0.113.20",
        "scheme": "https", "host": "intercept.example.test", "prefix": "",
    }


def test_two_proxies_use_second_address_from_right(proxy_client):
    result = forwarded_request(proxy_client("2"))
    assert result["address"] == result["limiter_key"] == "198.51.100.10"


def test_short_forwarded_chain_keeps_peer_address(proxy_client):
    result = forwarded_request(proxy_client("2"), "203.0.113.20")
    assert result["address"] == result["limiter_key"] == "172.18.0.2"


def test_missing_forwarded_headers_keep_original_request(proxy_client):
    result = proxy_client("1").get("/", environ_overrides={"REMOTE_ADDR": "172.18.0.2"}).get_json()
    assert result == {
        "address": "172.18.0.2", "limiter_key": "172.18.0.2",
        "scheme": "http", "host": "localhost", "prefix": "",
    }
