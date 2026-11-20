"""网页采集规则业务规则：状态流转、字段校验与筛选口径都收在这里。

发布快照口径：
- 发布动作把目标网址、正文选择器、翻页参数、字符编码绑定成一份不可变的
  版本化快照（crawler_snapshot），格式解析器只认快照，不认规则当前字段。
- 快照一次性整体落库：要么四个要素齐全、状态「有效」，要么不存在。
  发布中断只留下状态「已回滚」的残痕，残痕永不进入可执行集；重试时从
  规则当前字段整体重建，绝不会把新选择器和旧编码拼成一套可执行规则。
- 已抓取的页面（crawler_page）绑定抓取那一刻的快照，之后规则再发新版，
  页面关联不变，也不允许用另一版规则重抓同一页。
"""
from __future__ import annotations

import base64
from datetime import datetime
from typing import Any

from app.fixtures import SIMULATED_SITES
from app.store import store

MODULE = "crawler"
SNAPSHOT_MODULE = "crawler_snapshot"
PAGE_MODULE = "crawler_page"
REQUIRED_FIELDS = ["规则编号", "目标网址", "页面选择器"]
STATUS_ORDER = ["草稿", "测试中", "已发布", "已停用"]
ACTION_RULES = {"提交测试": "测试中", "发布规则": "已发布", "停用规则": "已停用"}
NEGATIVE_ACTIONS = ["停用规则"]

# 发布快照绑定的四个要素：缺任何一个都不允许生成可执行版本。
SNAPSHOT_FIELDS = ["目标网址", "正文选择器", "翻页参数", "字符编码"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_id(module: str) -> int:
    return max((int(row.get("id", 0)) for row in store.rows(module)), default=0) + 1


class CrawlerService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
        extra: dict[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("规则编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if extra:
            for field, val in extra.items():
                rows = [row for row in rows if val in str(row.get(field, ""))]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"采集规则 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于网页采集规则可执行范围"
        if action == "发布规则":
            # 发布走原子快照流程：用规则当前字段整体出版，缺要素会被拦下。
            snapshot, message = self.publish_rule(entry_id)
            if snapshot is None:
                return None, message
            return entry, message
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"采集规则已{action}"

    # ---------- 发布快照 ----------

    def list_snapshots(self, entry_id: int) -> list[dict[str, Any]]:
        """规则的全部快照（含已回滚残痕），按版本号倒序。"""
        rows = [row for row in store.rows(SNAPSHOT_MODULE) if int(row.get("规则id", 0)) == entry_id]
        return sorted(rows, key=lambda row: int(row.get("版本号", 0)), reverse=True)

    def current_snapshot(self, entry_id: int) -> dict[str, Any] | None:
        """当前可执行快照：四要素齐全且状态「有效」的最新版本。

        已回滚的中断残痕在这里被天然滤掉，保证可执行规则永远是一套
        同一次发布产出的完整要素，不会出现新选择器配旧编码的拼接版。
        """
        usable = [row for row in self.list_snapshots(entry_id) if row.get("status") == "有效"]
        return usable[0] if usable else None

    def publish_rule(
        self,
        entry_id: int,
        overrides: dict[str, Any] | None = None,
        simulate_interruption: bool = False,
    ) -> tuple[dict[str, Any] | None, str]:
        """发布规则版本：把四个要素绑定成一份原子快照。

        overrides 用于「站点换了选择器/编码，先改规则再发布」的场景；
        simulate_interruption 模拟发布中途崩溃，验证重试不会拼出混合规则。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"采集规则 {entry_id} 不存在或已归档"
        overrides = overrides or {}
        merged = {field: str(overrides.get(field) or entry.get(field) or "").strip() for field in SNAPSHOT_FIELDS}
        missing = [field for field, val in merged.items() if not val]
        if missing:
            return None, f"发布失败：{'、'.join(missing)} 为空，四个要素齐全才能生成可执行快照"
        merged["字符编码"] = merged["字符编码"].upper()

        # 版本号只从「有效」快照顺延：中断残痕是已回滚的尝试，不占版本。
        # 重试沿用被回滚的版本号整体重建，而不是给残痕补字段。
        version = max(
            (int(row.get("版本号", 0)) for row in self.list_snapshots(entry_id) if row.get("status") == "有效"),
            default=0,
        ) + 1
        # 快照在内存里一次性组装完整，落库只有「整体提交」一步。
        snapshot = {
            "id": _next_id(SNAPSHOT_MODULE),
            "快照编号": f"SNAP-{entry_id:04d}-v{version}",
            "规则id": entry_id,
            "规则编号": entry.get("规则编号"),
            "版本号": version,
            **merged,
            "发布时间": _now(),
            "status": "有效",
            "pending": False,
            "abnormal": False,
        }

        if simulate_interruption:
            # 模拟崩溃：选择器已写、编码未写的半成品。残痕标记「已回滚」，
            # 永不进入可执行集；重试时整体重建，而不是给残痕补字段。
            residue = {
                "id": snapshot["id"],
                "快照编号": snapshot["快照编号"],
                "规则id": entry_id,
                "规则编号": entry.get("规则编号"),
                "版本号": version,
                "正文选择器": merged["正文选择器"],
                "发布时间": _now(),
                "status": "已回滚",
                "pending": False,
                "abnormal": True,
            }
            store.rows(SNAPSHOT_MODULE).append(residue)
            return None, f"发布中断：v{version} 半成品已回滚（未绑定字符编码），未生成可执行版本，请整体重试发布"

        store.rows(SNAPSHOT_MODULE).append(snapshot)
        # 发布成功后规则字段与最新快照对齐，状态置为已发布。
        entry.update(merged)
        entry["status"] = "已发布"
        entry["pending"] = False
        entry["abnormal"] = False
        return snapshot, f"采集规则已发布 v{version}（快照 {snapshot['快照编号']}，编码 {merged['字符编码']}）"

    # ---------- 页面抓取 ----------

    def list_pages(self, entry_id: int) -> list[dict[str, Any]]:
        rows = [row for row in store.rows(PAGE_MODULE) if int(row.get("规则id", 0)) == entry_id]
        return sorted(rows, key=lambda row: int(row.get("页码", 0)))

    def get_page(self, page_id: int) -> dict[str, Any] | None:
        return store.find(PAGE_MODULE, page_id)

    def fetch_page(self, entry_id: int, page_no: int) -> tuple[dict[str, Any] | None, str]:
        """按当前可执行快照抓取一页，页面从此绑定该快照版本。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"采集规则 {entry_id} 不存在或已归档"
        snapshot = self.current_snapshot(entry_id)
        if snapshot is None:
            return None, "规则还没有可执行的发布快照，请先发布规则"
        for page in self.list_pages(entry_id):
            if int(page.get("页码", 0)) == page_no:
                return None, (
                    f"第 {page_no} 页已抓取，保留原关联（快照 v{page['快照版本']}），"
                    "不能套用另一版规则重抓"
                )
        site = SIMULATED_SITES.get(str(snapshot["目标网址"]))
        page_bytes = (site or {}).get(page_no)
        if page_bytes is None:
            return None, f"目标站点没有第 {page_no} 页（模拟站点仅提供已登记页）"
        param = str(snapshot["翻页参数"])
        page = {
            "id": _next_id(PAGE_MODULE),
            "页面编号": f"PAGE-{entry_id:04d}-{page_no:03d}",
            "规则id": entry_id,
            "规则编号": entry.get("规则编号"),
            "快照id": snapshot["id"],
            "快照版本": snapshot["版本号"],
            "页码": page_no,
            "页面网址": f"{snapshot['目标网址']}?{param}={page_no}",
            "页面字节": base64.b64encode(page_bytes).decode("ascii"),
            "字节数": len(page_bytes),
            "抓取时间": _now(),
            "status": "已抓取",
            "pending": True,
            "abnormal": False,
        }
        store.rows(PAGE_MODULE).append(page)
        return page, f"第 {page_no} 页已按快照 v{snapshot['版本号']} 抓取（{len(page_bytes)} 字节）"
