"""Start the trainee web application."""

import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    args = sys.argv[1:]
    if any(arg == "--role" or arg.startswith("--role=") for arg in args):
        raise SystemExit("This launcher runs the trainee role.")
    from simu.server import main

    os.chdir(root)
    log_dir = root / "log"
    log_dir.mkdir(exist_ok=True)
    logger = logging.getLogger("simu.web")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        log_dir / "web.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    try:
        status = main([
            "--role", "trainee",
            "--models-dir", str(root / "data" / "models"),
            "--runtime-dir", str(root / "data" / "runtime"),
            *args,
        ])
    except Exception:
        logger.exception("Web service failed")
        raise
    finally:
        handler.close()
    sys.exit(status)
