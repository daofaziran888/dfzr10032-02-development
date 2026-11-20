"""HTTP 冒烟：把两页公告场景走一遍真实接口。

运行前先起服务：cd backend && ./run.sh
然后：.venv/bin/python3 tests/smoke_http.py
"""
from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


from urllib.parse import quote  # noqa: E402

print("1. 首页按 v1 解析:", call("POST", "/api/parser/4/parse", {"values": {"页面id": 1}})["message"])
view = call("GET", "/api/parser/notification?" + quote("规则编号") + "=CRAW-0004")
print("2. 闭馆时间是否已进入本次通知:", view["闭馆时间是否已进入本次通知"])
print("3. 模拟中断:", call("POST", "/api/crawler/4/publish", {"values": {"正文选择器": "div.notice p", "字符编码": "UTF-8", "模拟中断": "是"}})["message"])
print("4. 重试发布:", call("POST", "/api/crawler/4/publish", {"values": {"正文选择器": "div.notice p", "字符编码": "UTF-8"}})["message"])
print("5. 重抓首页被拒:", call("POST", "/api/crawler/4/fetch", {"values": {"页码": 1}})["message"])
print("6. 抓次页:", call("POST", "/api/crawler/4/fetch", {"values": {"页码": 2}})["message"])
print("7. 解析次页:", call("POST", "/api/parser/4/parse", {"values": {"页面id": 2}})["message"])
view = call("GET", "/api/parser/notification?" + quote("规则编号") + "=CRAW-0004")
print("8. 闭馆时间是否已进入本次通知:", view["闭馆时间是否已进入本次通知"])
for p in view["段落"]:
    mark = "【闭馆】" if p["是否闭馆信息"] else ""
    print(f"   第{p['页码']}页 v{p['快照版本']} [{p['正文选择器']}] {p['正文文本'][:30]}…{mark}")
records = call("GET", "/api/parser/records?" + quote("规则编号") + "=CRAW-0004&" + quote("快照版本") + "=2")
print("9. 按版本回查 v2 记录数:", records["total"])
