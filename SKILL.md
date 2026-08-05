---
name: docx-illustration
description: 文档自动化配图工作流：从 docx 提取指定「插图标记」（默认「（插图）」，支持自定义）及章节结构，映射为 GUI 菜单层级清单，用 Playwright 登录系统（可选）完成完整截图，再以修订模式（tracked changes）插入并自适应缩放。前端框架自动适配（ElementUI/Antd/layui/原生 HTML 等）。触发词：文档配图、手册配图、截图插入、截图工作流。
license: Apache License 2.0
---

# 文档自动化配图（docx-illustration）

将"文档 → GUI 截图 → 插回文档"的配图工作流自动化，四阶段闭环：

```
docx 源文件
  → ① 提取「插图标记」（可自定义，默认 （插图））+ 章节目录结构
  → ② 目录结构映射为 GUI 菜单层级 → 截图清单
  → ③ Playwright 登录系统（可选），按截图范围要求完整截图
  → ④ 修订模式插入图片（替换标记）+ 宽度自适应缩放
```

## 阶段一：提取插图标记与章节结构

**输入**：文档 docx（如"××管理维护手册-版本.docx"）+ 标记文本（默认 `（插图）`）
**输出**：插图清单，每条含：章节路径（一级>二级>三级）、上下文段落、插图序号

1. 用 pandoc 将 docx 转 markdown，快速定位章节标题与标记行：
   ```bash
   pandoc "手册.docx" -o /tmp/guide.md
   grep -n "^#\|（插图）" /tmp/guide.md
   ```
   （标记为自定义时，替换 grep 中的 `（插图）` 为用户标记）
2. 确定目标章节边界（标题1/2/3 的行号区间），列出区间内所有标记。
3. 精细提取（XML 级，供插入阶段使用）：`scripts/extract_illus.py` 直接从 docx（zip）解析
   `word/document.xml`，按 `w:pStyle` 级别维护标题栈，输出每条标记的章节路径与上下文。
   ```bash
   python3 scripts/extract_illus.py "手册.docx" --marker "（插图）" --json /tmp/illus.json
   ```

**技术要点**：
- **标记可自定义**：通过 `--marker` 参数指定，如 `【截图】`、`[图]` 等。
- **精准匹配（防误操作）**：段落文本去除全部空白后与标记**完全相等**才算命中，绝不用
  子串/模糊匹配，避免把正文中含标记字样的话误判为插图位。
- 标记在 document.xml 中可能编码为数字实体（如 `&#65288;&#25554;&#22270;&#65289;`），
  解析时统一先解码实体再比较。
- 标题级别：`w:pStyle w:val` 可能为数字（1/2/3）或 `Heading1/2/3`，需归一化映射。

## 阶段二：目录结构 → GUI 菜单层级 → 截图清单

| 文档标题 | GUI 元素 | 说明 |
|---------|---------|------|
| 标题1（#） | 一级菜单 | 左侧导航栏，树状结构，默认收起，点击展开/收起二级 |
| 标题2（##） | 二级菜单 | 点击一级菜单后展开 |
| 标题3（###） | 三级菜单 | Tab 页签，位于主内容区面包屑下方；非所有二级都有 |

- 三级菜单（若有）为内容区内的链接/Tab，点击后 URL 通常变化，可作导航成功验证。
- 生成截图清单（须含章节号 + 末级菜单名，如 `7.1.1-配置管理`），作为阶段三 targets。

## 阶段三：Playwright 截图

**截图范围要求**：主内容区面包屑下方起始（不含面包屑）至底栏信息区结束（不含底栏/版权/操作按钮）。

### 登录（可选）

不是每个系统都需要登录。仅在目标系统有登录态要求时启用：

- 配置 `loginUrl`：**用户必须提供精确的登录页 URL**（如 `https://host:port/login`），
  直接 `goto` 该地址定位到确切登录页面，避免在首页跳转中迷失。
- 登录方式（按实际系统选择其一，或都配置）：
  - HTTP Basic：`httpAuth: { username, password }`（配合 `ignoreHTTPSErrors: true`）；
  - 表单口令：`formAuth: { username, password }`，`fill` 用户名/密码后按 `Enter` 提交
    （部分系统登录页无 `<button>`，回车触发）。
- **验证码建议**：文字/图形验证码会阻塞自动化。若系统支持，建议提前在系统配置中
  关闭验证码校验；若无法关闭，需人工介入或跳过该目标并提示。
- 不需要登录的系统：配置 `loginUrl: null`，脚本跳过登录直接导航到目标页面。

### 前端框架自适应（重要）

Playwright 定位策略随目标系统前端框架变化，必须二选一：

1. **用户主动输入**（优先）：用户在配置中声明 `framework` 字段或在对话中说明前端框架
   （如 elementui / antd / layui / vanilla / vue / react），直接按对应策略执行。
2. **Playwright 被动探测**（未声明时）：页面加载后 `page.evaluate` 检测框架特征，输出探测
   结果到日志供人工核对，再按结果选择定位策略。

探测特征对照：

| 特征 | 判定框架 |
|------|---------|
| `.el-menu` / `.el-tabs` / `#app.__vue__` / `__vue_app__` | elementui（Vue） |
| `.ant-menu` / `.ant-tabs` / `[data-reactroot]` | antd（React/Vue） |
| `.layui-nav` / `.layui-tab` / `layui` 全局对象 | layui |
| `dl.menu_left` / `dl > dt > dd` 结构 | vanilla（原生 HTML） |

选择器策略对照表（定位一级/二级/三级菜单）：

| 框架 | 一级菜单 | 二级菜单 | 三级（Tab/链接） |
|------|---------|---------|-----------------|
| vanilla | `dl dt:has-text("服务管理")` | `dl dd a:has-text("应用代理")` | 内容区 `a:has-text("公共参数")` |
| elementui | `.el-submenu__title:has-text("…")` | `.el-menu-item:has-text("…")` | `.el-tabs__item:has-text("…")` |
| antd | `.ant-menu-submenu-title:has-text("…")` | `.ant-menu-item:has-text("…")` | `.ant-tabs-tab:has-text("…")` |
| layui | `.layui-nav-item:has-text("…")` | `.layui-nav-child a:has-text("…")` | `.layui-tab-title li:has-text("…")` |

若探测失败（无法识别框架），回退 vanilla 通用策略并输出 warning，由人工确认选择器。

### 关键实现点

1. **完整长截图**：滚动主内容容器（常见类名 `.rightContentScrollArea`，可配置），多轮滚动触发
   懒加载（滚动到底→回顶部），再按 `内容scrollHeight + 底栏高度 + 顶栏偏移` 动态调整视口高度。
2. **排除底栏**：探测底栏元素（候选选择器 `.bottomCopy` / `.bottom-bar` / `.footer` /
   `[class*="copyright"]` 等，取首个可见），用 `page.screenshot({ clip })` 裁剪
   `clipBottom = 底栏元素.top - 内容区.top`。
3. **命名与目录**：`章节号-末级菜单名称.png`，保存到 `<工作目录>/screenshot/`。

## 阶段四：修订模式插入 + 自适应缩放

1. **源文档不改动**：先复制副本（文件名带 `demo` 前缀），在副本上操作。
2. 解包：`python ooxml/scripts/unpack.py 副本.docx 目录`（依赖 docx skill）。
3. 用 docx skill 的 Document 库，`track_revisions=True`：
   - 定位目标标记所在 `<w:r>`（按章节路径匹配，勿用原始行号）；
   - 替换为 `<w:del>`（删除标记文本）+ `<w:ins>`（插入 `<w:drawing>` 图片）；
   - 图片拷贝到 `word/media/`，在 `document.xml.rels` 注册 image 关系，
     `[Content_Types].xml` 声明 png。
4. **标记一致性**：插入脚本的 `--marker` 必须与阶段一提取时的标记完全一致（精准匹配）。
5. **宽度自适应（防溢出）**：从 `w:sectPr` 读取 `w:pgSz` 与 `w:pgMar`：
   `可用宽(twips) = pgSz.w - pgMar.left - pgMar.right`，1 twip = 635 EMU；
   图片 `cx = 可用宽 × 635`（向下取整留余量），`cy = cx × 原高/原宽`，等比缩放充满不溢出。
6. 保存：`doc.save(输出目录, validate=False)`（文档可能存在历史空白字符校验问题，非本次改动引入）。
7. 打包：`python ooxml/scripts/pack.py 输出目录 副本.docx`。
8. **验证闭环**：`pandoc --track-changes=all 副本.docx`，检查每个目标章节处出现
   `[（插图）]{.deletion ...}[![](media/xxx.png)...]{.insertion ...}`。

## 关键经验（Gotchas）

1. **行号漂移**：每次 `replace_node` 后 document.xml 行号变化。多目标插入时按"文档末尾→开头"
   倒序处理，或一次性用 DOM 收集全部目标节点，按章节路径匹配后逐个替换。
2. **DOM 索引 ≠ 原始行号索引**：`getElementsByTagName('w:r')` 的匹配数（含 `w:delText` 等）
   可能与原始文件 grep 行号数不一致。定位目标必须用"所属章节路径"确认，不能盲信行号/序号。
3. **精准匹配**：标记匹配必须"去空白后完全相等"，防止把正文中含标记字样的话误判为插图位。
4. **多匹配**：`get_node` 要求唯一匹配，多匹配抛错；先收集全部匹配再按章节映射。
5. **截图懒加载**：长表格/图表页需多轮滚动等待（每步 600-800ms），再滚动回顶部截图。
6. **底栏排除**：主内容区底部的版权/操作按钮通过 clip 裁剪，不要用整元素截图。
7. **校验失败不 panic**：`validate=False` 仅在文档自身已存在空白字符问题时使用
   （如 `\xa0` 缺 `xml:space='preserve'`），保存后仍用 pandoc 做内容级验证。
8. **框架探测失败**：回退 vanilla 策略并输出 warning，明确告知用户"请主动声明前端框架"。
9. **登录非必需**：无登录态的系统配置 `loginUrl: null` 直接导航；需登录的系统务必提供
   精确 `loginUrl`，并优先关闭验证码。

## 产物模板（scripts/）

- `extract_illus.py`：阶段一自动提取（`--marker` 自定义标记 + 精准匹配 + 章节路径 + 序号，输出 JSON）
- `screenshot.js`：阶段三 Playwright 截图（登录可选/框架探测/导航/滚动/裁剪/命名，
  配置见 `screenshot-config.json` 模板，`framework` 字段支持用户主动声明）
- `insert_screenshots.py`：阶段四插入（`--marker` 与阶段一保持一致 + 章节路径匹配 + 动态宽度计算）
