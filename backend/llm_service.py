"""DeepSeek 调用封装（业务术语表·结构化输出契约）：咨询流式 + 报告四段式 JSON。
上游异常统一映射为 API 文档错误码：4202 超时 / 4203 服务不可用 / 4201 解析失败。"""
import json

import httpx

import config
from prompts import REPORT_SYSTEM


class LlmError(Exception):
    def __init__(self, code: int, message: str):
        self.code, self.message = code, message
        super().__init__(message)


def _headers():
    return {"Authorization": f"Bearer {config.DEEPSEEK_API_KEY}", "Content-Type": "application/json"}


def _guard_key():
    if not config.DEEPSEEK_API_KEY:
        raise LlmError(4203, "服务暂时不可用，请稍后重试")  # 未配置 Key 视同服务不可用


def chat_stream(messages: list[dict]):
    """流式聊天：逐段 yield 文本增量。C-E4：中断时由调用方保留已发出部分。"""
    _guard_key()
    payload = {"model": config.DEEPSEEK_MODEL, "messages": messages,
               "stream": True, "temperature": 0.7}
    try:
        with httpx.Client(base_url=config.DEEPSEEK_BASE_URL, headers=_headers(),
                          timeout=config.LLM_TIMEOUT) as client:
            with client.stream("POST", "/chat/completions", json=payload) as resp:
                if resp.status_code != 200:
                    raise LlmError(4203, "服务暂时不可用，请稍后重试")
                for line in resp.iter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content") or ""
                    except (KeyError, IndexError, json.JSONDecodeError):
                        continue
                    if delta:
                        yield delta
    except httpx.TimeoutException:
        raise LlmError(4202, "服务响应超时，请稍后重试")
    except LlmError:
        raise
    except httpx.HTTPError:
        raise LlmError(4203, "服务暂时不可用，请稍后重试")


def analyze_report(report_text: str) -> dict:
    """非流式：返回校验后的四段式结果；不符合契约按 4201 失败（R-BR-05/06）。"""
    _guard_key()
    payload = {"model": config.DEEPSEEK_MODEL,
               "messages": [{"role": "system", "content": REPORT_SYSTEM},
                            {"role": "user", "content": f"体检报告文本如下：\n{report_text}"}],
               "response_format": {"type": "json_object"}, "temperature": 0.2}
    try:
        with httpx.Client(base_url=config.DEEPSEEK_BASE_URL, headers=_headers(),
                          timeout=config.LLM_TIMEOUT) as client:
            resp = client.post("/chat/completions", json=payload)
            if resp.status_code != 200:
                raise LlmError(4203, "服务暂时不可用，请稍后重试")
            content = resp.json()["choices"][0]["message"]["content"]
    except httpx.TimeoutException:
        raise LlmError(4202, "服务响应超时，请稍后重试")
    except LlmError:
        raise
    except httpx.HTTPError:
        raise LlmError(4203, "服务暂时不可用，请稍后重试")

    try:
        raw = json.loads(content)
    except json.JSONDecodeError:
        raise LlmError(4201, "报告解析失败，请重试")
    return normalize_report(raw)


def normalize_report(raw: dict) -> dict:
    """四段式契约校验 + label 派生 + 姓名脱敏兜底（双保险）。"""
    fail = LlmError(4201, "报告解析失败，请重试")
    try:
        bi = raw["basic_info"]
        items = raw["abnormal_items"]
        advice, prec = raw["overall_advice"], raw["precautions"]
        assert isinstance(items, list) and advice.strip() and prec.strip()
    except (KeyError, TypeError, AssertionError, AttributeError):
        raise fail

    bi = {k: str(bi.get(k, "")) for k in ("name", "gender", "age", "report_date", "org")}
    bi["name"] = mask_name(bi["name"])

    norm_items = []
    for it in items:
        try:
            if it["status"] not in ("high", "low"):
                raise fail
            norm_items.append({
                "name": str(it["name"]), "value": str(it["value"]), "ref": str(it["ref"]),
                "status": it["status"],
                "label": "⚠️ 偏高" if it["status"] == "high" else "⚠️ 偏低",
                "advice": str(it["advice"]),
                "critical": bool(it.get("critical", False)),
            })
        except (KeyError, TypeError):
            raise fail
    return {"basic_info": bi, "abnormal_items": norm_items,
            "overall_advice": str(advice), "precautions": str(prec)}


def mask_name(name: str) -> str:
    """脱敏（业务术语表）：保留姓氏，其余以 * 代替。"""
    if not name or len(name) < 2:
        return name
    return name[0] + "*" * (len(name) - 1)


def report_brief(report: dict) -> str:
    """报告追问上下文注入（FOLLOWUP_CONTEXT 填充）。"""
    bi = report["basic_info"]
    return json.dumps(bi, ensure_ascii=False), \
        "；".join(f"{i['name']} {i['value']}（参考 {i['ref']}）{i['label']}" for i in report["abnormal_items"]) or "无", \
        report["overall_advice"]
