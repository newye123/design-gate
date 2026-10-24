#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""设计交付自检：两族规则，一个退出码。

G 族（闸门）——查一份设计文档有没有把五阶段走完：
    一份「看起来写了很多」的设计文档，最常见的病不是写得差，是**跳步**。
    没定核心任务就开始排页面，没画空态就交付。G 族只查"这一阶段有没有产物"。

D 族（反 AI 味）——查样式表有没有踩四条铁律：
    Inter / 纯黑 / 三等分卡片 / 居中 Hero。外加一份禁词表。
    这四条只在**落地页、宣传页**上成立；用在密集的后台界面上会大面积误报，
    所以 D 族必须带 --kind 声明页面类型，不声明就按 landing 处理并给出提示。

退出码三档：
    0  没有发现问题
    1  有 findings
    2  工具自己没跑起来（文件读不了、参数不对、一个规则都没执行）

第三档是刻意的。一个跑不起来的检查器，绝不许被读成"干净"。

用法：
    python tools/design_check.py docs/方案.md
    python tools/design_check.py --kind app src/styles.css src/pages/
    python tools/design_check.py --strict docs/方案.md      # 警告也算失败
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass

# ---------------------------------------------------------------- 数据

@dataclass
class Issue:
    code: str
    level: str      # "error" | "warn"
    file: str
    line: int
    msg: str

    def __str__(self) -> str:
        loc = f"{self.file}:{self.line}" if self.line > 0 else self.file
        return f"[{self.code}] {loc}  {self.msg}"


# 禁词：出现一个就该重写这句话，不是"尽量少用"。
BANNED_WORDS = ["赋能", "闭环", "一站式", "沉浸式", "极致", "丝滑"]

# 三态：设计交付里最容易漏的三样。漏了不算完成。
STATES = {
    "空态": ["空态", "空状态", "empty state", "empty-state", "没有数据", "无数据"],
    "加载态": ["加载态", "加载状态", "loading", "骨架屏", "skeleton"],
    "错误态": ["错误态", "错误状态", "error state", "error-state", "失败态"],
}

HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
SIZE_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:px|rem|em|pt)\b")
MEASURE_RE = re.compile(r"\d+\s*(?:%|秒|s\b|步|次|分钟|min|ms)|[≤≥<>]\s*\d")

# 适用域标记：设计交付文档一定会出现其中若干个；调研报告、会议纪要、复盘不会。
# 这是检查器的第一条规矩——先问「你检查的是不是这个东西」。
DESIGN_MARKERS = [
    "核心任务", "用户", "页面", "线框", "设计系统", "对抗审查",
    "成功标准", "验收标准", "信息架构",
]
DESIGN_MARKER_MIN = 3

TEXT_EXT = {".md", ".markdown", ".txt"}
STYLE_EXT = {".css", ".scss", ".less", ".html", ".htm", ".tsx", ".jsx", ".vue", ".svelte"}


def is_design_doc(text: str) -> tuple[bool, int]:
    """判断这份文档是不是「设计交付」这一类。返回 (是否适用, 命中标记数)。

    为什么要先判类型：拿五阶段闸门去查一份调研方案，会稳定报出 6 条
    「缺页面清单 / 缺三态 / 没有字号阶梯」——每一条都是真的"文档里没有"，
    每一条也都不该问。六条不适用加起来仍然是零，但"六条问题"这个数量
    本身在暗示"这份文档问题很大"，人很容易直接采信。
    """
    hits = sum(1 for m in DESIGN_MARKERS if m in text)
    return hits >= DESIGN_MARKER_MIN, hits


def read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def line_of(text: str, needle: str) -> int:
    """返回 needle 首次出现的行号（1 起），找不到返回 0。"""
    idx = text.find(needle)
    if idx < 0:
        return 0
    return text.count("\n", 0, idx) + 1


# ---------------------------------------------------------------- G 族

def section_window(text: str, heading_re: str, max_lines: int = 14) -> str:
    """取「标题行 + 其后若干行」作为一个窗口，遇到下一个分节就停。

    两次修都是被测试逼出来的：

    ① 第一版只把标题那一行当判据，于是 `**成功标准（可验收）**：` 后面明明列了
       「≤3 次点击」「≤10 分钟」「5 秒内」，却因为标题行本身没有数字被判成
       「没有可测指标」。判据不能只看标题——标题是标签，内容在下面。

    ② 第二版改成固定取 14 行，结果把**下一节**的「成功标准」也圈进来了：
       挖掉核心任务的量化之后，窗口里仍然有别的数字，G002 于是永远不响。
       窗口必须**有边界**，否则它测的就不是这一节。
    """
    m = re.search(heading_re, text)
    if not m:
        return ""

    lines = text[m.start():].split("\n")
    out = [lines[0]]
    for line in lines[1:max_lines]:
        stripped = line.strip()
        # 遇到下一个二级标题，或下一个加粗标签，就结束
        if stripped.startswith("## "):
            break
        if re.match(r"^\*\*[^*]+\*\*\s*[：:]?\s*$", stripped) and len(out) > 1:
            break
        out.append(line)
    return "\n".join(out)


def check_design_doc(path: str, text: str) -> list[Issue]:
    """五阶段闸门：只查「这一阶段有没有产物」，不评价好坏。"""
    issues: list[Issue] = []
    f = path
    low = text.lower()

    def has(*words: str) -> bool:
        return any(w.lower() in low for w in words)

    # G001/G002 核心任务
    # 必须是一个**标签**（加粗标签、二级标题、或「核心任务：」），不能只是文中提过。
    # 反例：对抗审查里有一句「核心任务真的三步内完成吗？」，第一版把这句当成产物，
    # 于是删掉「核心任务」整节之后 G001 仍然不响 —— 关键词出现 ≠ 这一阶段做完了。
    #
    # 但标签也不能要求一字不差：真实的文档写的是 `**核心任务（写死）**：`，
    # 括号里的限定词是作者在强调"这一句定死了"，不是没写。
    # 第三次修就是为这个括号。
    LABEL_GAP = r"\s*(?:[（(][^）)\n]{0,12}[）)])?\s*"
    core_label = (r"(?:^|\n)\s*(?:#{2,4}\s*[^\n]{0,12})?\*{0,2}\s*"
                  r"(?:核心任务|核心目标)" + LABEL_GAP + r"\*{0,2}\s*[：:]")
    if not re.search(core_label, text):
        issues.append(Issue("G001", "error", f, 0,
                            "缺「核心任务」——没有这一句，后面排的页面都是猜的"))
    else:
        win = section_window(text, core_label)
        if not MEASURE_RE.search(win):
            issues.append(Issue("G002", "error", f, line_of(text, "核心任务"),
                                "核心任务没有量化（缺「3 秒内」「≤2 步」「≥90%」这类判据）——"
                                "「提供 XX 功能」不是核心任务"))

    # G003 目标用户
    # 认「目标用户 / 用户画像 / **用户** / 用户：/ 受众 / 使用者」。
    # 第一版只写了「目标用户 / 用户画像」，于是在一份写着 `**用户**：` 的文档上误报。
    if not re.search(r"(?:目标用户|用户画像|\*\*\s*用户\s*\*\*|用户\s*[：:]|受众|使用者)", text):
        issues.append(Issue("G003", "error", f, 0, "缺「目标用户」——谁在用、什么设备、什么场景"))

    # G004 成功标准
    # 同一个东西有四个常见叫法：成功标准 / 验收标准 / 验收指标 / 成功判据。
    # 第一版只认前两个，于是在一份写着「验收指标（每节记录三个数）」的文档上误报——
    # 那三个数就是成功标准，只是作者换了名字。
    if not has("成功标准", "验收标准", "验收指标", "成功判据", "完成判据"):
        issues.append(Issue("G004", "error", f, 0,
                            "缺「成功标准」——没有判据就没法验收，只能靠「看起来还行」"))
    else:
        win = section_window(
            text, r"(?:成功标准|验收标准|验收指标|成功判据|完成判据)[^\n]*")
        if not MEASURE_RE.search(win):
            issues.append(Issue("G004b", "warn", f, line_of(text, win[:12]),
                                "成功标准里没有可测指标（%／秒／步／率）"))

    # G005 页面清单
    if not has("页面清单", "视图清单", "页面结构", "信息架构"):
        issues.append(Issue("G005", "error", f, 0,
                            "缺「页面清单／信息架构」——没排过结构就直接进视觉，是跳步"))

    # G006 三态必须齐
    missing = [name for name, alts in STATES.items()
               if not any(a.lower() in low for a in alts)]
    if missing:
        issues.append(Issue("G006", "error", f, 0,
                            f"缺{'、'.join(missing)}——三态没画出来，这个设计不算完成"))

    # G007 颜色 token 必须给 hex
    color_heading = re.search(r"(?:颜色|配色|色板|color)[^\n]{0,40}", text)
    if color_heading:
        window = text[color_heading.start(): color_heading.start() + 1200]
        if not HEX_RE.search(window):
            issues.append(Issue("G007", "error", f,
                                line_of(text, color_heading.group(0)[:10]),
                                "有颜色章节但没给具体 hex——「柔和的蓝色」不是 token"))
    else:
        issues.append(Issue("G007", "warn", f, 0, "没有颜色／配色章节"))

    # G008 字号阶梯
    if not SIZE_RE.search(text):
        issues.append(Issue("G008", "error", f, 0,
                            "全篇没有一个尺寸值（px/rem）——没有字号阶梯与间距刻度"))

    # G009 对抗审查
    adv = re.search(r"(?:对抗审查|自我审查|反方|红队|self.?review)", text, re.I)
    if not adv:
        issues.append(Issue("G009", "error", f, 0,
                            "缺「对抗审查」一节——设计做完要自己拆自己"))
    else:
        tail = text[adv.end():]
        items = len(re.findall(r"(?m)^\s*(?:[-*]|\d+[.、)])\s+", tail))
        if items < 5:
            issues.append(Issue("G009b", "warn", f, line_of(text, adv.group(0)),
                                f"对抗审查只有 {items} 条（<5）——五问至少要逐条答一次"))

    # G010 禁词
    for w in BANNED_WORDS:
        if w in text:
            issues.append(Issue("G010", "error", f, line_of(text, w),
                                f"禁词「{w}」——出现即重写这句话"))

    return issues


# ---------------------------------------------------------------- D 族

def check_styles(path: str, text: str, kind: str) -> list[Issue]:
    issues: list[Issue] = []
    f = path

    # D001 Inter
    for m in re.finditer(r"font-family\s*:\s*([^;}\n]+)", text, re.I):
        if re.search(r"\bInter\b", m.group(1)):
            issues.append(Issue("D001", "warn", f, line_of(text, m.group(0)[:16]),
                                "用了 Inter——四条铁律之一。换成有性格的字族，或明确说明为什么这里必须是 Inter"))

    # D002 纯黑：只算「大面积使用」，边框／分割线不算
    for m in re.finditer(r"([a-z-]+)\s*:\s*([^;{}\n]*)", text, re.I):
        prop, val = m.group(1).lower(), m.group(2)
        if not re.search(r"#000(?:000)?\b", val):
            continue
        if prop.startswith("border") or prop in ("outline", "box-shadow", "text-shadow"):
            continue  # 发丝线用纯黑是合理的，不算 AI 味
        issues.append(Issue("D002", "warn", f, line_of(text, m.group(0)[:16]),
                            f"{prop} 用了纯黑 #000——暗面要留色相，纯黑会把界面压成灰"))

    # D003 三等分卡片
    if re.search(r"repeat\(\s*3\s*,|1fr\s+1fr\s+1fr|grid-cols-3\b", text, re.I):
        level = "error" if kind == "landing" else "warn"
        note = ("落地页禁三等分卡片（三个等宽卡片是最容易被认出「AI 做的」的版式）"
                if kind == "landing"
                else f"当前按 --kind={kind} 处理，仅提示；后台密集界面用三列是合理的")
        issues.append(Issue("D003", level, f,
                            line_of(text, re.search(r"repeat\(\s*3\s*,|1fr\s+1fr\s+1fr|grid-cols-3", text, re.I).group(0)),
                            note))

    # D004 居中 Hero
    hero = re.search(r"\.hero[^{]*\{([^}]*)\}", text, re.I | re.S)
    if hero:
        body = hero.group(1)
        if re.search(r"text-align\s*:\s*center|justify-content\s*:\s*center|align-items\s*:\s*center", body, re.I):
            issues.append(Issue("D004", "warn" if kind != "landing" else "error", f,
                                line_of(text, hero.group(0)[:16]),
                                "居中 Hero——四条铁律之一。首屏全居中会让信息层级彻底平掉"))

    # D005 禁词进文案
    for w in BANNED_WORDS:
        if w in text:
            issues.append(Issue("D005", "error", f, line_of(text, w),
                                f"文案里的禁词「{w}」"))

    return issues


# ---------------------------------------------------------------- 主流程

def gather(paths: list[str]) -> list[tuple[str, str]]:
    """展开目录，返回 [(path, text)]。只收已知扩展名。"""
    out: list[tuple[str, str]] = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = [d for d in dirs if d not in
                           (".git", "node_modules", "dist", "build", "__pycache__", ".next")]
                for name in sorted(files):
                    ext = os.path.splitext(name)[1].lower()
                    if ext in TEXT_EXT | STYLE_EXT:
                        fp = os.path.join(root, name)
                        out.append((fp, read_text(fp)))
        else:
            out.append((p, read_text(p)))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="设计交付自检（闸门 + 反 AI 味）")
    ap.add_argument("paths", nargs="+", help="设计文档或样式文件／目录")
    ap.add_argument("--kind", choices=["landing", "app"], default=None,
                    help="页面类型，检查样式文件时必填。landing 严于 app（三列网格在后台是合理的）")
    ap.add_argument("--strict", action="store_true", help="警告也视为失败")
    args = ap.parse_args(argv)

    try:
        files = gather(args.paths)
    except OSError as e:
        print(f"读取失败：{e}", file=sys.stderr)
        return 2

    if not files:
        print("没有读到任何文件——路径不对，或扩展名都不在支持列表里", file=sys.stderr)
        return 2

    # 默认值就是立场。不给默认值，使用者必须想一次「我在检查什么」；
    # 给了默认值，他永远不去想，而工具会替他猜错。
    # 所以检查样式文件时 --kind 必填，缺失即 2（无法判定），不是 0。
    has_style = any(os.path.splitext(p)[1].lower() in STYLE_EXT for p, _ in files)
    if has_style and args.kind is None:
        print("检查样式文件时必须声明 --kind landing 或 --kind app。\n"
              "  落地页禁三等分卡片；后台密集界面用三列是合理的。\n"
              "  同一条规则在两个适用域里结论相反，工具不替你猜。", file=sys.stderr)
        return 2

    issues: list[Issue] = []
    checked_rules: set[str] = set()
    skipped: list[tuple[str, int]] = []

    for path, text in files:
        ext = os.path.splitext(path)[1].lower()
        if ext in TEXT_EXT:
            ok, hits = is_design_doc(text)
            if not ok:
                skipped.append((path, hits))
                continue
            issues.extend(check_design_doc(path, text))
            checked_rules.add("G")
        elif ext in STYLE_EXT:
            issues.extend(check_styles(path, text, args.kind))
            checked_rules.add("D")

    for path, hits in skipped:
        print(f"跳过 {path}  命中 {hits}/{len(DESIGN_MARKERS)} 个设计文档标记 —— "
              f"闸门对它不适用", file=sys.stderr)

    # 一条规则都没执行 ⇒ 工具没跑起来 / 对象不对，不是"干净"
    if not checked_rules:
        if skipped:
            print("被检查的文件都不像设计交付文档。请确认你在检查的是不是设计文档——"
                  "对不上的对象，正确退出码是 2（无法判定），不是 0（干净）。",
                  file=sys.stderr)
        else:
            print("一个规则族都没执行（既没有文档也没有样式文件）", file=sys.stderr)
        return 2

    for i in sorted(issues, key=lambda x: (x.file, x.line, x.code)):
        print(i)

    errors = [i for i in issues if i.level == "error"]
    warns = [i for i in issues if i.level == "warn"]

    print(f"\n检查 {len(files)} 个文件，规则族 {','.join(sorted(checked_rules))}，"
          f"error {len(errors)} / warn {len(warns)}")

    if errors or (args.strict and warns):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
