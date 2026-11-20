"""两页公告场景回归测试：发布快照原子性、页面原关联、正文记录可回查。

运行：cd backend && .venv/bin/python3 -m tests.test_snapshot_flow
（也可以直接 .venv/bin/python3 tests/test_snapshot_flow.py）

场景：同一份两页公告已按旧规则抓到首页；翻到次页前站点发布了新版正文
选择器。新版能抽出临时闭馆时间，旧版只识别常规开放时间。值班员重新
进入排班页时，要能查到闭馆时间是否已进入本次通知。
"""
from __future__ import annotations

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.fixtures import SIMULATED_SITES, ANNOUNCEMENT_URL  # noqa: E402
from app.services.crawler import CrawlerService  # noqa: E402
from app.services.parser import ParserService  # noqa: E402

RULE_ID = 4
PARSER_ID = 4

crawler = CrawlerService()
parser = ParserService()

passed = 0


def check(label: str, condition: bool) -> None:
    global passed
    assert condition, f"失败：{label}"
    passed += 1
    print(f"  ✓ {label}")


print("一、起态：旧版快照 v1 已发布，首页已按 v1 抓取")
snapshot = crawler.current_snapshot(RULE_ID)
check("当前可执行快照是 v1", snapshot is not None and snapshot["版本号"] == 1)
check("v1 绑定旧选择器 div.notice > p", snapshot["正文选择器"] == "div.notice > p")
check("v1 绑定字符编码 GBK", snapshot["字符编码"] == "GBK")
pages = crawler.list_pages(RULE_ID)
check("只抓了首页", len(pages) == 1 and pages[0]["页码"] == 1)
check("首页绑定快照 v1", pages[0]["快照版本"] == 1)

print("二、首页按原关联（v1）解析：只识别常规开放时间")
records, message = parser.parse_page(PARSER_ID, pages[0]["id"])
check("首页解析成功", records is not None)
check("首页抽出 3 段常规内容", records is not None and len(records) == 3)
check("每段都带快照版本与选择器", all(r["快照版本"] == 1 and r["正文选择器"] == "div.notice > p" for r in records or []))
check("首页正文里没有临时闭馆时间", all("临时闭馆" not in r["正文文本"] for r in records or []))
view, _ = parser.notification_view("CRAW-0004")
check("此时闭馆时间尚未进入本次通知", view is not None and view["闭馆时间是否已进入本次通知"] is False)

print("三、发布中断：半成品回滚，不产生可执行版本")
_, message = crawler.publish_rule(
    RULE_ID,
    overrides={"正文选择器": "div.notice p", "字符编码": "UTF-8"},
    simulate_interruption=True,
)
check("中断的发布被报告为失败", "中断" in message)
snapshot = crawler.current_snapshot(RULE_ID)
check("可执行快照仍是 v1，残痕进不了可执行集", snapshot is not None and snapshot["版本号"] == 1)
residues = [s for s in crawler.list_snapshots(RULE_ID) if s["status"] == "已回滚"]
check("中断只留下一条已回滚残痕", len(residues) == 1)
check("残痕里只有新选择器、没有字符编码（半成品）", residues[0].get("正文选择器") == "div.notice p" and "字符编码" not in residues[0])

print("四、重试发布：整体重建，绝不拼出「新选择器+旧编码」")
snapshot, message = crawler.publish_rule(
    RULE_ID,
    overrides={"正文选择器": "div.notice p", "字符编码": "UTF-8"},
)
check("重试发布成功，生成 v2", snapshot is not None and snapshot["版本号"] == 2)
check("v2 是新选择器", snapshot["正文选择器"] == "div.notice p")
check("v2 是新编码 UTF-8（不是旧编码 GBK 拼接）", snapshot["字符编码"] == "UTF-8")
mixed = [s for s in crawler.list_snapshots(RULE_ID) if s["status"] == "有效" and s["正文选择器"] == "div.notice p" and s.get("字符编码") == "GBK"]
check("可执行集中不存在新选择器配旧编码的混合规则", not mixed)

print("五、混合规则反事实：若真拼了新选择器+旧编码，次页根本解不开")
page2_bytes = SIMULATED_SITES[ANNOUNCEMENT_URL][2]
try:
    mojibake = page2_bytes.decode("gbk")
    decode_broke = "临时闭馆时间" not in mojibake
except UnicodeDecodeError:
    decode_broke = True
check("次页 UTF-8 字节按旧编码 GBK 解码必然失败或乱码", decode_broke)

print("六、已抓页面保留原关联，次页按新版 v2 抓取")
page, message = crawler.fetch_page(RULE_ID, 1)
check("首页不允许换版本重抓", page is None and "保留原关联" in message)
page2, message = crawler.fetch_page(RULE_ID, 2)
check("次页抓取成功", page2 is not None)
check("次页绑定快照 v2", page2 is not None and page2["快照版本"] == 2)
pages = crawler.list_pages(RULE_ID)
check("首页仍绑定 v1，未被套用新版", pages[0]["快照版本"] == 1)

print("七、格式解析器按各页绑定的快照生成正文记录")
records2, message = parser.parse_page(PARSER_ID, page2["id"])
check("次页解析成功", records2 is not None)
check("新版选择器抽出 3 段（含嵌套的闭馆段）", records2 is not None and len(records2) == 3)
closure = [r for r in records2 or [] if "临时闭馆时间" in r["正文文本"]]
check("临时闭馆时间被新版规则抽出", len(closure) == 1)
check("闭馆段记录可回查页面、版本与选择器", closure[0]["页面编号"] == "PAGE-0004-002" and closure[0]["快照版本"] == 2 and closure[0]["正文选择器"] == "div.notice p")
records1, _ = parser.parse_page(PARSER_ID, pages[0]["id"])
check("规则已发新版，首页重解析仍按原关联 v1", records1 is not None and all(r["快照版本"] == 1 for r in records1))
check("首页仍只识别常规开放时间", records1 is not None and all("临时闭馆" not in r["正文文本"] for r in records1))

print("八、值班员重新进入排班页：读持久化正文，闭馆时间已在通知里")
view, _ = parser.notification_view("CRAW-0004")
check("闭馆时间是否已进入本次通知 = 是", view is not None and view["闭馆时间是否已进入本次通知"] is True)
check("闭馆信息内容完整", view is not None and any("11月25日至11月27日" in t for t in view["闭馆信息"]))
check("通知共 6 段（首页 3 + 次页 3）", view is not None and len(view["段落"]) == 6)
check(
    "每段文字都能查回页面和选择器",
    view is not None and all(p["页面编号"] and p["正文选择器"] and p["快照版本"] for p in view["段落"]),
)
persisted = parser.list_records(规则编号="CRAW-0004", 快照版本=2)
check("持久化后仍可按规则编号+版本回查 v2 记录", len(persisted) == 3)

print(f"\n全部通过：{passed} 项检查")
