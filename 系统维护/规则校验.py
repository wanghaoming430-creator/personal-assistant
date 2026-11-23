#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
个人助手 · 规则校验

用法：
    cd [Vault根目录] && python3 系统维护/规则校验.py

检查依据：系统维护/命名与属性规范.md

退出码 0 = 全部通过；1 = 有硬错（FAIL）；2 = 只有警告（WARN）。

设计原则：
- 只读，不改任何文件。
- 硬错只放「违反了规则、且必须人改」的项；其余进警告。
- 豁免写在 WAIVERS 里，写清楚为什么豁免，不靠沉默通过。
"""

import os
import re
import sys
import json
import collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIP_DIRS = {'.obsidian', '.git', '.workbuddy', '.trash', '.claudian',
             '.agents', '.smtcmp_json_db', '.smtcmp_vector_db', 'node_modules',
             '归档'}

# ---------- 词表（与 命名与属性规范 2.1 / 2.2 同源） ----------

TYPES = {
    # 内容类
    '知识', '项目', 'SOP', '剪报', '书籍', '电影', '人物', '地点', '播客',
    '日记', '即时想法', '阶段回顾', '月度回顾', '年度回顾', '人生决策', '索引',
    # 记录类
    '个人画像', '长期记忆', '助手工作规则', '助手纠错档案', '个人经验记忆',
    '用户上下文摘要', '记忆规则', '用户信息采集计划', '检索验收记录', '本周清单',
    '个人画像更新提案', '长期记忆更新提案', '审计报告', '过程留痕',
    '项目定位', '项目记忆', '项目技能', '提示词',
    # 系统类
    '系统入口', '运行规则', '架构说明', '助手人格', '助手回复规范', '系统规则',
    '权限与隐私规则', '命名与属性规范', '数据流转规则', '云端模型接入说明',
    '检索验收规范', '系统变更记录', '方法库',
    '规则适用范围与升级规范', '睡眠学习规范', '模型适配规范', 'Smart Composer本地配置说明',
}

STATES = {
    # 还不能用
    '草稿', '待处理', '待回顾', '待阅读', '待观看', '待确认', '待验证',
    '规划中', '分析中',
    # 能用
    '进行中', '使用中', '已整理', '已确认', '已验证', '生效',
    # 不用了
    '归档',
}

PROJECT_STATES = {'进行中', '等待外部', '已结项', '归档'}

RULE_SCOPES = {'全局通用', '项目类型通用', '项目专属', '待验证'}

DATE_KEYS = {'创建', '更新', '采集', '发布日期', '开始', '结束', '目标完成',
             '复盘日期', '决策期限', '验证日期', '周开始', '周结束'}

# 允许没有 frontmatter 的文件（写清理由，不静默放过）
WAIVERS = {
    '系统/工作台.md': 'DataviewJS 单块页，Obsidian 不读取其属性',
    'AGENTS.md': '平台适配入口，只指向运行入口，不作为库内笔记',
    '内容/项目/游戏项目/示例游戏项目/AGENTS.md': '项目自带说明，与平台入口同名但不是库规则',
    '内容/项目/游戏项目/示例游戏项目/CLAUDE.md': '项目自带的 Claude 入口，内容为 [社交账号].md 导入指令，不改原格式',
    '内容/项目/游戏项目/示例游戏项目/Documents/concept.md': '项目自带设计文档，非库内笔记，保留原格式',
    '内容/项目/游戏项目/示例游戏项目/Documents/技术架构.md': '项目自带设计文档，非库内笔记，保留原格式',
    '内容/项目/游戏项目/给AI的搭建说明.md': '迁入的项目资料，非库内笔记',
    '内容/项目/行业情报项目/行业·行业情报项目·跟踪台账.md': '迁入的行业台账，保留原样',
    '内容/项目/行业情报项目/行业·行业情报项目·跟踪台账.md': '迁入的行业台账，保留原样',
    '内容/图/个人助手运行框架.md': 'Excalidraw 绘图文件，frontmatter 由插件管理，不按笔记词表补类型',
}
WAIVER_PATTERNS = [
    (re.compile(r'^内容/项目/作品档案/批次/'), '批次图文档案，图与记录同目录，归作品档案总览管'),
    (re.compile(r'^外部收件箱/剪报/'), '剪藏按硬约束只读，不改 frontmatter 与日期写法'),
]

# 索引页的 Dataview 条件应与类型词表一致
INDEX_TYPE_FILTERS = {
    '内容/知识/知识索引.md': ['知识'],
    '内容/项目/项目索引.md': ['项目'],
    '内容/流程/流程索引.md': ['SOP'],
    '内容/决策/决策索引.md': ['人生决策'],
    '外部收件箱/剪报/剪报索引.md': ['剪报'],
    '日志/即时想法/即时想法索引.md': ['即时想法', '日记'],
    '日志/阶段回顾/阶段回顾索引.md': ['阶段回顾'],
    '日志/月度回顾/月度回顾索引.md': ['月度回顾'],
    '日志/年度回顾/年度回顾索引.md': ['年度回顾'],
}


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, '/')


def is_waived(path):
    if path in WAIVERS:
        return True
    return any(rx.match(path) for rx, _ in WAIVER_PATTERNS)


def walk_md():
    out = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            if f.endswith('.md'):
                out.append(os.path.join(dp, f))
    return sorted(out)


FM = re.compile(r'^---\r?\n(.*?)\r?\n---', re.S)


def parse_fm(text):
    m = FM.match(text)
    if not m:
        return None
    fm = {}
    for line in m.group(1).split('\n'):
        mm = re.match(r'^([^\s:#][^:]*):[ \t]*(.*)$', line)
        if mm:
            v = mm.group(2).strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
                v = v[1:-1]
            fm[mm.group(1).strip()] = v
    return fm


def check_frontmatter(files):
    fails, warns = [], []
    for p in files:
        r = rel(p)
        if r.startswith('模板/'):
            continue
        try:
            text = open(p, encoding='utf-8', errors='ignore').read()
        except OSError:
            continue
        fm = parse_fm(text)
        if fm is None:
            if not is_waived(r):
                warns.append((r, '没有 frontmatter', '补 类型/创建，或在 WAIVERS 里写明豁免理由'))
            continue
        if is_waived(r):
            continue
        t = fm.get('类型', '')
        s = fm.get('状态', '')
        ps = fm.get('项目状态', '')
        rs = fm.get('规则范围', '')
        if not t:
            fails.append((r, '缺 类型', '按命名与属性规范 2.1 补一个值'))
        elif t not in TYPES:
            fails.append((r, f'类型「{t}」不在词表', '改词表，或改用规范里的值'))
        if s and s not in STATES:
            hint = '含复合值' if re.search(r'[/／、]', s) else '不在词表'
            fails.append((r, f'状态「{s}」{hint}', '按 2.2 改成单一值'))
        if ps and ps not in PROJECT_STATES:
            hint = '含复合值' if re.search(r'[/／、]', ps) else '不在项目状态词表'
            fails.append((r, f'项目状态「{ps}」{hint}', '按 2.3 改成进行中/等待外部/已结项/归档'))
        if rs and rs not in RULE_SCOPES:
            hint = '含复合值' if re.search(r'[/／、]', rs) else '不在规则范围词表'
            fails.append((r, f'规则范围「{rs}」{hint}', '按 2.3 改成全局通用/项目类型通用/项目专属/待验证'))
        if t == '知识' and not (r.startswith('内容/知识/') or r.startswith('沉淀/概念/')):
            fails.append((r, '知识页不在规定目录', '放到 内容/知识/ 或 沉淀/概念/'))
        if t == '项目' and not ps:
            warns.append((r, '缺 项目状态', '补 进行中/等待外部/已结项/归档'))
        for k in DATE_KEYS:
            if k in fm:
                v = fm[k]
                if v and v != 'YYYY-MM-DD' and not re.match(r'^\d{4}-\d{2}-\d{2}$', v):
                    fails.append((r, f'{k}「{v}」格式不对', '写裸日期 YYYY-MM-DD，不加引号'))
    return fails, warns


def check_quoted_dates(files):
    out = []
    # 空值写 "" 是规范允许的，只查引号里有内容的情况
    rx = re.compile(r'^(?:' + '|'.join(DATE_KEYS) + r'):[ \t]*"[^"]+')
    for p in files:
        if is_waived(rel(p)):
            continue
        try:
            text = open(p, encoding='utf-8', errors='ignore').read()
        except OSError:
            continue
        m = FM.match(text)
        if not m:
            continue
        for line in m.group(1).split('\n'):
            if rx.match(line.strip()):
                out.append((rel(p), line.strip(), '去掉引号，用裸日期'))
    return out


def check_empty(files):
    out = []
    for p in files:
        try:
            if os.path.getsize(p) == 0:
                out.append((rel(p), '0 字节', '补正文，或删文件'))
        except OSError:
            pass
    return out


def check_duplicates(files):
    idx = collections.defaultdict(list)
    for p in files:
        r = rel(p)
        if r.startswith('模板/') or is_waived(r):
            continue
        idx[os.path.basename(p)].append(r)
    return [(name, paths, '定一处为正本，另一处改成索引或删除')
            for name, paths in idx.items() if len(paths) > 1]


def build_asset_index():
    """索引图片、附件等非 Markdown 文件，避免把有效的附件嵌入误报为断链。"""
    assets = {}
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        for f in fn:
            assets.setdefault(f, []).append(rel(os.path.join(dp, f)))
    return assets


def check_links(files):
    names = {}
    for p in files:
        r = rel(p)
        names.setdefault(os.path.basename(p)[:-3], []).append(r)
        names.setdefault(r[:-3], []).append(r)
    assets = build_asset_index()
    broken = []
    rx = re.compile(r'\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]')
    for p in files:
        if is_waived(rel(p)):
            continue
        text = open(p, encoding='utf-8', errors='ignore').read()
        # 行内代码里的 [[...]] 是示例文本，Obsidian 不解析，跳过
        scan = re.sub(r'`[^`\n]*`', '', text)
        for m in rx.finditer(scan):
            target = m.group(1).strip().rstrip('\\')
            if not target or target in names:
                continue
            # 表格里的图片嵌入写作 ![[图.jpg\|240]]，去掉转义后按附件索引解析
            if target in assets or os.path.basename(target) in assets:
                continue
            cand = target if target.endswith('.md') else target + '.md'
            if os.path.exists(os.path.join(ROOT, cand)):
                continue
            # Obsidian 按路径后缀解析：任一路径以 target 结尾即算命中
            if any(x.endswith('/' + target) or x.endswith('/' + cand) for x in names.get(os.path.basename(cand)[:-3], [])):
                continue
            broken.append((rel(p), '[[' + target + ']]', '改指向或删链接'))
    return broken


def check_rag():
    p = os.path.join(ROOT, '.obsidian/plugins/smart-composer/data.json')
    out = []
    if not os.path.exists(p):
        return out
    try:
        d = json.load(open(p, encoding='utf-8'))
    except Exception as e:
        return [(p, f'JSON 解析失败：{e}', '恢复备份或重装插件')]
    rag = d.get('ragOptions') or {}
    ex = rag.get('excludePatterns') or []
    inc = rag.get('includePatterns') or []
    all_blocked = any(x.strip() in ('**/*', '**', '*') for x in ex)
    if not ex and not inc:
        out.append(('.obsidian/plugins/smart-composer/data.json',
                    'RAG 无排除、无白名单，模板与画像都在可索引范围',
                    '设 excludePatterns 或改用白名单'))
    emb = str(d.get('embeddingModelId', ''))
    if not all_blocked and (emb.startswith('openai/') or emb.startswith('gemini/')):
        out.append(('.obsidian/plugins/smart-composer/data.json',
                    f'可索引状态下嵌入模型是云端的（{emb}）', '换成本地嵌入，或把 RAG 全排除'))
    return out


def check_index_filters():
    out = []
    for rel_path, expected in INDEX_TYPE_FILTERS.items():
        p = os.path.join(ROOT, rel_path)
        if not os.path.exists(p):
            out.append((rel_path, '索引页不存在', '补建或从清单里删掉'))
            continue
        text = open(p, encoding='utf-8').read()
        found = set(re.findall(r'类型\s*=\s*"([^"]+)"', text))
        for v in found:
            if v not in TYPES:
                out.append((rel_path, f'查询用了词表外的类型「{v}」', '改查询或改词表'))
        states = set(re.findall(r'项目状态\s*=\s*"([^"]+)"', text))
        for v in states:
            if v not in PROJECT_STATES:
                out.append((rel_path, f'查询用了词表外的项目状态「{v}」', '改成进行中/等待外部/已结项/归档'))
    return out


def check_entry_counts(files):
    p = os.path.join(ROOT, '系统/入口.md')
    if not os.path.exists(p):
        return []
    text = open(p, encoding='utf-8').read()
    stats = collections.Counter()
    for fp in files:
        r = rel(fp)
        fm = parse_fm(open(fp, encoding='utf-8', errors='ignore').read())
        if not fm:
            continue
        if fm.get('类型') == '项目' and r.startswith('内容/项目/'):
            stats['项目'] += 1
        if fm.get('类型') == '知识' and r.startswith('内容/知识/') and fm.get('状态') != '归档':
            stats['知识'] += 1
        if fm.get('类型') == '剪报' and r.startswith('外部收件箱/剪报/'):
            stats['剪报'] += 1
    out = []
    for label in ('项目', '知识', '剪报'):
        m = re.search(label + r'[^\n]{0,10}?(\d+)\s*篇', text)
        if m and int(m.group(1)) != stats[label]:
            out.append(('系统/入口.md', f'写「{label} {m.group(1)} 篇」，实际 {stats[label]} 篇',
                        '改成实际数，或删掉硬数字'))
    return out


def check_empty_dirs():
    out = []
    for dp, dn, fn in os.walk(ROOT):
        dn[:] = [d for d in dn if d not in SKIP_DIRS]
        if dp == ROOT:
            continue
        entries = [x for x in os.listdir(dp) if x != '.DS_Store']
        if not entries:
            out.append((rel(dp) + '/', '空目录', '删掉，或加一行说明它暂不启用'))
    return out


def report(title, rows, level, limit=25):
    if not rows:
        return 0
    print(f'\n{level} · {title}（{len(rows)}）')
    for row in rows[:limit]:
        print('  ' + ' | '.join(str(x) for x in row))
    if len(rows) > limit:
        print(f'  …… 另有 {len(rows) - limit} 条')
    return len(rows)


def main():
    files = walk_md()
    print(f'个人助手 · 规则校验  库内 Markdown {len(files)} 个')

    f1, w1 = check_frontmatter(files)
    fails = []
    fails += [('词表',) + x for x in f1]
    warns = list(w1)

    quoted = check_quoted_dates(files)
    fails += [('日期引号',) + x for x in quoted]

    empty = check_empty(files)
    fails += [('空文件',) + x for x in empty]

    dup = check_duplicates(files)
    fails += [('同名',) + x for x in dup]

    broken = check_links(files)
    fails += [('断链',) + x for x in broken]

    rag = check_rag()
    fails += [('RAG',) + x for x in rag]

    idx = check_index_filters()
    fails += [('索引查询',) + x for x in idx]

    warns += [('入口数字',) + x for x in check_entry_counts(files)]
    warns += [('空目录',) + x for x in check_empty_dirs()]

    n_fail = report('硬错', fails, 'FAIL')
    n_warn = report('警告', warns, 'WARN')

    print()
    if n_fail:
        print(f'结果：{n_fail} 项硬错，{n_warn} 项警告。硬错按提示改，或把豁免理由写进脚本 WAIVERS。')
        return 1
    if n_warn:
        print(f'结果：0 项硬错，{n_warn} 项警告。警告不影响使用，看着办。')
        return 2
    print('结果：全部通过。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
