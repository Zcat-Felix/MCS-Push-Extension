"""京东秒送 (jd_instant) 填表策略 — 迁移自 fill_engine.py，逻辑不变
用法: python -m strategies.jd_instant <task_json_file> [--skip-nav]
"""
import json, sys, time, os, re, tempfile, urllib.request, base64
from datetime import datetime

from lib.cdp import (CDP, cdp_eval, cdp_new_tab, cdp_targets, cdp_navigate,
                     cdp_set_files, cdp_upload_files, cdp_click_xy, cdp_screenshot, cdp_close)
from lib.utils import load_mapping, js_escape, resolve_selector, extract_value, get_local_paths

JD_DOMAIN = "store.jddj.com"

# ============ 标签页复用 ============
def find_or_create_tab(target_url):
    try:
        tabs = cdp_targets()
        jd_tabs = [t for t in tabs if JD_DOMAIN in t.get('url', '')]
        if jd_tabs:
            old_id = jd_tabs[-1]['targetId']
            print(f"[jd_instant] reuse JD tab: {old_id}", file=sys.stderr)
            cdp_navigate(old_id, target_url)
            time.sleep(8)
            for _ in range(5):
                try:
                    r = cdp_eval(old_id, "(function(){var i=document.querySelectorAll('input[placeholder]');if(i.length>=5)return'ready';return'waiting'})()")
                    if 'ready' in str(r): break
                except: pass
                time.sleep(1)
            tabs2 = cdp_targets()
            jd_tabs2 = [t for t in tabs2 if JD_DOMAIN in t.get('url', '')]
            if jd_tabs2:
                new_id = jd_tabs2[-1]['targetId']
                return new_id
            return old_id
    except Exception as e:
        print(f"[jd_instant] tab lookup failed: {e}", file=sys.stderr)
    target_id = cdp_new_tab(target_url)
    if target_id:
        print(f"[jd_instant] new tab: {target_id}", file=sys.stderr)
        time.sleep(6)
    return target_id

# ============ 后置动作 ============
def do_post_actions(target, field_map):
    actions = field_map.get('post_actions', [])
    results = []
    for action in actions:
        atype = action.get('type', '')
        if atype == 'wait_category':
            try:
                # Tier 1: 聚焦输入框触发推荐 → 再轮询 3s 检查自动填充
                cdp_eval(target, "(function(){var i=document.querySelectorAll('input[placeholder]');if(i.length>2){i[2].focus();document.body.click();}return'ok'})()")
                auto_filled = False
                for _ in range(10):
                    time.sleep(0.3)
                    v = cdp_eval(target, "(function(){var i=document.querySelectorAll('input[placeholder]');if(i.length>2)return i[2].value||'';return''})()")
                    if v and '>' in str(v) and len(str(v)) > 3:
                        auto_filled = True; results.append(f"category auto-filled: {v[:60]}"); break
                if auto_filled:
                    continue
                # Tier 2: 尝试"使用"按钮 1s
                for _ in range(5):
                    time.sleep(0.2)
                    r = cdp_eval(target,
                        "(function(){var els=document.querySelectorAll('*');"
                        "for(var i=0;i<els.length;i++){var cn=els[i].childNodes;"
                        "if(cn.length===1&&cn[0].nodeType===3&&cn[0].textContent.trim()==='使用'){"
                        "var p=els[i].parentElement;"
                        "if(p&&(p.textContent||'').indexOf('建议分类')>-1){els[i].click();return'c';}}}"
                        "return'w'})()")
                    if 'c' in str(r): results.append("clicked 使用"); time.sleep(0.5); break
            except Exception as e:
                results.append(f"wait_category err: {e}")
        elif atype == 'click_text':
            text = action.get('text', '')
            time.sleep(action.get('wait', 0.5))
            try:
                safe = js_escape(text)
                js = f"(function(){{var a=document.querySelectorAll('span,button,a,div');for(var i=0;i<a.length;i++){{if(a[i].textContent.trim()==='{safe}'){{a[i].click();return'ok'}}}}return'nf'}})()"
                results.append(f"click[{text}]: {cdp_eval(target, js)}")
            except: pass
            time.sleep(action.get('wait_after', 0.5))
        elif atype == 'wait':
            s = action.get('seconds', 1); time.sleep(s)
            results.append(f"wait:{s}s")
    return results

# ============ 字段填写 ============
def fill_text(target, field_map, task):
    label = field_map['label']
    sel_spec, source = field_map['selector'], field_map['source']
    max_len = field_map.get('max_len', 999)
    is_dropdown = field_map.get('dropdown', False)

    val = extract_value(task, source)
    if not val: return ("skipped", f"{label}: no data")
    val = val[:max_len]
    safe_val = js_escape(val)
    is_index = sel_spec.startswith('index:')

    print(f"  [{label}] filling: {val[:40]}" + (f" (index:{is_index})" if is_index else f" (sel:{sel_spec[:40]})"), file=sys.stderr)

    if is_index:
        idx = sel_spec[len('index:'):]
        js = (f"(function(){{var el=document.querySelectorAll('input[placeholder]')[{idx}];"
              f"if(!el)return'NF';el.focus();"
              f"var desc=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');"
              f"desc.set.call(el,'{safe_val}');"
              "el.dispatchEvent(new InputEvent('input',{bubbles:true,data:'" + safe_val + "'}));"
              "el.dispatchEvent(new Event('change',{bubbles:true}));"
              "el.dispatchEvent(new Event('blur',{bubbles:true}));return'ok'})()")
    else:
        sel = resolve_selector(target, sel_spec)
        js = (f"(function(){{var el=document.querySelector('{sel}');if(!el)return'NF';"
              f"var v=\"{safe_val}\";el.focus();el.value='';"
              "for(var i=0;i<v.length;i++){el.value+=v[i];el.dispatchEvent(new Event('input',{bubbles:true}));}"
              "el.dispatchEvent(new Event('change',{bubbles:true}));"
              "el.dispatchEvent(new Event('blur',{bubbles:true}));return v.length})()")
    result = cdp_eval(target, js)
    if 'NF' in str(result): return ("failed", f"{label}: selector [{sel_spec}]")

    if is_dropdown:
        status, msg = fill_dropdown(target, val, field_map=field_map, component='cascader', label=label)
        if status == 'filled': return (status, msg)

    post_results = do_post_actions(target, field_map)
    return ("filled", f"{label}: {val}" + (f" | post: {'; '.join(post_results)}" if post_results else ""))

# ============ 品牌级联选择 ============
def fill_brand(target, field_map, task):
    """商品品牌: jd-select 搜索组件，clickXY 点击输入框 + 逐字输入触发 Vue 远程搜索"""
    label = field_map['label']
    source = field_map['source']
    val = extract_value(task, source)
    if not val: return ("skipped", f"{label}: no data")
    print(f"  [{label}] extracting brand: {val}", file=sys.stderr)

    input_idx = field_map.get('input_idx', 3)

    pos_js = f"(function(){{var i=document.querySelectorAll('input[placeholder]')[{input_idx}];if(!i)return'NF';i.focus();var r=i.getBoundingClientRect();return JSON.stringify({{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}})}})()"
    pos = cdp_eval(target, pos_js)
    if 'NF' in str(pos): return ("failed", f"{label}: input not found")

    try:
        coords = json.loads(pos)
        cdp_click_xy(target, coords['x'], coords['y'])
        print(f"  [{label}] clickXY({coords['x']},{coords['y']})", file=sys.stderr)
    except Exception as e:
        return ("failed", f"{label}: click err {e}")
    time.sleep(0.3)

    kw_escaped = ''.join(f'\\u{ord(c):04x}' for c in val)
    type_js = (
        f"(function(){{var i=document.querySelectorAll('input[placeholder]')[{input_idx}];"
        f"if(!i)return'NF';"
        f"i.value='{kw_escaped}';"
        "i.dispatchEvent(new Event('input',{bubbles:true}));"
        "i.dispatchEvent(new Event('change',{bubbles:true}));"
        "i.dispatchEvent(new Event('compositionend',{bubbles:true}));"
        "return i.value.length||0})()"
    )
    result = cdp_eval(target, type_js)
    if 'NF' in str(result): return ("failed", f"{label}: lost input")
    print(f"  [{label}] typed: {val}", file=sys.stderr)

    escaped_kw = js_escape(val)
    poll = (
        f"(function(){{var kw='{escaped_kw}';var MAX=1500,P=100,w=0;"
        "return new Promise(function(resolve){var tid=setInterval(function(){w+=P;"
        "var is=document.querySelectorAll('.jd-select-dropdown__item');"
        "for(var j=0;j<is.length;j++){var t=(is[j].textContent||'').trim();"
        "if(!t||t.length<kw.length)continue;"
        "var isBrand=false;"
        "var rex=new RegExp('^\\\\s*'+kw+'\\\\s*[（(]');if(rex.test(t))isBrand=true;"
        "if(!isBrand&&t.indexOf(kw)===0&&t.length>kw.length){var next=t.charAt(kw.length);if(!/[\\u4e00-\\u9fff]/.test(next))isBrand=true;}"
        "if(!isBrand){var idx=t.indexOf(kw);if(idx>0){var prev=t.charAt(idx-1);"
        "if(!/[\\u4e00-\\u9fff]/.test(prev)&&(/[a-zA-Z0-9]/.test(t)||/[（(]/.test(t)))isBrand=true;}}"
        "if(!isBrand)continue;"
        "if(/^(g|kg|斤|两|磅|ml|L)$/i.test(t))continue;"
        "var r=is[j].getBoundingClientRect();if(r.width>0&&r.height>0){clearInterval(tid);"
        "resolve(JSON.stringify({x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}));return;}}"
        "if(w>=MAX){clearInterval(tid);resolve('timeout');}},P);});})()"
    )
    result = cdp_eval(target, poll)
    
    coords2 = None
    if result and result != 'timeout':
        try: coords2 = json.loads(result)
        except: pass
    if not coords2: return ("skipped", f"{label}: no dropdown match for '{val}'")

    print(f"  [{label}] click dropdown ({coords2['x']},{coords2['y']})", file=sys.stderr)
    try: cdp_click_xy(target, coords2['x'], coords2['y'])
    except: pass

    time.sleep(0.5)
    try:
        v = cdp_eval(target, f"(function(){{var i=document.querySelectorAll('input[placeholder]');if(i.length>{input_idx})return i[{input_idx}].value||'EMPTY';return'NI'}})()")
        if v and v not in ('EMPTY','NI'): return ("filled", f"{label}: {v}")
    except: pass
    return ("filled", f"{label}: clicked ({val})")

# ============ 商品类目关键词映射 ============

CATEGORY_KW = None

# ============ Pending 映射队列 ============

PENDING_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'mappings', 'pending_mappings.json')

def load_pending():
    if not os.path.exists(PENDING_FILE): return []
    try:
        with open(PENDING_FILE, encoding='utf-8') as f: return json.load(f)
    except: return []

def save_pending(pending):
    with open(PENDING_FILE, 'w', encoding='utf-8') as f:
        json.dump(pending, f, ensure_ascii=False, indent=2)

def append_pending(p_type, product_name, task_id='', **extra):
    pending = load_pending()
    for p in pending:
        if not p['resolved'] and p['type'] == p_type and p['product_name'] == product_name:
            return
    entry = {
        "id": f"pm_{int(time.time())}_{len(pending)}",
        "type": p_type,
        "product_name": product_name,
        "task_id": task_id,
        "created_at": datetime.now().isoformat(),
        "resolved": False
    }
    entry.update(extra)
    pending.append(entry)
    save_pending(pending)

def resolve_pending_mappings():
    pending = load_pending()
    total = len(pending)
    unresolved = [p for p in pending if not p['resolved']]
    unresolved_count = len(unresolved)
    
    print(f"[pending] ====== 开始解析 ======", file=sys.stderr)
    print(f"[pending] 总条目: {total}, 未解析: {unresolved_count}", file=sys.stderr)
    
    if not unresolved:
        print(f"[pending] 没有待解析的条目，完成", file=sys.stderr)
        return
    
    cat_map = load_category_map()
    mapping = cat_map.get('mapping', {})
    updated = 0
    start_time = time.time()
    
    for i, item in enumerate(unresolved):
        p_name = item.get('product_name', '')
        p_type = item.get('type', '')
        n = i + 1
        print(f"[pending] [{n}/{unresolved_count}] {p_type}: '{p_name[:40]}'", file=sys.stderr)
        
        if p_type == 'category':
            kw = extract_minimal_keyword(p_name)
            if kw and kw not in mapping:
                display = item.get('display', item.get('llm_pick', ''))
                parent = item.get('parent', '')
                entry = {"d": display}
                if parent: entry['p'] = parent
                entry['v'] = [kw]
                mapping[kw] = entry
                updated += 1
                print(f"[pending]   ✅ 新增映射: '{kw}' → {entry}", file=sys.stderr)
            elif kw and kw in mapping:
                print(f"[pending]   ⚠️ 关键词 '{kw}' 已存在映射，跳过", file=sys.stderr)
            else:
                print(f"[pending]   ⚠️ 无法提取关键词", file=sys.stderr)
        elif p_type == 'field':
            field = item.get('field', '')
            value = item.get('value', '')
            print(f"[pending]   📝 字段: {field}={value} (待手动处理)", file=sys.stderr)
        
        item['resolved'] = True
    
    elapsed = time.time() - start_time
    if updated > 0:
        cat_map['mapping'] = mapping
        cat_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'mappings', 'jd_category_kw.json')
        with open(cat_path, 'w', encoding='utf-8') as f:
            json.dump(cat_map, f, ensure_ascii=False, indent=2)
        print(f"[pending] ✅ 已更新 {updated} 条到 jd_category_kw.json", file=sys.stderr)
    
    save_pending(pending)
    remaining = len([p for p in pending if not p['resolved']])
    print(f"[pending] ====== 完成 ({elapsed:.1f}s) 新增{updated}条，剩余{remaining}条 ======", file=sys.stderr)

def extract_minimal_keyword(product_name):
    name = product_name.strip()
    models = re.findall(r'[A-Z]+[\d\-]*[A-Z\d\-]*', name)
    if models: return models[0]
    words = re.findall(r'[\u4e00-\u9fff]+', name)
    if words: return words[-1]
    return name[:10]

def load_category_map():
    global CATEGORY_KW
    if CATEGORY_KW is None:
        p = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'mappings', 'jd_category_kw.json')
        if os.path.exists(p):
            CATEGORY_KW = json.load(open(p, encoding='utf-8'))
    return CATEGORY_KW or {}

def match_category_kw(product_name):
    m = load_category_map()
    mapping = m.get('mapping', {})
    task_id = m.get('_task_id', '')
    
    best_kw = None
    best_info = None
    for kw in sorted(mapping.keys(), key=len, reverse=True):
        if kw in product_name:
            best_kw = kw
            best_info = mapping[kw]
            break
    
    if not best_info:
        append_pending('category', product_name, task_id=task_id, display='', parent='')
        return None
    
    vk = best_info.get('v', [])
    if not vk:
        display = best_info.get('d', '')
        vk = [display.split('>')[-1].split('/')[0]] if display else []
    
    if vk and not any(v in product_name for v in vk):
        append_pending('category', product_name, task_id=task_id,
                       display=best_info.get('d', ''),
                       parent=best_info.get('p', ''),
                       note=f"kw={best_kw} matched but validation {vk} not in product_name")
        return None
    
    if best_info.get('p'):
        return {'display': best_info['d'], 'parent': best_info['p']}
    return {'display': best_info['d']}

def _load_llm_config():
    """从 config.json > llm 读取 LLM API 配置；api_url 为空则不调用 LLM"""
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                            'mappings', 'config.json')
    default = {"api_url": "", "api_key": "", "model_id": ""}
    if not os.path.exists(cfg_path):
        print(f"  [LLM config] config.json 不存在, LLM 功能已禁用", file=sys.stderr)
        return default
    try:
        with open(cfg_path, encoding='utf-8') as f:
            root = json.load(f)
        cfg = root.get('llm', default)
        api_url = cfg.get('api_url', '').strip()
        if not api_url:
            print(f"  [LLM config] api_url 为空, LLM 功能已禁用", file=sys.stderr)
        return cfg
    except Exception as e:
        print(f"  [LLM config] 读取失败: {e}", file=sys.stderr)
        return default

_LLM_CFG = _load_llm_config()
LLM_API_URL = _LLM_CFG.get('api_url', '').strip()
LLM_API_KEY = _LLM_CFG.get('api_key', '').strip()
LLM_MODEL_ID = _LLM_CFG.get('model_id', '').strip()
_LLM_AVAILABLE = bool(LLM_API_URL)

def extract_all_cats(target):
    js = ("(function(){var items=document.querySelectorAll('.jd-select-dropdown__item');"
          "var r=[];for(var i=0;i<items.length;i++){var t=items[i].textContent.trim();"
          "if(t&&t!=='支持7天无理由退货'&&t!=='爆款推荐')r.push(t)}"
          "return JSON.stringify(r.slice(0,25))})()")
    val = cdp_eval(target, js)
    try: return json.loads(val)
    except: return []

def extract_top_categories(target):
    js = ("(function(){var items=document.querySelectorAll('.jd-select-dropdown__item');"
          "var r=[];for(var i=0;i<items.length;i++){var t=items[i].textContent.trim();"
          "if(t&&t!=='支持7天无理由退货'&&t!=='爆款推荐'&&t!=='未分类')r.push(t)}"
          "return JSON.stringify(r.slice(0,20))})()")
    val = cdp_eval(target, js)
    try: return json.loads(val)
    except: return []

def classify_category_via_llm(product_name, categories):
    """用 LLM 选择最佳 JD 类目；API 为空时直接返回空"""
    if not _LLM_AVAILABLE:
        print(f"  [LLM category] api_url 为空, 跳过 LLM 调用", file=sys.stderr)
        return ''
    cats_json = json.dumps(categories, ensure_ascii=False)
    prompt = f"Product: {product_name}\nCategories: {cats_json}\nPick the MOST SPECIFIC match. If exact category not listed, pick closest child subcategory. Return JSON: {{\"pick\":\"...\"}}"
    
    try:
        req_body = json.dumps({
            "model": LLM_MODEL_ID,
            "messages": [
                {"role": "system", "content": "You pick the best JD product category. Reply JSON only."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 500,
            "temperature": 0
        }).encode()
        
        req = urllib.request.Request(LLM_API_URL, data=req_body, method='POST')
        req.add_header('Authorization', f'Bearer {LLM_API_KEY}')
        req.add_header('Content-Type', 'application/json')
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        choice = data.get('choices', [{}])[0] if data.get('choices') else {}
        msg = choice.get('message', {})
        content = msg.get('content', '') or msg.get('reasoning_content', '')
        print(f"  [LLM category] raw: {content[:80]}", file=sys.stderr)
        
        m = re.search(r'\{[^}]+\}', content)
        if m: return json.loads(m.group()).get('pick', '')
    except Exception as e:
        print(f"  [LLM category] error: {e}", file=sys.stderr)
    return ''

def click_category_item(target, keyword):
    kw_safe = js_escape(keyword)
    poll = (
        f"(function(){{var kw='{kw_safe}';var MAX=4000,P=100,w=0;"
        "var tid=setInterval(function(){w+=P;"
        "var is=document.querySelectorAll('.jd-select-dropdown__item');"
        "for(var j=0;j<is.length;j++){"
        "if((is[j].textContent||'').indexOf(kw)>-1){"
        "var r=is[j].getBoundingClientRect();"
        "if(r.width>0&&r.height>0){clearInterval(tid);"
        "window.__wb_xy=JSON.stringify({x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)});return;}}}"
        "if(w>=MAX){clearInterval(tid);window.__wb_xy='timeout';}},P);return'poll'})()"
    )
    try: cdp_eval(target, poll)
    except: pass
    time.sleep(0.5)
    coords = None
    try:
        v = cdp_eval(target, "(function(){return window.__wb_xy||null})()")
        if v and v not in ('timeout','null'): coords = json.loads(v)
    except: pass
    if coords:
        cdp_click_xy(target, coords['x'], coords['y'])
        return True
    return False

def click_cascader_item(target, keyword):
    kw = js_escape(keyword)
    js = (
        "(function(){var kw='" + kw + "';"
        "var items=document.querySelectorAll('.dj-cascader-item-item-content');"
        "for(var i=items.length-1;i>=0;i--){"
        "var t=(items[i].textContent||'');"
        "if(t.indexOf(kw)>-1){"
        "  var suffix=t.slice(t.indexOf(kw)+kw.length);"
        "  if(suffix.length>0&&suffix.charCodeAt(0)>=0x4e00)continue;"
        "  items[i].scrollIntoView({block:'center'});"
        "  items[i].click();return'ok'}}"
        "return'nf'})()"
    )
    return cdp_eval(target, js) == 'ok'

def fill_category(target, field_map, task):
    label = field_map['label']
    product_name = task.get('product', {}).get('name', '')
    
    # Tier 1: 聚焦输入框触发推荐 → 轮询 3s 检查自动填充
    try:
        cdp_eval(target, "(function(){var i=document.querySelectorAll('input[placeholder]');if(i.length>2){i[2].focus();document.body.click();}return'ok'})()")
        for _ in range(10):
            time.sleep(0.3)
            v = cdp_eval(target, "(function(){var i=document.querySelectorAll('input[placeholder]');if(i.length>2)return i[2].value||'';return''})()")
            if v and '>' in str(v) and len(str(v)) > 3:
                print(f"  [{label}] auto-filled: {v[:60]}", file=sys.stderr)
                return ("filled", f"{label}: {v[:60]} (auto-recommend)")
    except Exception as e:
        print(f"  [{label}] Tier1 err: {e}", file=sys.stderr)

    # Tier 2: 尝试"建议分类"下方的"使用"按钮 1s
    try:
        for _ in range(5):
            time.sleep(0.2)
            r = cdp_eval(target,
                "(function(){var els=document.querySelectorAll('*');"
                "for(var i=0;i<els.length;i++){var cn=els[i].childNodes;"
                "if(cn.length===1&&cn[0].nodeType===3&&cn[0].textContent.trim()==='使用'){"
                "var p=els[i].parentElement;"
                "if(p&&(p.textContent||'').indexOf('建议分类')>-1){els[i].click();return'c';}}}"
                "return'w'})()")
            if 'c' in str(r):
                time.sleep(0.5)
                v = cdp_eval(target, "(function(){var i=document.querySelectorAll('input[placeholder]');if(i.length>2)return i[2].value||'';return''})()")
                if v and '>' in str(v) and len(str(v)) > 3:
                    print(f"  [{label}] filled via 使用 button: {v[:60]}", file=sys.stderr)
                    return ("filled", f"{label}: {v[:60]} (建议分类)")
    except Exception as e:
        print(f"  [{label}] Tier2 err: {e}", file=sys.stderr)

    # Tier 3: 手动 cascader 级联选择
    match = match_category_kw(product_name)
    if not match:
        return ("skipped", f"{label}: no kw match for '{product_name[:30]}'")

    display = match['display']
    print(f"  [{label}] keyword: {display}", file=sys.stderr)

    pos_js = ("(function(){var i=document.querySelectorAll('input[placeholder]')[2];"
              "if(!i)return'NF';i.focus();var r=i.getBoundingClientRect();"
              "return JSON.stringify({x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)})})()")
    pos = cdp_eval(target, pos_js)
    if 'NF' in str(pos): return ("skipped", f"{label}: no category input")
    try: coords = json.loads(pos)
    except: return ("failed", f"{label}: bad coords")

    try: cdp_eval(target, "(function(){document.body.click();return'ok'})()")
    except: pass
    time.sleep(0.2)

    try: cdp_click_xy(target, coords['x'], coords['y'])
    except: pass
    time.sleep(0.4)

    kw = js_escape(display)
    type_js = (
        "(function(){var kw='" + kw + "';"
        "var inp=document.querySelectorAll('input[placeholder]')[2];"
        "var desc=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');"
        "desc.set.call(inp,kw);"
        "inp.dispatchEvent(new InputEvent('input',{bubbles:true,data:kw}));"
        "inp.dispatchEvent(new Event('change',{bubbles:true}));"
        "return'ok'})()"
    )
    cdp_eval(target, type_js)
    time.sleep(0.5)

    check_js = (
        "(function(){var pop=document.querySelector('.dj-cascader-popover');"
        "if(!pop||window.getComputedStyle(pop).display==='none')return'NF';"
        "var items=pop.querySelectorAll('.dj-cascader-item-item-content');"
        "if(items.length===0)return'NE';"
        "items[0].scrollIntoView({block:'center'});"
        "items[0].click();"
        "return'ok'})()"
    )
    result = 'NF'
    for retry in range(3):
        result = cdp_eval(target, check_js)
        if result == 'ok': break
        if retry < 2:
            cdp_eval(target, type_js)
            time.sleep(0.3)
    
    if result != 'ok':
        print(f"  [{label}] V2 filter failed ({result}), cascade fallback (slow)", file=sys.stderr)
        return fill_category_cascade(target, field_map, task, match)
    
    time.sleep(0.3)
    v = cdp_eval(target, "(function(){var i=document.querySelectorAll('input[placeholder]');if(i.length>2)return i[2].value||'EMPTY';return'NI'})()")
    if v and v not in ('EMPTY','NI'):
        return ("filled", f"{label}: {v}")
    return ("filled", f"{label}: {display}")

def fill_category_cascade(target, field_map, task, match):
    label = field_map['label']
    display = match['display']
    parent_jd = match.get('parent', '')

    pos_js = ("(function(){var i=document.querySelectorAll('input[placeholder]')[2];"
              "if(!i)return'NF';i.focus();var r=i.getBoundingClientRect();"
              "return JSON.stringify({x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)})})()")
    pos = cdp_eval(target, pos_js)
    if 'NF' in str(pos): return ("skipped", f"{label}: no category input")
    try: coords = json.loads(pos)
    except: return ("failed", f"{label}: bad coords")

    try: cdp_eval(target, "(function(){document.body.click();return'ok'})()")
    except: pass
    time.sleep(0.2)

    try: cdp_click_xy(target, coords['x'], coords['y'])
    except: pass
    time.sleep(0.5)

    path = ['家用电器']
    if parent_jd: path.append(parent_jd)
    if display != parent_jd and display != path[-1]:
        path.append(display)
    
    for i, step in enumerate(path):
        ok = click_cascader_item(target, step)
        if not ok:
            if i == len(path) - 1 and i >= 1:
                time.sleep(0.3)
                v = cdp_eval(target, "(function(){var i=document.querySelectorAll('input[placeholder]');if(i.length>2)return i[2].value||'EMPTY';return'NI'})()")
                if v and v not in ('EMPTY','NI') and ('>' in str(v)):
                    return ("filled", f"{label}: {v} (L2 only)")
            return ("skipped", f"{label}: '{step}' not found at level {i}")
        print(f"  [{label}] L{i+1}: {step} ✓", file=sys.stderr)
        time.sleep(0.5)

    time.sleep(0.3)
    v = cdp_eval(target, "(function(){var i=document.querySelectorAll('input[placeholder]');if(i.length>2)return i[2].value||'EMPTY';return'NI'})()")
    if v and v not in ('EMPTY','NI'):
        return ("filled", f"{label}: {v}")
    return ("filled", f"{label}: path={' > '.join(path)}")

# ============ 统一下拉填值 ============
def fill_store_category(target, field_map, task):
    label = field_map.get('label', '店内分类')
    try:
        js = "(function(){var i=document.querySelectorAll('input[placeholder]');if(i.length>2)return i[2].value||'';return''})()"
        cat_val = cdp_eval(target, js) or ''
    except: cat_val = ''
    last_cat = cat_val.split('>')[-1].strip() if '>' in cat_val else cat_val.strip()
    if not last_cat: return ("skipped", f"{label}: no category")
    CAT_MAP = {'空调': ('壁挂式空调', '空调')}
    for kw in CAT_MAP.get(last_cat, (last_cat,)):
        status, msg = fill_dropdown(target, kw, field_map=field_map, component='select', label=label)
        if status == 'filled': return (status, msg)
    return ("skipped", f"{label}: all candidates failed ({last_cat})")

def fill_dropdown(target, keyword, field_map=None, component='cascader', label=''):
    kw_escaped = ''.join(f'\\u{ord(c):04x}' for c in keyword)
    input_idx = field_map.get('input_idx', 3) if field_map else 3
    verify_idx = field_map.get('verify_idx', 3) if field_map else 3

    if component == 'cascader':
        item_sel = '.dj-cascader-item-item-content'
        escaped_kw = js_escape(keyword)
        match_js = f'(t.indexOf("{escaped_kw}")>-1)'
        type_js = (
            f"(function(){{var inputs=document.querySelectorAll('input[placeholder]');"
            f"if(inputs.length<={input_idx})return'NIDX';"
            f"var i=inputs[{input_idx}];"
            f"i.focus();i.click();i.value='{kw_escaped}';"
            "i.dispatchEvent(new Event('input',{bubbles:true}));"
            "i.dispatchEvent(new Event('change',{bubbles:true}));return'ok'})()"
        )
    else:
        item_sel = '.jd-select-dropdown__item'
        escaped_kw = js_escape(keyword)
        match_js = f'(t.indexOf("{escaped_kw}")>-1)'
        if field_map and field_map.get('input_idx') is not None:
            type_js = (
                f"(function(){{var inputs=document.querySelectorAll('input[placeholder]');"
                f"if(inputs.length<={input_idx})return'NIDX';"
                f"var i=inputs[{input_idx}];"
                f"i.focus();i.click();i.value='{kw_escaped}';"
                "i.dispatchEvent(new Event('input',{bubbles:true}));"
                "i.dispatchEvent(new Event('change',{bubbles:true}));return'ok'})()"
            )
        else:
            type_js = (
                "(function(){var i=document.querySelector('.jd-select.is-filterable .jd-select__input');"
                "if(!i)return'NF';"
                f"i.focus();i.click();i.value='{kw_escaped}';"
                "i.dispatchEvent(new Event('input',{bubbles:true}));"
                "i.dispatchEvent(new Event('change',{bubbles:true}));return'ok'})()"
            )

    result = cdp_eval(target, type_js)
    if 'NIDX' in str(result): return ("failed", f"{label}: no input at idx {input_idx}")
    if 'NF' in str(result): return ("failed", f"{label}: input not found")
    print(f"  [{label}] typed: {keyword}, waiting for dropdown...", file=sys.stderr)
    time.sleep(0.8)

    poll = (
        f"(function(){{var S='{item_sel}',M=function(t){{return {match_js};}},MAX=5000,P=100,w=0;"
        "var tid=setInterval(function(){w+=P;"
        "var is=document.querySelectorAll(S);for(var j=0;j<is.length;j++){"
        "if(M(is[j].textContent||'')){var r=is[j].getBoundingClientRect();"
        "if(r.width>0){clearInterval(tid);"
        "window.__wb_xy=JSON.stringify({x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)});return;}}}"
        "if(w>=MAX){clearInterval(tid);window.__wb_xy='timeout';}},P);return'poll'})()"
    )
    try: cdp_eval(target, poll)
    except: pass
    time.sleep(1)

    coords = None
    try:
        v = cdp_eval(target, "(function(){return window.__wb_xy||null})()")
        if v and v not in ('timeout','null'): coords = json.loads(v)
    except: pass
    if not coords: return ("skipped", f"{label}: no dropdown match for '{keyword}'")

    print(f"  [{label}] clickXY({coords['x']},{coords['y']})", file=sys.stderr)
    try: cdp_click_xy(target, coords['x'], coords['y'])
    except: pass

    time.sleep(0.5)
    try:
        v = cdp_eval(target, f"(function(){{var i=document.querySelectorAll('input[placeholder]');if(i.length>{verify_idx})return i[{verify_idx}].value||'EMPTY';return'NI'}})()")
        if v and v not in ('EMPTY','NI'): return ("filled", f"{label}: {v}")
    except: pass
    return ("filled", f"{label}: clicked ({keyword})")

# ============ 图片 ============
def fill_images(target, field_map, task):
    label, sel, source, max_n = field_map['label'], field_map['selector'], field_map['source'], field_map.get('max', 10)
    if source == 'images_mainThumb': paths = get_local_paths(task, 'mainThumb', max_n)
    elif source == 'images_detail': paths = get_local_paths(task, 'detail', max_n)
    else: return ("skipped", f"{label}: unknown")
    if not paths: return ("skipped", f"{label}: no local images")
    
    trigger_sel = field_map.get('trigger_selector', '')
    paths = paths[:max_n]
    
    result = cdp_upload_files(target, trigger_sel, sel, paths)
    if result.get('success'):
        return ("filled", f"{label}: {result.get('files', len(paths))}张 ✓")
    
    result2 = cdp_set_files(target, sel, paths)
    if result2.get('success'):
        return ("filled", f"{label}: {result2.get('files', len(paths))}张 (UI未刷新)")
    
    return ("failed", f"{label}: {result.get('error', 'unknown')}")

def fill_form_images(target, field_map, task):
    label = field_map['label']
    form_field = field_map.get('form_field', 'materialList')
    source = field_map['source']
    max_n = field_map.get('max', 10)
    
    if source == 'images_mainThumb':
        urls = task.get('images_mainThumb', [])
    elif source == 'images_detail':
        urls = task.get('images_detail', [])
    else:
        return ("skipped", f"{label}: unknown source")
    
    if not urls:
        return ("skipped", f"{label}: no URLs")
    
    urls = urls[:max_n]
    
    for action in field_map.get('pre_actions', []):
        if action['type'] == 'set_field_visible':
            field = action['field']
            js = f"""var f=null,vn=document.getElementById('app')._vnode;
(function w(vn,d){{if(d>20||!vn||f)return;if(vn.component&&vn.component.props&&vn.component.props.form)f=vn.component.props.form;
if(vn.component&&vn.component.subTree)w(vn.component.subTree,d+1);
if(Array.isArray(vn.children)){{for(var i=0;i<vn.children.length;i++)w(vn.children[i],d+1)}}
if(Array.isArray(vn.dynamicChildren)){{for(var i=0;i<vn.dynamicChildren.length;i++)w(vn.dynamicChildren[i],d+1)}}}})(vn,0);
if(f)f.setFieldState('{field}',function(s){{s.display='visible';s.visible=true}});
JSON.stringify({{done:true}})"""
            try: cdp_eval(target, js)
            except: pass
    
    urls_json = json.dumps(urls, ensure_ascii=False)
    js = f"""var f=null,vn=document.getElementById('app')._vnode;
(function w(vn,d){{if(d>20||!vn||f)return;if(vn.component&&vn.component.props&&vn.component.props.form)f=vn.component.props.form;
if(vn.component&&vn.component.subTree)w(vn.component.subTree,d+1);
if(Array.isArray(vn.children)){{for(var i=0;i<vn.children.length;i++)w(vn.children[i],d+1)}}
if(Array.isArray(vn.dynamicChildren)){{for(var i=0;i<vn.dynamicChildren.length;i++)w(vn.dynamicChildren[i],d+1)}}}})(vn,0);
if(f)f.setValuesIn('{form_field}',{urls_json});
JSON.stringify({{set:(f?f.values.{form_field}:[]).length}});
"""
    result = cdp_eval(target, js)
    try:
        info = json.loads(result)
        count = info.get('set', 0)
    except:
        count = len(urls)
    
    return ("filled", f"{label}: {count}张 ✓ (form.{form_field})")

JD_UPLOAD_API = 'https://sff.jddj.com/api?v=1.0&appId=YNE4XWZFDHXOYGKZU5FN&api=dsm.web.material.img.upload'
JD_CDN_PREFIX = '//img10.360buyimg.com/jddjstorepicture/'

def fill_form_images_cached(target, field_map, task):
    """通过页面原生上传组件上传图片到 JD CDN, 再 setValuesIn 写回表单"""
    label = field_map['label']
    form_field = field_map.get('form_field', 'materialList')
    source = field_map['source']
    max_n = field_map.get('max', 10)
    
    if source == 'images_mainThumb':
        urls = task.get('images_mainThumb', [])
    elif source == 'images_detail':
        urls = task.get('images_detail', [])
    else:
        return ("skipped", f"{label}: unknown source")
    
    if not urls:
        return ("skipped", f"{label}: no URLs")
    
    urls = urls[:max_n]
    print(f"  [{label}] click-uploading {len(urls)} images...", file=sys.stderr)
    
    for action in field_map.get('pre_actions', []):
        if action.get('type') == 'set_field_visible':
            field = action['field']
            js = f"var f=window.__wb_form;if(f)f.setFieldState('{field}',function(s){{s.display='visible';s.visible=true}});'ok'"
            try: cdp_eval(target, js)
            except: pass
    
    jd_urls = []
    local_paths = []
    
    # 先下载所有图片到本地
    for i, url in enumerate(urls):
        print(f"    [{i+1}/{len(urls)}] downloading {url[:60]}...", file=sys.stderr)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                img_bytes = resp.read()
        except Exception as e:
            print(f"    [{i+1}] download failed: {e}", file=sys.stderr)
            continue
        ext = url.rsplit('.', 1)[-1].split('?')[0] or 'jpg'
        if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'): ext = 'jpg'
        tf = tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False)
        tf.write(img_bytes); tf.close()
        local_paths.append(tf.name.replace('\\', '/'))
    
    if not local_paths:
        return ("failed", f"{label}: all downloads failed")
    
    # 批量上传: 一次打开弹窗, 塞所有文件
    print(f"    batch-uploading {len(local_paths)} files...", file=sys.stderr)
    trigger_sel = field_map.get('trigger_selector', '.dj-upload-upload-btn')
    try:
        upload_body = json.dumps({
            "triggerSelector": trigger_sel,
            "files": local_paths
        }).encode('utf-8')
        upload_req = urllib.request.Request(f'{CDP}/uploadFiles?target={target}', data=upload_body, method='POST')
        upload_req.add_header('Content-Type', 'application/json')
        with urllib.request.urlopen(upload_req, timeout=45) as resp:
            upload_result = json.loads(resp.read().decode('utf-8'))
        print(f"    upload result: {upload_result}", file=sys.stderr)
    except Exception as e:
        print(f"    upload failed: {e}", file=sys.stderr)
    
    # 清理临时文件
    for lp in local_paths:
        try: os.unlink(lp)
        except: pass
    
    # 等待上传完成, 读取 materialList (server 端已处理等待+点确定)
    time.sleep(3)
    after = cdp_eval(target,
        "var f=window.__wb_form;return f?f.values.materialList.length:'NF'")
    after_count = int(after) if str(after).isdigit() else 0
    print(f"    materialList: 0 -> {after_count}", file=sys.stderr)
    
    if after_count > 0:
        ml = cdp_eval(target,
            "var f=window.__wb_form;var ml=f.values.materialList;return JSON.stringify(ml)")
        try:
            jd_urls = json.loads(ml) if ml else []
            for u in jd_urls:
                print(f"    -> {str(u)[:80]}", file=sys.stderr)
        except: pass
    
    if not jd_urls:
        # 兜底: 直接用 setValuesIn 写回已下载的 URL
        print(f"  [{label}] native upload failed, trying direct setValuesIn...", file=sys.stderr)
        # 如果已经是 JD CDN URL, 直接写入
        jd_urls = [u for u in urls if '360buyimg.com' in u or 'jddj' in u]
        if not jd_urls:
            return ("failed", f"{label}: all uploads failed")
    
    urls_json = json.dumps(jd_urls, ensure_ascii=False)
    js = f"var f=window.__wb_form;if(f)f.setValuesIn('{form_field}',{urls_json});JSON.stringify({{n:(f?f.values.{form_field}:[]).length}});"
    result = cdp_eval(target, js)
    try:
        count = json.loads(result).get('n', 0)
    except:
        count = len(jd_urls)
    
    return ("filled", f"{label}: {count}张 \u2713")

def fill_wang_editor(target, field_map, task):
    label = field_map['label']
    source = field_map['source']
    max_n = field_map.get('max', 14)
    
    if source == 'images_detail':
        urls = task.get('images_detail', [])
    elif source == 'images_mainThumb':
        urls = task.get('images_mainThumb', [])
    else:
        return ("skipped", f"{label}: unknown source")
    
    if not urls:
        return ("skipped", f"{label}: no URLs")
    
    urls = urls[:max_n]
    print(f"  [{label}] inserting {len(urls)} detail images", file=sys.stderr)
    
    img_tags = ''.join(f'<p style="text-align:center"><img src="{u}" style="max-width:100%"/></p>' for u in urls)
    
    insert_js = f"""(function(){{
var ed=document.querySelector('.w-e-text');
if(!ed)return'NO_EDITOR';
ed.innerHTML={json.dumps(img_tags, ensure_ascii=False)};
ed.dispatchEvent(new Event('input',{{bubbles:true}}));
ed.dispatchEvent(new Event('change',{{bubbles:true}}));
ed.dispatchEvent(new Event('blur',{{bubbles:true}}));
return'ok:'+ed.querySelectorAll('img').length;
}})()"""
    result = cdp_eval(target, insert_js)
    
    toggle_js = """(function(){
var radios=document.querySelectorAll('.jd-radio');
for(var i=0;i<radios.length;i++){
if(radios[i].textContent.indexOf('对用户展示')>-1 && !radios[i].classList.contains('is-checked')){
radios[i].click();return'clicked';
}}
return'skip';
})()"""
    try: cdp_eval(target, toggle_js)
    except: pass
    
    clear_js = "var f=window.__wb_form;if(f)f.setValuesIn('synopsisImages',[]);'ok'"
    try: cdp_eval(target, clear_js)
    except: pass
    
    n = 0
    try:
        if 'ok:' in str(result):
            n = int(str(result).split(':')[1])
    except:
        n = len(urls)
    
    return ("filled", f"{label}: {n}张 \u2713 (WangEditor)")

# ============ 主流程 ============
def fill_form(task_file, dry_run=False, skip_nav=False, target_id_override=None):
    task = json.load(open(task_file, encoding='utf-8'))
    mapping = load_mapping(task.get('target_site', ''))
    if not mapping: return {"success": False, "need_ai": True, "error": "no mapping"}
    target_url = mapping.get('target_url', task.get('target_url', ''))
    if not target_url: return {"success": False, "need_ai": True, "error": "no url"}

    if dry_run:
        flds = [f['label'] for f in mapping.get('text_fields', [])] + [f['label'] for f in mapping.get('image_fields', [])]
        return {"success": True, "dry_run": True, "would_fill": flds}

    if target_id_override:
        target_id = target_id_override
        print(f"[jd_instant] using override tab: {target_id}", file=sys.stderr)
    elif skip_nav:
        tabs = cdp_targets()
        jd_tabs = [t for t in tabs if JD_DOMAIN in t.get('url', '')]
        if jd_tabs:
            target_id = jd_tabs[-1]['targetId']
            print(f"[jd_instant] skip nav, using: {target_id}", file=sys.stderr)
        else:
            return {"success": False, "need_ai": True, "error": "JD tab not found, need navigate"}
    else:
        target_id = find_or_create_tab(target_url)
    if not target_id: return {"success": False, "need_ai": True, "error": "nav failed"}

    results, filled, skipped, failed = [], [], [], []

    cache_js = "var f=null,vn=document.getElementById('app')._vnode;(function w(vn,d){if(d>20||!vn||f)return;if(vn.component&&vn.component.props&&vn.component.props.form)f=vn.component.props.form;if(vn.component&&vn.component.subTree)w(vn.component.subTree,d+1);if(Array.isArray(vn.children)){for(var i=0;i<vn.children.length;i++)w(vn.children[i],d+1)}if(Array.isArray(vn.dynamicChildren)){for(var i=0;i<vn.dynamicChildren.length;i++)w(vn.dynamicChildren[i],d+1)}})(vn,0);window.__wb_form=f;JSON.stringify({ok:!!f})"
    try: cdp_eval(target_id, cache_js)
    except: pass

    for f in mapping.get('text_fields', []):
        ftype = f.get('type', 'text')
        t1 = time.time()
        if ftype == 'brand':
            status, msg = fill_brand(target_id, f, task)
        elif ftype == 'category':
            status, msg = fill_category(target_id, f, task)
        elif ftype == 'store_category':
            status, msg = fill_store_category(target_id, f, task)
        else:
            status, msg = fill_text(target_id, f, task)
        elapsed = time.time() - t1
        print(f"  [{f['label']}] elapsed: {elapsed:.1f}s", file=sys.stderr)
        if status == 'filled': filled.append(f['label'])
        elif status == 'skipped': skipped.append(f['label'])
        else: failed.append(f['label'])

    for f in mapping.get('image_fields', []):
        ftype = f.get('type', '')
        if ftype == 'form_set':
            status, msg = fill_form_images_cached(target_id, f, task)
        elif ftype == 'wang_editor':
            status, msg = fill_wang_editor(target_id, f, task)
        else:
            status, msg = fill_images(target_id, f, task)
        results.append(msg)
        if status == 'filled': filled.append(f['label'])
        elif status == 'skipped': skipped.append(f['label'])
        else: failed.append(f['label'])

    skipped += mapping.get('skip_fields', [])
    ss = os.path.join(tempfile.gettempdir(), 'workbuddy_form_filled.png')
    try: cdp_screenshot(target_id, ss)
    except: ss = None
    
    print(f"[jd_instant] done. filled={len(filled)}({','.join(filled)}) skipped={len(skipped)} failed={len(failed)}", file=sys.stderr)

    unmapped = check_unmapped(task, mapping)
    
    ai_required = []
    for f in mapping.get('text_fields', []):
        label = f['label']
        if label in skipped and label in mapping.get('skip_fields', []):
            src = f.get('source', '')
            val = extract_value(task, src) if src else ''
            ai_required.append({
                "field": label,
                "selector_type": f.get('type', 'text'),
                "selector": f.get('selector', ''),
                "value": val
            })
    for label in failed:
        ai_required.append({
            "field": label,
            "selector_type": "text",
            "selector": "",
            "value": ""
        })
    
    return {
        "success": len(filled) > 0,
        "need_ai": len(filled) == 0,
        "filled": filled, "skipped": skipped, "failed": failed,
        "unmapped_params": unmapped, "screenshot": ss, "details": results,
        "ai_required": ai_required
    }

def check_unmapped(task, mapping):
    text_sources = [f.get('source','') for f in mapping.get('text_fields', [])]
    unmapped = []
    for p in task.get('product', {}).get('params', []):
        src = f"params.{p['key']}"
        if src not in text_sources and p['key'] not in mapping.get('skip_fields', []):
            if len(p['key']) > 1 and not re.match(r'^\d+(\.\d+)?$', p['key']):
                unmapped.append(p['key'])
    return unmapped[:10]

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python -m strategies.jd_instant <task.json> [--skip-nav]"}))
        sys.exit(1)
    skip_nav = '--skip-nav' in sys.argv
    try:
        result = fill_form(sys.argv[1], dry_run='--dry-run' in sys.argv, skip_nav=skip_nav)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}, ensure_ascii=False))
