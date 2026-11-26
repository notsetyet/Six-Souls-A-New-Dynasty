#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
  game_python=.venv/bin/python
elif [ -x ../../work/byok-runtime/bin/python ]; then
  game_python=../../work/byok-runtime/bin/python
elif [ -x ../../work/.venv/bin/python ]; then
  game_python=../../work/.venv/bin/python
elif command -v python3.11 >/dev/null 2>&1; then
  echo '首次运行，正在创建本项目的 Python 环境…'
  python3.11 -m venv .venv
  game_python=.venv/bin/python
else
  if ! python3 -c 'import sys; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
    echo '需要 Python 3.11 或更新版本。安装后再双击本文件。'
    read -r -p '按回车关闭。'
    exit 1
  fi
  echo '首次运行，正在创建本项目的 Python 环境…'
  python3 -m venv .venv
  game_python=.venv/bin/python
fi
if ! "$game_python" -c 'import fastapi,uvicorn,cryptography' >/dev/null 2>&1; then
  echo '正在安装场景版依赖（首次运行需要联网）…'
  if ! "$game_python" -m pip install -r requirements-scene.txt; then
    echo '依赖未安装完成，请检查网络后再次运行；当前游戏文件未改变。'
    read -r -p '按回车关闭。'
    exit 1
  fi
fi
if [ -z "${BYOK_COOKIE_SECRET:-}" ]; then
  "$game_python" tools/setup_cookie_secret.py >/dev/null
  BYOK_COOKIE_SECRET="$(cat .local/byok-cookie-secret)"
  export BYOK_COOKIE_SECRET
fi
export SCENE_PORT="${SCENE_PORT:-7864}"
echo "v3 剧情版：http://127.0.0.1:$SCENE_PORT/"
echo '顶部可输入自己的 API Key；勾选记住后，下一局无需重新输入。'
echo '请在浏览器打开上面的地址。终端保持开启，关闭后本局存档会清空。'
exec "$game_python" scene_app.py
