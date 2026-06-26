"""解析 pending 映射队列 — 独立脚本
功能: 
1. 读取 pending_mappings.json 中的未决条目
2. 对类目条目：从 Excel 类目表 + LLM 选最佳匹配 → 自动写入 jd_category_kw.json
3. 对字段条目：记录到 unmapped_fields.json 供手动处理

用法: 
  python scripts/resolve_mappings.py
  python scripts/resolve_mappings.py --dry-run   # 只预览不写入
"""
import json, os, sys, time, re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAPPINGS_DIR = os.path.join(BASE_DIR, 'mappings')
PENDING_FILE = os.path.join(MAPPINGS_DIR, 'pending_mappings.json')
CATEGORY_FILE = os.path.join(MAPPINGS_DIR, 'jd_category_kw.json')
UNMAPPED_FILE = os.path.join(MAPPINGS_DIR, 'unmapped_fields.json')

# ====== LLM 配置 (从 config.json 读取, 可随时修改) ======
CONFIG_FILE = os.path.join(MAPPINGS_DIR, 'config.json')

def _load_llm_config():
    """从 config.json > llm 读取 LLM API 配置; api_url 为空则不调用 LLM"""
    default = {"api_url": "", "api_key": "", "model_id": ""}
    if not os.path.exists(CONFIG_FILE):
        print(f"  [LLM config] {CONFIG_FILE} 不存在, LLM 功能已禁用", flush=True)
        return default
    try:
        with open(CONFIG_FILE, encoding='utf-8') as f:
            root = json.load(f)
        cfg = root.get('llm', default)
        api_url = cfg.get('api_url', '').strip()
        if not api_url:
            print(f"  [LLM config] api_url 为空, LLM 功能已禁用", flush=True)
        return cfg
    except Exception as e:
        print(f"  [LLM config] 读取失败: {e}", flush=True)
        return default

_LLM_CONFIG = _load_llm_config()
LLM_API_URL = _LLM_CONFIG.get('api_url', '').strip()
LLM_API_KEY = _LLM_CONFIG.get('api_key', '').strip()
LLM_MODEL_ID = _LLM_CONFIG.get('model_id', '').strip()
_LLM_AVAILABLE = bool(LLM_API_URL)

def load_json(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def save_json(path, data):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def call_llm(prompt):
    """调用 LLM API，返回 response JSON；API 为空时直接返回 None"""
    if not _LLM_AVAILABLE:
        print(f"    [LLM skip] api_url 为空, 跳过 LLM 调用", flush=True)
        return None
    import urllib.request
    body = json.dumps({
        "model": LLM_MODEL_ID,
        "messages": [
            {"role": "system", "content": "You are a JD/Meituan category expert. Reply JSON only."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 800,
        "temperature": 0
    }).encode()
    req = urllib.request.Request(LLM_API_URL, data=body, method='POST')
    req.add_header('Authorization', f'Bearer {LLM_API_KEY}')
    req.add_header('Content-Type', 'application/json')
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read().decode())
        print(f"    [LLM ok] tokens={result.get('usage',{}).get('total_tokens','?')}")
        sys.stdout.flush()
        return result
    except Exception as e:
        print(f"    [LLM error] {e}")
        sys.stdout.flush()
        return None

def resolve_category(item, dry_run):
    """用 LLM 解析类目 pending 条目；API 为空时跳过"""
    if not _LLM_AVAILABLE:
        print(f"\n  [{item['id']}] ⏭️ 跳过类目解析 (LLM 不可用): {item.get('product_name','')[:40]}")
        return None
    p_name = item['product_name']
    print(f"\n  [{item['id']}] 解析类目: {p_name[:40]}")
    
    # 从 display 推断可能的关键词
    display = item.get('display', '')
    note = item.get('note', '')
    if note:
        print(f"    备注: {note}")
    
    # 构造 LLM prompt
    prompt = (
        f"Product name: {p_name}\n"
        f"Suggested category display: {display}\n\n"
        f"Task: Determine the BEST JD category for this product.\n"
        f"Return JSON: {{\n"
        f'  "keyword": "the shortest unique keyword from product name",\n'
        f'  "display": "JD category display name",\n'
        f'  "parent": "parent category if any, or empty string",\n'
        f'  "validation": ["list of keywords that must appear in product name for validation"]\n'
        f"}}\n"
        f"Example for '美的MBJ-20A制冰机': {{\"keyword\":\"MBJ\",\"display\":\"小型制冰机\",\"parent\":\"厨房小电\",\"validation\":[\"制冰\",\"小型制冰机\"]}}"
    )
    
    if dry_run:
        print(f"    [dry-run] 将调 LLM 解析: {p_name}")
        return None
    
    result = call_llm(prompt)
    if not result:
        print(f"    ❌ LLM 调用失败")
        return None
    
    try:
        choice = json.loads(result['choices'][0]['message']['content'])
        kw = choice.get('keyword', '')
        display = choice.get('display', '')
        parent = choice.get('parent', '')
        validation = choice.get('validation', [])
        
        if not kw or not display:
            print(f"    ❌ LLM 返回不完整: {choice}")
            return None
        
        return {
            'keyword': kw,
            'display': display,
            'parent': parent,
            'validation': validation + [kw] if kw not in validation else validation
        }
    except (KeyError, json.JSONDecodeError) as e:
        print(f"    ❌ 解析 LLM 响应失败: {e}")
        return None


def _parse_llm_json(result):
    """从 LLM 响应中提取 JSON, 增加容错"""
    content = result['choices'][0]['message']['content']
    if not content:
        print(f"    ❌ LLM 返回空内容", flush=True)
        return None
    content = content.strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[-1]
        if content.endswith('```'):
            content = content[:-3]
        content = content.strip()
        if content.startswith('json'):
            content = content[4:].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        print(f"    ❌ JSON 解析失败: {e}", flush=True)
        print(f"    原始({len(content)}chars): {content[:300]}", flush=True)
        # 尝试补全未闭合的括号/引号
        if 'Unterminated string' in str(e):
            if content.count('{') > content.count('}'):
                content += '}'
            if content.count('"') % 2 != 0:
                content += '"'
            try:
                return json.loads(content)
            except:
                pass
        return None


# ═══════════════════════════════════════════════════════════
# 两级校验: Level1=规则引擎(零成本) + Level2=LLM语义(兜底)
# ═══════════════════════════════════════════════════════════

# 禁止映射表: {form_label_pattern: [forbidden_source_keys]}
FORBIDDEN_MAP = {
    "信用代码": ["品牌", "品牌名称", "商品型号", "商品条码"],
    "3C认证":   ["品牌", "品牌名称", "商品型号", "商品条码"],
    "合格证":    ["品牌", "品牌名称", "商品型号", "商品条码"],
    "商品类别":  ["品牌名称", "商品条码", "商品编码"],
    "经营许可证": ["品牌名称", "商品型号", "商品条码"],
}

# 正则规则: (form_label_regex, source_key_regex) → 禁止
FORBIDDEN_PATTERNS = [
    (r"信用.*代码|3C.*证|合格.*证|许可.*证", r"品牌|型号|条码|编码"),
    (r"证书.*编号|认证.*编号", r"品牌|型号|条码"),
    (r"商品类别|类目", r"品牌|型号|编码"),
]


def _validate_level1(mapping, field_label, source_keys=None):
    """Level 1 规则引擎: 零成本语义校验"""
    source_key = mapping.get('source_key', '')
    field_type = mapping.get('field_type', '')

    # Level0: source_key 必须存在于 source_keys (如果提供了)
    if source_keys and source_key not in source_keys:
        return (False, f"source_key='{source_key}' 不在源表中 (可用: {len(source_keys)}个)")

    # 检查禁止映射表
    for pattern, forbidden in FORBIDDEN_MAP.items():
        if pattern in field_label:
            for fb in forbidden:
                if fb in source_key:
                    return (False, f"禁止映射: {field_label} → {source_key}")
    # 检查正则规则
    for f_re, s_re in FORBIDDEN_PATTERNS:
        if re.search(f_re, field_label) and re.search(s_re, source_key):
            return (False, f"禁止映射(正则): {field_label} → {source_key}")

    # select 字段: value_map 与 default 一致性
    if field_type == 'select':
        vm = mapping.get('value_map', {})
        df = mapping.get('default', '')
        if df and vm and df not in vm.values():
            return (False, f"default='{df}' 不在 value_map 的 values 中")
        # default 不能是 key (源值)，除非 key==value（同值映射）
        if df and vm and df in vm and vm[df] != df:
            return (False, f"default='{df}' 是源值(key)应为 '{vm[df]}'")

    return (True, None)


def _validate_level2(mapping, field_label, category):
    """Level 2 LLM 兜底: 仅规则无法判断时调用；API 为空时跳过"""
    if not _LLM_AVAILABLE:
        print(f"    ⚠️  Level2 校验: LLM 不可用, 降级通过")
        return True
    source_key = mapping.get('source_key', '')
    field_type = mapping.get('field_type', '')
    value_map = mapping.get('value_map', {})
    default = mapping.get('default', '')

    prompt = (
        f"校验任务: 判断以下字段映射的语义和质量是否合理。\n\n"
        f"表单字段: label='{field_label}', type='{field_type}'\n"
        f"源字段: source_key='{source_key}'\n"
        f"类目: {category}")
    if field_type == 'select':
        prompt += f"\nvalue_map={json.dumps(value_map, ensure_ascii=False)}"
        prompt += f"\ndefault='{default}'"
    prompt += (
        f"\n\n规则: 字段映射应语义匹配; select的default必须是表单中真实存在的选项名; "
        f"输出: {{\"valid\":true}} 或 {{\"valid\":false,\"reason\":\"原因\"}}。只输出JSON。"
    )

    r = call_llm(prompt)
    if not r:
        print(f"    ⚠️  Level2 校验调用失败, 降级通过")
        return True
    try:
        c = _parse_llm_json(r)
        if c.get('valid') is False:
            print(f"    ❌ Level2 语义错误: {c.get('reason','')}")
            return False
        return True
    except:
        print(f"    ⚠️  Level2 解析失败, 降级通过")
        return True


def _validate_mapping(mapping, field_label, category, source_keys=None):
    """两级校验入口: Level1 规则 → Level2 LLM(兜底)"""
    valid, reason = _validate_level1(mapping, field_label, source_keys)
    if not valid:
        print(f"    ❌ Level1(规则): {reason}")
        return False
    # Level1 通过 → 再走 Level2 LLM 深度校验
    return _validate_level2(mapping, field_label, category)


def resolve_attr_mapping(item, dry_run):
    """用 LLM 解析美团属性映射条目 → 写入 mt_attr_mapping.json
    两套独立流程:
      步骤1 LLM — 属性名匹配: source_keys → source_key+form_label
      步骤2 LLM — 子选项值匹配: params[source_key] → value_map+default
    """
    category = item.get('category', '')
    field_label = item.get('field_label', '')
    field_type = item.get('field_type', '')
    product_name = item.get('product_name', '')
    select_opts = item.get('select_opts', [])
    source_keys = item.get('source_keys', [])
    params = item.get('params', {})

    if dry_run:
        print(f"    [dry-run] attr_mapping: {field_label} @ {category}")
        return None

    # ═══ 步骤1 LLM: 属性名匹配 (source_keys → source_key) ═══
    # 传入子选项值作上下文(both select_opts + params), 但只输出 source_key
    prompt1 = (
        f"任务: 匹配美云销字段名到美团表单字段。\n\n"
        f"商品类目: {category}\n商品名称: {product_name}\n"
        f"美团表单字段: '{field_label}'\n"
        f"美云销可用字段名: {json.dumps(source_keys, ensure_ascii=False)}\n"
        f"美云销各字段取值: {json.dumps(params, ensure_ascii=False) if params else '(无)'}\n"
    )
    if select_opts:
        prompt1 += f"美团该字段可选值: {json.dumps(select_opts, ensure_ascii=False)}\n"
    prompt1 += (
        f"\n规则: 从美云销字段中选出与'{field_label}'语义最匹配的一个。如果都不匹配则返回skip。\n"
        f"⚠️ 只输出 source_key, 不要输出 value_map 或 default。\n"
        f"输出: {{\"source_key\":\"字段名\"}} 或 {{\"skip\":true,\"reason\":\"原因\"}}\n"
        f"只输出一行 JSON, 不要 markdown 代码块。"
    )
    result1 = call_llm(prompt1)
    if not result1:
        print(f"    ❌ [步骤1 LLM] 调用失败: {field_label}")
        return None

    step1 = _parse_llm_json(result1)
    if not step1:
        return None
    if step1.get('skip'):
        print(f"    ⏭️  [步骤1] {field_label}: 属性名无匹配 ({step1.get('reason','')})")
        return None
    source_key = step1.get('source_key', '')
    if not source_key or source_key not in source_keys:
        print(f"    ❌ [步骤1] {field_label}: source_key='{source_key}' 不在 source_keys 中")
        return None
    print(f"    ✅ [步骤1] {field_label} ← {source_key}")

    # ═══ 步骤2 LLM: 子选项值匹配 (params[source_key] → value_map) ═══
    if field_type != 'select' or not select_opts:
        # text/structured: 步骤1已足够, 直接生成映射
        mapping = {"source_key": source_key, "form_label": field_label,
                   "field_type": field_type}
        _save_attr_mapping(item, mapping, dry_run)
        return mapping

    # ═══ 步骤2 LLM: 子选项值匹配 (params[source_key] → value_map) ═══
    # 传入属性名作上下文(source_key + form_label + 全部params), 但只输出 value_map + default
    source_value = params.get(source_key, '')
    prompt2 = (
        f"任务: 映射美云销源值到美团表单选项。\n\n"
        f"商品类目: {category}\n"
        f"源字段名: '{source_key}' (已由步骤1匹配)\n"
        f"目标表单字段: '{field_label}'\n"
        f"源表实际值: '{source_value}'\n"
        f"表单可选值: {json.dumps(select_opts, ensure_ascii=False)}\n"
        f"所有源表数据(供参考): {json.dumps(params, ensure_ascii=False) if params else '(无)'}\n\n"
        f"规则:\n"
        f"1. value_map 的 key 固定为源值'{source_value}', value 从表单可选值中选最匹配的\n"
        f"2. default 必须是表单可选值之一\n"
        f"3. source_key 固定为'{source_key}', form_label 固定为'{field_label}', 不要修改\n"
        f"4. 输出: {{\"source_key\":\"{source_key}\",\"form_label\":\"{field_label}\",\"field_type\":\"select\","
        f"\"value_map\":{{\"源值\":\"表单值\"}},\"default\":\"表单值\"}}\n"
        f"只输出一行 JSON, 不要 markdown。"
    )
    result2 = call_llm(prompt2)
    if not result2:
        print(f"    ❌ [步骤2 LLM] 调用失败: {field_label}")
        return None

    mapping = _parse_llm_json(result2)
    if not mapping:
        return None
    if mapping.get('skip'):
        print(f"    ⏭️  [步骤2] {field_label}: 值无匹配 ({mapping.get('reason','')})")
        return None
    if not mapping.get('source_key') or not mapping.get('form_label'):
        print(f"    ❌ [步骤2] 返回不完整: {mapping}")
        return None

    # 校验: value_map key 必须在 params 中有对应源值
    validation_source_keys = {source_key: source_value} if source_value else {}
    if not _validate_mapping(mapping, field_label, category, list(validation_source_keys.keys())):
        return None
    print(f"    ✅ [步骤2] {field_label}: {len(mapping.get('value_map',{}))} 个选项映射")

    _save_attr_mapping(item, mapping, dry_run)
    cpath = f"{category}/{item.get('sub_category','')}" if item.get('sub_category','') else category
    sk = mapping.get('source_key','')
    print(f"    ✅ 新增映射: {cpath} / {field_label} ({len(mapping.get('value_map',{}))} 选项)")
    return mapping


def _save_attr_mapping(item, mapping, dry_run):
    """写入映射到 mt_attr_mapping.json"""
    category = item.get('category', '')
    field_label = item.get('field_label', '')

    attr_file = os.path.join(MAPPINGS_DIR, 'mt_attr_mapping.json')
    attr_data = load_json(attr_file)
    if not isinstance(attr_data, dict):
        attr_data = {"categories": {}}

    cats = attr_data.setdefault('categories', {})
    sub_cat = item.get('sub_category', category)
    if category not in cats:
        cats[category] = {"sub_category_field": "", "default_sub": sub_cat,
                          "subcategories": {sub_cat: {"mappings": []}}}

    sc = cats[category].setdefault('subcategories', {}).setdefault(sub_cat, {"mappings": []})
    existing = {m['form_label'] for m in sc.get('mappings', [])}
    if field_label not in existing:
        sc['mappings'].append(mapping)

    save_json(attr_file, attr_data)
    return mapping

def resolve_all(dry_run=False):
    """主逻辑 — 多轮迭代直到清空或达到上限"""
    print(f"\n[resolve] ═══════════ 后台解析开始 ═══════════", flush=True)
    pending = load_json(PENDING_FILE)
    if not pending:
        print("[resolve] pending_mappings.json 为空或不存在", flush=True)
        return
    
    unresolved = [p for p in pending if not p.get('resolved')]
    total_unresolved = len(unresolved)
    print(f"[resolve] 共 {len(pending)} 条，其中未解析 {total_unresolved} 条", flush=True)
    
    if not unresolved:
        print(f"[resolve] ═══════════ 无需解析 ═══════════", flush=True)
        return

    BATCH_SIZE = 5
    MAX_TOTAL = 30  # 单次派发最多处理30条
    cat_map = load_json(CATEGORY_FILE)
    mapping = cat_map.get('mapping', {}) if isinstance(cat_map, dict) else {}
    
    total_processed = 0
    total_updated = 0
    
    for round_num in range(1, 8):  # 最多7轮 (7×5=35, 但MAX_TOTAL=30)
        # 重新读取 (可能有新增条目)
        pending = load_json(PENDING_FILE)
        unresolved = [p for p in pending if not p.get('resolved')]
        
        if not unresolved:
            break
        
        # 去重
        seen = set()
        unique = []
        for p in unresolved:
            key = (p.get('type',''), p.get('category',''), p.get('sub_category',''), p.get('field_label',''))
            if key not in seen:
                seen.add(key)
                unique.append(p)
        
        batch = unique[:BATCH_SIZE]
        if total_processed >= MAX_TOTAL or not batch:
            break
        
        print(f"\n[resolve] 第{round_num}轮: 处理 {len(batch)} 条 (已处理{total_processed}/{MAX_TOTAL})", flush=True)
        round_updated = 0
        
        for item in batch:
            p_type = item.get('type', '')
            if p_type == 'category':
                result = resolve_category(item, dry_run)
                if result and result['keyword'] not in mapping:
                    entry = {"d": result['display'], "v": result['validation']}
                    if result['parent']:
                        entry['p'] = result['parent']
                    mapping[result['keyword']] = entry
                    round_updated += 1
                    print(f"    ✅ 新增映射: \"{result['keyword']}\" → {entry}")
                if not dry_run:
                    item['resolved'] = True
                    if result:
                        item['result'] = result
            
            elif p_type == 'field':
                unmapped = load_json(UNMAPPED_FILE)
                unmapped.append(item)
                save_json(UNMAPPED_FILE, unmapped)
                item['resolved'] = True
                print(f"    📝 字段 → 记录")
            
            elif p_type == 'attr_mapping':
                result = resolve_attr_mapping(item, dry_run)
                if not dry_run:
                    if result:
                        item['resolved'] = True
                        item['result'] = result
                        round_updated += 1
                    elif result is None and item.get('attempts', 0) >= 2:
                        item['resolved'] = True
                        item['skipped'] = True
                        print(f"    📌 {item.get('field_label','')}: 2次解析失败, 标记为跳过", flush=True)
                    else:
                        item['attempts'] = (item.get('attempts', 0) + 1)
            
            total_processed += 1
            if total_processed >= MAX_TOTAL:
                break
        
        total_updated += round_updated
        
        # 每轮后保存状态
        if not dry_run:
            save_json(PENDING_FILE, pending)
    
    # 写入更新后的 mapping
    if total_updated > 0 and not dry_run:
        if isinstance(cat_map, dict):
            cat_map['mapping'] = mapping
            save_json(CATEGORY_FILE, cat_map)
            print(f"\n[resolve] ✅ 已更新 {total_updated} 条到 jd_category_kw.json")
    
    if not dry_run:
        pending = load_json(PENDING_FILE)
        remaining = len([p for p in pending if not p.get('resolved')])
        print(f"\n[resolve] ═══════ 本轮完成: 处理{total_processed}条, 新增{total_updated}条, 剩余{remaining}条 ═══════", flush=True)
    
    if dry_run:
        print(f"\n[dry-run] 预览完成，将处理 {min(total_unresolved, MAX_TOTAL)} 条")

def auto_dedup_mappings(dry_run=False):
    """扫描 mt_attr_mapping.json，将 3+ 类目共享的映射提升到 _shared，删除副本"""
    attr_file = os.path.join(MAPPINGS_DIR, 'mt_attr_mapping.json')
    data = load_json(attr_file)
    if not isinstance(data, dict):
        print("[dedup] mt_attr_mapping.json 格式异常", flush=True)
        return
    
    cats = data.get('categories', {})
    shared = data.setdefault('_shared', {})
    
    # Step 1: 收集所有 (form_label, source_key) → {category: [mapping_instances]}
    from collections import defaultdict
    
    # key = (form_label, source_key) → list of (category, sub_category, mapping_index, mapping)
    occurrences = defaultdict(list)
    
    for cat_name, cat_data in cats.items():
        subs = cat_data.get('subcategories', {})
        for sub_name, sub_data in subs.items():
            mappings = sub_data.get('mappings', [])
            for idx, m in enumerate(mappings):
                fl = m.get('form_label', '')
                sk = m.get('source_key', '')
                if fl and sk:
                    key = (fl, sk)
                    occurrences[key].append({
                        'category': cat_name,
                        'sub_category': sub_name,
                        'index': idx,
                        'mapping': m
                    })
    
    if not occurrences:
        print("[dedup] 没有找到任何映射", flush=True)
        return
    
    # Step 2: 筛选 ≥3 类目共享的映射
    promoted_count = 0
    removed_count = 0
    
    for (form_label, source_key), instances in occurrences.items():
        unique_cats = set(i['category'] for i in instances)
        
        if len(unique_cats) < 3:
            continue  # 不足3个类目，跳过
        
        # 检查 _shared 是否已存在同名映射
        existing = shared.get(form_label)
        if existing and existing.get('source_key') == source_key:
            # _shared 已有此映射，只需删除子类目副本
            skip_promote = True
        else:
            skip_promote = False
        
        # Step 3: 合并 value_map（取所有 occurrence 的并集）
        merged_value_map = {}
        all_defaults = []
        field_type = instances[0]['mapping'].get('field_type', '')
        
        for inst in instances:
            m = inst['mapping']
            vm = m.get('value_map', {})
            if isinstance(vm, dict):
                for k, v in vm.items():
                    if k not in merged_value_map:
                        merged_value_map[k] = v
            df = m.get('default', '')
            if df:
                all_defaults.append(df)
        
        # 选最常见的 default
        best_default = ''
        if all_defaults:
            from collections import Counter
            best_default = Counter(all_defaults).most_common(1)[0][0]
        
        # Step 4: 提升到 _shared
        if not skip_promote:
            canonical = {
                'source_key': source_key,
                'field_type': field_type
            }
            if merged_value_map:
                canonical['value_map'] = merged_value_map
            if best_default:
                canonical['default'] = best_default
            
            shared[form_label] = canonical
            promoted_count += 1
            
            cat_list = ', '.join(sorted(unique_cats))
            print(f"  [promote] {form_label} ← {source_key}  ({len(unique_cats)}类目: {cat_list})", flush=True)
        else:
            print(f"  [skip-promote] {form_label} 已在 _shared, 仅删除副本", flush=True)
        
        # Step 5: 删除各子类目内的副本（保留第一个类目中的第一个作为参考？不，全删）
        for inst in instances:
            cat_name = inst['category']
            sub_name = inst['sub_category']
            idx = inst['index']
            
            # 获取该 mapping 的当前列表（可能因之前的删除导致 index 偏移）
            subs = cats[cat_name].get('subcategories', {})
            if sub_name not in subs:
                continue
            mapping_list = subs[sub_name].get('mappings', [])
            
            # 按内容匹配删除（避免索引偏移问题）
            new_list = []
            for m in mapping_list:
                if not (m.get('form_label') == form_label and m.get('source_key') == source_key):
                    new_list.append(m)
                else:
                    removed_count += 1
            
            subs[sub_name]['mappings'] = new_list
    
    # Phase 2: 清理已在 _shared 中存在的映射副本（不限类目数阈值）
    # 重新扫描 categories，删除 form_label 已在 _shared 中的条目
    phase2_removed = 0
    for cat_name, cat_data in cats.items():
        subs = cat_data.get('subcategories', {})
        for sub_name, sub_data in subs.items():
            mappings = sub_data.get('mappings', [])
            new_list = []
            for m in mappings:
                fl = m.get('form_label', '')
                sk = m.get('source_key', '')
                shared_entry = shared.get(fl)
                if shared_entry and shared_entry.get('source_key') == sk:
                    # 已在 _shared 中，删除副本
                    phase2_removed += 1
                else:
                    new_list.append(m)
            subs[sub_name]['mappings'] = new_list
    
    if phase2_removed > 0:
        print(f"[dedup] Phase2: 删除 {phase2_removed} 个 _shared 已存在的副本", flush=True)
        removed_count += phase2_removed
    
    # 清理空的 subcategory 和 category
    for cat_name in list(cats.keys()):
        subs = cats[cat_name].get('subcategories', {})
        empty_subs = [s for s, d in subs.items() if not d.get('mappings')]
        for s in empty_subs:
            del subs[s]
    empty_cats = [c for c, d in cats.items() if not d.get('subcategories')]
    for c in empty_cats:
        del cats[c]
    
    # 保存
    print(f"\n[dedup] 提升 {promoted_count} 个映射到 _shared, 删除 {removed_count} 个副本", flush=True)
    
    if not dry_run:
        save_json(attr_file, data)
        print(f"[dedup] ✅ 已保存到 {attr_file}", flush=True)
    else:
        print(f"[dedup] [dry-run] 未实际写入", flush=True)


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    if '--dedup' in sys.argv:
        auto_dedup_mappings(dry_run=dry_run)
    elif '--resolve' in sys.argv or not any(a.startswith('--') for a in sys.argv[1:]):
        resolve_all(dry_run=dry_run)
