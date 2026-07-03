"""Entry point: python -m crawler_service"""

import logging
import sys

import uvicorn

from . import config

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
# one log line per fetched URL is noise at production volume
logging.getLogger("httpx").setLevel(logging.WARNING)


def main():
    uvicorn.run(
        "crawler_service.web.main:app",
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
