"""Route modules; `app.create_app` includes every router."""
from . import library, live, monitor, ring, rules, teach

ROUTERS = [ring.router, library.router, teach.router, rules.router, live.router, monitor.router]

__all__ = ["ROUTERS"]
