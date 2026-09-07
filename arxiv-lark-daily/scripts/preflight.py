#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from common import SkillError, load_config, run_command, walk_values


def is_ready_text(value: object) -> bool:
    return isinstance(value, str) and value.lower() in {"ready", "valid", "verified", "ok", "success"}


def has_user_identity(item: dict) -> bool:
    for key in ("identity", "as", "type", "account_type", "profile"):
        value = item.get(key)
        if isinstance(value, str) and value.lower() == "user":
            return True
    return False


def auth_status_ready(status: dict) -> bool:
    verified_anywhere = False
    ready_anywhere = False
    user_ready = False
    for item in walk_values(status):
        if not isinstance(item, dict):
            continue
        verified = item.get("verified") is True or item.get("is_verified") is True
        ready = any(is_ready_text(item.get(key)) for key in ("status", "tokenStatus", "token_status", "state"))
        if verified:
            verified_anywhere = True
        if ready:
            ready_anywhere = True
        if has_user_identity(item) and (verified or ready):
            user_ready = True
    return user_ready or (verified_anywhere and ready_anywhere)


def check_lark_cli() -> dict:
    executable = shutil.which("lark-cli")
    if not executable:
        raise SkillError("未找到 lark-cli。请先安装并完成配置，然后重新运行。")
    status = run_command([executable, "auth", "status", "--json", "--verify"])
    if not auth_status_ready(status):
        raise SkillError("未检测到已验证且可用的 lark-cli user 身份。请先完成 user 身份登录。")
    return {"executable": executable, "verified": True, "identity": "user"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate arxiv-lark-daily runtime prerequisites")
    parser.add_argument("--config", required=True)
    parser.add_argument("--skip-auth", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    try:
        load_config(args.config)
        result = {"ok": True, "config": str(Path(args.config))}
        if not args.skip_auth:
            result["lark_cli"] = check_lark_cli()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except SkillError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
