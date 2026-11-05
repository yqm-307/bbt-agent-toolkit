#!/usr/bin/env python3
"""Check/archive the current named-profile WebUI session via its HTTP API."""
import argparse
import http.cookiejar
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


class Blocked(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Blocked("HTTP redirect refused")


def identity(env):
    # The agent ID rotates on compression; only the UI ID names the WebUI row.
    sid = env.get("HERMES_UI_SESSION_ID", "")
    home = Path(env.get("HERMES_HOME", ""))
    port = env.get("HERMES_WEBUI_PORT", "")
    if env.get("HERMES_SESSION_PLATFORM") != "webui":
        raise Blocked("Current platform is not WebUI")
    if not re.fullmatch(r"[a-f0-9]{12}", sid):
        raise Blocked("Current WebUI session identity is missing or invalid")
    if not home.is_absolute() or home.parent.name != "profiles":
        raise Blocked("Named profile home required")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", home.name):
        raise Blocked("Invalid profile name")
    if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
        raise Blocked("Invalid HERMES_WEBUI_PORT")
    return sid, home.name, f"http://127.0.0.1:{int(port)}"


def perform(api, sid, profile, action):
    query = urllib.parse.urlencode({"session_id": sid, "messages": 0,
                                  "resolve_model": 0, "profile": profile})

    def read():
        session = api("/api/session?" + query).get("session", {})
        if session.get("session_id") != sid or session.get("profile") != profile:
            raise Blocked("API session identity/profile mismatch")
        if type(session.get("archived")) is not bool:
            raise Blocked("API archive state missing or invalid")
        return session

    before = read()
    if action == "archive" and not before["archived"]:
        response = api("/api/session/archive", {"session_id": sid, "archived": True})
        if response.get("ok") is not True:
            raise Blocked("Archive API did not acknowledge the request; read state before retry")
    after = read()
    if action == "archive" and after["archived"] is not True:
        raise Blocked("Archive readback failed")
    return {"session_id": sid, "profile": profile, "archived": after["archived"],
            "verified": True, "changed": action == "archive" and not before["archived"]}


def run(action, confirm_session):
    sid, profile, base = identity(os.environ)
    if action == "archive" and confirm_session != sid:
        raise Blocked("Archive requires --confirm-session matching the current session")
    jar = http.cookiejar.CookieJar()
    client = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPCookieProcessor(jar))

    def api(path, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(base + path, data=data,
                                         headers={"Content-Type": "application/json"})
        with client.open(request, timeout=15) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise Blocked("Invalid API response")
        return result

    try:
        status = api("/api/auth/status")
        if status.get("auth_enabled") is not True or status.get("password_auth_enabled") is not True:
            raise Blocked("Password-authenticated WebUI required; use an approved browser session instead")
        password = os.environ.get("HERMES_WEBUI_PASSWORD")
        if not password:
            raise Blocked("HERMES_WEBUI_PASSWORD unavailable; approved login required")
        if api("/api/auth/login", {"password": password}).get("ok") is not True:
            raise Blocked("Login failed")
        if api("/api/auth/status").get("logged_in") is not True:
            raise Blocked("Login readback failed")
        result = perform(api, sid, profile, action)
    finally:
        if jar:
            try:
                api("/api/auth/logout", {})
                if api("/api/auth/status").get("logged_in") is not False:
                    raise Blocked("Logout readback failed")
            except Exception:
                raise Blocked("Temporary login cleanup failed; check archive and login state") from None
            finally:
                jar.clear()
    return result


def self_test():
    env = {"HERMES_SESSION_PLATFORM": "webui", "HERMES_SESSION_ID": "012345abcdef",
           "HERMES_UI_SESSION_ID": "012345abcdef", "HERMES_HOME": "/test/profiles/demo",
           "HERMES_WEBUI_PORT": "12345"}
    sid, profile, _ = identity(env)
    assert identity(env | {"HERMES_SESSION_ID": "abcdef012345"})[0] == sid
    for field, value in (("HERMES_UI_SESSION_ID", sid + "\n"), ("HERMES_UI_SESSION_ID", ""),
                         ("HERMES_WEBUI_PORT", "65536"), ("HERMES_SESSION_PLATFORM", "subagent"),
                         ("HERMES_HOME", "/test/default")):
        try:
            identity(env | {field: value})
        except Blocked:
            pass
        else:
            raise AssertionError(field)
    state = {"session_id": sid, "profile": profile, "archived": False}
    writes = []

    def api(path, body=None):
        if body is not None:
            assert path == "/api/session/archive" and body == {"session_id": sid, "archived": True}
            writes.append(body)
            state["archived"] = True
            return {"ok": True}
        return {"session": dict(state)}

    assert perform(api, sid, profile, "check")["archived"] is False and not writes
    assert perform(api, sid, profile, "archive")["changed"] is True
    assert perform(api, sid, profile, "archive")["changed"] is False and len(writes) == 1
    for bad in ({"profile": "other"}, {"session_id": "other"}, {"archived": "true"}):
        try:
            perform(lambda *_: {"session": state | bad}, sid, profile, "archive")
        except Blocked:
            pass
        else:
            raise AssertionError(bad)
    try:
        perform(lambda *args: {"ok": True} if len(args) > 1 else
                {"session": state | {"archived": False}}, sid, profile, "archive")
    except Blocked:
        pass
    else:
        raise AssertionError("Acknowledgement without state change must fail")
    print("PASS: identity, check-only, exact write, idempotence, profile/type guards, readback failure")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "archive", "self-test"))
    parser.add_argument("--confirm-session", help="Exact current session ID, only after user approval")
    args = parser.parse_args()
    try:
        if args.action == "self-test":
            self_test()
        else:
            print(json.dumps(run(args.action, args.confirm_session), ensure_ascii=False))
    except Exception as exc:
        # Never print HTTP bodies, cookies, passwords, or exception URLs.
        detail = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
        print("BLOCKED: " + detail, file=sys.stderr)
        sys.exit(1)
