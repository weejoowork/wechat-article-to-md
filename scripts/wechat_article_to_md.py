#!/usr/bin/env python3
"""
微信公众号文章抓取并转换为 Markdown 文档
"""

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"缺少依赖库: {e}")
    print("请运行: pip install requests beautifulsoup4")
    sys.exit(1)


def sanitize_filename(name):
    """清理文件名中的非法字符"""
    # 替换 Windows/macOS/Linux 非法字符
    illegal_chars = r'[<>:"/\\|?*]'
    name = re.sub(illegal_chars, '_', name)
    # 去除首尾空格和点
    name = name.strip('. ')
    return name or 'article'


# 公众号文章 URL 允许的域名
ARTICLE_HOST = 'mp.weixin.qq.com'
# 图片 CDN 白名单（微信公众号文章内常见图床）
ALLOWED_IMAGE_HOSTS = frozenset({
    'mmbiz.qpic.cn',
    'mmbiz.qlogo.cn',
    'res.wx.qq.com',
    'wx.qlogo.cn',
})


def validate_url(url, for_article=True):
    """校验 URL，防止 SSRF：文章仅允许 mp.weixin.qq.com，图片仅允许微信 CDN 白名单。

    Args:
        url: 待校验的 URL 字符串
        for_article: True 表示文章 URL，False 表示图片 URL

    Returns:
        True 表示通过校验

    Raises:
        ValueError: 校验不通过时，消息描述原因
    """
    if not url or not url.strip():
        raise ValueError('URL 为空')
    parsed = urlparse(url.strip())
    if for_article:
        if parsed.scheme != 'https':
            raise ValueError('文章 URL 必须为 https')
        if (parsed.netloc or '').lower() != ARTICLE_HOST:
            raise ValueError(f'文章 URL 仅允许域名: {ARTICLE_HOST}')
        return True
    # 图片 URL
    if parsed.scheme and parsed.scheme.lower() not in ('http', 'https'):
        raise ValueError('图片 URL 仅允许 http/https')
    host = (parsed.netloc or '').lower()
    if not host:
        raise ValueError('图片 URL 缺少主机名')
    if host not in ALLOWED_IMAGE_HOSTS:
        raise ValueError(f'图片 URL 仅允许以下域名: {", ".join(sorted(ALLOWED_IMAGE_HOSTS))}')
    return True


# 禁止作为输出目录的系统路径前缀（防止写入系统关键目录）
FORBIDDEN_OUTPUT_PREFIXES = [
    Path(p).resolve() for p in (
        '/etc', '/usr', '/bin', '/sbin', '/var', '/tmp',
        '/System', '/Library', '/Applications',
    )
]


def validate_output_path(dir_path, path_name='输出目录'):
    """校验输出路径在当前工作目录下且不在系统目录，防止任意路径写入。

    Args:
        dir_path: 待校验的目录路径（字符串或 Path）
        path_name: 用于错误提示的名称

    Returns:
        解析后的绝对 Path

    Raises:
        ValueError: 路径不在 CWD 下或在禁止的系统目录下
    """
    resolved = Path(dir_path).resolve()
    cwd = Path.cwd().resolve()
    try:
        under_cwd = resolved == cwd or resolved.is_relative_to(cwd)
    except (TypeError, ValueError):
        under_cwd = False
    if not under_cwd:
        raise ValueError(f'{path_name} 必须在当前工作目录下: {resolved}')
    def _path_under(path, prefix):
        try:
            return path == prefix or path.is_relative_to(prefix)
        except ValueError:
            return False

    for forbidden in FORBIDDEN_OUTPUT_PREFIXES:
        if _path_under(resolved, forbidden):
            raise ValueError(f'{path_name} 不能为系统目录或其子目录: {forbidden}')
    return resolved


def download_image(url, img_dir, index, article_id=None):
    """下载图片到本地

    Args:
        url: 图片 URL
        img_dir: 图片保存目录
        index: 图片序号
        article_id: 文章唯一标识，用于生成唯一文件名
    """
    try:
        url = url.strip()
        if url.startswith('//'):
            url = 'https:' + url
        validate_url(url, for_article=False)
    except ValueError as e:
        print(f"  跳过非法图片 URL ({url[:50]}...): {e}")
        return None
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        # 从 URL 中提取文件扩展名
        ext = Path(url).suffix or '.png'
        # 如果 URL 中有参数，提取文件扩展名
        if '?' in ext:
            ext = ext.split('?')[0]
        if not ext or ext == '':
            ext = '.png'

        # 确保扩展名有效
        valid_exts = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
        if ext.lower() not in valid_exts:
            ext = '.png'

        # 使用文章 ID 作为前缀，避免不同文章的图片文件名冲突
        if article_id:
            filename = f"{article_id}_{index:03d}{ext}"
        else:
            filename = f"image_{index:03d}{ext}"
        file_path = img_dir / filename

        file_path.write_bytes(response.content)
        print(f"  下载图片: {filename}")
        return filename
    except Exception as e:
        print(f"  下载图片失败 ({url}): {e}")
        return None


def html_to_markdown(soup, img_dir=None, article_id=None, obsidian_mode=False, article_url=None):
    """将 HTML 内容转换为 Markdown，保持原始元素顺序

    Args:
        soup: BeautifulSoup 对象
        img_dir: 图片保存目录
        article_id: 文章唯一标识，用于生成唯一图片文件名
        obsidian_mode: 是否使用 Obsidian 格式（图片保存到 attachments/img/，使用 ![[filename]]）
        article_url: 原文链接，用于视频提示
    """
    md_content = []
    img_index = 0
    img_map = {}  # URL -> 本地文件名映射
    video_index = 0  # 视频计数器

    # 首先收集所有图片并下载
    if img_dir:
        for img in soup.find_all('img'):
            src = img.get('data-src') or img.get('src', '')
            if src and src not in img_map:
                img_index += 1
                local_img = download_image(src, img_dir, img_index, article_id)
                if local_img:
                    if obsidian_mode:
                        # Obsidian 格式：只需要文件名，不需要路径前缀
                        img_map[src] = local_img
                    else:
                        img_map[src] = f"images/{local_img}"

    # 按照元素在 DOM 中的顺序遍历
    def process_element(element):
        nonlocal md_content
        tag_name = element.name

        # 跳过已处理的元素（在列表、引用等容器内）
        if element.find_parent(['ul', 'ol', 'blockquote', 'li']):
            return

        # 标题
        if tag_name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            level = int(tag_name[1])
            text = element.get_text(strip=True)
            md_content.append(f"{'#' * level} {text}\n")

        # 段落
        elif tag_name == 'p':
            # 处理段落内的内联元素
            content = process_inline_elements(element)
            if content:
                md_content.append(content + "\n")

        # 无序列表
        elif tag_name == 'ul':
            for li in element.find_all('li', recursive=False):
                text = li.get_text(strip=True)
                md_content.append(f"- {text}\n")

        # 有序列表
        elif tag_name == 'ol':
            for i, li in enumerate(element.find_all('li', recursive=False), 1):
                text = li.get_text(strip=True)
                md_content.append(f"{i}. {text}\n")

        # 引用
        elif tag_name == 'blockquote':
            text = element.get_text(strip=True)
            if text:
                md_content.append(f"> {text}\n")

        # 代码块
        elif tag_name == 'pre':
            code = element.get_text()
            md_content.append(f"```\n{code}\n```\n")

        # 分隔线
        elif tag_name == 'hr':
            md_content.append("---\n")

        # 视频（微信视频 iframe）
        elif tag_name == 'iframe':
            nonlocal video_index
            video_index += 1
            md_content.append(f"> 🎥 [视频 {video_index}]\n")
            md_content.append("> 注：微信视频无法在 Markdown 中直接查看\n")
            if article_url:
                md_content.append(f"> 请访问原文观看: {article_url}\n")
            md_content.append("\n")

        # 图片
        elif tag_name == 'img':
            src = element.get('data-src') or element.get('src', '')
            alt = element.get('alt', '')
            if src:
                if src in img_map:
                    if obsidian_mode:
                        md_content.append(f"![[{img_map[src]}]]\n")
                    else:
                        md_content.append(f"![{alt}]({img_map[src]})\n")
                else:
                    md_content.append(f"![{alt}]({src})\n")

        # 处理子元素（对于容器元素）
        for child in element.children:
            if hasattr(child, 'name') and child.name:
                # 跳过已经特殊处理的容器内的元素
                if tag_name not in ['ul', 'ol', 'blockquote', 'li']:
                    process_element(child)

    def process_inline_elements(element):
        """处理段落内的内联元素（粗体、斜体、链接、图片）"""
        parts = []
        for child in element.children:
            if hasattr(child, 'name') and child.name:
                tag_name = child.name

                # 粗体
                if tag_name in ['b', 'strong']:
                    text = child.get_text(strip=True)
                    parts.append(f"**{text}**")

                # 斜体
                elif tag_name in ['i', 'em']:
                    text = child.get_text(strip=True)
                    parts.append(f"*{text}*")

                # 链接
                elif tag_name == 'a':
                    href = child.get('href', '')
                    text = child.get_text(strip=True)
                    if text:
                        parts.append(f"[{text}]({href})")

                # 图片
                elif tag_name == 'img':
                    src = child.get('data-src') or child.get('src', '')
                    alt = child.get('alt', '')
                    if src:
                        if src in img_map:
                            if obsidian_mode:
                                parts.append(f"![[{img_map[src]}]]")
                            else:
                                parts.append(f"![{alt}]({img_map[src]})")
                        else:
                            parts.append(f"![{alt}]({src})")

                # 递归处理其他嵌套元素
                else:
                    result = process_inline_elements(child)
                    if result:
                        parts.append(result)
            else:
                # 文本节点
                text = str(child).strip()
                if text:
                    parts.append(text)

        return ''.join(parts)

    # 从根元素开始遍历
    for element in soup.children:
        if hasattr(element, 'name') and element.name:
            process_element(element)

    return '\n'.join(md_content)


def find_attachments_img_dir(start_path):
    """从起始路径向上查找固定的 attachments/img/ 目录

    Args:
        start_path: 开始查找的路径（通常是 md 文件所在目录或输出目录）

    Returns:
        找到的 attachments/img/ 目录路径，如果没找到则返回 None
    """
    path = Path(start_path).resolve()

    # 向上最多查找 3 层目录
    max_levels = 3
    for level in range(max_levels):
        attachments_dir = path / 'attachments'
        img_dir = attachments_dir / 'img'

        # 检查 attachments/img/ 是否存在，或者可以创建
        # 优先使用已存在的目录
        if img_dir.exists() and img_dir.is_dir():
            return img_dir

        # 检查 attachments/ 目录是否存在
        if attachments_dir.exists() and attachments_dir.is_dir():
            # 尝试创建 img 目录
            img_dir.mkdir(exist_ok=True)
            return img_dir

        # 如果这层不是 attachments/，继续向上查找
        if path.parent == path:  # 已到达根目录
            break
        path = path.parent

    # 如果没找到，尝试在 start_path 的父目录创建
    path = Path(start_path).resolve().parent
    for level in range(max_levels):
        attachments_dir = path / 'attachments'
        img_dir = attachments_dir / 'img'

        if attachments_dir.exists() or level == 0:  # 第一层直接尝试创建
            img_dir.mkdir(parents=True, exist_ok=True)
            return img_dir

        if path.parent == path:
            break
        path = path.parent

    # 最后尝试在 start_path 下方创建（降级方案）
    fallback_img_dir = Path(start_path).resolve() / 'attachments' / 'img'
    fallback_img_dir.mkdir(parents=True, exist_ok=True)
    print(f"  注意: 降级在 {start_path} 下创建图片目录")
    return fallback_img_dir


def fetch_wechat_article(url, output_dir='.', download_images=True, obsidian_mode=False, img_output_dir=None):
    """
    抓取微信公众号文章

    Args:
        url: 微信文章链接
        output_dir: 输出目录（Markdown 文件保存位置）
        download_images: 是否下载图片到本地
        obsidian_mode: 是否使用 Obsidian 格式（图片引用格式 ![[filename]]）
        img_output_dir: 图片保存目录（绝对路径，None 表示相对于 output_dir）
    """
    try:
        output_path = validate_output_path(output_dir)
    except ValueError as e:
        print(f"输出路径校验失败: {e}")
        return
    if img_output_dir is not None:
        try:
            img_output_dir = validate_output_path(img_output_dir, '图片目录')
        except ValueError as e:
            print(f"图片目录校验失败: {e}")
            return

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    }

    try:
        validate_url(url, for_article=True)
    except ValueError as e:
        print(f"URL 校验失败: {e}")
        return

    print(f"正在请求: {url}")
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        response.encoding = 'utf-8'
    except Exception as e:
        print(f"请求失败: {e}")
        return

    soup = BeautifulSoup(response.text, 'html.parser')

    # 获取标题
    title = soup.find('meta', property='og:title')
    if title:
        title = title.get('content', '无标题')
    else:
        title_elem = soup.find('h1', class_='rich_media_title')
        title = title_elem.get_text(strip=True) if title_elem else '无标题'

    print(f"标题: {title}")

    # 获取作者 - 优先从 js_author_name 获取
    author_elem = soup.find(id='js_author_name')
    author = author_elem.get_text(strip=True) if author_elem else None
    if not author:
        # 备用方式：从 rich_media_meta_link 获取
        author_elem = soup.find('a', class_='rich_media_meta_link')
        author = author_elem.get_text(strip=True) if author_elem else '未知作者'
    print(f"作者: {author}")

    # 获取正文内容
    content_div = soup.find('div', class_='rich_media_content') or soup.find('div', id='js_content')
    if not content_div:
        print("未找到文章内容")
        return

    # 创建输出目录（output_path 已在入口校验）
    output_path.mkdir(parents=True, exist_ok=True)

    # 创建图片目录
    img_dir = None
    article_id = None
    if download_images:
        if img_output_dir is not None:
            # 使用指定的绝对路径作为图片目录（已在入口校验）
            img_dir = img_output_dir
            img_dir.mkdir(parents=True, exist_ok=True)
            print(f"创建图片目录: {img_dir.absolute()}/")
        elif obsidian_mode:
            # Obsidian 模式：向上查找固定的 attachments/img/ 目录
            img_dir = find_attachments_img_dir(output_dir)
            print(f"使用固定图片目录: {img_dir.relative_to(Path.cwd()) if img_dir.is_relative_to(Path.cwd()) else img_dir}/")
        else:
            # 普通模式：保存到 images/
            img_dir = output_path / 'images'
            img_dir.mkdir(exist_ok=True)
            print("创建图片目录: images/")
        # 使用清理后的标题作为文章唯一标识
        article_id = sanitize_filename(title)

    # 构建 Markdown
    md_lines = []
    md_lines.append(f"# {title}\n")
    md_lines.append(f"**作者**: {author}\n")
    md_lines.append(f"**来源**: {url}\n")
    md_lines.append("---\n\n")

    # 转换正文
    body_md = html_to_markdown(content_div, img_dir, article_id, obsidian_mode, url)
    md_lines.append(body_md)

    md_content = '\n'.join(md_lines)

    # 保存文件
    filename = sanitize_filename(title) + '.md'
    file_path = output_path / filename

    file_path.write_text(md_content, encoding='utf-8')
    print(f"\n保存成功: {file_path.absolute()}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python wechat_article_to_md.py <微信文章URL> [输出目录] [选项]")
        print("选项:")
        print("  -obsidian     使用 Obsidian 格式（图片引用格式 ![[filename]]）")
        print("  -img-dir DIR  指定图片保存目录（绝对路径，优先于默认位置）")
        print("示例:")
        print("  python wechat_article_to_md.py https://mp.weixin.qq.com/s/B5hK8BywPla6LG3hVxHGqA")
        print("  python wechat_article_to_md.py https://mp.weixin.qq.com/s/B5hK8BywPla6LG3hVxHGqA . -obsidian")
        print("  python wechat_article_to_md.py https://mp.weixin.qq.com/s/B5hK8BywPla6LG3hVxHGqA . -obsidian -img-dir /attachments/img")
        sys.exit(1)

    url = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].upper().startswith('-') else '.'
    obsidian_mode = any(arg.upper() == '-OBSIDIAN' for arg in sys.argv)

    # 解析 -img-dir 参数
    img_output_dir = None
    for i, arg in enumerate(sys.argv):
        if arg.upper() == '-IMG-DIR' and i + 1 < len(sys.argv):
            img_output_dir = sys.argv[i + 1]
            break

    fetch_wechat_article(url, output_dir, True, obsidian_mode, img_output_dir)