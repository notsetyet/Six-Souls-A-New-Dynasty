"""Create one local deployment secret without printing its value.

This is the app's cookie-encryption key, never a player's model API key.
The resulting .local directory must stay out of source and deployment archives.
"""
from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path
import secrets

DEFAULT_PATH = Path(__file__).resolve().parents[1] / ".local" / "byok-cookie-secret"


def load_or_create_secret(path: Path = DEFAULT_PATH) -> str:
    path = Path(path)
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError("加密主密钥路径不能是符号链接。")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            value = path.read_text(encoding="ascii").strip()
            if len(value) != 44 or len(base64.b64decode(value, altchars=b"-_", validate=True)) != 32:
                raise ValueError
        except (ValueError, UnicodeError):
            raise ValueError("已有加密主密钥格式无效；请检查文件，不会自动覆盖。") from None
        path.chmod(0o600)
        return value
    with os.fdopen(fd, "w", encoding="ascii") as target:
        target.write(value + "\n")
    return value


def main():
    parser = argparse.ArgumentParser(description="建立或复用本机加密主密钥；不会显示密钥。")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()
    load_or_create_secret(args.path)
    print("本机加密主密钥已就绪：" + str(args.path.resolve()))


if __name__ == "__main__":
    main()
