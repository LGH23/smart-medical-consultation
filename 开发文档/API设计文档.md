# 智能问诊系统 — API 接口设计文档

| 文档版本 | **V2.0** |
|----------|------|
| 编写日期 | 2026-10-18（V1.1/V2.0 同日连续修订） |
| 基础路径 | `/api` |
| 关联文档 | 《../需求文档/PRD.md》《数据库设计.md》《../需求文档/用户注册功能需求.md》《../需求文档/用户登录功能需求.md》《../需求文档/历史记录查看功能需求.md》 |
| 修订记录 | V1.0 十个接口、浏览器标识归属；V1.1 新增认证 4 接口（共 14 个）；**V2.0（2026-10-18）与《数据库设计.md》V2.0 对齐：彻底移除 X-Client-Id（4301 退役），全部业务接口统一 `X-Token` 鉴权，凭证对应 auth_token 表** |

---

## 1. 通用约定

### 1.1 请求约定

| 项 | 约定 |
|----|------|
| 协议 | HTTP/1.1，本地部署 http |
| 数据格式 | 普通请求 `application/json`；文件上传 `multipart/form-data` |
| 身份标识 | **V1.1**：除注册/登录/健康检查外，所有请求携带请求头 **`X-Token`**（登录成功后服务端颁发的不透明令牌，服务端映射到 user_id）。令牌缺失/失效返回 `4411`；数据查询/删除强制按 user_id 隔离（防越权）。注册与登录接口无需凭证 |
| 超时 | 普通接口 30s；AI 流式接口整体上限 120s（PRD 性能要求） |
| 字符编码 | UTF-8 |

### 1.2 统一响应格式

```json
{
  "code": 0,
  "message": "ok",
  "data": { }
}
```

- `code = 0` 表示成功；非 0 为业务错误码（见 1.3）。
- `message` 为**可直接展示给用户的中文友好文案**（PRD 6.2：不暴露技术堆栈）。
- HTTP 状态码：成功 200；业务错误也返回 200（code 区分）；仅系统级故障返回 500。

### 1.3 错误码表（与 PRD 异常场景一一对应）

| code | HTTP | 场景 | message（用户文案） | PRD 来源 |
|------|------|------|---------------------|----------|
| 0 | 200 | 成功 | ok | — |
| 4001 | 200 | 空/纯空格输入 | 请先输入您的健康问题 | C-E1 |
| 4002 | 200 | 输入超 2000 字符 | 输入内容超过 2000 字符，请精简后发送 | C-E2 |
| 4101 | 200 | 非 PDF 文件 | 仅支持 PDF 格式 | R-E1 |
| 4102 | 200 | 文件 >10MB | 文件大小不能超过 10MB | R-E2 |
| 4103 | 200 | 0 字节空文件 | 文件无效，请重新选择 | R-E3 |
| 4104 | 200 | 未选择文件提交 | 请先选择要上传的文件 | US-504 |
| 4105 | 200 | PDF 损坏/加密无法打开 | 文件无法读取，可能已损坏或加密，请检查后重新上传 | US-502 |
| 4106 | 200 | 报告无文本层/无法识别 | 报告内容无法识别，请上传清晰 PDF | R-E5 |
| 4201 | 200 | AI 解析失败（接口异常） | 报告解析失败，请重试 | R-E4 |
| 4202 | 200 | AI 响应超时 | 服务响应超时，请稍后重试 | C-E5 / 120s 上限 |
| 4203 | 200 | DeepSeek 服务不可用/限流 | 服务暂时不可用，请稍后重试 | C-E3 / R-E4 |
| 4204 | 200 | 解析中重复提交 | 报告解析中，请勿重复提交 | R-E7 / C-E8 |
| ~~4301~~ | — | **V2.0 已退役**（原 client_id 非法场景），统一由 4411 承载 | 登录已过期，请重新登录 | 安全约定 |
| 4302 | 200 | 记录不存在或已删除（含越权访问他人记录，统一按不存在处理防探测） | 记录不存在或已被删除 | FR-14/US-605 |
| 4401 | 200 | 注册用户名已存在 | 用户名已存在 | FR-15 |
| 4402 | 200 | 注册邮箱已被注册 | 邮箱已被注册 | FR-15 |
| 4403 | 200 | 用户名格式非法（3-20 位字母/数字/下划线） | 用户名需为 3-20 位字母、数字或下划线 | FR-15 |
| 4404 | 200 | 邮箱格式非法 | 邮箱格式不正确，请重新输入 | FR-15 |
| 4405 | 200 | 密码长度不合规（6-20） | 密码需为 6-20 个字符 | FR-15 |
| 4406 | 200 | 两次密码不一致（后端兜底；前端应拦截不提交） | 密码不一致，请重新输入 | FR-15 |
| 4410 | 200 | 登录失败（账号不存在或密码错误，统一文案防枚举） | 用户名或密码错误 | FR-16 |
| 4411 | 200 | 未登录 / Token 缺失或失效 | 登录已过期，请重新登录 | FR-16/FR-18 |
| 5000 | 500 | 系统未知异常 | 系统繁忙，请稍后重试 | 兜底 |

### 1.4 接口总清单（14 个 = 原 10 + V1.1 认证 4）

| # | 方法与路径 | 名称 | 类型 | 对应需求 |
|---|-----------|------|------|----------|
| A1 | POST `/api/register` | 用户注册 | JSON | FR-15 |
| A2 | POST `/api/login` | 用户登录（成功颁发 Token） | JSON | FR-16 |
| A3 | POST `/api/logout` | 退出登录（作废 Token） | JSON | FR-17 |
| A4 | GET `/api/me` | 当前登录用户信息 | JSON | FR-16（页面显示用户名用） |
| 1 | GET `/api/health` | 健康检查 | JSON | 阶段 5/6 部署自检 |
| 2 | POST `/api/chat` | 发送咨询消息 | **SSE 流式** | FR-1、FR-2、FR-12、US-303 |
| 3 | GET `/api/conversations` | 咨询历史列表 | JSON | FR-8 |
| 4 | GET `/api/conversations/{id}` | 会话消息详情 | JSON | FR-8 / US-401 |
| 5 | DELETE `/api/conversations/{id}` | 删除咨询会话 | JSON | FR-14 |
| 6 | POST `/api/report/upload` | 上传报告并发起分析 | multipart | FR-3~FR-6 |
| 7 | GET `/api/report/{id}` | 查询分析结果（轮询） | JSON | FR-7 / R-BR-04 |
| 8 | GET `/api/reports` | 分析历史列表 | JSON | FR-9 |
| 9 | GET `/api/report/{id}/download` | 下载分析报告 | 文件流 | FR-13 |
| 10 | DELETE `/api/report/{id}` | 删除分析记录 | JSON | FR-14 |

> 说明：①"重新分析"（FR-13）= 前端重置状态后再次调用接口 6，不单独设接口；②页面清空对话（C-BR-06）默认仅前端重置；若需同步删除落库会话，调用接口 5；③下载报告（接口 9）提供后端导出，前端 Blob 方案为原型降级路径。

---

## 2. 通用模块

### 2.1 GET /api/health — 健康检查

- 用途：启动自检、测试套件冒烟用例。
- 请求：无参数。
- 响应 `data`：

```json
{ "status": "ok", "version": "1.0", "time": "2026-10-18 16:00:00" }
```

### 2.2 POST /api/register — 用户注册（A1，V2.0）

- 请求体：`{ "username": "user_01", "email": "a@b.com", "password": "Abc123", "confirm_password": "Abc123" }`
- 校验顺序与错误码（前后端文案一致）：
  1. 用户名空/格式 → 4403；2. 密码长度 → 4405；3. 两次不一致 → 4406；4. 邮箱格式 → 4404；5. 用户名唯一 → 4401；6. 邮箱唯一 → 4402（唯一索引兜底并发）。
- 成功：`{"code":0,"data":{"username":"user_01"}}`；**密码经 PBKDF2 加盐哈希后入库（user.password_hash），请求响应与日志全程无明文**；前端收到成功后跳转登录页。
- 无需凭证。

### 2.3 POST /api/login — 用户登录（A2，V2.0）

- 请求体：`{ "username": "user_01", "password": "Abc123" }`；空值由前端拦截（"请输入用户名/密码"）。
- 成功：`{"code":0,"data":{"token":"<opaque>","username":"user_01"}}`——Token 为 `secrets.token_hex(32)`，**写入 auth_token 表（有效期 7 天）**，前端存储并在后续请求头携带 `X-Token`，跳转主页面。
- 失败（账号不存在或密码错误）：统一 4410"用户名或密码错误"，不区分原因（防枚举）。
- 无需凭证。

### 2.4 POST /api/logout — 退出登录（A3，V2.0）

- 需 `X-Token`；服务端删除 auth_token 对应行，前端清除本地存储并回登录页。
- 成功 `data`：`{"logged_out": true}`；已失效 Token 登出同样返回成功（幂等）。

### 2.5 GET /api/me — 当前用户信息（A4，V2.0）

- 需 `X-Token`；返回 `{"username": "user_01", "created_at": "..."}`；Token 缺失/过期返回 4411（前端跳登录页）。

> 鉴权中间约定（对应《数据库设计.md》3.2）：每请求以 `X-Token` 查 auth_token 且 `expires_at > now` → 解出 user_id 注入业务查询；过期行由后端定期清理。

---

## 3. 健康咨询模块

### 3.1 POST /api/chat — 发送咨询消息（SSE 流式）

**核心接口**。用户发送问题，后端落库用户消息 → 组装上下文（会话内最近 20 条 + System Prompt 五段式约束）→ 调用 DeepSeek 流式接口 → 以 SSE 逐 token 转发前端 → 回复完成后落库 AI 消息。

- 请求头：**`X-Token`**、`Content-Type: application/json`、`Accept: text/event-stream`（无/失效凭证 → 4411）
- 请求体：

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| content | string | 是 | 用户问题，1~2000 字符（4001/4002） |
| conversation_id | long | 否 | 会话 ID；**缺省时后端新建会话**（title 取 content 前 30 字）并返回 |
| analysis_id | long | 否 | 报告追问场景（US-303）：传入分析记录 ID，后端将该报告四段式摘要注入上下文，会话 `scene=report_followup` |

```json
{ "content": "牙疼怎么办", "conversation_id": null, "analysis_id": null }
```

- 响应：**SSE 事件流**（`Content-Type: text/event-stream`），事件定义：

| 事件 | data 内容 | 说明 |
|------|-----------|------|
| `start` | `{"conversation_id": 12}` | 首个事件，回传会话 ID（新会话场景前端需保存） |
| `token` | `{"text": "部"}` | 增量文本片段（Markdown 原文，前端行式解析渲染，保证无半截标签 C-BR-03） |
| `done` | `{"message_id": 101}` | 正常结束 |
| `error` | `{"code": 4203, "message": "服务暂时不可用，请稍后重试"}` | 流式中断/失败；已输出部分保留（C-E4），会话不丢（C-BR-09） |

- 业务校验：`content` 空/纯空格 → 直接返回 `code 4001`（非流式）；超长 → `4002`；上一请求未完成并发提交由**前端禁用按钮**保证（C-E8），后端对同会话加轻量互斥，冲突返回 `4204`。
- 急危/无关输入（C-E7/C-E6）由 System Prompt 约束 DeepSeek 输出，不设独立错误码。

### 3.2 GET /api/conversations — 咨询历史列表（FR-8）

| 参数 | 位置 | 说明 |
|------|------|------|
| X-Token | header | 必填（需登录，FR-18） |
| page / size | query | 默认 1 / 20 |

响应 `data.list[]`：

```json
{
  "id": 12,
  "title": "牙疼怎么办",
  "scene": "chat",
  "message_count": 8,
  "updated_at": "2026-10-18 15:30:00"
}
```
> 排序：`updated_at DESC`（命中索引 idx_client_updated）。

### 3.3 GET /api/conversations/{id} — 会话消息详情（US-401 回看）

响应 `data`：

```json
{
  "conversation": { "id": 12, "title": "牙疼怎么办", "scene": "chat", "related_analysis_id": null },
  "messages": [
    { "id": 100, "role": "user",      "content": "牙疼怎么办", "created_at": "..." },
    { "id": 101, "role": "assistant", "content": "### ① 症状分析\n- ...", "created_at": "..." }
  ]
}
```
> `content` 为 Markdown 原文，前端渲染。不属于该 client 或已删除 → `4302`。

### 3.4 DELETE /api/conversations/{id} — 删除会话（FR-14）

- 物理删除，`message` 外键级联删除；前端二次确认后才调用。
- 响应 `data`：`{ "deleted": true }`

---

## 4. 体检报告分析模块

### 4.1 POST /api/report/upload — 上传并发起分析（异步受理，FR-3~FR-6）

**流程**：三重校验 → 存临时目录 → 立即返回受理 ID → 后台异步执行（文本提取 → 有效性检查 → DeepSeek 结构化分析 → 写库 → **删除临时文件（阅后即焚，R-BR-09）**）→ 前端轮询接口 7。选择异步是为了不占用长连接、支持超时终止与"不残留半成品"（R-E6）。

- 请求头：**`X-Token`**；`Content-Type: multipart/form-data`（无/失效凭证 → 4411）
- 表单字段：`file`（必填，单个文件）
- 服务端校验链（前端已做同类即时校验，后端兜底，文案一致）：

| 顺序 | 校验 | 失败 code |
|------|------|-----------|
| 1 | file 缺失 | 4104 |
| 2 | 扩展名 + MIME 双判 PDF | 4101 |
| 3 | 大小 == 0 | 4103 |
| 4 | 大小 > 10485760 | 4102 |
| 5 | 同客户端存在 processing 中记录 | 4204 |
| 6 | 文件名清洗（去路径分隔符/特殊字符，防路径穿越） | — |

- 成功响应：

```json
{ "code": 0, "message": "ok", "data": { "report_id": 33, "status": "processing" } }
```
> 此刻 `report_analysis` 已插入 `status=processing` 记录（file_name/file_size 落库）。

### 4.2 GET /api/report/{id} — 查询分析结果（轮询，FR-7）

前端每 2s 轮询，直至状态终态（成功/失败），总时限 120s（超时前端主动停轮询并提示重试）。

响应 `data` 三种形态：

**① 解析中**
```json
{ "status": "processing" }
```

**② 成功（四段式，R-BR-05/06）**
```json
{
  "status": "success",
  "file_name": "2026年度体检报告.pdf",
  "file_size": 345876,
  "created_at": "2026-10-18 15:40:00",
  "has_critical": false,
  "result": {
    "basic_info": { "name": "张*", "gender": "男", "age": "42岁",
                    "report_date": "2026-09-15", "org": "示例人民医院体检中心" },
    "abnormal_items": [
      { "name": "血压（收缩压）", "value": "145 mmHg", "ref": "90–140 mmHg",
        "status": "high", "label": "⚠️ 偏高",
        "advice": "低盐饮食，规律有氧运动…", "critical": false }
    ],
    "overall_advice": "本次体检整体提示存在代谢相关异常倾向……",
    "precautions": "血压多次≥140/90或血糖复查仍偏高时请及时就医……\n本分析仅供参考，不替代专业医疗建议。"
  }
}
```
> `abnormal_items[]` 字段与《数据库设计.md》4.2 JSON Schema 完全一致，即 DeepSeek 结构化输出的校验契约；后端校验四段式任一缺失 → 按 4201 失败处理（R-BR-05）。

**③ 失败**
```json
{ "status": "failed", "error_code": 4106, "message": "报告内容无法识别，请上传清晰 PDF" }
```
> 失败记录**不出现在历史列表**（US-304 AC2），仅供本次轮询取错误文案；后端定期清理 processing 超时僵尸记录。

### 4.3 GET /api/reports — 分析历史列表（FR-9）

| 参数 | 位置 | 说明 |
|------|------|------|
| X-Token | header | 必填（需登录，FR-18） |
| page / size | query | 默认 1 / 20 |

- 仅返回 `status=success` 记录，`created_at DESC`。

```json
{
  "total": 3,
  "list": [
    { "id": 33, "file_name": "2026年度体检报告.pdf", "abnormal_count": 3,
      "has_critical": false, "summary": "存在代谢相关异常倾向…", "created_at": "2026-10-18 15:40:00" }
  ]
}
```
> `summary` 取总体健康建议首句，`abnormal_count` 由 JSON 数组长度计算，列表页急危项展示 ⚠️ 标记。

### 4.4 GET /api/report/{id}/download — 下载分析报告（FR-13）

- 响应：`Content-Type: text/plain; charset=utf-8` + `Content-Disposition: attachment; filename="体检报告分析结果.txt"`（UTF-8 文件名，带 BOM 防乱码）。
- 正文为四段式纯文本版 + 免责声明（与原型下载文件内容一致）。
- 失败（网络/记录不存在）：普通 JSON 错误（4302/5000），前端提示"下载失败，请重试"允许重试（R-E8）。

### 4.5 DELETE /api/report/{id} — 删除分析记录（FR-14）

- 物理删除该条分析结果；若存在关联 `scene=report_followup` 会话，仅解除引用不删会话（会话可独立删除，见 3.4）。
- 响应 `data`：`{ "deleted": true }`

---

## 5. 后端内部约定（非对外接口，开发必读）

1. **DeepSeek 调用封装**：`llm_service` 独立模块，暴露 `chat_stream(messages)` 与 `analyze_report(text)`；API Key/BaseUrl 读环境变量（`DEEPSEEK_API_KEY` 等），严禁入库/入前端（PRD 安全）。
2. **提示词**：咨询 System Prompt（五段式 FR-12 + C-BR-04/05/07 约束）与报告分析 Prompt（强制按 4.2 ② Schema 返回 JSON）在《提示词设计.md》（开发文档，下一份交付）中定义。
3. **流式协议映射**：后端将 DeepSeek SSE 转译为本文 3.1 事件格式；上游断开时发 `error` 事件且已发 token 不回滚（C-E4 保留已返回部分）。
4. **临时文件生命周期**：上传→解析→（成功/失败）→ 立即删除；服务器重启遗留临时目录启动时清空。
5. **上下文截断**：组装消息取 `WHERE conversation_id=? ORDER BY id DESC LIMIT 20` 反转后携带（《数据库设计.md》第 5 章）。

---

## 6. 需求 → 接口覆盖核对表（防遗漏）

| 需求条目 | 覆盖接口 |
|----------|----------|
| FR-1 对话问答（流式/Markdown/防重复/空输入/超长/急危） | 3.1（含 4001/4002/4204/4203、SSE error 事件） |
| FR-2 会话管理（欢迎/清空/上下文） | 3.1（新建会话回传 id）+ 3.4 |
| FR-3/FR-4 上传与三重校验（前后端兜底、文案一致） | 4.1（4101/4102/4103/4104 + 文件名清洗） |
| FR-5 文本提取（扫描件/损坏识别） | 4.1→4.2（4105/4106/4201） |
| FR-6 AI 结构化分析 | 4.1 + 4.2（R-BR-05/06 校验契约） |
| FR-7 四段式结果展示 | 4.2 ② |
| FR-8 咨询历史列表/回看 | 3.2 + 3.3 |
| FR-9 分析历史列表/回看 | 4.3 + 4.2 |
| FR-10 合规免责 | 3.1 System Prompt（温馨提示）+ 4.2/4.4 文案内置 |
| FR-11 异常错误提示全场景 | 1.3 错误码表逐条对应 |
| FR-12 五段式回答 | 3.1（Prompt 约束，见第 5 章） |
| FR-13 下载/重新分析 | 4.4；重新分析=再调 4.1 |
| FR-14 删除历史（二次确认） | 3.4 + 4.5 |
| US-303 报告追问 | 3.1 `analysis_id` 参数 |
| US-501~504 容错 | 1.3 + SSE error + 轮询超时约定 |
| R-BR-04/E7 解析中禁并发 | 4.1 校验 5（4204） |
| R-BR-09 隐私不落盘 | 第 5 章临时文件生命周期 |
| 阶段 5/6 冒烟自检 | 2.1 |
| FR-15 注册（校验+双唯一+跳登录） | A1（4401~4406） |
| FR-16 登录（颁发凭证/统一失败文案） | A2（4410）+ A4 |
| FR-17 退出登录 | A3 |
| FR-18 登录态历史（双 Tab/倒序/仅本人） | 3.2~3.4、4.3 全部要求 X-Token（4411） |
| US-605 删除归属保护 | 3.4/4.5 按 user_id 过滤，越权统一 4302 |

> PRD 全部 18 项 FR（V1.1 含认证 4 项）、两模块 19 条 BR、18 条异常场景均已映射，无未覆盖项。
>
> **实现状态说明（2026-10-18 更新）**：**全部 14 个接口已实现并联调通过**（`backend/main.py` + `auth_service.py`，数据库 V2.0 `backend/ai_clinic.db`）。X-Client-Id 旧口径已废弃，全接口统一 X-Token 鉴权、user_id 归属；演示账号 admin/123456 由后端首次启动自动播种。

## 7. 测试要点提示（供 test/ 阶段展开）

- 4101/4102/4103 校验链顺序与文案逐字断言；**10MB 恰界值放行**、10MB+1 拒绝。
- SSE：`start/token/done` 事件序列完整性；上游中断出 `error` 且已有 token 保留。
- 轮询状态机：processing→success / processing→failed；失败记录不进 4.3 列表。
- 越权：A 的 Token 访问/删除 B 的记录必须 4302（不泄露存在性）。
- 认证链（V2.0 设计稿实现后测）：注册校验链顺序与文案（4403→4405→4406→4404→4401→4402）；密码库内为 PBKDF2 哈希非明文；登录成功 Token 可用、登出后同 Token 复返 4411；服务重启后 Token 仍有效（auth_token 表持久化）；错误登录统一 4410。
- 并发：processing 中二次上传 → 4204。
