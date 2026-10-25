"""全局配置：路径、限制值、DeepSeek 环境变量读取（PRD 安全约定：API Key 仅存后端）。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

# 可选加载 backend/.env（不引入第三方 dotenv）
_env_file = BASE_DIR / ".env"
if _env_file.exists():
    for line in _env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

DB_PATH = str(BASE_DIR / "ai_clinic.db")
TMP_DIR = BASE_DIR / "uploads_tmp"          # 阅后即焚临时目录
TMP_DIR.mkdir(exist_ok=True)

MAX_INPUT_LEN = 2000                         # C-BR-02
MAX_FILE_BYTES = 10 * 1024 * 1024            # R-BR-02：10485760，边界内允许
MIN_PDF_TEXT = 50                            # R-E5：提取文本 <50 字判定无法识别
CONTEXT_MSG_LIMIT = 20                       # 上下文截断：最近 20 条（API文档 5.4）
LLM_TIMEOUT = 120.0                          # PRD：AI 上限 120s
ZOMBIE_MINUTES = 10
TOKEN_TTL_DAYS = 7                           # 登录凭证有效期（API设计文档 2.3）                          # processing 超时清理（业务术语表·僵尸记录）

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

DISCLAIMER_TIP = "以上建议仅供参考，请以专业医生诊断为准，不构成医疗诊断。"
