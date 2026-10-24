#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库自检：案例、链接、脱敏、frontmatter、资源清单。

和另外两个仓库同一套判据：仓库自己说「有三个真实案例」，就必须真的有三个、
真的可点开、真的不含客户信息。不然它就是它自己批判的那个东西。
"""

from __future__ import annotations

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CASES = os.path.join(ROOT, "cases")
SKILL = os.path.join(ROOT, "SKILL.md")
CASES_README = os.path.join(CASES, "README.md")

BANNED = [
    "图译", "工坊", "tuyigf", "SmallRig", "斯莫格",
    "5775", "6746", "yt-visual", "飞书", "镜已", "健身教练", "ai-body-coach",
]

REQUIRED_SECTIONS = ["现象", "取证", "结论", "可迁移的判据"]
MIN_CHARS = 800


def case_files() -> list[str]:
    return sorted(
        os.path.join(CASES, f)
        for f in os.listdir(CASES)
        if f.endswith(".md") and f.lower() != "readme.md"
    )


def read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def md_links(text: str) -> list[str]:
    out = []
    for m in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text):
        target = m.group(1).strip()
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        out.append(target.split("#")[0])
    return out


class TestCaseStructure(unittest.TestCase):
    def test_at_least_three_cases(self):
        self.assertGreaterEqual(len(case_files()), 3, "至少三个案例，否则「真实案例」是空话")

    def test_every_case_has_required_sections(self):
        for path in case_files():
            body = read(path)
            for sec in REQUIRED_SECTIONS:
                with self.subTest(case=os.path.basename(path), section=sec):
                    self.assertRegex(body, rf"(?m)^##\s+{sec}\s*$",
                                     f"{path} 缺一节：## {sec}")

    def test_every_case_is_long_enough(self):
        for path in case_files():
            with self.subTest(case=os.path.basename(path)):
                self.assertGreaterEqual(len(read(path)), MIN_CHARS, f"{path} 太短，像占位")

    def test_every_case_shows_a_real_reading(self):
        for path in case_files():
            body = read(path)
            with self.subTest(case=os.path.basename(path)):
                has = ("```" in body) or re.search(r"rc\s*=\s*\d", body) or ("[G0" in body) or ("[D0" in body)
                self.assertTrue(has, f"{path} 没有任何可核的读数")


class TestCaseIndex(unittest.TestCase):
    def test_cases_readme_links_every_case(self):
        index = read(CASES_README)
        for path in case_files():
            name = os.path.basename(path)
            with self.subTest(case=name):
                self.assertIn(name, index, f"cases/README.md 没有索引 {name}")

    def test_skill_links_at_least_three_cases(self):
        body = read(SKILL)
        linked = [t for t in md_links(body) if t.startswith("cases/")]
        self.assertGreaterEqual(len(linked), 3, "SKILL.md 应至少引用三个案例")


class TestLinks(unittest.TestCase):
    def test_all_relative_links_resolve(self):
        targets = [(CASES, f) for f in sorted(os.listdir(CASES)) if f.endswith(".md")]
        targets.append((ROOT, "README.md"))
        targets.append((ROOT, "SKILL.md"))
        for directory, fname in targets:
            for target in md_links(read(os.path.join(directory, fname))):
                with self.subTest(file=fname, link=target):
                    resolved = os.path.normpath(os.path.join(directory, target))
                    self.assertTrue(os.path.exists(resolved), f"{fname} 里的死链：{target}")

    def test_skill_references_exist(self):
        body = read(SKILL)
        for ref in re.findall(r"`((?:tools|fixtures|tests|cases)/[^`]+)`", body):
            with self.subTest(ref=ref):
                self.assertTrue(os.path.exists(os.path.join(ROOT, ref)),
                                f"SKILL.md 引用了不存在的 {ref}")


class TestDesensitization(unittest.TestCase):
    def test_no_banned_strings(self):
        me = os.path.abspath(__file__)
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
            for fname in filenames:
                path = os.path.join(dirpath, fname)
                if os.path.abspath(path) == me:
                    continue
                if not fname.lower().endswith((".md", ".py", ".css", ".txt", ".yml", ".yaml")):
                    continue
                body = read(path)
                for word in BANNED:
                    with self.subTest(file=os.path.relpath(path, ROOT), word=word):
                        self.assertNotIn(word, body,
                                         f"{os.path.relpath(path, ROOT)} 含敏感串：{word}")

    def test_no_absolute_paths(self):
        me = os.path.abspath(__file__)
        pat = re.compile(r"[A-Za-z]:[\\/](?:Users|工具开发|01_AI)")
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__")]
            for fname in filenames:
                path = os.path.join(dirpath, fname)
                if os.path.abspath(path) == me:
                    continue
                if not fname.lower().endswith(".md"):
                    continue
                with self.subTest(file=os.path.relpath(path, ROOT)):
                    self.assertIsNone(pat.search(read(path)),
                                      f"{os.path.relpath(path, ROOT)} 含本机绝对路径")


class TestFrontmatter(unittest.TestCase):
    def setUp(self):
        body = read(SKILL)
        m = re.match(r"^---\n(.*?)\n---\n", body, re.S)
        self.assertIsNotNone(m, "SKILL.md 缺 frontmatter")
        self.meta = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                self.meta[k.strip()] = v.strip()

    def test_required_keys(self):
        for key in ("name", "description", "version", "license"):
            with self.subTest(key=key):
                self.assertIn(key, self.meta)
                self.assertTrue(self.meta[key])

    def test_name_matches_dir(self):
        self.assertEqual(self.meta["name"], "design-gate")

    def test_version_is_semver(self):
        self.assertRegex(self.meta["version"], r'^"?\d+\.\d+\.\d+"?$')

    def test_description_has_triggers(self):
        self.assertIn("触发词", self.meta["description"])

    def test_license_is_nc(self):
        self.assertIn("NC-1.0", self.meta["license"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
