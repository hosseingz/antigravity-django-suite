"""
Apps namespace package marker.

All domain business logic applications (e.g. users, catalog, orders)
are created inside this directory. Because `apps/` is injected into
`sys.path` in `config/settings.py`, applications must be imported directly
(e.g., `import users.models`) rather than prefixing with `apps.`
"""
