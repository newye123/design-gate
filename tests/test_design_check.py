#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""design_check.py 的测试：四层。

1. fixture 层 —— 合格样本必须零问题通过（--strict 下也通过）
2. mutation 层 —— 从合格样本逐条挖掉一个产物，对应规则必须触发
3. 退出码层 —— 真跑子进程，断言 0 / 1 / 2 三档
4. 适用域层 —— 同一份代码，--kind 不同必须得到不同裁决

第 2 层是这组测试的主体。它的意义在于：**一条从来没红过的规则，等于没有这条规则。**
合格样本通过只证明"不误报"，挖掉东西还通过就说明"这条规则根本不会响"。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOOL = os.path.join(ROOT, "tools", "design_check.py")
FIXTURES = os.path.join(ROOT, "fixtures")
GOOD = os.path.join(FIXTURES, "good_design.md")
AI_TELL = os.path.join(FIXTURES, "ai_tell.css")

sys.path.insert(0, os.path.join(ROOT, "tools"))
import design_check as dc  # noqa: E402


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def codes(issues) -> set[str]:
    return {i.code for i in issues}


def run_tool(*args: str) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, TOOL, *args],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


class TestFixture(unittest.TestCase):
    def test_good_design_has_zero_issues(self):
        issues = dc.check_design_doc("good_design.md", read(GOOD))
        self.assertEqual(
            [], [str(i) for i in issues],
            "合格样本不该有任何问题——它通过不了，说明规则太紧",
        )

    def test_ai_tell_css_fires_all_five(self):
        found = codes(dc.check_styles("ai_tell.css", read(AI_TELL), "landing"))
        for code in ("D001", "D002", "D003", "D004", "D005"):
            with self.subTest(code=code):
                self.assertIn(code, found, f"{code} 没触发——这条规则是死的")

    def test_hairline_black_is_not_flagged(self):
        """发丝线用纯黑是合理的。D002 只该管大面积着色。"""
        css = ".x { border: 1px solid #000; border-top: 2px solid #000000; }"
        found = codes(dc.check_styles("x.css", css, "landing"))
        self.assertNotIn("D002", found, "把 border 的纯黑也算成 AI 味，是误报")


class TestMutations(unittest.TestCase):
    """逐条挖掉一个产物，对应规则必须响。"""

    def mutate(self, old: str, new: str) -> str:
        src = read(GOOD)
        self.assertIn(old, src, f"样本里找不到要挖掉的内容：{old!r}")
        return src.replace(old, new)

    def assert_fires(self, text: str, code: str):
        found = codes(dc.check_design_doc("mutated.md", text))
        self.assertIn(code, found, f"挖掉产物后 {code} 没有触发")

    def test_g001_missing_core_task(self):
        self.assert_fires(self.mutate("**核心任务**：", "**主要想法**："), "G001")

    def test_g002_core_task_not_quantified(self):
        text = self.mutate(
            "**核心任务**：租客在 3 步内提交一条报修工单，且不需要打电话。",
            "**核心任务**：提供一个好用的报修功能。",
        )
        self.assert_fires(text, "G002")

    def test_g003_missing_user(self):
        text = self.mutate("**用户**：", "**背景**：")
        self.assert_fires(text, "G003")

    def test_g004_missing_success_criteria(self):
        text = self.mutate("**成功标准**：", "**一些想法**：")
        self.assert_fires(text, "G004")

    def test_g004b_success_criteria_not_measurable(self):
        src = read(GOOD)
        # 只把成功标准那一段换成没有数字的说法
        text = re.sub(
            r"\*\*成功标准\*\*：.*?(?=\n## )",
            "**成功标准**：\n1. 用户觉得好用。\n2. 界面看起来专业。\n\n",
            src, flags=re.S,
        )
        self.assert_fires(text, "G004b")

    def test_g005_missing_page_list(self):
        # 要把「页面清单」和「信息架构」两个标记都拿掉。
        # 只改一个标签不算挖掉产物——G005 认的是「有没有排过结构」，
        # 而不是「有没有用过这个词」。这一条是测试逼着说清楚的。
        text = read(GOOD).replace("## 二、信息架构", "## 二、一些想法").replace("**页面清单**：", "**随便排排**：")
        self.assert_fires(text, "G005")

    def test_g006_missing_empty_state(self):
        text = read(GOOD).replace("空态", "某态")
        self.assert_fires(text, "G006")

    def test_g006_missing_loading_state(self):
        text = read(GOOD).replace("加载态", "某态")
        self.assert_fires(text, "G006")

    def test_g006_missing_error_state(self):
        text = read(GOOD).replace("错误态", "某态")
        self.assert_fires(text, "G006")

    def test_g007_colors_without_hex(self):
        src = read(GOOD)
        text = re.sub(r"#[0-9A-Fa-f]{6}", "柔和的颜色", src)
        text = re.sub(r"#[0-9A-Fa-f]{3}\b", "柔和的颜色", text)
        self.assert_fires(text, "G007")

    def test_g008_no_sizes(self):
        src = read(GOOD)
        text = re.sub(r"\b\d+(?:\.\d+)?\s*(?:px|rem|em)\b", "某个尺寸", src)
        self.assert_fires(text, "G008")

    def test_g009_missing_adversarial_review(self):
        text = self.mutate("## 五、对抗审查", "## 五、总结")
        self.assert_fires(text, "G009")

    def test_g010_banned_word(self):
        text = read(GOOD) + "\n\n本方案赋能整个报修闭环。\n"
        self.assert_fires(text, "G010")


class TestExitCodes(unittest.TestCase):
    def test_good_fixture_exits_zero(self):
        rc, out = run_tool("--strict", "fixtures/good_design.md")
        self.assertEqual(0, rc, out)

    def test_ai_tell_fixture_exits_one(self):
        rc, out = run_tool("--kind", "landing", "fixtures/ai_tell.css")
        self.assertEqual(1, rc, out)

    def test_missing_file_exits_two(self):
        """文件不存在必须是 2，不能是 0 —— 读不到不等于干净。"""
        rc, out = run_tool("fixtures/这个文件不存在.md")
        self.assertEqual(2, rc, out)

    def test_empty_dir_exits_two(self):
        """目录里没有任何受支持的文件，也是 2：一条规则都没跑。"""
        with tempfile.TemporaryDirectory() as d:
            rc, out = run_tool(d)
            self.assertEqual(2, rc, out)

    def test_bad_flag_exits_nonzero(self):
        rc, _ = run_tool("--kind", "nonsense", "fixtures/good_design.md")
        self.assertNotEqual(0, rc)

    def test_style_without_kind_exits_two(self):
        """检查样式文件时不给 --kind，必须 2。

        默认值就是立场：给了默认值，使用者永远不去想「我在检查什么」，
        工具会替他猜错——而在最常见的场景里猜"最严"，等于制造噪音。
        """
        rc, out = run_tool("fixtures/ai_tell.css")
        self.assertEqual(2, rc, out)
        self.assertIn("--kind", out)

    def test_clean_styles_exits_zero(self):
        with tempfile.NamedTemporaryFile("w", suffix=".css", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(".a { color: #1F2328; background: #FBF9F6; font-family: serif; }\n")
            path = fh.name
        try:
            rc, out = run_tool("--kind", "landing", "--strict", path)
            self.assertEqual(0, rc, out)
        finally:
            os.unlink(path)


class TestApplicabilityGate(unittest.TestCase):
    """检查器的第一条规矩：先问「你检查的是不是这个东西」。"""

    RESEARCH = """# 某方向调研与执行方案

## 一、竞品形态

NOBOOK / 希沃 / 101 教育 PPT 的共同形态：逼真实验 + 老师演示。

## 二、研究依据

Peer Instruction（Crouch & Mazur 2001）的归一化学习增益约为传统讲授的 2 倍。

## 三、执行排期

| 阶段 | 交付 | 工作量 |
|---|---|---|
| v0.2 | 任务卡 12 张 | 3 天 |
"""

    def test_research_doc_is_not_a_design_doc(self):
        ok, hits = dc.is_design_doc(self.RESEARCH)
        self.assertFalse(ok, f"调研文档被误判成设计文档（命中 {hits} 个标记）")

    def test_good_fixture_is_a_design_doc(self):
        ok, hits = dc.is_design_doc(read(GOOD))
        self.assertTrue(ok, f"合格样本被判成不是设计文档（命中 {hits} 个标记）")

    def test_non_design_doc_exits_two(self):
        """对象不对必须是 2。返回 0 是撒谎，返回 1 是冤枉。"""
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                         encoding="utf-8") as fh:
            fh.write(self.RESEARCH)
            path = fh.name
        try:
            rc, out = run_tool(path)
            self.assertEqual(2, rc, out)
            self.assertIn("不适用", out)
        finally:
            os.unlink(path)


class TestApplicability(unittest.TestCase):
    """同一份代码，两个裁决。差别不在代码，在声明的适用域。"""

    CSS = """
.hero { justify-content: center; align-items: center; background: #000; }
body { font-family: Inter, sans-serif; }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); }
"""

    def test_landing_is_stricter_than_app(self):
        landing = dc.check_styles("x.css", self.CSS, "landing")
        app = dc.check_styles("x.css", self.CSS, "app")

        landing_errors = [i for i in landing if i.level == "error"]
        app_errors = [i for i in app if i.level == "error"]

        self.assertGreater(
            len(landing_errors), len(app_errors),
            "landing 应该比 app 更严：三列网格在后台界面是合理的",
        )

    def test_app_still_reports_inter_and_black(self):
        """放宽不等于关掉。Inter 与纯黑在 app 里也只是 warn，不是消失。"""
        found = codes(dc.check_styles("x.css", self.CSS, "app"))
        self.assertIn("D001", found)
        self.assertIn("D002", found)


if __name__ == "__main__":
    unittest.main(verbosity=2)
