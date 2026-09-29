"""有版本的幂等内容契约；调用方先通过字段类型及业务校验。"""

import hashlib
import json


def request_digest(*, actor_id: str, operation: str, target_id: str | None, payload: dict) -> str:
    def validate(value):
        if value is None or type(value) in (str, int, bool):
            return
        if isinstance(value, list):
            for item in value:
                validate(item)
            return
        if isinstance(value, dict) and all(isinstance(key, str) for key in value):
            for item in value.values():
                validate(item)
            return
        raise ValueError("规范化请求仅接受JSON整数、字符串、布尔值、空值和容器；Decimal/日期/ID应先转字符串。")
    validate(payload)
    if not actor_id.isascii() or not actor_id.isdecimal() or not 0 < int(actor_id) <= 9223372036854775807:
        raise ValueError("操作者编号无效。")
    content = {"contract": "request-v1", "actor_id": str(int(actor_id)),
               "operation": operation, "target_id": target_id, "payload": payload}
    canonical = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
