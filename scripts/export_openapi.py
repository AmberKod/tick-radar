"""导出后端接口契约；无需启动 API 或连接数据库。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cross_market.apps.api.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.output.parent.is_dir():
        parser.error("输出目录必须已存在")
    schema = create_app().openapi()
    args.output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"OpenAPI contract: {args.output}")


if __name__ == "__main__":
    main()
