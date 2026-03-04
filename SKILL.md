---
name: wechat-article-to-md
description: 抓取微信公众号文章并转换为 Markdown 文档。使用脚本自动获取文章标题、作者、正文内容，保留格式并保存为 .md 文件，支持下载图片到本地。适用场景：用户要求抓取/获取/下载/保存微信公众号文章内容为 Markdown 格式，或给出 mp.weixin.qq.com 链接需要提取内容。支持 Obsidian 模式（使用 -obsidian 参数）。
---

# 微信公众号文章转 Markdown

抓取微信公众号文章并将其转换为 Markdown 文档。

## 执行环境（可选 venv）

从**项目根目录**执行本 skill 的脚本。选择 Python 解释器时：

- 若项目根下存在 **`.venv`** 或 **`venv`** 目录，则使用该虚拟环境中的 Python：  
  **`.venv/bin/python`** 或 **`venv/bin/python`**
- 否则使用系统 **`python3`**

脚本路径（任选其一，视 skill 部署位置而定）：

- skill 在项目内（如 `.claude/skills/wechat-article-to-md/`）时：  
  **`.claude/skills/wechat-article-to-md/scripts/wechat_article_to_md.py`**
- 在 skill 目录下执行时：  
  **`scripts/wechat_article_to_md.py`**

## 快速使用

### 普通模式
```bash
# 基本用法（自动下载图片）。若项目根有 .venv 或 venv，请将 python3 改为 .venv/bin/python 或 venv/bin/python
python3 .claude/skills/wechat-article-to-md/scripts/wechat_article_to_md.py <文章URL>
# 或从 skill 目录执行：
# python3 scripts/wechat_article_to_md.py <文章URL>

# 指定输出目录
python3 .claude/skills/wechat-article-to-md/scripts/wechat_article_to_md.py <文章URL> <输出目录>
```

**图片保存位置**: `images/`
**图片引用格式**: `![alt](images/filename.png)`

### Obsidian 模式
```bash
# 使用 Obsidian 格式（同上，如有 .venv/venv 则用其 python）
python3 .claude/skills/wechat-article-to-md/scripts/wechat_article_to_md.py <文章URL> [输出目录] -obsidian
```

**图片保存位置**: `attachments/img/`（向上查找固定的目录，可能位于输出目录的上级或更上级）
**图片引用格式**: `![[filename.png]]`

## 输出内容

脚本会自动提取并保存：

- **标题**: 文章主标题
- **作者**: 公众号作者名称
- **来源**: 原文链接
- **正文**: 完整内容，转换为 Markdown 格式
  - 标题层级 (h1-h6)
  - 粗体、斜体
  - 列表（有序/无序）
  - 链接
  - 图片（保留图片链接）
  - 代码块
  - 引用块

## 文件命名

输出文件名自动使用文章标题，文件名中的非法字符会被自动替换为下划线。

## 脚本位置

可执行脚本位于 `scripts/wechat_article_to_md.py`（在 skill 目录内）。从项目根执行时路径为 `.claude/skills/wechat-article-to-md/scripts/wechat_article_to_md.py`。优先使用项目根下的 `.venv` 或 `venv` 中的 Python。