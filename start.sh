#!/bin/sh
# Claude 用量助手 — macOS / Linux 启动脚本
# 用法:  ./start.sh    (或双击;首次需 chmod +x start.sh)
# 等价于 Windows 上的 启动卡片.bat
cd "$(dirname "$0")" || exit 1

# 优先用 python3,没有则退回 python
if command -v python3 >/dev/null 2>&1; then
    exec python3 quota_card.py "$@"
else
    exec python quota_card.py "$@"
fi
