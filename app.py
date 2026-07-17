# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.app_factory import create_app

app = create_app()


if __name__ == "__main__":
    app.run(
        host=app.config.get("HOST", "127.0.0.1"),
        port=int(app.config.get("PORT", 8000)),
        debug=bool(app.config.get("DEBUG", True)),
    )
