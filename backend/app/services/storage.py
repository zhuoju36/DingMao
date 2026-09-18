"""本地文件存储服务（P0-7-A）。

P0-7-A：MVP 只用本地存储（V2 加 COS）。

设计：
- 存储路径：backend/storage/projects/{project_id}/{doc_id}{ext}
- 文件名带 doc_id 避免冲突
- 不入库文件内容，只入库路径
"""
from __future__ import annotations

import shutil
from pathlib import Path

from app.core.config import settings

# P0-7-A hardcode：MVP 文件大小限制 50MB（参考 upload-flow.md §七）
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


def get_storage_root() -> Path:
    """存储根目录。"""
    return Path(settings.storage_root)


def _safe_extension(file_name: str) -> str:
    """提取安全的扩展名（避免路径注入：只保留字母数字 + .）。

    例: "合同.pdf" → ".pdf"，"evil.exe" → ".exe"
    """
    if "." not in file_name:
        return ""
    ext = "." + file_name.rsplit(".", 1)[-1].lower()
    # 只保留字母数字，长度 ≤ 8
    safe = "".join(c for c in ext if c.isalnum() or c == ".")
    return safe[:8] if safe else ""


def save_file(
    *,
    project_id: int,
    document_id: int,
    file_name: str,
    source_path: Path,
) -> tuple[str, int]:
    """把已上传的临时文件移到项目目录下。

    Returns:
        (storage_path, file_size) — 写入 DB 用

    Raises:
        FileNotFoundError: 临时文件不存在
        ValueError: 文件超过 MAX_FILE_SIZE_BYTES
    """
    if not source_path.exists():
        raise FileNotFoundError(f"临时文件不存在: {source_path}")

    file_size = source_path.stat().st_size
    if file_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"文件超过 {MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB 限制"
        )

    # 目标路径：backend/storage/projects/{project_id}/{document_id}{ext}
    project_dir = get_storage_root() / "projects" / str(project_id)
    project_dir.mkdir(parents=True, exist_ok=True)

    ext = _safe_extension(file_name)
    target = project_dir / f"{document_id}{ext}"

    # 移动（不是复制，避免大文件 IO 双倍）
    shutil.move(str(source_path), str(target))

    # 存相对路径（DB 友好，便于跨机器迁移）
    rel_path = target.relative_to(get_storage_root())
    return str(rel_path), file_size


def file_exists(storage_path: str) -> bool:
    """检查存储文件是否存在。"""
    return (get_storage_root() / storage_path).exists()


def delete_file(storage_path: str) -> bool:
    """删除存储文件（软删除，DB 记录由 caller 处理）。

    Returns: 是否真的删了文件
    """
    target = get_storage_root() / storage_path
    if target.exists():
        target.unlink()
        return True
    return False
