-- 智能问诊系统 SQLite 建库脚本 V2.0（依据 开发文档/数据库设计.md V2.0）
-- 建表顺序：user → auth_token → report_analysis → conversation → message
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS user (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,                            -- 3-20位字母数字下划线，应用层校验(4403)
  email         TEXT NOT NULL UNIQUE,                            -- 格式应用层校验(4404)，唯一兜底(4402)
  password_hash TEXT NOT NULL,                                   -- pbkdf2_sha256$迭代$盐$哈希，严禁明文
  created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS auth_token (
  token      TEXT PRIMARY KEY,                                   -- secrets.token_hex(32)
  user_id    INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  expires_at TEXT NOT NULL                                       -- 颁发+7天，过期4411
);
CREATE INDEX IF NOT EXISTS idx_token_user ON auth_token(user_id);

CREATE TABLE IF NOT EXISTS report_analysis (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id        INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  file_name      TEXT NOT NULL,
  file_size      INTEGER NOT NULL,
  status         TEXT NOT NULL DEFAULT 'processing'
                 CHECK (status IN ('processing','success','failed')),
  basic_info     TEXT,                                           -- JSON 四段式①（name已脱敏）
  abnormal_items TEXT,                                           -- JSON 四段式②
  overall_advice TEXT,                                           -- 四段式③
  precautions    TEXT,                                           -- 四段式④
  has_critical   INTEGER NOT NULL DEFAULT 0 CHECK (has_critical IN (0,1)),
  error_message  TEXT,                                           -- 格式：错误码|用户文案
  created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_rep_user_created ON report_analysis(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS conversation (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id             INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
  title               TEXT NOT NULL DEFAULT '新会话',
  scene               TEXT NOT NULL DEFAULT 'chat' CHECK (scene IN ('chat','report_followup')),
  related_analysis_id INTEGER REFERENCES report_analysis(id),
  created_at          TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at          TEXT NOT NULL DEFAULT (datetime('now','localtime'))  -- 应用层维护
);
CREATE INDEX IF NOT EXISTS idx_conv_user_updated ON conversation(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS message (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL REFERENCES conversation(id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content         TEXT NOT NULL,                                 -- Markdown 原文
  created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_msg_conv ON message(conversation_id, id);
