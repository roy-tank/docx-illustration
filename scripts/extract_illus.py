#!/usr/bin/env python3
"""extract_illus.py - 阶段一：从 docx 提取插图标记及章节结构。

用法:
    python3 extract_illus.py "手册.docx"                          # 默认标记（插图），打印清单
    python3 extract_illus.py "手册.docx" --marker "【截图】"       # 自定义标记
    python3 extract_illus.py "手册.docx" --json out.json          # 同时输出 JSON
    python3 extract_illus.py "手册.docx" --section 服务管理>应用代理  # 仅打印匹配章节

匹配规则: 段落文本去除全部空白后与标记【完全相等】才算命中（精准匹配，防误操作）。
输出: 每条标记的章节路径（一级>二级>三级）、上下文、序号（0-based，按文档顺序）。
"""
import argparse
import json
import re
import sys
import zipfile
from xml.dom import minidom


def decode_entities(text):
    return re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)


def normalize_level(pstyle_val):
    """归一化标题级别：数字(1/2/3) 或 Heading1/Heading2/Heading3 -> int；非标题返回 None。"""
    if not pstyle_val:
        return None
    if pstyle_val.isdigit():
        return int(pstyle_val)
    m = re.match(r'[Hh]eading(\d+)', pstyle_val)
    if m:
        return int(m.group(1))
    return None


def heading_offsets(body):
    """动态锚定标题级别：取文档所有数字 pStyle val 的最小值作为 H1（相对级别 1）。
    返回 {绝对val: 相对级别}。兼容 Word 自定义样式映射（如 H1=2, H2=3, H3=4）。"""
    vals = set()
    for p in body.getElementsByTagName('w:p'):
        pPr = p.getElementsByTagName('w:pPr')
        if pPr:
            pstyle = pPr[0].getElementsByTagName('w:pStyle')
            if pstyle:
                v = pstyle[0].getAttribute('w:val')
                if v.isdigit():
                    vals.add(int(v))
    if not vals:
        return {}
    min_val = min(vals)
    return {v: v - min_val + 1 for v in vals}


def get_para_text(p):
    """提取段落全部文本（含 w:t 与 w:delText），解码实体。"""
    texts = []
    for tag in ('w:t', 'w:delText'):
        for t in p.getElementsByTagName(tag):
            if t.firstChild:
                texts.append(t.firstChild.nodeValue)
    return decode_entities(''.join(texts))


def extract(docx_path, marker='（插图）'):
    """返回插图清单: [{path: [标题1,标题2,标题3], context: str}, ...]
    精准匹配：段落文本去空白后与 marker 完全相等。"""
    marker_norm = re.sub(r'\s+', '', marker)

    with zipfile.ZipFile(docx_path) as z:
        xml = z.read('word/document.xml')
    dom = minidom.parseString(xml)
    body = dom.getElementsByTagName('w:body')
    if not body:
        raise ValueError('word/document.xml 缺少 w:body')
    body = body[0]

    headings = []  # 标题栈: [(相对级别, text), ...]
    illus = []
    offsets = heading_offsets(body)

    for p in body.getElementsByTagName('w:p'):
        # 标题级别（相对级别）
        level = None
        pPr = p.getElementsByTagName('w:pPr')
        if pPr:
            pstyle = pPr[0].getElementsByTagName('w:pStyle')
            if pstyle:
                abs_level = normalize_level(pstyle[0].getAttribute('w:val'))
                if abs_level is not None:
                    level = offsets.get(abs_level) or (abs_level if abs_level <= 3 else None)

        text = get_para_text(p).strip()

        if level and 1 <= level <= 3 and text:
            headings = [h for h in headings if h[0] < level]
            headings.append((level, text))
        elif text and re.sub(r'\s+', '', text) == marker_norm:
            illus.append({
                'path': [h[1] for h in headings],
                'context': text[:120],
            })

    return illus


def main():
    ap = argparse.ArgumentParser(description='从 docx 提取插图标记及章节结构')
    ap.add_argument('docx', help='文档 docx 路径')
    ap.add_argument('--marker', default='（插图）', help='插图标记文本（默认 （插图）），精准匹配')
    ap.add_argument('--json', help='输出 JSON 文件路径（可选）')
    ap.add_argument('--section', help='按章节路径过滤，如 "服务管理>应用代理"')
    args = ap.parse_args()

    illus = extract(args.docx, args.marker)
    if not illus:
        print(f'未找到任何匹配「{args.marker}」的标记', file=sys.stderr)
        return 1

    section_filter = args.section.split('>') if args.section else None

    matched = []
    for i, item in enumerate(illus):
        path_str = '>'.join(item['path'])
        if section_filter and (item['path'][:len(section_filter)] != section_filter
                               or len(item['path']) < len(section_filter)):
            continue
        matched.append(item)
        print(f'[{i}] {path_str} | {item["context"]}')

    if args.json:
        with open(args.json, 'w', encoding='utf-8') as f:
            json.dump(matched, f, ensure_ascii=False, indent=2)
        print(f'\n已输出 {len(matched)} 条到 {args.json}', file=sys.stderr)

    return 0


if __name__ == '__main__':
    sys.exit(main())
