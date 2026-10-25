"""智能问诊系统后端入口（FastAPI，V2.0）。接口与错误码严格对齐《开发文档/API设计文档.md》V2.0。
鉴权：除注册/登录/健康检查外，所有接口需请求头 X-Token（auth_token 表校验 → user_id 归属）。
启动：uv run uvicorn main:app --host 0.0.0.0 --port 8000
"""
import json
import os
import re
import threading
import uuid
from datetime import datetime
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

import auth_service
import config
import db
from auth_service import AuthError
from llm_service import LlmError, analyze_report, chat_stream, report_brief
from pdf_service import extract_text
from prompts import CHAT_SYSTEM, FOLLOWUP_CONTEXT

app = FastAPI(title="智能问诊系统 API", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_busy_lock = threading.Lock()
_busy_convs: set[int] = set()          # 会话级互斥：4204（API文档 3.1）


class BizError(Exception):
    def __init__(self, code: int, message: str):
        self.code, self.message = code, message


@app.exception_handler(BizError)
async def biz_handler(_, e: BizError):
    return JSONResponse({"code": e.code, "message": e.message, "data": None})


@app.exception_handler(AuthError)
async def auth_handler(_, e: AuthError):
    return JSONResponse({"code": e.code, "message": e.message, "data": None})


def ok(data=None):
    return {"code": 0, "message": "ok", "data": data}


def err(code: int, message: str):
    return JSONResponse({"code": code, "message": message, "data": None})


def user_of(request: Request) -> dict:
    """X-Token 鉴权（API文档 1.1 V2.0）：解析出 {user_id, username}，失效 4411。"""
    return auth_service.authenticate(request.headers.get("X-Token", "").strip())


# ==================== A. 认证模块（V2.0 新增） ====================

class RegisterReq(BaseModel):
    username: str = ""
    email: str = ""
    password: str = ""
    confirm_password: str = ""


class LoginReq(BaseModel):
    username: str = ""
    password: str = ""


@app.post("/api/register")
def register(body: RegisterReq):
    name = auth_service.register(body.username.strip(), body.email.strip(),
                                 body.password, body.confirm_password)
    return ok({"username": name})           # 前端收到成功后跳转登录页


@app.post("/api/login")
def login(body: LoginReq):
    token, name = auth_service.login(body.username.strip(), body.password)
    return ok({"token": token, "username": name})


@app.post("/api/logout")
def logout(request: Request):
    auth_service.logout(request.headers.get("X-Token", "").strip())   # 幂等，不校验有效性
    return ok({"logged_out": True})


@app.get("/api/me")
def me(request: Request):
    u = user_of(request)
    full = db.get_user(u["user_id"])
    return ok({"username": full["username"], "email": full["email"], "created_at": full["created_at"]})


# ==================== 1. 健康检查 ====================

@app.get("/api/health")
def health():
    return ok({"status": "ok", "version": "2.0",
               "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})


# ==================== 2. 健康咨询（SSE 流式） ====================

class ChatReq(BaseModel):
    content: str = ""
    conversation_id: int | None = None
    analysis_id: int | None = None


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/chat")
def chat(body: ChatReq, request: Request):
    user = user_of(request)
    uid = user["user_id"]
    text = body.content.strip()
    if not text:                                   # 4001（非流式直接返回，API文档 3.1）
        return err(4001, "请先输入您的健康问题")
    if len(text) > config.MAX_INPUT_LEN:           # 4002
        return err(4002, "输入内容超过 2000 字符，请精简后发送")

    followup_report = None
    if body.analysis_id is not None:               # 报告追问（US-303）
        followup_report = db.get_report(uid, body.analysis_id)
        if not followup_report or followup_report["status"] != "success":
            raise BizError(4302, "记录不存在或已被删除")

    if body.conversation_id is not None:           # 既有会话：校验归属
        if not db.get_conversation(uid, body.conversation_id):
            raise BizError(4302, "记录不存在或已被删除")
        conv_id = body.conversation_id
    else:                                          # 新会话：title 取首问前 30 字
        conv_id = db.create_conversation(
            uid, text[:30],
            scene="report_followup" if followup_report else "chat",
            related_analysis_id=body.analysis_id)

    with _busy_lock:                               # 防并发：4204（C-E8 同会话互斥）
        if conv_id in _busy_convs:
            raise BizError(4204, "上一条消息回复中，请稍候")
        _busy_convs.add(conv_id)

    db.add_message(conv_id, "user", text)
    db.touch_conversation(conv_id)

    history = db.get_recent_messages(conv_id, config.CONTEXT_MSG_LIMIT)
    messages = [{"role": "system", "content": CHAT_SYSTEM}]
    if followup_report:                            # 追问上下文注入（API文档 3.1）
        bi, ab, adv = report_brief(followup_report)
        messages.append({"role": "system",
                         "content": FOLLOWUP_CONTEXT.format(basic_info=bi, abnormal=ab, advice=adv)})
    messages += history

    def event_stream():
        buffer = []
        try:
            yield _sse("start", {"conversation_id": conv_id})
            for chunk in chat_stream(messages):
                buffer.append(chunk)
                yield _sse("token", {"text": chunk})
            msg_id = db.add_message(conv_id, "assistant", "".join(buffer))
            db.touch_conversation(conv_id)
            yield _sse("done", {"message_id": msg_id})
        except LlmError as e:                      # C-E3/E4/E5：error 事件，已发 token 保留
            if buffer:                             # 断流也把已输出部分入库，历史不丢
                db.add_message(conv_id, "assistant", "".join(buffer))
            yield _sse("error", {"code": e.code, "message": e.message})
        except Exception:
            yield _sse("error", {"code": 5000, "message": "系统繁忙，请稍后重试"})
        finally:
            with _busy_lock:
                _busy_convs.discard(conv_id)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


# ==================== 3~5. 咨询历史 ====================

@app.get("/api/conversations")
def conversations(request: Request, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
    return ok(db.list_conversations(user_of(request)["user_id"], page, size))


@app.get("/api/conversations/{conv_id}")
def conversation_detail(conv_id: int, request: Request):
    uid = user_of(request)["user_id"]
    conv = db.get_conversation(uid, conv_id)
    if not conv:
        raise BizError(4302, "记录不存在或已被删除")
    return ok({"conversation": conv, "messages": db.get_conversation_messages(uid, conv_id)})


@app.delete("/api/conversations/{conv_id}")
def conversation_delete(conv_id: int, request: Request):
    if not db.delete_conversation(user_of(request)["user_id"], conv_id):
        raise BizError(4302, "记录不存在或已被删除")   # 越权与不存在同响应（US-605）
    return ok({"deleted": True})


# ==================== 6~10. 体检报告分析 ====================

def _safe_name(name: str) -> str:
    """文件名清洗：防路径穿越（API文档 4.1 校验 6）。"""
    name = os.path.basename((name or "").replace("\\", "/"))
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    return name[:100] or "report.pdf"


def _run_analysis(user_id: int, report_id: int, tmp_path: str):
    """后台解析任务：提取→分析→落库→删除临时文件（阅后即焚，R-BR-09）。"""
    try:
        text = extract_text(tmp_path)
        result = analyze_report(text)
        db.finish_report(report_id, result, None)
    except LlmError as e:
        db.finish_report(report_id, None, (e.code, e.message))
    except Exception:
        db.finish_report(report_id, None, (5000, "系统繁忙，请稍后重试"))
    finally:
        try:
            os.remove(tmp_path)                    # 无论成败，原始文件立即删除
        except OSError:
            pass


@app.post("/api/report/upload")
async def report_upload(request: Request, file: UploadFile | None = None,
                        background: BackgroundTasks = None):
    user = user_of(request)
    uid = user["user_id"]
    if file is None:                                                # 校验 1：4104
        return err(4104, "请先选择要上传的文件")
    data = await file.read()
    name = _safe_name(file.filename)
    is_pdf = name.lower().endswith(".pdf") and (file.content_type in (
        "application/pdf", "application/octet-stream", "", None))  # 校验 2：双重判断
    if not is_pdf:
        return err(4101, "仅支持 PDF 格式")
    if len(data) == 0:                                              # 校验 3：空文件
        return err(4103, "文件无效，请重新选择")
    if len(data) > config.MAX_FILE_BYTES:                           # 校验 4：≤10MB
        return err(4102, "文件大小不能超过 10MB")
    if db.has_processing(uid):                                      # 校验 5：禁并发
        return err(4204, "报告解析中，请勿重复提交")

    report_id = db.insert_report(uid, name, len(data))
    tmp_path = str(config.TMP_DIR / f"{uuid.uuid4().hex}.pdf")
    with open(tmp_path, "wb") as f:
        f.write(data)
    background.add_task(_run_analysis, uid, report_id, tmp_path)
    return ok({"report_id": report_id, "status": "processing"})


@app.get("/api/report/{report_id}")
def report_result(report_id: int, request: Request):
    r = db.get_report(user_of(request)["user_id"], report_id)
    if not r:
        raise BizError(4302, "记录不存在或已被删除")
    if r["status"] == "processing":
        return ok({"status": "processing"})
    if r["status"] == "failed":
        code, _, msg = (r["error_message"] or "4201|报告解析失败，请重试").partition("|")
        return ok({"status": "failed", "error_code": int(code), "message": msg})
    return ok({"status": "success", "file_name": r["file_name"], "file_size": r["file_size"],
               "created_at": r["created_at"], "has_critical": bool(r["has_critical"]),
               "result": {"basic_info": r["basic_info"], "abnormal_items": r["abnormal_items"],
                          "overall_advice": r["overall_advice"], "precautions": r["precautions"]}})


@app.get("/api/reports")
def reports_list(request: Request, page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=100)):
    return ok(db.list_reports(user_of(request)["user_id"], page, size))


def _report_to_text(r: dict) -> str:
    items = "、".join(f"{i['name']} {i['value']}（参考 {i['ref']}）{i['label']}"
                      for i in r["abnormal_items"]) or "无"
    return (f"姓名：{r['basic_info']['name']}    性别：{r['basic_info']['gender']}    "
            f"年龄：{r['basic_info']['age']}\n"
            f"体检日期：{r['basic_info']['report_date']}    体检机构：{r['basic_info']['org']}\n\n"
            f"异常指标：\n{items}\n\n"
            f"总体健康建议：{r['overall_advice']}\n\n"
            f"注意事项：{r['precautions']}\n")


@app.get("/api/report/{report_id}/download")
def report_download(report_id: int, request: Request):
    r = db.get_report(user_of(request)["user_id"], report_id)
    if not r or r["status"] != "success":
        raise BizError(4302, "记录不存在或已被删除")
    content = ("———— 智能问诊系统 · 体检报告分析结果 ————\n"
               "仅供参考，不构成医疗诊断，请以专业医生面诊结果为准。\n\n"
               + _report_to_text(r))
    filename = f"体检报告分析结果_{report_id}.txt"
    quoted = f"attachment; filename=report_{report_id}.txt; filename*=UTF-8''{quote(filename)}"
    return Response(content="﻿" + content, media_type="text/plain; charset=utf-8",
                    headers={"Content-Disposition": quoted})


@app.delete("/api/report/{report_id}")
def report_delete(report_id: int, request: Request):
    if not db.delete_report(user_of(request)["user_id"], report_id):
        raise BizError(4302, "记录不存在或已被删除")
    return ok({"deleted": True})


# ==================== 启动事件 ====================

@app.on_event("startup")
def startup():
    with db.get_conn() as c:                        # 幂等建表（库缺失/新部署时自愈）
        c.executescript(open(config.BASE_DIR / "schema.sql", encoding="utf-8").read())
    auth_service.seed_demo_admin()                  # 空库首次播种 admin/123456
    db.cleanup_zombies()                            # 清理僵尸 processing 记录
    db.cleanup_expired_tokens()                     # 清理过期凭证
    for f in config.TMP_DIR.glob("*"):              # 清空重启遗留临时文件（API文档 5.4）
        try:
            os.remove(f)
        except OSError:
            pass
