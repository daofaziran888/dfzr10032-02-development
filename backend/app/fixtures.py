"""模拟站点：演示用的两页公告原始字节。

真实项目里抓取动作会走网络；这里用内置字节代替，重点是让两页公告的
字符编码不同（首页 GBK、次页 UTF-8），从而体现发布快照绑定字符编码的意义：
一旦把新选择器和旧编码拼成一套规则，次页字节就会解码失败。
"""
from __future__ import annotations

ANNOUNCEMENT_URL = "https://notice.example.com/bulletin"

# 首页：常规开放时间，GBK 字节（对应旧版快照的字符编码）。
ANNOUNCEMENT_PAGE1_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="GBK"><title>场馆开放公告（第1页）</title></head>
<body>
<div class="notice">
  <h1>场馆开放公告</h1>
  <p>常规开放时间：周二至周日 9:00-17:00（16:30 停止入馆）。</p>
  <p>周一例行闭馆，法定节假日照常开放。</p>
  <p>咨询电话：010-8888 6666，预约平台每日 20:00 放票。</p>
</div>
</body>
</html>
"""

# 次页：临时闭馆时间放在 div.closure 里的嵌套段落，UTF-8 字节。
# 旧选择器 div.notice > p 只认直接子段落，抽不到它；新选择器 div.notice p 可以。
ANNOUNCEMENT_PAGE2_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>场馆开放公告（第2页）</title></head>
<body>
<div class="notice">
  <p>参观须知：请勿触摸展品，馆内禁止饮食与闪光灯拍摄。</p>
  <div class="closure">
    <p>临时闭馆时间：2026年11月25日至11月27日设备检修，暂停开放。</p>
  </div>
  <p>团队参观请提前三个工作日在预约平台登记。</p>
</div>
</body>
</html>
"""

# 目标网址 -> {页码: 页面字节}
SIMULATED_SITES: dict[str, dict[int, bytes]] = {
    ANNOUNCEMENT_URL: {
        1: ANNOUNCEMENT_PAGE1_HTML.encode("gbk"),
        2: ANNOUNCEMENT_PAGE2_HTML.encode("utf-8"),
    }
}
