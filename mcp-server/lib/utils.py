"""工具函数 — 字符串转义、选择器解析、值提取、路径处理"""
import json, os, re, io, sys

# 强制 stdout/stderr 为 UTF-8，无缓冲写入
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', write_through=True)


def load_mapping(site):
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'mappings', f"{site}.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def js_escape(s):
    """将字符串转义为 JS 字符串字面量（双引号包裹时安全）。
    
    转义字符: \\, ", ', \n, \r, \t 和控制字符。
    非 ASCII (Unicode) 保持原样（CDP eval 支持 UTF-8 编码）。
    """
    escaped = []
    for c in s:
        if c == '\\':
            escaped.append('\\\\')
        elif c == '"':
            escaped.append('\\"')
        elif c == "'":
            escaped.append("\\'")
        elif c == '\n':
            escaped.append('\\n')
        elif c == '\r':
            escaped.append('\\r')
        elif c == '\t':
            escaped.append('\\t')
        elif ord(c) < 0x20 or (ord(c) > 0x7e and ord(c) < 0xa0):
            escaped.append(f'\\x{ord(c):02x}')
        else:
            escaped.append(c)
    return ''.join(escaped)


def resolve_selector(target, sel_spec):
    if sel_spec.startswith('placeholder:'):
        kw = sel_spec[len('placeholder:'):]
        return f'input[placeholder*="{js_escape(kw)}"]'
    if sel_spec.startswith('index:'):
        idx = sel_spec[len('index:'):]
        return f"document.querySelectorAll('input[placeholder]')[{idx}]"
    return sel_spec


def extract_value(task, source):
    if source == 'product.name':
        return task.get('product', {}).get('name', '')
    if source == 'product.code':
        return task.get('product', {}).get('code', '')
    if source.startswith('params_sum:'):
        # 求和所有匹配关键词的 params 数值（用于空调内机+外机毛重）
        keyword = source[11:]
        total = 0.0
        for p in task.get('product', {}).get('params', []):
            key = p.get('key', '')
            if keyword in key:
                val = str(p.get('value', '0'))
                nums = re.findall(r'[\d.]+', val)
                if nums:
                    total += float(nums[0])
        return str(total) if total > 0 else ''
    if source.startswith('params.'):
        key = source[7:]
        for p in task.get('product', {}).get('params', []):
            if p.get('key') == key:
                return p.get('value', '')
        return ''
    if source.startswith('const:'):
        return source[6:]
    return ''


def get_local_paths(task, img_type, max_n):
    """读取分目录缓存: images_mainThumb_local / images_detail_local"""
    if img_type == 'mainThumb':
        paths = task.get('images_mainThumb_local', [])
    elif img_type == 'detail':
        paths = task.get('images_detail_local', [])
    else:
        # 兼容旧格式 images_local
        images_local = task.get('images_local', [])
        main_count = len(task.get('images_mainThumb', []))
        if img_type == 'mainThumb':
            paths = images_local[:min(main_count, max_n)]
        else:
            paths = images_local[main_count:main_count + max_n]
    return paths[:max_n]
