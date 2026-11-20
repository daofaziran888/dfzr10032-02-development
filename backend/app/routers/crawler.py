"""网页采集规则接口：维护采集规则，覆盖提交测试、发布规则、停用规则等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.crawler import CrawlerService

router = APIRouter(prefix="/api/crawler", tags=["网页采集规则"])

service = CrawlerService()

LIST_FIELDS = ["规则编号", "目标网址", "页面选择器", "正文选择器", "翻页参数", "抓取频率", "字符编码", "去重策略"]
STATUSES = ["草稿", "测试中", "已发布", "已停用"]


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出网页采集规则清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "crawler", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    request: Request,
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    status: str | None = Query(default=None, description="草稿、测试中、已发布、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按规则编号与状态过滤网页采集规则列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    extra = {k: v for k, v in request.query_params.items() if k not in ("keyword", "status", "page", "size") and v.strip()}
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size, extra=extra)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条采集规则明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"采集规则 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条采集规则，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="采集规则已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条采集规则执行提交测试、发布规则、停用规则；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/{entry_id}/snapshots")
def list_snapshots(entry_id: int) -> dict[str, Any]:
    """列出规则的发布快照（含已回滚的中断残痕），可执行口径以「有效」为准。"""
    if service.get_entry(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"采集规则 {entry_id} 不存在或已归档")
    snapshots = service.list_snapshots(entry_id)
    current = service.current_snapshot(entry_id)
    return {
        "items": snapshots,
        "total": len(snapshots),
        "当前可执行版本": current["版本号"] if current else None,
    }


@router.post("/{entry_id}/publish", response_model=ActionResult)
def publish_rule(entry_id: int, payload: EntryPayload) -> ActionResult:
    """发布规则版本：四要素整体绑定成原子快照；模拟中断时只留回滚残痕，可安全重试。"""
    overrides = {field: payload.values.get(field) for field in ("目标网址", "正文选择器", "翻页参数", "字符编码") if payload.values.get(field)}
    simulate = str(payload.values.get("模拟中断") or "").strip() in ("1", "true", "是")
    snapshot, message = service.publish_rule(entry_id, overrides=overrides or None, simulate_interruption=simulate)
    if snapshot is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=snapshot)


@router.get("/{entry_id}/pages")
def list_pages(entry_id: int) -> dict[str, Any]:
    """列出规则已抓取的页面，每页都绑定了抓取时的快照版本。"""
    if service.get_entry(entry_id) is None:
        raise HTTPException(status_code=404, detail=f"采集规则 {entry_id} 不存在或已归档")
    pages = service.list_pages(entry_id)
    return {"items": pages, "total": len(pages)}


@router.post("/{entry_id}/fetch", response_model=ActionResult)
def fetch_page(entry_id: int, payload: EntryPayload) -> ActionResult:
    """按当前可执行快照抓取一页；已抓过的页保留原关联，不允许换版本重抓。"""
    try:
        page_no = int(payload.values.get("页码"))
    except (TypeError, ValueError):
        return ActionResult(ok=False, message="请给出要抓取的页码（整数）")
    page, message = service.fetch_page(entry_id, page_no)
    if page is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=page)
