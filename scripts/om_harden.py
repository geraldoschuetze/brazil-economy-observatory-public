#!/usr/bin/env python3
"""Harden OpenMetadata for (shared-viewer) public exposure.

1. Change the default admin password (admin/admin) to a strong one.
2. Create a read-only `viewer` user (the shared, public-by-design login that
   only ever reads public government data; writes are also blocked at the
   read-only nginx proxy).

Idempotent-ish: skips the admin change if the new password already works.
Stdlib only; run on the VM host against the loopback OM API.

Usage:
    OM_URL=http://127.0.0.1:8595 \
    OM_ADMIN_PASSWORD=admin OM_ADMIN_NEW_PASSWORD=... \
    OM_VIEWER_PASSWORD=... python3 scripts/om_harden.py
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

OM_URL = os.environ.get("OM_URL", "http://127.0.0.1:8595").rstrip("/")
ADMIN_EMAIL = os.environ.get("OM_ADMIN_EMAIL", "admin@open-metadata.org")
ADMIN_PW = os.environ.get("OM_ADMIN_PASSWORD", "admin")
ADMIN_NEW_PW = os.environ.get("OM_ADMIN_NEW_PASSWORD", "")
VIEWER_EMAIL = os.environ.get("OM_VIEWER_EMAIL", "viewer@brazil-economy.observatory")
VIEWER_PW = os.environ.get("OM_VIEWER_PASSWORD", "")


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def login(pw: str) -> str | None:
    body = json.dumps({"email": ADMIN_EMAIL, "password": b64(pw)}).encode()
    req = urllib.request.Request(
        f"{OM_URL}/api/v1/users/login",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.load(r)["accessToken"]
    except urllib.error.HTTPError:
        return None


def call(tok, method, path, payload=None, ct="application/json"):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        f"{OM_URL}{path}",
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": ct},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            # some endpoints (e.g. changePassword) return 200 with an empty body
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def main() -> None:
    # 1) admin password
    if ADMIN_NEW_PW and login(ADMIN_NEW_PW):
        print("admin password already updated; skipping")
        tok = login(ADMIN_NEW_PW)
    else:
        tok = login(ADMIN_PW)
        if not tok:
            print("! cannot log in as admin with the current password")
            return
        if ADMIN_NEW_PW:
            code, resp = call(
                tok,
                "PUT",
                "/api/v1/users/changePassword",
                {
                    "username": "admin",
                    "oldPassword": ADMIN_PW,
                    "newPassword": ADMIN_NEW_PW,
                    "confirmPassword": ADMIN_NEW_PW,
                    "requestType": "SELF",
                },
            )
            print(f"change admin password -> {code} {('' if code < 300 else resp)}")
            tok = login(ADMIN_NEW_PW) or tok

    # 2) read-only viewer — delete-then-create so the password is set cleanly
    # (a pre-existing user blocks creation with 409 and leaves no usable basic
    # password; the password must satisfy OM's policy: 8+ chars, upper/lower/
    # digit/special). The viewer inherits the read-only DataConsumer role.
    if VIEWER_PW:
        # OM derives the user `name` from the email local-part, so look up and
        # create under THAT name (not a hardcoded "viewer"). A hardcoded name
        # breaks delete-then-create whenever the email's local-part differs
        # (e.g. guest@...): the lookup misses, leaving a 409 on re-create.
        viewer_name = VIEWER_EMAIL.split("@", 1)[0]
        code, existing = call(tok, "GET", f"/api/v1/users/name/{viewer_name}")
        if code < 300 and isinstance(existing, dict) and existing.get("id"):
            # M8: never hard-delete an admin/bot that happens to share the viewer
            # name (a misconfigured OM_VIEWER_EMAIL must not nuke a real account).
            # Also drop recursive=true — the viewer owns nothing by design.
            if existing.get("isAdmin") or existing.get("isBot"):
                print(
                    f"! refusing to delete '{viewer_name}': it is an admin/bot account "
                    "— check OM_VIEWER_EMAIL; skipping viewer setup"
                )
                print("done.")
                return
            call(tok, "DELETE", f"/api/v1/users/{existing['id']}?hardDelete=true")
            print("existing viewer removed")
        code, resp = call(
            tok,
            "POST",
            "/api/v1/users",
            {
                "name": viewer_name,
                "email": VIEWER_EMAIL,
                "displayName": "Viewer (público, read-only)",
                "password": VIEWER_PW,
                "confirmPassword": VIEWER_PW,
                "createPasswordType": "ADMIN_CREATE",
                "isAdmin": False,
                "isBot": False,
            },
        )
        print(f"create viewer -> {code} {('' if code < 300 else resp)}")
        # M3: explicitly grant the least-privilege read-only role so the viewer's
        # permissions never depend on OM's default-role policy (which may change).
        if code < 300 and isinstance(resp, dict) and resp.get("id"):
            rc, role = call(tok, "GET", "/api/v1/roles/name/DataConsumer")
            if rc < 300 and isinstance(role, dict) and role.get("id"):
                prc, _ = call(
                    tok,
                    "PATCH",
                    f"/api/v1/users/{resp['id']}",
                    [
                        {
                            "op": "add",
                            "path": "/roles/0",
                            "value": {"id": role["id"], "type": "role"},
                        }
                    ],
                    ct="application/json-patch+json",
                )
                print(f"grant viewer DataConsumer role -> {prc}")
            else:
                print(f"! DataConsumer role not found ({rc}) — viewer left on default role")
    print("done.")


if __name__ == "__main__":
    main()
