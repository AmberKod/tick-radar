"""首次生成本地凭据，不打印密钥，也不覆盖已有配置。"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    target = ROOT / ".env"
    if target.exists():
        raise SystemExit(".env 已存在，保留现有配置。")
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    replacements = {
        "TR_MYSQL_PASSWORD=replace-with-local-password": "TR_MYSQL_PASSWORD="
        + secrets.token_urlsafe(32),
        "TR_MYSQL_ROOT_PASSWORD=replace-with-local-root-password": "TR_MYSQL_ROOT_PASSWORD="
        + secrets.token_urlsafe(32),
        "TR_API_TOKEN=\n": "TR_API_TOKEN=" + secrets.token_urlsafe(48) + "\n",
    }
    for before, after in replacements.items():
        if template.count(before) != 1:
            raise SystemExit("配置模板结构已变化，请检查示例字段。")
        template = template.replace(before, after)
    # 排他创建避免覆盖用户已配置的凭据。
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(template)
    print("已生成本地 .env，凭据未输出；请勿提交该文件。")


if __name__ == "__main__":
    main()
