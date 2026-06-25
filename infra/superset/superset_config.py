"""Superset configuration — loaded via SUPERSET_CONFIG_PATH."""
import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]

SQLALCHEMY_DATABASE_URI = (
    "postgresql+psycopg2://superset:"
    f"{os.environ['SUPERSET_DB_PASSWORD']}@postgres:5432/superset"
)

FEATURE_FLAGS = {
    "DASHBOARD_RBAC": True,
}

# Anonymous visitors can VIEW published dashboards (read-only portfolio mode).
# Editing, SQL Lab and admin remain login-only.
# NOTE: PUBLIC_ROLE_LIKE = "Gamma" is intentionally NOT set — it would copy a
# content creator's whole permission set to anonymous visitors (write on charts,
# Charts/Datasets/Databases menus, CSV export, SQL view). bootstrap_dashboard.py
# instead grants the Public role a curated view-only-dashboard set on each deploy.
AUTH_ROLE_PUBLIC = "Public"

# Behind the Cloudflare Tunnel, Superset is reached over HTTPS via a reverse
# proxy. Honor X-Forwarded-* so generated URLs/redirects use https and cookies
# are marked secure (avoids mixed-content and login/redirect loops).
ENABLE_PROXY_FIX = True
PREFERRED_URL_SCHEME = "https"
# Secure cookies require HTTPS. Default OFF so HTTP API clients on loopback work
# — preset-cli (dashboard-as-code sync) and admin over an SSH tunnel both hit
# Superset on plain http://localhost; a Secure cookie would never be sent back,
# breaking login. Enable on the public HTTPS environments with
# SUPERSET_SECURE_COOKIES=true (the tunnel still serves everything over TLS).
SESSION_COOKIE_SECURE = os.environ.get("SUPERSET_SECURE_COOKIES", "false").lower() == "true"
SESSION_COOKIE_SAMESITE = "Lax"
