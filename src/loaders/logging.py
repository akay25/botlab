import logging
from typing import Union

from pythonjsonlogger import jsonlogger

from .config import config


def get_log_level(log_level: str) -> int:
    log_level = log_level.upper()
    if log_level == "CRITICAL":
        return logging.CRITICAL
    elif log_level == "ERROR":
        return logging.ERROR
    elif log_level == "WARNING":
        return logging.WARN
    elif log_level == "DEBUG":
        return logging.DEBUG
    return logging.INFO


def get_logger(
    logger_name: str = "", log_level: Union[str, None] = None
) -> logging.Logger:
    level = get_log_level(log_level or config.LOG_LEVEL)
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    return logger
