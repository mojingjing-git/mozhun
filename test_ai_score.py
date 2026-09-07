# -*- coding: utf-8 -*-
"""v5.0.2 客户端 AI 味评分测试套件 (app/ai_score_local.py).

run_all_tests.py 按 test_*.py glob 自动发现 (无需注册).
ai_score_local 是纯函数 (无 IO 无网络无随机), 无需 test_isolate 隔离,
但按套件约定统一 import (无副作用).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_isolate  # noqa: F401  测试隔离, 防止污染真实 ~/.proofreader

passed = 0
failed = 0
errors_list = []


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        errors_list.append(name)
        print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def test_weights_sum_100():
    """权重总和必须恒等于 100 (AGENTS §34 裁定), 且阈值/上限为初始拍定值."""
    print("\n--- 权重与常量 ---")
    from app.ai_score_local import DIM_WEIGHTS, REVISE_THRESHOLD, _MAX_OFFENDERS
    check("权重和 = 100", sum(DIM_WEIGHTS.values()) == 100, str(DIM_WEIGHTS))
    check("六维齐全", set(DIM_WEIGHTS) == {
        "blacklist", "patterns", "counter", "burstiness", "markdown", "punct"})
    check("REVISE_THRESHOLD 在 (0, 100)", 0 < REVISE_THRESHOLD < 100,
          str(REVISE_THRESHOLD))
    check("offenders 上限 = 5", _MAX_OFFENDERS == 5)


def test_empty_text():
    """空文本: score 0, 无 dims, 无 offenders."""
    print("\n--- 空文本 ---")
    from app.ai_score_local import ai_score
    for t in ["", "   ", "\n\n"]:
        r = ai_score(t)
        check(f"空文本 {t!r} → 0 分", r["score"] == 0 and r["dims"] == {}
              and r["offenders"] == [], str(r))


def test_pure_idempotent():
    """纯函数幂等: 同输入两次调用结果完全相等 (无随机/无状态)."""
    print("\n--- 纯函数幂等 ---")
    from app.ai_score_local import ai_score
    sample = ("我们要为业务赋能，形成闭环。总之，希望对您有帮助！\n\n"
              "# 标题\n\n- 列表项\n\n专家认为，这不是终点，而是新的起点。")
    r1, r2 = ai_score(sample), ai_score(sample)
    check("同输入同输出", r1 == r2)
    check("结果可 JSON 序列化 (payload 可推前端)",
          isinstance(r1["score"], int) and isinstance(r1["dims"], dict))


def test_blacklist_dim():
    """硬黑名单词频: 中英文命中拉高分数, 出戏句携带黑名单原因."""
    print("\n--- 硬黑名单维度 ---")
    from app.ai_score_local import ai_score
    text = "本文将深入探讨如何为企业赋能，构建业务闭环，巩固护城河，" \
           "并复盘过去的经验。这套打法在赛道里已经蔚然成风。"
    r = ai_score(text)
    check("黑名单维度得分 > 0", r["dims"]["blacklist"]["score"] > 0,
          str(r["dims"]["blacklist"]))
    check("英文黑名单命中 (delve)", ai_score(
        "We need to delve into the details of this tapestry.")[
        "dims"]["blacklist"]["score"] > 0)
    check("offenders 摘出戏句且带原因", any(
        "黑名单" in reason for o in r["offenders"] for reason in o["reasons"]),
        str(r["offenders"]))


def test_patterns_dim():
    """7 大类痕迹 (第 2-7 类): 否定对照 / 意义膨胀 / 模糊归因 / 破折号泛滥."""
    print("\n--- 7 大类维度 ---")
    from app.ai_score_local import ai_score
    check("否定式对照命中", ai_score(
        "这不是一个问题，而是通往成长的阶梯。")[
        "dims"]["patterns"]["score"] > 0)
    check("意义膨胀命中", ai_score(
        "这次合作标志着关键转折点，为未来奠定基础。")[
        "dims"]["patterns"]["score"] > 0)
    check("模糊归因命中", ai_score(
        "专家认为，这项技术将改变一切。研究表明前景广阔。")[
        "dims"]["patterns"]["score"] > 0)
    check("破折号泛滥命中 (单段 3+)", ai_score(
        "他走了——留下门开着——屋里很静——像什么都没发生。")[
        "dims"]["patterns"]["score"] > 0)
    check("三连词命中", ai_score(
        "首先我们要统一认知，其次要明确分工，最后要落实责任。")[
        "dims"]["patterns"]["score"] > 0)


def test_counter_dim():
    """AI 6 处反制 (本地可测 5 项): 结尾太圆 / 鸡汤化 / 推进太顺 / 缺专名."""
    print("\n--- 6 处反制维度 ---")
    from app.ai_score_local import ai_score
    check("结尾太圆命中", ai_score(
        "方法讲完了，总之，希望对您有帮助。")[
        "dims"]["counter"]["score"] > 0)
    check("鸡汤化命中", ai_score(
        "站在更高的视角看，这不过是成长的一步。")[
        "dims"]["counter"]["score"] > 0)
    body = "\n\n".join(
        f"第{i}段讲了项目从启动到上线的过程中，团队按计划完成了需求评审、"
        f"开发联调、测试验收，最后顺利交付，客户非常满意，项目圆满结束。"
        for i in range(1, 5))
    check("推进太顺命中 (4 段无转折)", ai_score(body)[
        "dims"]["counter"]["score"] > 0)


def test_burstiness_dim():
    """句长方差: 等长句串记满, 长短交错记低, 短文本不判."""
    print("\n--- 句长方差维度 ---")
    from app.ai_score_local import ai_score
    uniform = "。".join(["这一段讲的是同一个意思的十个字左右"] * 6) + "。"
    varied = ("好。这句话稍微长一点，带了一些补充说明的成分，所以更长。"
              "短。然后又是一句很长很长的话，中间绕了几个弯，"
              "把前面说的那个意思重新讲了一遍，还举了个例子。")
    ru, rv = ai_score(uniform), ai_score(varied)
    check("等长句串 burstiness 高", ru["dims"]["burstiness"]["score"] >= 8,
          str(ru["dims"]["burstiness"]))
    check("长短交错 burstiness 低", rv["dims"]["burstiness"]["score"] <
          ru["dims"]["burstiness"]["score"], str(rv["dims"]["burstiness"]))
    check("单句不判 (记 0)", ai_score("就一句话。")[
        "dims"]["burstiness"]["score"] == 0)


def test_markdown_and_punct_dims():
    """Markdown 装饰密度 + 标点签名 (半角混排 / emoji)."""
    print("\n--- Markdown / 标点维度 ---")
    from app.ai_score_local import ai_score
    md_text = "# 大标题\n## 小标题\n**加粗的要点**\n- 要点一\n- 要点二\n> 引用\n---\n正文行"
    r = ai_score(md_text)
    check("Markdown 密度记满 (>=25% 装饰行)",
          r["dims"]["markdown"]["score"] == 10, str(r["dims"]["markdown"]))
    check("半角标点混排命中", ai_score(
        "这个功能很好用,但是文档没写清楚.大家都在等.")[
        "dims"]["punct"]["score"] > 0)
    check("emoji 命中", ai_score("太棒了👍👍继续保持！")[
        "dims"]["punct"]["score"] > 0)


def test_offenders_capped():
    """出戏句最多 5 条 (revise 反馈过长会稀释 prompt 信号)."""
    print("\n--- offenders 截断 ---")
    from app.ai_score_local import ai_score, _MAX_OFFENDERS
    text = "。".join(f"第{i}句要为业务赋能并形成闭环" for i in range(1, 12)) + "。"
    r = ai_score(text)
    check(f"offenders <= {_MAX_OFFENDERS}", len(r["offenders"]) <= _MAX_OFFENDERS,
          str(len(r["offenders"])))
    check("offenders 每条含 text+reasons", all(
        o.get("text") and o.get("reasons") for o in r["offenders"]))


def test_score_bounds_and_clean_text():
    """界值: 0 <= score <= 100; 洁净文本低于 REVISE_THRESHOLD (不误触发 revise)."""
    print("\n--- 界值与洁净文本 ---")
    from app.ai_score_local import ai_score, REVISE_THRESHOLD
    adversarial = ("赋能" * 30) + "# 标题\n" + ("!!" * 20) + "👍👍👍" + \
        "总之希望对您有帮助" + ("——" * 10) + "这不是终点，而是起点。" + \
        ("简短句。" * 15)
    r = ai_score(adversarial)
    check("对抗样本界值 0 <= score <= 100", 0 <= r["score"] <= 100, str(r["score"]))
    clean = ("昨天下午去了一趟老城区的菜市场，卖鱼的老板娘认出我，多塞了两根葱。"
             "回家路上想了想，其实她跟所有顾客都这样，只是我来得少才觉得稀奇。"
             "晚饭做了个鲫鱼豆腐汤，孩子挑刺挑得慢，汤倒是鲜的。饭后翻了几页书，"
             "没看进去，就下楼走了走。风比昨天凉，秋天是真的近了。")
    rc = ai_score(clean)
    check(f"洁净人写文本 ({rc['score']} 分) 低于 revise 阈值 {REVISE_THRESHOLD}",
          rc["score"] < REVISE_THRESHOLD, str(rc))


def test_deai_prompts_output_shape():
    """prompt 配合: REWRITE_V5 有「输出形态」节, AUDIT_V5 有本地评分关系节."""
    print("\n--- prompt 配合 ---")
    from app.templates import (
        SYSTEM_PROMPT_DEAI_REWRITE_V5, SYSTEM_PROMPT_DEAI_AUDIT_V5)
    check("REWRITE_V5 含输出形态节", "输出形态" in SYSTEM_PROMPT_DEAI_REWRITE_V5
          and "不要 Markdown 装饰" in SYSTEM_PROMPT_DEAI_REWRITE_V5)
    check("AUDIT_V5 含本地评分关系节",
          "本地 0-100 AI 味初筛" in SYSTEM_PROMPT_DEAI_AUDIT_V5
          and "出戏句" in SYSTEM_PROMPT_DEAI_AUDIT_V5)
    # verifier 裁定: 引用 blader 分类只用 "five sections + 25 patterns", 禁用编号
    for name, p in (("REWRITE_V5", SYSTEM_PROMPT_DEAI_REWRITE_V5),
                    ("AUDIT_V5", SYSTEM_PROMPT_DEAI_AUDIT_V5)):
        check(f"{name} 未沿用 blader v2.x 旧编号",
              "#18" not in p and "#31" not in p and "patterns #1" not in p)


def main():
    global passed, failed
    tests = [
        test_weights_sum_100,
        test_empty_text,
        test_pure_idempotent,
        test_blacklist_dim,
        test_patterns_dim,
        test_counter_dim,
        test_burstiness_dim,
        test_markdown_and_punct_dims,
        test_offenders_capped,
        test_score_bounds_and_clean_text,
        test_deai_prompts_output_shape,
    ]
    for t in tests:
        try:
            t()
        except Exception as e:
            import traceback
            check(t.__name__, False, f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
    print()
    print("=" * 60)
    print(f"  结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    if errors_list:
        print("\n失败项:")
        for name in errors_list:
            print(f"  - {name}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
