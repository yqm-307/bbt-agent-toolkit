#!/usr/bin/env python3
"""Check/archive this turn's own session: WebUI over its HTTP API, WebApp/Desktop over the gateway's session store."""
import argparse
import contextlib
import http.cookiejar
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


class Blocked(Exception):
    pass


#: WebUI row id (12 lowercase hex). The agent id rotates on compression; only this names the row.
WEBUI_ID = re.compile(r"[a-f0-9]{12}")
#: Gateway-hosted row id (``local-`` + 64 lowercase hex), shared by the WebApp and the Desktop app.
GATEWAY_ID = re.compile(r"local-[0-9a-f]{64}")
GATEWAY_PLATFORMS = frozenset({"local", "gui", "desktop"})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Blocked("HTTP redirect refused")


def target(env):
    """``(surface, session id, profile, home)`` for this turn's own session; Blocked otherwise."""
    platform = env.get("HERMES_SESSION_PLATFORM", "")
    home = Path(env.get("HERMES_HOME", ""))
    if platform == "webui":
        sid = env.get("HERMES_UI_SESSION_ID", "")
        port = env.get("HERMES_WEBUI_PORT", "")
        if not WEBUI_ID.fullmatch(sid):
            raise Blocked("Current WebUI session identity is missing or invalid")
        if not home.is_absolute() or home.parent.name != "profiles":
            raise Blocked("Named profile home required")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", home.name):
            raise Blocked("Invalid profile name")
        if not re.fullmatch(r"[0-9]{1,5}", port) or not 1 <= int(port) <= 65535:
            raise Blocked("Invalid HERMES_WEBUI_PORT")
        return "webui", sid, home.name, home
    sid = env.get("HERMES_SESSION_ID", "")
    # Compression rotates the agent id to ``<timestamp>_<hex>``; the chat id keeps naming the conversation.
    key = sid if GATEWAY_ID.fullmatch(sid) else env.get("HERMES_SESSION_CHAT_ID", "")
    if platform in GATEWAY_PLATFORMS and GATEWAY_ID.fullmatch(key):
        if not home.is_absolute() or not (home / "state.db").is_file():
            raise Blocked("Profile home with a session store required")
        return "webapp", key, home.name, home
    raise Blocked("Current session is neither WebUI nor a gateway WebApp/Desktop chat")


# -- WebUI: its own HTTP API -------------------------------------------------

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
    return {"platform": "webui", "session_id": sid, "profile": profile,
            "archived": after["archived"], "verified": True,
            "changed": action == "archive" and not before["archived"]}


def perform_webui(port, sid, profile, action):
    base = f"http://127.0.0.1:{int(port)}"
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


# -- WebApp/Desktop: the gateway's session store -----------------------------

def read_session(home, key):
    """The current session's store row, read-only: id, chat_id, archived, pinned."""
    db = home / "state.db"
    try:
        with contextlib.closing(sqlite3.connect(f"file:{db}?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT id, chat_id, archived, pinned FROM sessions WHERE id = ?"
                               " AND COALESCE(end_reason, '') <> 'compression'", (key,)).fetchone()
            if row is None:
                # A compression rotation mints a new row id; the chat id still names the live segment.
                # The archived-away parent can itself carry the chat id as its row id, so it is skipped.
                row = conn.execute(
                    "SELECT id, chat_id, archived, pinned FROM sessions WHERE chat_id = ?"
                    " AND COALESCE(end_reason, '') <> 'compression'"
                    " ORDER BY COALESCE(last_activity_at, started_at) DESC LIMIT 1", (key,)).fetchone()
    except sqlite3.Error as exc:
        # A store from another Hermes version may lack a column this check reads; name the reason.
        raise Blocked(f"Session store unreadable: {exc}") from None
    return dict(row) if row is not None else None


def archive_cli(chat_id):
    """Archive one store row through the public CLI; returns the session count it reports."""
    exe = shutil.which("hermes")
    if exe is None:
        raise Blocked("hermes CLI not found on PATH")
    proc = subprocess.run([exe, "sessions", "archive", "--chat-id", chat_id,
                           "--include-open", "--yes"],
                          capture_output=True, text=True, timeout=120, env=dict(os.environ))
    if proc.returncode != 0:
        raise Blocked(f"hermes sessions archive exited {proc.returncode}")
    match = re.search(r"Archived (\d+) session", proc.stdout)
    if match is None:
        raise Blocked("Archive CLI reported no session count")
    return int(match.group(1))


def perform_webapp(home, key, action, archive=archive_cli, confirm=None):
    row = read_session(home, key)
    if row is None:
        raise Blocked("Session row not found in this profile's store")
    if type(row.get("archived")) is not int:
        raise Blocked("Store archive state missing or invalid")
    result = {"platform": "webapp", "session_id": row["id"], "profile": home.name,
              "archived": bool(row["archived"]), "pinned": bool(row["pinned"]),
              "verified": True, "changed": False}
    if action == "check":
        return result
    if confirm != row["id"]:
        raise Blocked("Archive requires --confirm-session matching the resolved session row")
    if row["pinned"]:
        raise Blocked("Session is pinned; unpin it first, then archive")
    # The CLI selects by chat id (exact, chat-wide). A normal local chat carries ``local-<64hex>``;
    # an adopted chat's foreign id could match sibling sessions, so it is refused rather than guessed.
    chat_id = row.get("chat_id")
    if not isinstance(chat_id, str) or not GATEWAY_ID.fullmatch(chat_id):
        raise Blocked("Session has no local chat id to target; archive it in the app")
    if row["archived"]:
        return result
    if archive(chat_id) != 1:
        raise Blocked("Archive CLI matched an unexpected number of sessions")
    after = read_session(home, row["id"])
    if after is None or after["id"] != row["id"] or after["archived"] != 1:
        raise Blocked("Archive readback failed")
    return {**result, "archived": True, "changed": True}


def run(action, confirm_session):
    surface, key, profile, home = target(os.environ)
    if surface == "webui":
        if action == "archive" and confirm_session != key:
            raise Blocked("Archive requires --confirm-session matching the current session")
        return perform_webui(os.environ["HERMES_WEBUI_PORT"], key, profile, action)
    if action == "archive" and not confirm_session:
        raise Blocked("Archive requires --confirm-session matching the current session")
    return perform_webapp(home, key, action, confirm=confirm_session)


# -- self-test ---------------------------------------------------------------

def self_test():
    import tempfile

    webui = {"HERMES_SESSION_PLATFORM": "webui", "HERMES_SESSION_ID": "012345abcdef",
             "HERMES_UI_SESSION_ID": "012345abcdef", "HERMES_HOME": "/test/profiles/demo",
             "HERMES_WEBUI_PORT": "12345"}
    sid, profile, _ = target(webui)[1:]
    assert target(webui | {"HERMES_SESSION_ID": "abcdef012345"})[1] == sid
    for field, value in (("HERMES_UI_SESSION_ID", sid + "\n"), ("HERMES_UI_SESSION_ID", ""),
                         ("HERMES_WEBUI_PORT", "65536"), ("HERMES_SESSION_PLATFORM", "subagent"),
                         ("HERMES_HOME", "/test/default")):
        try:
            target(webui | {field: value})
        except Blocked:
            pass
        else:
            raise AssertionError(field)

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        store = home / "state.db"
        store.write_bytes(b"")
        gid = "local-" + "a" * 64
        rotated = "20200101_000000_abcdef"  # a compression child's row id (synthetic)
        gateway = {"HERMES_SESSION_PLATFORM": "local", "HERMES_HOME": str(home),
                   "HERMES_SESSION_ID": gid}
        assert target(gateway)[:2] == ("webapp", gid) and target(gateway)[3] == home
        # After compression the agent id rotates; the chat id still names the conversation.
        assert target(gateway | {"HERMES_SESSION_ID": rotated,
                                 "HERMES_SESSION_CHAT_ID": gid})[:2] == ("webapp", gid)
        for field, value in (("HERMES_SESSION_ID", "012345abcdef"), ("HERMES_SESSION_ID", "local-" + "A" * 64),
                             ("HERMES_SESSION_PLATFORM", "cli"), ("HERMES_HOME", "/test/profiles/demo")):
            try:
                target(gateway | {field: value})
            except Blocked:
                pass
            else:
                raise AssertionError(field)
        try:
            target(gateway | {"HERMES_SESSION_ID": rotated})
        except Blocked:
            pass
        else:
            raise AssertionError("rotated id without a chat id must be refused")

        # The gateway branch reads and writes one store row; the CLI is injected, never run here.
        def write(sql, params=()):
            # isolation_level=None: every fixture write commits before the connection closes.
            with contextlib.closing(sqlite3.connect(store, isolation_level=None)) as conn:
                conn.execute(sql, params)

        write("CREATE TABLE sessions (id TEXT PRIMARY KEY, chat_id TEXT, archived INTEGER,"
              " pinned INTEGER, end_reason TEXT, started_at REAL, last_activity_at REAL)")
        write("INSERT INTO sessions VALUES (?, ?, 0, 0, NULL, 1, 1)", (gid, gid))
        calls = []

        def cli(chat_id):
            calls.append(chat_id)
            write("UPDATE sessions SET archived = 1 WHERE chat_id = ?", (chat_id,))
            return 1

        assert perform_webapp(home, gid, "check")["archived"] is False and not calls
        assert perform_webapp(home, gid, "archive", cli, confirm=gid)["changed"] is True and calls == [gid]
        assert perform_webapp(home, gid, "archive", cli, confirm=gid)["changed"] is False and len(calls) == 1
        write("UPDATE sessions SET archived = 0 WHERE id = ?", (gid,))
        try:
            perform_webapp(home, gid, "archive", cli, confirm="other")
        except Blocked:
            pass
        else:
            raise AssertionError("confirm must name the resolved row")
        for fake, label in ((lambda _: 2, "two matches"), (lambda _: 0, "no match"),
                            (lambda _: (_ for _ in ()).throw(Blocked("cli failed")), "cli failure")):
            write("UPDATE sessions SET archived = 0 WHERE id = ?", (gid,))
            try:
                perform_webapp(home, gid, "archive", fake, confirm=gid)
            except Blocked:
                pass
            else:
                raise AssertionError(label)
        write("UPDATE sessions SET archived = 0, pinned = 1 WHERE id = ?", (gid,))
        try:
            perform_webapp(home, gid, "archive", cli, confirm=gid)
        except Blocked:
            pass
        else:
            raise AssertionError("pinned session must be refused")

        # A compressed lineage: the archived-away parent is skipped, the live child resolves by chat id.
        write("UPDATE sessions SET end_reason = 'compression', pinned = 0 WHERE id = ?", (gid,))
        write("INSERT INTO sessions VALUES (?, ?, 0, 0, NULL, 2, 2)", (rotated, gid))
        checked = perform_webapp(home, gid, "check")
        assert checked["session_id"] == rotated, checked
        calls.clear()
        assert perform_webapp(home, gid, "archive", cli, confirm=rotated)["changed"] is True and calls == [gid]
        write("UPDATE sessions SET archived = 0")

        # A chat id that is not a local conversation could match siblings; refuse instead of guessing.
        for row_id, chat, label in ((("local-" + "c" * 64), "telegram:42", "adopted chat"),
                                    (("local-" + "d" * 64), None, "missing chat id")):
            write("INSERT INTO sessions VALUES (?, ?, 0, 0, NULL, 1, 1)", (row_id, chat))
            try:
                perform_webapp(home, row_id, "archive", cli, confirm=row_id)
            except Blocked:
                pass
            else:
                raise AssertionError(label)
        try:
            perform_webapp(home, "local-" + "b" * 64, "check")
        except Blocked:
            pass
        else:
            raise AssertionError("missing row must be refused")

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
    print("PASS: platform routing, identity guards, WebUI check-only/exact write/idempotence/readback,"
          " WebApp pinned/CLI-count/readback guards")


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
