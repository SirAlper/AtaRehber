import os
import sys
import logging
from logging.handlers import RotatingFileHandler
from src.core.config import LOG_LEVEL, LOG_FILE


def setup_logging(log_level: str = LOG_LEVEL, log_file: str = LOG_FILE) -> logging.Logger:
    """Configure centralized logging with console and rotating file output."""
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger("EnterpriseRAG")
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers if setup_logging is called multiple times
    if not root_logger.handlers:
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # 1. Console Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(numeric_level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

        # 2. Rotating File Handler (up to 10MB per file, max 5 backups)
        if log_file:
            try:
                log_dir = os.path.dirname(log_file)
                if log_dir:
                    os.makedirs(log_dir, exist_ok=True)
                file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
                file_handler.setLevel(numeric_level)
                file_handler.setFormatter(formatter)
                root_logger.addHandler(file_handler)
            except Exception as e:
                root_logger.warning(f"Failed to initialize file logger at '{log_file}': {e}")

    return root_logger


def get_logger(name: str = "EnterpriseRAG") -> logging.Logger:
    """Return a logger child instance under the centralized configuration."""
    setup_logging()
    if name == "EnterpriseRAG":
        return logging.getLogger("EnterpriseRAG")
    return logging.getLogger(f"EnterpriseRAG.{name}")


logger = get_logger()
