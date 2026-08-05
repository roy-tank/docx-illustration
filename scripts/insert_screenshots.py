#!/usr/bin/env python3
"""insert_screenshots.py - 阶段四：修订模式插入截图 + 宽度自适应缩放。

用法:
    PYTHONPATH=<docx-skill根目录> python3 insert_screenshots.py \
        --source "手册.docx" \
        --images screenshot/ \
        --mapping mapping.json \
        [--marker "（插图）"] \
        [--output "demo-手册.docx"]

依赖: docx skill 的 Document 库（scripts/document.py），需 PYTHONPATH 指向 docx skill 根目录。
       PIL (Pillow)。

mapping.json 格式（由阶段一/二生成）:
    [
      {"path": ["服务管理", "应用代理", "配置管理"], "image": "7.1.1-配置管理.png", "index": 0},
      {"path": ["系统管理", "系统信息", "资源监控"], "image": "11.1.4-资源监控.png"}
    ]

说明:
    - 源文档不改动；输出副本（未指定 --output 时自动加 "demo-" 前缀）
    - 标记可自定义（--marker，默认 （插图）），必须与阶段一提取时一致；精准匹配
      （段落文本去空白后完全相等），防止误替换正文中含标记字样的话
    - 修订模式: <w:del> 删除标记文本 + <w:ins> 插入 <w:drawing> 图片
    - 宽度自适应: 从 w:sectPr 读取 w:pgSz / w:pgMar 计算可用宽度（1 twip = 635 EMU），
      图片等比缩放充满可用区域且不溢出右边界
    - 定位目标按"章节路径"匹配（勿用行号，插入会致行号漂移）
"""
import argparse
import json
import os
import re
import shutil
import sys
import subprocess
import tempfile
import zipfile
from xml.dom import minidom

from PIL import Image


def decode_entities(text):
    return re.sub(r'&#(\d+);', lambda m: chr(int(m.group(1))), text)


def normalize_level(pstyle_val):
    if not pstyle_val:
        return None
    if pstyle_val.isdigit():
        return int(pstyle_val)
    m = re.match(r'[Hh]eading(\d+)', pstyle_val)
    return int(m.group(1)) if m else None


def heading_offsets(body):
    """动态锚定标题级别：取文档所有数字 pStyle val 的最小值作为 H1（相对级别 1）。
    返回 {绝对val: 相对级别}。与 extract_illus.py 保持一致，保证两阶段路径一致。"""
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
    texts = []
    for tag in ('w:t', 'w:delText'):
        for t in p.getElementsByTagName(tag):
            if t.firstChild:
                texts.append(t.firstChild.nodeValue)
    return decode_entities(''.join(texts))


def unpack_to_temp(docx_path):
    """解包 docx 到临时目录，返回目录路径。"""
    tmp = tempfile.mkdtemp(prefix='docx_edit_')
    with zipfile.ZipFile(docx_path) as z:
        z.extractall(tmp)
    return tmp


def find_illus_with_paths(dom, marker='（插图）'):
    """遍历所有段落，返回标记列表:
    [{node: <w:p> 段落, path: [标题1,...], runs: [<w:r> 含文本的run]}, ...]
    精准匹配：段落文本去空白后与 marker 完全相等（与 extract_illus.py 一致，
    保证阶段一/四计数一致）。段落内标记可能被 Word 拆成多个 run。"""
    marker_norm = re.sub(r'\s+', '', marker)
    illus = []
    headings = []
    offsets = heading_offsets(dom.getElementsByTagName('w:body')[0])
    for p in dom.getElementsByTagName('w:p'):
        level = None
        pPr = p.getElementsByTagName('w:pPr')
        if pPr:
            pstyle = pPr[0].getElementsByTagName('w:pStyle')
            if pstyle:
                abs_level = normalize_level(pstyle[0].getAttribute('w:val'))
                if abs_level is not None:
                    level = offsets.get(abs_level) or (abs_level if abs_level <= 3 else None)
        text = get_para_text(p)
        if level and 1 <= level <= 3 and text.strip():
            headings = [h for h in headings if h[0] < level]
            headings.append((level, text.strip()))
        elif text and re.sub(r'\s+', '', text) == marker_norm:
            runs = [r for r in p.getElementsByTagName('w:r')
                    if r.getElementsByTagName('w:t')]
            illus.append({'node': p, 'path': [h[1] for h in headings], 'runs': runs})
    return illus


def replace_paragraph_with_image(editor, p_node, ins_xml):
    """段落级替换：将段落内每个含文本的 run 删除（w:del，保留原文以便校验恢复），
    再在段落末尾插入图片（w:ins）。支持标记被拆成多个 run 的情况。"""
    runs = [r for r in p_node.getElementsByTagName('w:r')
            if r.getElementsByTagName('w:t')]
    last_del = None
    for r in runs:
        rtext = ''.join(
            t.firstChild.nodeValue for t in r.getElementsByTagName('w:t')
            if t.firstChild)
        # 转实体（保持与原文一致，便于校验回退）
        rtext_entity = ''.join(f'&#{ord(c)};' for c in rtext)
        rpr = ''
        rpr_tags = r.getElementsByTagName('w:rPr')
        if rpr_tags:
            rpr = rpr_tags[0].toxml()
        del_xml = f'<w:del><w:r>{rpr}<w:delText>{rtext_entity}</w:delText></w:r></w:del>'
        nodes = editor.replace_node(r, del_xml)
        last_del = nodes[-1]
    if last_del is not None:
        editor.insert_after(last_del, ins_xml)
        return True
    return False


def get_usable_width_emu(dom):
    """从 sectPr 计算可用宽度（EMU）。A4 常见: 11906-1800-1800=8306 twips * 635 = 5274310 EMU。"""
    for s in dom.getElementsByTagName('w:sectPr'):
        pgSz = s.getElementsByTagName('w:pgSz')
        pgMar = s.getElementsByTagName('w:pgMar')
        if pgSz and pgMar:
            w = int(pgSz[0].getAttribute('w:w'))
            left = int(pgMar[0].getAttribute('w:left'))
            right = int(pgMar[0].getAttribute('w:right'))
            usable = (w - left - right) * 635
            if usable > 0:
                return int(usable / 1000) * 1000  # 向下取整留余量
    return int(6.0 * 914400)  # 兜底


def ensure_png_content_type(ct_editor):
    defaults = ct_editor.dom.documentElement.getElementsByTagName('Default')
    if not any(e.getAttribute('Extension') == 'png' for e in defaults):
        ct_editor.append_to(ct_editor.dom.documentElement,
                            '<Default Extension="png" ContentType="image/png"/>')


def make_image_ins_xml(rid, docpr, img_name, width_emu, height_emu):
    """生成图片插入 XML（w:ins 包裹 drawing），供 replace_paragraph_with_image 使用。"""
    return f'''<w:ins>
  <w:r>
    <w:drawing>
      <wp:inline distT="0" distB="0" distL="0" distR="0">
        <wp:extent cx="{width_emu}" cy="{height_emu}"/>
        <wp:docPr id="{docpr}" name="Picture {docpr}"/>
        <a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
            <pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">
              <pic:nvPicPr><pic:cNvPr id="{docpr}" name="{img_name}"/><pic:cNvPicPr/></pic:nvPicPr>
              <pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>
              <pic:spPr><a:xfrm><a:ext cx="{width_emu}" cy="{height_emu}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>
            </pic:pic>
          </a:graphicData>
        </a:graphic>
      </wp:inline>
    </w:drawing>
  </w:r>
</w:ins>'''


def match_target(all_illus, target):
    """按章节路径 + index 匹配标记节点。"""
    path, idx = target.get('path'), target.get('index', 0)
    candidates = [it for it in all_illus
                  if it['path'][:len(path)] == path and len(it['path']) >= len(path)]
    if idx >= len(candidates):
        raise ValueError(f'章节 {" > ".join(path)} 下第 {idx} 个标记不存在（共 {len(candidates)} 个）')
    return candidates[idx]['node']


def main():
    ap = argparse.ArgumentParser(description='修订模式插入截图并自适应缩放')
    ap.add_argument('--source', required=True, help='源 docx（不改动）')
    ap.add_argument('--images', required=True, help='截图目录')
    ap.add_argument('--mapping', required=True, help='mapping.json（path/image/index）')
    ap.add_argument('--marker', default='（插图）', help='插图标记文本（默认 （插图）），须与阶段一一致')
    ap.add_argument('--output', help='输出 docx（默认源文件同目录 demo- 前缀）')
    ap.add_argument('--author', default='Editor', help='修订作者名')
    args = ap.parse_args()

    with open(args.mapping, encoding='utf-8') as f:
        targets = json.load(f)

    output = args.output or os.path.join(
        os.path.dirname(args.source), 'demo-' + os.path.basename(args.source))
    shutil.copy(args.source, output)
    print(f'副本: {output}')

    workdir = unpack_to_temp(output)
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'docx'))
        from scripts.document import Document
        doc = Document(workdir, author=args.author, initials='ED', track_revisions=True)
        dom = doc['word/document.xml'].dom
        editor = doc['word/document.xml']

        media_dir = os.path.join(workdir, 'word/media')
        os.makedirs(media_dir, exist_ok=True)

        rels = doc['word/_rels/document.xml.rels']
        next_rid = int(re.match(r'rId(\d+)', rels.get_next_rid()).group(1))
        ensure_png_content_type(doc['[Content_Types].xml'])

        usable_w = get_usable_width_emu(dom)
        print(f'可用宽度: {usable_w} EMU ({usable_w / 914400:.3f} in)')

        all_illus = find_illus_with_paths(dom, args.marker)
        print(f'文档共 {len(all_illus)} 处「{args.marker}」标记')

        # 倒序处理，避免替换后对后续节点引用失效的边界影响
        for target in reversed(targets):
            img_name = target['image']
            img_src = os.path.join(args.images, img_name)
            if not os.path.exists(img_src):
                print(f'  [SKIP] 图片不存在: {img_src}')
                continue

            node = match_target(all_illus, target)
            section = '>'.join(target['path'])

            # 拷贝图片并计算等比尺寸
            media_name = f'pua_screenshot_{len(targets) - targets.index(target)}.png'
            shutil.copy(img_src, os.path.join(media_dir, media_name))
            with Image.open(os.path.join(media_dir, media_name)) as im:
                cx = usable_w
                cy = int(cx * im.size[1] / im.size[0])

            rid = f'rId{next_rid}'; next_rid += 1
            docpr = next_rid; next_rid += 1
            rels.append_to(rels.dom.documentElement,
                f'<Relationship Id="{rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{media_name}"/>')

            ins_xml = make_image_ins_xml(rid, docpr, media_name, cx, cy)
            replace_paragraph_with_image(editor, node, ins_xml)
            print(f'  [{section}] 插入 {media_name} ({cx}x{cy} EMU, RID={rid})')

        doc.save(validate=False)  # 文档可能存在历史空白字符问题，保存后仍用 pandoc 验证
        print(f'\n已写入临时目录，打包中...')
        return workdir, output
    except Exception:
        shutil.rmtree(workdir, ignore_errors=True)
        raise


if __name__ == '__main__':
    workdir, output = main()
    pack_script = os.path.join(os.path.dirname(__file__), '..', '..', 'docx', 'ooxml', 'scripts', 'pack.py')
    subprocess.run([sys.executable, pack_script, workdir, output], check=True)
    shutil.rmtree(workdir, ignore_errors=True)
    print(f'\n完成: {output}')
