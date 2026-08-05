# docx-illustration（文档自动化配图）

将「文档 → GUI 截图 → 插回文档」配图工作流自动化的 Agent Skill，四阶段闭环：

1. **提取**：从 docx 提取插图标记（默认 `（插图）`，支持 `--marker` 自定义标记精准匹配）及章节目录结构
2. **映射**：将目录结构映射为 GUI 菜单层级（一级/二级/三级菜单）生成截图清单
3. **截图**：Playwright 登录系统（可选，需精确 `loginUrl`，建议关闭验证码）按截图范围要求完成完整长截图；前端框架自动适配（ElementUI / Ant Design / layui / 原生 HTML），支持用户主动声明与被动探测
4. **插入**：以修订模式（tracked changes）将截图插入对应章节标记处并替换标记，图片宽度按页面可用区域（`pgSz - pgMar`）自适应缩放，保证充满不溢出

## 用法

```bash
# 阶段一：提取插图标记与章节结构
python3 scripts/extract_illus.py "手册.docx" --json /tmp/illus.json

# 阶段二：生成截图清单（screenshot-config.json 的 targets）

# 阶段三：Playwright 截图（需 npm install playwright）
node scripts/screenshot.js screenshot-config.json

# 阶段四：修订模式插入（依赖 docx skill 的 Document 库）
PYTHONPATH=<docx-skill根目录> python3 scripts/insert_screenshots.py \
    --source "手册.docx" --images screenshot/ --mapping mapping.json
```

## 目录结构

```
SKILL.md                          # 工作流主文档
scripts/
├── extract_illus.py              # 阶段一：提取标记+章节结构（自定义标记精准匹配）
├── screenshot.js                 # 阶段三：Playwright 截图（框架自适应/登录可选）
├── screenshot-config.json        # 截图配置模板
└── insert_screenshots.py         # 阶段四：修订模式插入+宽度自适应缩放
```

## 关键特性

- 插图标记可自定义，段落级精准匹配（去空白完全相等），防止误替换正文
- 标题级别动态锚定，兼容 Word 自定义样式映射（H1/H2/H3 不依赖固定 styleId）
- 支持标记被 Word 拆分为多个 run 的段落（逐 run 删除 + 段尾插图）
- 截图区域裁剪排除底栏（版权/操作按钮），多轮滚动触发懒加载保证完整长截图
- 登录可选：无登录态系统直接导航，登录系统需提供精确登录页 URL
