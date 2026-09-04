"""Entry point for the web process.

Hosting platforms assign the port at runtime through $PORT, so it cannot be
hardcoded. Start with:  python -m lyfe.web
"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "lyfe.web.app:app",
        host=os.getenv("WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("PORT") or os.getenv("WEB_PORT") or 8000),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
