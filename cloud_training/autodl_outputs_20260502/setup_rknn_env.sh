#!/usr/bin/env bash
set -euo pipefail
export PYTHONIOENCODING=utf-8
export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export TMPDIR=/root/autodl-tmp/tmp
export PIP_CACHE_DIR=/root/autodl-tmp/pip_cache
mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"
/root/miniconda3/bin/python -m venv /root/autodl-tmp/rknn_env
/root/autodl-tmp/rknn_env/bin/python -m pip install --upgrade pip wheel -i https://pypi.tuna.tsinghua.edu.cn/simple
/root/autodl-tmp/rknn_env/bin/python -m pip install "setuptools==69.5.1" -i https://pypi.tuna.tsinghua.edu.cn/simple
/root/autodl-tmp/rknn_env/bin/python -m pip install "rknn-toolkit2==2.3.2" -i https://pypi.tuna.tsinghua.edu.cn/simple
/root/autodl-tmp/rknn_env/bin/python - <<'PY'
from rknn.api import RKNN
print('RKNN Toolkit2 import ok')
PY
