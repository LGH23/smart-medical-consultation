"""PDF 文本提取（FR-5）。异常映射：加密/损坏 4105，无文本层/过短 4106。"""
from pypdf import PdfReader

import config
from llm_service import LlmError


def extract_text(path: str) -> str:
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            try:
                reader.decrypt("")  # 尝试空密码，失败视为加密文件
            except Exception:
                raise LlmError(4105, "文件无法读取，可能已损坏或加密，请检查后重新上传")
            if reader.is_encrypted:
                raise LlmError(4105, "文件无法读取，可能已损坏或加密，请检查后重新上传")
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except LlmError:
        raise
    except Exception:
        raise LlmError(4105, "文件无法读取，可能已损坏或加密，请检查后重新上传")

    if len(text.strip()) < config.MIN_PDF_TEXT:   # R-E5：扫描件/无文本层
        raise LlmError(4106, "报告内容无法识别，请上传清晰 PDF")
    return text[:30000]                           # 控制上下文长度
