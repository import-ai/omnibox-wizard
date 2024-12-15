import json
import logging
import traceback
from datetime import datetime
from typing import Optional

from wizard.common import env


class CustomFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        source = ":".join([record.filename, str(record.lineno)])
        if isinstance(record.msg, dict):
            if "_source" in record.msg:  # override call stack
                source = record.msg["_source"]
                message = {k: v for k, v in record.msg.items() if k not in ["_source"]}
            else:
                message = record.msg
        else:
            message = record.getMessage()
        log = {
            'name': record.name,
            'level': record.levelname,
            'source': source,
            'create_time': datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S.%f'),
            'message': message
        }
        if record.exc_info:
            log["traceback"] = self.formatException(record.exc_info)
        str_log = json.dumps(log, ensure_ascii=False, separators=(',', ':'))
        if (length := len(str_log)) > 65535:
            log = {
                "error": "logging entity too long",
                "length": length,
                "traceback": ''.join(traceback.format_list(traceback.extract_stack()))
            }
            str_log = json.dumps(log)
        if "traceback" in log:  # 方便本地 DEBUG
            str_log += "\n" + log["traceback"]
        return str_log


logger = logging.getLogger("app")

formatter = CustomFormatter()
handler = logging.StreamHandler()
handler.setFormatter(formatter)

logger.addHandler(handler)
logger.setLevel(logging.INFO if env.is_prod() else logging.DEBUG)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    return logger.getChild(name) if name and name not in ["root", "app"] else logger


__all__ = ["get_logger"]
