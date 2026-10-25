# -*- coding: utf-8 -*-
"""联调冒烟测试：前端(5500) → 后端(8000) → DeepSeek 全链路。测试数据最后清理。"""
import json
import sys
import urllib.request

from playwright.sync_api import sync_playwright

FRONT = "http://127.0.0.1:5500/index.html"
BACK = "http://127.0.0.1:8000"
FIXTURE_PDF = r"D:\heimaAI应用与智能体开发\章节测评1\04-练习作业\智能问诊系统\test\fixtures\real_report.pdf"
SHOT_DIR = r"D:\heimaAI应用与智能体开发\章节测评1\04-练习作业\智能问诊系统\test\screenshots"

results = []

def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS" if cond else "FAIL"), "-", name, detail if not cond else "")

page_errors = []

with sync_playwright() as p:
    # 本机 Edge 驱动测试（避免 Playwright 私有 Chromium 版本不匹配）；也可回退到本地 chromium-1234
    browser = p.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 800})
    page.on("pageerror", lambda e: page_errors.append(str(e)))
    page.on("console", lambda m: page_errors.append(m.text) if m.type == "error" else None)
    page.goto(FRONT)
    page.wait_for_load_state("networkidle")

    # 1. 页面结构
    check("欢迎语展示", page.locator(".bubble-ai").count() == 1)
    check("底部免责声明", "仅供健康咨询使用" in page.locator(".footer").inner_text())

    # 2. 空输入拦截（C-E1）
    page.fill("#chatInput", "   ")
    page.click("#btnSend")
    page.wait_for_timeout(300)
    check("空输入拦截提示", page.locator(".toast.warn").count() >= 1)
    check("空输入未追加消息", page.locator(".msg.user").count() == 0)

    # 3. 真实流式咨询
    page.fill("#chatInput", "最近总失眠，有什么改善建议？")
    page.keyboard.press("Enter")
    check("用户消息上屏", page.locator(".msg.user").count() == 1)
    check("发送按钮进入回复态", page.locator("#btnSend").inner_text() == "回复中…")
    page.wait_for_selector("#btnSend:not(:disabled)", timeout=110000)   # 流结束恢复
    ai_text = page.locator(".msg.ai .md-block").last.inner_text()
    for seg in ("症状分析", "缓解建议", "需警惕事项", "何时就医", "温馨提示"):
        check(f"五段式含[{seg}]", seg in ai_text)
    check("Markdown 列表渲染", page.locator(".msg.ai .md-block ul li").count() > 3)
    page.screenshot(path=SHOT_DIR + r"\chat_real.png", full_page=False)

    # 3b. 多轮上下文：第二问能引用前文
    page.fill("#chatInput", "第二种方法具体怎么做？")
    page.keyboard.press("Enter")
    page.wait_for_selector("#btnSend:not(:disabled)", timeout=110000)
    check("第二轮回复产生", page.locator(".msg.user").count() == 2)

    # 4. 报告：非法文件拦截
    page.set_input_files("#fileInput", FIXTURE_PDF.replace("real_report.pdf", "photo.jpg"))
    page.wait_for_timeout(400)
    check("非PDF拦截toast", page.locator(".toast.error").count() >= 1)
    check("拦截后仍在上传区", page.locator("#uploadZone").is_visible())

    # 5. 报告：真实上传 + 轮询 + 四段式
    page.set_input_files("#fileInput", FIXTURE_PDF)
    page.wait_for_selector("#analyzing", state="visible", timeout=8000)
    check("进入AI分析加载态", page.locator("#analyzing p").inner_text().startswith("AI正在分析"))
    page.wait_for_selector("#result", state="visible", timeout=125000)
    rtext = page.locator("#result").inner_text()
    check("结果四段式", all(s in rtext for s in ("基本信息", "异常项明细", "总体健康建议", "注意事项")))
    abn = page.locator(".abn-item")
    check("异常项四要素", abn.count() > 0
          and "参考范围" in abn.first.inner_text()
          and page.locator(".abn-adv").count() == abn.count()   # 每条都带改进方案
          and "偏高" in rtext)
    page.screenshot(path=SHOT_DIR + r"\report_real.png", full_page=False)

    # 6. 重新分析回到上传态
    page.click("#btnReanalyze")
    check("重新分析重置", page.locator("#uploadZone").is_visible() and page.locator("#result").is_hidden())

    client_id = page.evaluate("localStorage.getItem('clinic_client_id')")
    browser.close()

# 7. 后端落库验证 + 测试数据清理
def http(method, path, cid):
    req = urllib.request.Request(BACK + path, method=method, headers={"X-Client-Id": cid})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read().decode("utf-8"))["data"]

convs = http("GET", "/api/conversations", client_id)
reports = http("GET", "/api/reports", client_id)
check("会话落库", len(convs["list"]) >= 1)
check("分析记录落库", len(reports["list"]) >= 1)

for c in convs["list"]:
    http("DELETE", f"/api/conversations/{c['id']}", client_id)
for r in reports["list"]:
    http("DELETE", f"/api/report/{r['id']}", client_id)
check("测试数据已清理",
      http("GET", "/api/conversations", client_id)["total"] == 0
      and http("GET", "/api/reports", client_id)["total"] == 0)
check("无JS报错", not page_errors, "; ".join(page_errors[:3]))

fails = [n for n, okk, _ in results if not okk]
print(f"\n===== 共 {len(results)} 项，通过 {len(results)-len(fails)}，失败 {len(fails)} =====")
sys.exit(1 if fails else 0)
