"""格式解析器业务规则：状态流转、字段校验与筛选口径都收在这里。

正文提取口径：
- 解析器不直接读采集规则的当前字段，而是读页面绑定的网页采集规则发布快照：
  用快照里的字符编码解码页面字节，用快照里的正文选择器抽取段落。
- 每段正文落库为一条正文记录（parser_record），记录页面、快照版本与选择器，
  持久化之后随时可以回查「这段文字是哪一页、按哪一版规则、用哪个选择器抽的」。
- 已抓取的页面保留原关联：规则再发新版，已抓页面仍按抓取时的快照解析。
"""
from __future__ import annotations

import base64
import re
from datetime import datetime
from typing import Any

from app.services.crawler import SNAPSHOT_MODULE, CrawlerService
from app.services.html_extract import extract_paragraphs
from app.store import store

MODULE = "parser"
RECORD_MODULE = "parser_record"
REQUIRED_FIELDS = ["解析编号", "输入格式", "输出格式"]
STATUS_ORDER = ["草稿", "已配置", "生效中", "已废弃"]
ACTION_RULES = {"提交配置": "已配置", "启用解析": "生效中", "废弃解析": "已废弃"}
NEGATIVE_ACTIONS = []

# 闭馆口径：正文里出现这些说法，就认为闭馆时间已进入本次通知。
CLOSURE_PATTERN = re.compile(r"临时闭馆|闭馆时间|暂停开放|暂停对外开放")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ParserService:
    def __init__(self) -> None:
        self._crawler = CrawlerService()

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
            rows = [row for row in rows if keyword in str(row.get("解析编号", ""))]
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
            return None, f"解析配置 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于格式解析器可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"解析配置已{action}"

    # ---------- 正文记录 ----------

    def list_records(
        self,
        *,
        规则编号: str | None = None,
        快照版本: int | None = None,
        页面id: int | None = None,
    ) -> list[dict[str, Any]]:
        rows = list(store.rows(RECORD_MODULE))
        if 规则编号:
            rows = [row for row in rows if row.get("规则编号") == 规则编号]
        if 快照版本 is not None:
            rows = [row for row in rows if int(row.get("快照版本", 0)) == 快照版本]
        if 页面id is not None:
            rows = [row for row in rows if int(row.get("页面id", 0)) == 页面id]
        return sorted(rows, key=lambda row: (int(row.get("页码", 0)), int(row.get("段落序号", 0))))

    def parse_page(self, parser_id: int, page_id: int) -> tuple[list[dict[str, Any]] | None, str]:
        """按页面绑定的发布快照解析一页，正文记录整体重写（幂等）。"""
        parser = store.find(MODULE, parser_id)
        if parser is None:
            return None, f"解析配置 {parser_id} 不存在或已废弃"
        if parser.get("status") != "生效中":
            return None, f"解析配置 {parser.get('解析编号')} 尚未生效，不能执行解析"
        page = self._crawler.get_page(page_id)
        if page is None:
            return None, f"页面 {page_id} 不存在或已归档"
        # 关键口径：用页面抓取时绑定的快照，而不是规则当前版本。
        snapshot = store.find(SNAPSHOT_MODULE, int(page.get("快照id", 0)))
        if snapshot is None or snapshot.get("status") != "有效":
            return None, f"页面 {page['页面编号']} 绑定的快照不可用，无法解析"

        charset = str(snapshot["字符编码"])
        raw = base64.b64decode(str(page["页面字节"]))
        try:
            html = raw.decode(charset)
        except (UnicodeDecodeError, LookupError) as exc:
            return None, (
                f"页面 {page['页面编号']} 按快照 v{snapshot['版本号']} 的编码 {charset} 解码失败：{exc}。"
                "请核对快照绑定的字符编码是否与页面字节一致"
            )
        try:
            paragraphs = extract_paragraphs(html, str(snapshot["正文选择器"]))
        except ValueError as exc:
            return None, f"快照 v{snapshot['版本号']} 的正文选择器不可用：{exc}"

        table = store.rows(RECORD_MODULE)
        table[:] = [row for row in table if int(row.get("页面id", 0)) != page_id]
        next_id = max((int(row.get("id", 0)) for row in table), default=0) + 1
        records: list[dict[str, Any]] = []
        for seq, text in enumerate(paragraphs, start=1):
            record = {
                "id": next_id,
                "记录编号": f"PARA-{page_id:04d}-{seq:03d}",
                "解析编号": parser.get("解析编号"),
                "页面id": page_id,
                "页面编号": page["页面编号"],
                "页码": page["页码"],
                "规则编号": page["规则编号"],
                "快照id": snapshot["id"],
                "快照版本": snapshot["版本号"],
                "正文选择器": snapshot["正文选择器"],
                "字符编码": charset,
                "段落序号": seq,
                "正文文本": text,
                "解析时间": _now(),
                "status": "已解析",
                "pending": False,
                "abnormal": False,
            }
            table.append(record)
            records.append(record)
            next_id += 1
        return records, (
            f"页面 {page['页面编号']} 已按快照 v{snapshot['版本号']} 解析，"
            f"生成 {len(records)} 段正文记录"
        )

    def parse_rule_pages(self, parser_id: int, rule_id: int) -> tuple[list[dict[str, Any]] | None, str]:
        """把一条规则下所有已抓页面逐页解析，每页仍按各自绑定的快照。"""
        pages = self._crawler.list_pages(rule_id)
        if not pages:
            return None, f"采集规则 {rule_id} 还没有抓取任何页面"
        all_records: list[dict[str, Any]] = []
        for page in pages:
            records, message = self.parse_page(parser_id, int(page["id"]))
            if records is None:
                return None, message
            all_records.extend(records)
        return all_records, f"规则下 {len(pages)} 个已抓页面全部解析完成，共 {len(all_records)} 段正文记录"

    # ---------- 值班员通知视图 ----------

    def notification_view(self, rule_code: str) -> tuple[dict[str, Any] | None, str]:
        """汇总一份通知的全部正文段落，标注闭馆时间是否已进入本次通知。

        每段文字都带页面、快照版本与选择器，值班员重新进入排班页时，
        读到的就是持久化后的同一份结果。
        """
        rules = [row for row in store.rows("crawler") if row.get("规则编号") == rule_code]
        if not rules:
            return None, f"采集规则 {rule_code} 不存在"
        rule = rules[0]
        rule_id = int(rule["id"])
        pages = self._crawler.list_pages(rule_id)
        records = self.list_records(规则编号=rule_code)
        closure_texts = [row["正文文本"] for row in records if CLOSURE_PATTERN.search(str(row["正文文本"]))]
        view = {
            "规则编号": rule_code,
            "目标网址": rule.get("目标网址"),
            "闭馆时间是否已进入本次通知": bool(closure_texts),
            "闭馆信息": closure_texts,
            "页面": [
                {
                    "页面id": page["id"],
                    "页面编号": page["页面编号"],
                    "页码": page["页码"],
                    "快照版本": page["快照版本"],
                    "抓取时间": page["抓取时间"],
                    "是否已解析": any(int(row.get("页面id", 0)) == int(page["id"]) for row in records),
                }
                for page in pages
            ],
            "段落": [
                {
                    "记录编号": row["记录编号"],
                    "页码": row["页码"],
                    "页面编号": row["页面编号"],
                    "快照版本": row["快照版本"],
                    "正文选择器": row["正文选择器"],
                    "段落序号": row["段落序号"],
                    "正文文本": row["正文文本"],
                    "是否闭馆信息": bool(CLOSURE_PATTERN.search(str(row["正文文本"]))),
                }
                for row in records
            ],
        }
        return view, "ok"
