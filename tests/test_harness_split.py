"""
tests/test_harness_split.py — Harness / 重写 双轨配置 单元 + 集成测试 (v5.2c+)

按 docs/.workbuddy/plan-v5.2c-harness-split.md §5.1 + §5.2 测试分块清单.

覆盖: 12 单元 (字段默认值 / from_dict 老配置迁移 / from_dict 新配置 / to_dict 32 字段
       / compute_prompt_hash 4 字段 / 引擎 helper / _stream_single 派生 / _call_api_stream 派生
       / _harness_active 复用 / 兼容字段同步写) + 3 集成 (端到端 harness / 端到端 rewrite
       / 跨模式切换 hash 变化)

基线: 1335 (v5.1.0) → ~1409 (v5.2c 增量 14)
"""
import sys
import unittest
from pathlib import Path

# 让 tests/ 能 import app/
sys.path.insert(0, str(Path(__file__).parent.parent))

# v5.4.3 (F0-②): 测试隔离必须在任何 import app.* 之前 ——
# app/logger.py:14 / app/utils.py:595 在 import 期把 PROOFREADER_HOME 冻成模块常量,
# 漏这一行则隔离静默失效, 测试会污染用户真实 ~/.proofreader。
# run_all_tests.py 现已同时预置 env 作为第二道防线。
import test_isolate  # noqa: F401

from app.utils import (
    ProjectConfig,
    compute_prompt_hash,
    compute_prompt_hash_for_config,
    CHUNKING_PRESETS,
    CHUNKING_PRESETS_MAP,
    DEFAULT_CHUNK_PRESET,
)


# ============================================================
# ProjectConfig 字段 (v5.2c +4 字段, 27→31) — 单元 #1-#4
# ============================================================

class TestProjectConfigDefaults(unittest.TestCase):
    """单元 #1: 4 新字段默认值"""

    def test_default_values(self):
        """4 字段默认值与 plan v2 §1.1 一致"""
        cfg = ProjectConfig()
        self.assertEqual(cfg.chunking_preset_harness, "large")
        self.assertEqual(cfg.chunking_preset_rewrite, "balanced")
        self.assertEqual(cfg.harness_request_timeout, 180)
        self.assertEqual(cfg.rewrite_request_timeout, 120)

    def test_field_count_29(self):
        """ProjectConfig 字段数 27→31→32→29 (死字段清理: -output_format/-output_dir/-schema_version)"""
        cfg = ProjectConfig()
        d = cfg.to_dict()
        self.assertEqual(len(d), 29)

    def test_new_fields_in_to_dict(self):
        """4 字段都在 to_dict 里"""
        cfg = ProjectConfig()
        d = cfg.to_dict()
        for k in (
            "chunking_preset_harness",
            "chunking_preset_rewrite",
            "harness_request_timeout",
            "rewrite_request_timeout",
        ):
            self.assertIn(k, d, f"to_dict 缺 {k}")


class TestProjectConfigFromDictLegacy(unittest.TestCase):
    """单元 #2: from_dict 老配置 (无新字段) 自动迁移"""

    def test_legacy_chunking_migrates_to_rewrite(self):
        """老 chunking_preset='fast' → chunking_preset_rewrite='fast'"""
        legacy = {
            "api_base": "http://test",
            "api_key": "",
            "model": "gpt-4",
            "chunking_preset": "fast",   # 老字段
            "timeout": 90,                 # 老字段
        }
        cfg = ProjectConfig.from_dict(legacy)
        # 兼容迁移: 老 chunking_preset → rewrite 字段
        self.assertEqual(cfg.chunking_preset_rewrite, "fast")
        # 老 timeout → rewrite_request_timeout
        self.assertEqual(cfg.rewrite_request_timeout, 90)
        # harness 字段走默认 (不被老字段覆盖)
        self.assertEqual(cfg.chunking_preset_harness, "large")
        self.assertEqual(cfg.harness_request_timeout, 180)

    def test_legacy_default_chunking_rewrite(self):
        """老配置无 chunking_preset → rewrite 走默认 balanced"""
        cfg = ProjectConfig.from_dict({})
        self.assertEqual(cfg.chunking_preset_rewrite, "balanced")
        self.assertEqual(cfg.rewrite_request_timeout, 120)


class TestProjectConfigFromDictNew(unittest.TestCase):
    """单元 #3: from_dict 新配置 (有新字段) 优先用新字段"""

    def test_new_fields_override_legacy(self):
        """新字段优先于老字段 (显式覆盖)"""
        new_config = {
            "chunking_preset": "fast",           # 老字段
            "chunking_preset_rewrite": "large",  # 新字段优先
            "timeout": 90,                        # 老字段
            "rewrite_request_timeout": 240,        # 新字段优先
            "chunking_preset_harness": "high_context",
            "harness_request_timeout": 300,
        }
        cfg = ProjectConfig.from_dict(new_config)
        self.assertEqual(cfg.chunking_preset_rewrite, "large")
        self.assertEqual(cfg.rewrite_request_timeout, 240)
        self.assertEqual(cfg.chunking_preset_harness, "high_context")
        self.assertEqual(cfg.harness_request_timeout, 300)


class TestProjectConfigRoundtrip(unittest.TestCase):
    """单元 #4: to_dict 32 字段全部往返无丢失"""

    def test_roundtrip_all_32_fields(self):
        cfg = ProjectConfig(
            chunking_preset_harness="high_context",
            chunking_preset_rewrite="large",
            harness_request_timeout=300,
            rewrite_request_timeout=180,
        )
        d = cfg.to_dict()
        cfg2 = ProjectConfig.from_dict(d)
        # 4 字段往返无丢失
        self.assertEqual(cfg.chunking_preset_harness, cfg2.chunking_preset_harness)
        self.assertEqual(cfg.chunking_preset_rewrite, cfg2.chunking_preset_rewrite)
        self.assertEqual(cfg.harness_request_timeout, cfg2.harness_request_timeout)
        self.assertEqual(cfg.rewrite_request_timeout, cfg2.rewrite_request_timeout)


# ============================================================
# compute_prompt_hash 4 字段 (v5.2c) — 单元 #5-#6
# ============================================================

class TestComputePromptHashV52c(unittest.TestCase):
    """单元 #5-#6: compute_prompt_hash 加 4 字段"""

    def test_hash_includes_harness_chunk(self):
        """chunking_preset_harness 不同 → hash 不同"""
        h1 = compute_prompt_hash(
            "strict", "gpt-4", "",
            chunking_preset_harness="large",
            chunking_preset_rewrite="balanced",
        )
        h2 = compute_prompt_hash(
            "strict", "gpt-4", "",
            chunking_preset_harness="high_context",  # 改
            chunking_preset_rewrite="balanced",
        )
        self.assertNotEqual(h1, h2)

    def test_hash_includes_rewrite_chunk(self):
        """chunking_preset_rewrite 不同 → hash 不同"""
        h1 = compute_prompt_hash(
            "strict", "gpt-4", "",
            chunking_preset_harness="large",
            chunking_preset_rewrite="balanced",
        )
        h2 = compute_prompt_hash(
            "strict", "gpt-4", "",
            chunking_preset_harness="large",
            chunking_preset_rewrite="fast",  # 改
        )
        self.assertNotEqual(h1, h2)

    def test_hash_includes_harness_timeout(self):
        """harness_request_timeout 不同 → hash 不同"""
        h1 = compute_prompt_hash("strict", "gpt-4", "", harness_request_timeout=180)
        h2 = compute_prompt_hash("strict", "gpt-4", "", harness_request_timeout=300)
        self.assertNotEqual(h1, h2)

    def test_hash_includes_rewrite_timeout(self):
        """rewrite_request_timeout 不同 → hash 不同"""
        h1 = compute_prompt_hash("strict", "gpt-4", "", rewrite_request_timeout=120)
        h2 = compute_prompt_hash("strict", "gpt-4", "", rewrite_request_timeout=240)
        self.assertNotEqual(h1, h2)

    def test_compute_prompt_hash_for_config_uses_new_fields(self):
        """compute_prompt_hash_for_config 同步新字段"""
        cfg1 = ProjectConfig(
            chunking_preset_harness="large",
            chunking_preset_rewrite="balanced",
        )
        cfg2 = ProjectConfig(
            chunking_preset_harness="high_context",  # 改
            chunking_preset_rewrite="balanced",
        )
        h1 = compute_prompt_hash_for_config(cfg1)
        h2 = compute_prompt_hash_for_config(cfg2)
        self.assertNotEqual(h1, h2)


# ============================================================
# 引擎 helper (v5.2c) — 单元 #7-#11
# ============================================================

class TestEngineHelpers(unittest.TestCase):
    """单元 #7-#11: 引擎 _effective_chunk_preset / _effective_timeout / _harness_active"""

    def _make_engine_stub(self, cfg: ProjectConfig):
        """构造最小 ProcessingEngine 桩, 绕过 __init__"""
        from app.processor import ProcessingEngine
        # 桩: 不调 __init__, 直接挂 config + 必需方法
        eng = ProcessingEngine.__new__(ProcessingEngine)
        eng.config = cfg
        return eng

    def test_harness_active_true_strict(self):
        """harness_enabled=True + prompt_mode=strict → _harness_active()=True"""
        cfg = ProjectConfig(harness_enabled=True, prompt_mode="strict")
        eng = self._make_engine_stub(cfg)
        self.assertTrue(eng._harness_active())

    def test_harness_active_true_polish(self):
        """harness_enabled=True + prompt_mode=polish → _harness_active()=True"""
        cfg = ProjectConfig(harness_enabled=True, prompt_mode="polish")
        eng = self._make_engine_stub(cfg)
        self.assertTrue(eng._harness_active())

    def test_harness_active_false_when_disabled(self):
        """harness_enabled=False → _harness_active()=False (即使 strict)"""
        cfg = ProjectConfig(harness_enabled=False, prompt_mode="strict")
        eng = self._make_engine_stub(cfg)
        self.assertFalse(eng._harness_active())

    def test_harness_active_false_when_custom(self):
        """prompt_mode=custom → _harness_active()=False (白名单)"""
        cfg = ProjectConfig(harness_enabled=True, prompt_mode="custom")
        eng = self._make_engine_stub(cfg)
        self.assertFalse(eng._harness_active())

    def test_harness_active_false_when_punct_local(self):
        """prompt_mode=punct_local → _harness_active()=False (本地模式不走 harness)"""
        cfg = ProjectConfig(harness_enabled=True, prompt_mode="punct_local")
        eng = self._make_engine_stub(cfg)
        self.assertFalse(eng._harness_active())

    def test_effective_chunk_preset_harness_mode(self):
        """harness 模式 → chunking_preset_harness (默认 'large')"""
        cfg = ProjectConfig(
            harness_enabled=True, prompt_mode="strict",
            chunking_preset_harness="high_context",
            chunking_preset_rewrite="balanced",
        )
        eng = self._make_engine_stub(cfg)
        self.assertEqual(eng._effective_chunk_preset(), "high_context")

    def test_effective_chunk_preset_rewrite_mode(self):
        """重写模式 → chunking_preset_rewrite (默认 'balanced')"""
        cfg = ProjectConfig(
            harness_enabled=False, prompt_mode="strict",  # harness 关 → 走 rewrite
            chunking_preset_harness="large",
            chunking_preset_rewrite="fast",
        )
        eng = self._make_engine_stub(cfg)
        self.assertEqual(eng._effective_chunk_preset(), "fast")

    def test_effective_timeout_harness_mode(self):
        """harness 模式 → harness_request_timeout (默认 180)"""
        cfg = ProjectConfig(
            harness_enabled=True, prompt_mode="strict",
            harness_request_timeout=300,
            rewrite_request_timeout=120,
        )
        eng = self._make_engine_stub(cfg)
        self.assertEqual(eng._effective_timeout(), 300)

    def test_effective_timeout_rewrite_mode(self):
        """重写模式 → rewrite_request_timeout (默认 120)"""
        cfg = ProjectConfig(
            harness_enabled=False, prompt_mode="strict",
            harness_request_timeout=180,
            rewrite_request_timeout=240,
        )
        eng = self._make_engine_stub(cfg)
        self.assertEqual(eng._effective_timeout(), 240)

    def test_effective_chunk_preset_fallback_when_missing(self):
        """字段缺失时走 getattr 兜底 (不抛异常)"""
        # 模拟老 ProjectConfig 内存对象 (无 4 字段) — 用 __dict__ 临时去掉
        cfg = ProjectConfig()
        del cfg.chunking_preset_harness  # 模拟缺失
        cfg.harness_enabled = True
        cfg.prompt_mode = "strict"
        eng = self._make_engine_stub(cfg)
        # 兜底: "large" 默认
        self.assertEqual(eng._effective_chunk_preset(), "large")

    def test_effective_timeout_fallback_when_missing(self):
        """timeout 字段缺失时走兜底 180"""
        cfg = ProjectConfig()
        del cfg.harness_request_timeout
        cfg.harness_enabled = True
        cfg.prompt_mode = "strict"
        eng = self._make_engine_stub(cfg)
        self.assertEqual(eng._effective_timeout(), 180)


# ============================================================
# 集成 — 跨模式切换 hash 变化 (v5.2c 端到端)
# ============================================================

class TestCrossModeHashChanges(unittest.TestCase):
    """集成 #3: 跨模式切换 hash 变化"""

    def test_strict_to_custom_hash_changes(self):
        """prompt_mode strict → custom → hash 变化 (因 harness 档切换派生)"""
        cfg1 = ProjectConfig(
            prompt_mode="strict",  # harness 模式
            harness_enabled=True,
        )
        cfg2 = ProjectConfig(
            prompt_mode="custom",  # 重写模式
            harness_enabled=True,
        )
        h1 = compute_prompt_hash_for_config(cfg1)
        h2 = compute_prompt_hash_for_config(cfg2)
        # 不等: prompt_mode 不同 + 4 字段派生不同
        self.assertNotEqual(h1, h2)

    def test_harness_enabled_toggle_hash_changes(self):
        """harness_enabled True → False → hash 变化 (派生 chunking 不同)"""
        cfg1 = ProjectConfig(
            prompt_mode="strict",
            harness_enabled=True,
            chunking_preset_harness="large",
            chunking_preset_rewrite="balanced",
        )
        cfg2 = ProjectConfig(
            prompt_mode="strict",
            harness_enabled=False,  # 切换
            chunking_preset_harness="large",
            chunking_preset_rewrite="balanced",
        )
        h1 = compute_prompt_hash_for_config(cfg1)
        h2 = compute_prompt_hash_for_config(cfg2)
        # 不等: harness_enabled 不同 + 派生 chunking 不同
        self.assertNotEqual(h1, h2)


# ============================================================
# v5.3.0: workflow 一等身份 (docs/archive/README.md 第二节 (已封存) §2 D4/D7)
# ============================================================

class TestWorkflowModeV530(unittest.TestCase):
    """workflow_mode 派生 / 白名单 / 档位按轨过滤 / hash 纳入"""

    def test_derives_when_empty(self):
        """未显式指定 → 按 v5.2c 之前旧逻辑派生 (老配置行为不变)"""
        from app.utils import effective_workflow
        self.assertEqual(effective_workflow(ProjectConfig()), "harness")
        self.assertEqual(
            effective_workflow(ProjectConfig(harness_enabled=False)), "rewrite")
        self.assertEqual(
            effective_workflow(ProjectConfig(prompt_mode="custom")), "rewrite")
        self.assertEqual(
            effective_workflow(ProjectConfig(prompt_mode="tech_doc")), "rewrite")
        self.assertEqual(
            effective_workflow(ProjectConfig(prompt_mode="punct_local")), "rewrite")

    def test_explicit_wins_and_invalid_falls_back(self):
        """显式值优先; 非法值回退派生 (不抛异常)"""
        from app.utils import effective_workflow
        # harness 轨关掉 (显式 rewrite) — 即使 harness_enabled=True + strict
        cfg = ProjectConfig(harness_enabled=True, prompt_mode="strict",
                            workflow_mode="rewrite")
        self.assertEqual(effective_workflow(cfg), "rewrite")
        # 显式 harness + harness_enabled=False → 仍按 harness (workflow 是权威)
        cfg2 = ProjectConfig(harness_enabled=False, prompt_mode="strict",
                             workflow_mode="harness")
        self.assertEqual(effective_workflow(cfg2), "harness")
        # 非法值 → 回退派生
        self.assertEqual(
            effective_workflow(ProjectConfig(prompt_mode="strict", workflow_mode="bogus")),
            "harness")

    def test_normalize_workflow_rejects_bad_input(self):
        from app.utils import normalize_workflow
        self.assertEqual(normalize_workflow("  HARNESS "), "harness")
        self.assertEqual(normalize_workflow("rewrite"), "rewrite")
        self.assertEqual(normalize_workflow(""), "")
        self.assertEqual(normalize_workflow(None), "")
        self.assertEqual(normalize_workflow(123), "")

    def test_tools_matrix(self):
        """白名单优先: workflow=harness 但模式不在白名单 → 不走工具链"""
        from app.utils import workflow_allows_tools
        self.assertTrue(workflow_allows_tools(ProjectConfig(prompt_mode="strict")))
        self.assertTrue(workflow_allows_tools(ProjectConfig(prompt_mode="polish")))
        self.assertFalse(workflow_allows_tools(
            ProjectConfig(prompt_mode="custom", workflow_mode="harness")))
        self.assertFalse(workflow_allows_tools(
            ProjectConfig(prompt_mode="tech_doc", workflow_mode="harness")))
        self.assertFalse(workflow_allows_tools(
            ProjectConfig(prompt_mode="strict", workflow_mode="rewrite")))

    def test_hash_includes_effective_workflow(self):
        """工作流不同 → 断点指纹不同 (老断点一次性失效, 属预期)"""
        h_harness = compute_prompt_hash_for_config(
            ProjectConfig(prompt_mode="strict", workflow_mode="harness"))
        h_rewrite = compute_prompt_hash_for_config(
            ProjectConfig(prompt_mode="strict", workflow_mode="rewrite"))
        self.assertNotEqual(h_harness, h_rewrite)
        # 显式 harness 与"派生得到 harness"应等价 (老配置升级不无谓失效)
        h_derived = compute_prompt_hash_for_config(ProjectConfig(prompt_mode="strict"))
        self.assertEqual(h_harness, h_derived)

    def test_from_dict_missing_workflow_is_empty(self):
        """老配置文件无 workflow_mode → "" (走派生, 升级后行为可预测)"""
        cfg = ProjectConfig.from_dict({"prompt_mode": "strict"})
        self.assertEqual(cfg.workflow_mode, "")
        from app.utils import effective_workflow
        self.assertEqual(effective_workflow(cfg), "harness")
        # 非法值也规整为 ""
        cfg2 = ProjectConfig.from_dict({"workflow_mode": "nonsense"})
        self.assertEqual(cfg2.workflow_mode, "")

    def test_resolve_chunk_preset_extra_large_harness_only(self):
        """extra_large 只对 harness 轨生效; 越轨一律回退 large"""
        from app.utils import resolve_chunk_preset
        cfg = ProjectConfig(
            prompt_mode="strict",
            chunking_preset_harness="extra_large",
            chunking_preset_rewrite="extra_large",  # 被老 API / 老配置写脏
        )
        self.assertEqual(resolve_chunk_preset(cfg), "extra_large")
        # 显式切到 rewrite 轨 → 回退 large (50000 不进流式整篇重写)
        self.assertEqual(resolve_chunk_preset(cfg, "rewrite"), "large")
        # 未知档位 → balanced
        self.assertEqual(
            resolve_chunk_preset(ProjectConfig(chunking_preset_harness="nope")),
            "balanced")

    def test_resolve_request_timeout_per_track(self):
        from app.utils import resolve_request_timeout
        cfg = ProjectConfig(
            prompt_mode="strict",
            harness_request_timeout=180, rewrite_request_timeout=120,
        )
        self.assertEqual(resolve_request_timeout(cfg), 180)
        self.assertEqual(resolve_request_timeout(cfg, "rewrite"), 120)

    def test_presets_for_workflow_filters(self):
        """按轨过滤: harness 含 extra_large, rewrite 不含; 空参 = 全量"""
        from app.utils import presets_for_workflow
        all_keys = [p["key"] for p in presets_for_workflow()]
        harness_keys = [p["key"] for p in presets_for_workflow("harness")]
        rewrite_keys = [p["key"] for p in presets_for_workflow("rewrite")]
        self.assertEqual(len(all_keys), 6)
        self.assertIn("extra_large", harness_keys)
        self.assertNotIn("extra_large", rewrite_keys)
        self.assertIn("whole_file", rewrite_keys)
        # 返回副本, 改不动全局常量
        presets_for_workflow("harness")[0]["label"] = "MUTATED"
        self.assertNotEqual(presets_for_workflow("harness")[0]["label"], "MUTATED")

    def test_engine_effective_preset_falls_back(self):
        """引擎侧闭环: 整篇轨写出 extra_large 也不会真的用 50000"""
        from app.processor import ProcessingEngine
        cfg = ProjectConfig(
            prompt_mode="strict", harness_enabled=False,
            chunking_preset_rewrite="extra_large",
        )
        eng = ProcessingEngine.__new__(ProcessingEngine)
        eng.config = cfg
        self.assertEqual(eng._effective_chunk_preset(), "large")


# ============================================================
# 主入口 — 兼容 run_all_tests.py 的 [PASS]/[FAIL] 统计
# ============================================================

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    total = result.testsRun
    failed = len(result.failures) + len(result.errors)
    passed = total - failed
    # v5.4.3 (F0-①): 0 用例必须判失败 —— unittest.wasSuccessful() 对空 suite 返回 True,
    # 会打印 [PASS] (0/0) 且 exit 0, 门禁静默绿灯。类名写错 / 用例被误改名即触发。
    assert total > 0, "test_harness_split 收集到 0 个用例 (类名/方法名被误改?)"
    if result.wasSuccessful():
        print(f"[PASS] test_harness_split ({passed}/{total})")
    else:
        print(f"[FAIL] test_harness_split ({passed}/{total}, {failed} fail)")
    sys.exit(0 if result.wasSuccessful() else 1)
