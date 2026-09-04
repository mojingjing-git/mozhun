import logging
import re
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

LOG_DIR = Path.home() / ".proofreader"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "app.log"
# v4.1 (I10): 加一个 debug.log 专门存 DEBUG 级别日志 (含网络异常 / 推流失败 / 拖拽事件).
# windowed 模式没控制台, 用户没法看 stdout; 文件能落地, 排查时让用户直接看路径.
DEBUG_LOG_FILE = LOG_DIR / "app-debug.log"

_SENSITIVE_RE = re.compile(r"(sk-|api[_-]?key[=:\s]+)(\S{4})\S{4,}", re.IGNORECASE)


def _mask_sensitive(msg: str) -> str:
    return _SENSITIVE_RE.sub(r"\1\2****", msg)


class _SensitiveFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _mask_sensitive(record.msg)
        return True


_logger: logging.Logger | None = None


def setup_logging() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    logger = logging.getLogger("Proofreader")
    logger.setLevel(logging.DEBUG)
    logger.addFilter(_SensitiveFilter())

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 主日志: 5MB × 3 备份, 记 INFO 及以上 (生产用)
    file_handler = RotatingFileHandler(
        str(LOG_FILE), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    # v4.1 (I10): DEBUG 日志, 10MB × 2 备份, 排查问题时给开发/用户看
    debug_handler = RotatingFileHandler(
        str(DEBUG_LOG_FILE), maxBytes=10 * 1024 * 1024, backupCount=2, encoding="utf-8"
    )
    debug_handler.setLevel(logging.DEBUG)
    debug_handler.setFormatter(fmt)
    logger.addHandler(debug_handler)

    # 控制台: INFO 及以上. windowed 模式 stdout 看不到, 但 dev 模式 (python main.py) 能看.
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    logger.info(f"调试日志路径: {DEBUG_LOG_FILE}")

    _logger = logger
    return logger
