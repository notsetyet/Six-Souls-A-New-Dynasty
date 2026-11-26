"""Assemble a clean ModelScope scene-runtime archive from an explicit allowlist.

No credentials, diagnostics, tests, old playthroughs or local environments enter
this archive. Run from a complete project containing its original assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    "Dockerfile", ".dockerignore", "requirements-scene.txt", "scene_app.py",
    "docs/BYOK_MODELSCOPE.md",
    "game/__init__.py", "game/agents.py", "game/config.py", "game/council.py",
    "game/credential_vault.py", "game/dialogue.py", "game/diary.py", "game/ending.py",
    "game/engine.py", "game/events.py", "game/intrigue.py", "game/model_catalog.py",
    "game/provider.py", "game/roster.py", "game/social.py", "game/state.py",
    "game/story.py", "game/succession_pressure.py", "game/web_sessions.py",
    "game/characters.json", "game/tuning.json", "game/lines/dialogue_matrix.json",
    "scene_web/index.html", "scene_web/app.js", "scene_web/ai-settings.js",
    "scene_web/story-markdown.js", "scene_web/styles.css", "assets/manifest.json",
)
ASSET_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".avif", ".woff", ".woff2"})
FORBIDDEN_PARTS = frozenset({".local", ".git", ".env", ".venv", "venv", "node_modules",
                             "__pycache__", "validation", "tests", "history", "work"})


def _safe_file(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or any(part in FORBIDDEN_PARTS for part in rel.parts):
        raise ValueError("不允许的打包路径。")
    candidate = root
    for part in rel.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError("打包文件不能使用符号链接：" + relative)
    if not candidate.is_file():
        raise ValueError("缺少部署所需文件：" + relative)
    return candidate


def collect_files(root: Path = ROOT) -> list[tuple[str, Path]]:
    root = Path(root).resolve()
    files = [(name, _safe_file(root, name)) for name in RUNTIME_FILES]
    for asset in sorted((root / "assets").rglob("*")):
        relative = asset.relative_to(root)
        # Reject links, even if their target looks like a normal image.
        if asset.is_symlink():
            raise ValueError("素材不能使用符号链接：" + relative.as_posix())
        if not asset.is_file() or asset.suffix.lower() not in ASSET_SUFFIXES:
            continue
        if any(part.startswith(".") or part in FORBIDDEN_PARTS for part in relative.parts):
            continue
        files.append((relative.as_posix(), _safe_file(root, relative.as_posix())))
    return sorted(files)


def build_package(root: Path = ROOT, output: Path | None = None, *, force=False) -> Path:
    root = Path(root).resolve()
    output = Path(output) if output is not None else root.parent / (root.name + "-modelscope.zip")
    output = output.resolve()
    if output.exists() and not force:
        raise FileExistsError("输出文件已存在；需要替换时请显式使用 --force。")
    files = collect_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".modelscope-package-", suffix=".zip", dir=output.parent)
    os.close(fd)
    manifest = []
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, path in files:
                data = path.read_bytes()
                manifest.append({"path": name, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
                archive.writestr(name, data)
            archive.writestr("PACKAGE_CONTENTS.json", json.dumps({
                "purpose": "ModelScope scene runtime", "files": manifest,
                "contains_player_credentials": False,
            }, ensure_ascii=False, indent=2) + "\n")
            archive.writestr("README.md", "# 六魂新朝 · 魔搭场景版部署包\n\n"
                             "使用 Docker 创空间，以本目录作为仓库根目录。\n\n"
                             "应用在魔搭页面内运行，无需外链。部署前阅读 `docs/BYOK_MODELSCOPE.md`，"
                             "设置稳定的 `BYOK_COOKIE_SECRET` 和实际 `APP_PUBLIC_ORIGIN`。\n\n"
                             "包内没有玩家密钥、本机环境、测试记录或历史对局。"
                             "此包的生成不代表已通过魔搭线上或真实模型验收。\n")
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("部署包校验失败。")
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return output


def main():
    parser = argparse.ArgumentParser(description="按允许列表生成魔搭场景版 ZIP，不包含本机密钥与历史记录。")
    parser.add_argument("--output", type=Path, help="默认输出在项目上一级目录。")
    parser.add_argument("--list", action="store_true", help="仅列出将打包的文件，不创建 ZIP。")
    parser.add_argument("--force", action="store_true", help="允许替换已有输出 ZIP。")
    args = parser.parse_args()
    if args.list:
        for name, _ in collect_files():
            print(name)
        return
    output = build_package(output=args.output, force=args.force)
    print("已生成部署包：" + str(output))


if __name__ == "__main__":
    main()
