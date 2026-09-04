"""测试隔离样板 (v4.1.8.1 审计修复 H10).

所有 test_*.py 在 ``from app.*`` import 之前 ``import test_isolate``,
把配置/断点/文风目录重定向到一次性临时目录, 杜绝:

1. save_config 覆盖用户真实 ~/.proofreader/last_config.json
2. save_checkpoint 往真实 checkpoints 写孤儿断点
3. start_proofread / deai 测试用真实 api_key 外呼

用法 (放在文件最顶部, app import 之前):
    import test_isolate  # noqa: F401  测试隔离, 防止污染真实 ~/.proofreader

实现: 设置环境变量 PROOFREADER_HOME -> app/utils.py CONFIG_DIR 与
app/style_profiles/loader.py STYLES_DIR 的根目录在 import 时读取该变量.
因此本模块必须在任何 ``import app.*`` 之前被 import.
"""
import os
import sys
import tempfile
from pathlib import Path

# 顶层 import 前就已 import os/sys/tempfile 的文件仍可用本模块, 无副作用.

_home = os.environ.get("PROOFREADER_HOME")
if not _home:
    _home = tempfile.mkdtemp(prefix="pr_test_home_")
    os.environ["PROOFREADER_HOME"] = _home
    # 预创建, 避免首次 mkdir 的竞态噪音 (无实际影响)
    Path(_home).mkdir(parents=True, exist_ok=True)
