"""A small Zammad REST client: the calls the tools and the seeder need, nothing more."""

import os
import time
from typing import Any

import httpx


class ZammadError(Exception):
    pass


class Zammad:
    def __init__(self, url: str | None = None, token: str | None = None, transport: httpx.BaseTransport | None = None):
        url = url or os.environ.get("ZAMMAD_URL", "http://127.0.0.1:8090")
        token = token or os.environ.get("ZAMMAD_TOKEN", "")
        if not token:
            raise ZammadError("ZAMMAD_TOKEN is not set (scripts/up.sh writes it to .env)")
        self.url = url.rstrip("/")
        self.http = httpx.Client(
            base_url=self.url + "/api/v1/",
            headers={"Authorization": f"Token token={token}", "Accept": "application/json"},
            timeout=30,
            transport=transport,
        )

    def call(self, method: str, path: str, headers: dict | None = None, **kw: Any) -> Any:
        for wait in (1, 2, 4, 0):
            r = self.http.request(method, path, headers=headers, **kw)
            if r.status_code != 429 or not wait:
                break
            time.sleep(wait)
        if r.status_code == 404:
            raise ZammadError("not found")
        if r.status_code >= 400:
            try:
                msg = r.json().get("error_human") or r.json().get("error")
            except ValueError:
                msg = None
            raise ZammadError(msg or f"Zammad answered {r.status_code}")
        return r.json() if r.content else None

    def get(self, path: str, **params: Any) -> Any:
        return self.call("GET", path, params=params)

    def post(self, path: str, data: dict, on_behalf_of: str | None = None) -> Any:
        return self.call("POST", path, json=data, headers={"X-On-Behalf-Of": on_behalf_of} if on_behalf_of else None)

    def put(self, path: str, data: dict) -> Any:
        return self.call("PUT", path, json=data)
