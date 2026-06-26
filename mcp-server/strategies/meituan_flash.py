"""美团闪购 (meituan_flash) 填表策略 — Phase 1-6 逐字段实现
架构: React 外壳 + Vue2/iView(boo-) iframe (#hashframe)
表单: #/reuse/sc/product/views/merchant/product/addDetail

约定: _raw_iframe_eval 已提供 function(document){JS} 作用域,
      所有 JS 字符串直接用 return 语句, 不要额外包 (function(){...})()
"""
import json, sys, time, os, re, tempfile, subprocess

from lib.cdp import (CDP, cdp_targets, cdp_navigate,
                     cdp_set_files, cdp_upload_files, cdp_click_xy, cdp_screenshot)
from lib.utils import load_mapping, js_escape, resolve_selector, extract_value, get_local_paths

# 直连 cdp_eval (subprocess+curl 避免 urllib 中文编码截断)
def _cdp_eval(target, js_code):
    import tempfile
    tf = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8')
    try:
        tf.write(js_code)
        tf.close()
        r = subprocess.run(
            ['curl', '-s', '-X', 'POST', f'{CDP}/eval?target={target}', '--data-binary', f'@{tf.name}'],
            capture_output=True, text=True, timeout=60, encoding='utf-8')
        resp = json.loads(r.stdout)
        if 'value' in resp:
            return resp['value']
        if 'error' in resp:
            return f'CDP_EVAL_ERR:{resp["error"]}'
        return ''
    except subprocess.TimeoutExpired:
        return 'CDP_TIMEOUT'
    except Exception as e:
        return f'CDP_ERR:{e}'
    finally:
        os.unlink(tf.name)

MT_DOMAIN = "shangoue.meituan.com"
IFRAME_ID = "hashframe"


def _raw_iframe_eval(target, js_code):
    """在 iframe 内执行 JS, 直接返回原始结果.
    
    包装为: (function(document){js_code})(contentDocument)
    调用方 JS 直接访问 document 变量, 用 return 返回结果即可.
    """
    full = (
        "(function(){var f=document.querySelector('#" + IFRAME_ID + "');"
        "if(!f||!f.contentDocument)return'NO_IFRAME';"
        "var _d=f.contentDocument;"
        "return (function(document){" + js_code + "})(_d);})()"
    )
    return _cdp_eval(target, full)


# ═══════════════════════════════════════════════════════════
# 任务前清理
# ═══════════════════════════════════════════════════════════

def _reset_form(target):
    """清理表单残留数据 (类目/名称/图片等)，确保新任务不受旧数据污染."""
    print(f"  [meituan_flash] resetting form...", file=sys.stderr)
    js = (
        "var cleaned=0;"
        # 1. 清除类目标签 (含关闭按钮)
        "var tagCloses=document.querySelectorAll('.category-path .tag .close');"
        "if(tagCloses.length>0){"
        "for(var i=0;i<tagCloses.length;i++){tagCloses[i].click();cleaned++;}"
        "}"
        # 2. 清除商品名称 (第一个规范命名placeholder的input)
        "var nameInput=document.querySelector('input[placeholder*=\"规范命名\"]');"
        "if(nameInput&&nameInput.value){"
        "var desc=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');"
        "desc.set.call(nameInput,'');"
        "nameInput.dispatchEvent(new InputEvent('input',{bubbles:true,data:''}));"
        "nameInput.dispatchEvent(new Event('change',{bubbles:true}));"
        "cleaned++;}"
        # 3. 清除规格表格内容
        "var rows=document.querySelectorAll('table tbody tr');"
        "if(rows.length>0){"
        "var firstRow=rows[0];"
        "var cells=firstRow.querySelectorAll('input');"
        "for(var j=0;j<cells.length;j++){"
        "desc.set.call(cells[j],'');"
        "cells[j].dispatchEvent(new InputEvent('input',{bubbles:true}));"
        "}cleaned++;}"
        "return 'cleaned:'+cleaned")
    r = _raw_iframe_eval(target, js)
    print(f"  [meituan_flash] reset: {r}", file=sys.stderr)
    time.sleep(0.5)


# ═══════════════════════════════════════════════════════════
# Phase 主流程
# ═══════════════════════════════════════════════════════════

def fill_form(task_file, dry_run=False, skip_nav=False):
    task = json.load(open(task_file, encoding='utf-8'))
    mapping = load_mapping(task.get('target_site', 'meituan_flash'))
    if not mapping:
        return {"success": False, "need_ai": True, "error": "no mapping for meituan_flash"}

    if dry_run:
        flds = [f['label'] for f in mapping.get('text_fields', [])]
        return {"success": True, "dry_run": True, "would_fill": flds}

    # 找美团闪购标签页
    tabs = cdp_targets()
    mt_tabs = [t for t in tabs if MT_DOMAIN in t.get('url', '')]
    if not mt_tabs:
        return {"success": False, "need_ai": True, "error": "Meituan tab not found"}
    add_tabs = [t for t in mt_tabs if 'addDetail' in t.get('url', '')]
    if add_tabs:
        target_id = add_tabs[-1]['targetId']
    else:
        att_tabs = [t for t in mt_tabs if t.get('attached')]
        target_id = att_tabs[-1]['targetId'] if att_tabs else mt_tabs[-1]['targetId']
    print(f"[meituan_flash] using tab: {target_id}", file=sys.stderr)

    # 激活标签页 (后台标签页点击事件可能被浏览器节流)
    _cdp_eval(target_id, "document.title")  # 强制 attach session
    import urllib.request as _ur
    _ur.urlopen(_ur.Request(f'{CDP}/activate?target={target_id}', data=b'', method='POST'), timeout=5)
    time.sleep(0.5)

    check = _raw_iframe_eval(target_id, "return document.title || 'NO_TITLE'")
    if 'NO_IFRAME' in str(check):
        return {"success": False, "need_ai": True, "error": "iframe #hashframe not accessible"}
    print(f"[meituan_flash] iframe ready: {check}", file=sys.stderr)

    # ===== 任务前清理: 重置表单状态 (避免上次任务的残留数据) =====
    _reset_form(target_id)

    results, filled, skipped, failed = [], [], [], []
    category_clicked = False

    # ===== Phase 1: 文本字段 =====
    for f in mapping.get('text_fields', []):
        ftype = f.get('type', 'text')
        if ftype == 'text':
            status, msg = _fill_text(target_id, f, task)
        elif ftype in ('brand', 'category', 'store_category'):
            status, msg = ("skipped", f"{f['label']}: not yet implemented")
        else:
            status, msg = _fill_text(target_id, f, task)

        if status == 'filled': filled.append(f['label'])
        elif status == 'skipped': skipped.append(f['label'])
        else: failed.append(f['label'])
        results.append(msg)

        post_results = _do_post_actions(target_id, f)
        for pr in post_results:
            results.append(pr)
            if pr.startswith('category_recommend') and 'clicked' in pr:
                filled.append('商品类目(推荐)')
                category_clicked = True
                time.sleep(1.0)

    # ===== Phase 1b: 类目关键词 =====
    if not category_clicked:
        cat_kw = _fill_category_keyword(target_id, task)
        if cat_kw:
            results.append(cat_kw)
            filled.append('商品类目')
        else:
            results.append("category_keyword: already exists (pre-check)")
        category_clicked = True
        time.sleep(1.0)

    # ===== Phase 3: 规格表格 =====
    for f in mapping.get('table_fields', []):
        status, msg = _fill_table_row(target_id, f, task)
        if status == 'filled': filled.append(f['label'])
        elif status == 'skipped': skipped.append(f['label'])
        else: failed.append(f['label'])
        results.append(msg)

    # ===== Phase 6: 图片上传 (主图暂禁用, 详情图正常) =====
    uploaded_main_urls = []
    for f in mapping.get('image_fields', []):
        if f.get('type') == 'detail':
            status, msg = _fill_detail_images(target_id, f, task)
            if status == 'filled': filled.append(f['label'])
            elif status == 'skipped': skipped.append(f['label'])
            else: failed.append(f['label'])
            results.append(msg)
        else:
            skipped.append(f['label'])
            results.append(f"  [{f['label']}] skipped (main image upload disabled)")
            print(f"  [{f['label']}] ⏭️ 主图上传已禁用, 跳过", file=sys.stderr)

    # ===== 兜底: 轮询 undo 按钮 =====
    if not category_clicked:
        print(f"  [meituan_flash] retrying undo (max 15s)...", file=sys.stderr)
        _raw_iframe_eval(target_id, "document.body.click();return'clicked'")
        time.sleep(0.3)
        end = time.time() + 15
        while time.time() < end:
            r = _raw_iframe_eval(target_id,
                "var btn=document.querySelector('.undo-edit');"
                "if(!btn)return'wait';btn.click();return'clicked'")
            if 'clicked' in str(r):
                category_clicked = True
                results.append("category_recommend: clicked ✓ (retry)")
                filled.append('商品类目(推荐)')
                time.sleep(1.0); break
            time.sleep(0.5)

    # ===== Phase 2: 商品属性 =====
    _wait_for_attributes(target_id, timeout=15)
    attr_status, attr_msg = _fill_attributes(target_id, task)
    if attr_status == 'filled': filled.append('商品属性')
    elif attr_status == 'skipped': skipped.append('商品属性')
    if attr_msg: results.append(attr_msg)

    # ===== Phase 4: 店内分类 =====
    for f in mapping.get('select_fields', []):
        status, msg = _fill_boo_select(target_id, f, task)
        if status == 'filled': filled.append(f['label'])
        elif status == 'skipped': skipped.append(f['label'])
        else: failed.append(f['label'])
        results.append(msg)

    # ===== Post-sync: 重新写入父组件图片状态 (防止后续属性/品牌操作触发 Vue 重渲染覆盖) =====
    if uploaded_main_urls:
        post_urls = json.dumps(uploaded_main_urls, ensure_ascii=False)
        post_sync = _raw_iframe_eval(target_id,
            "var pc=document.querySelector('.product-picture-container');"
            "if(!pc)return'NO_PC';"
            "var pp=pc;while(pp&&!pp.__vue__)pp=pp.parentElement;"
            "if(!pp||!pp.__vue__)return'NO_PP';"
            "var urls=" + post_urls + ";"
            "var prods=[];"
            "for(var i=0;i<urls.length;i++){prods.push({src:urls[i],url:urls[i]});}"
            "pp.__vue__.value=prods;"
            "pp.__vue__.showList=true;"
            "return JSON.stringify({restored:prods.length})")
        print(f"[meituan_flash] post-sync images: {post_sync}", file=sys.stderr)

    print(f"[meituan_flash] done. filled={len(filled)} skipped={len(skipped)} failed={len(failed)}", file=sys.stderr)
    return {
        "success": len(filled) > 0,
        "need_ai": len(filled) == 0,
        "filled": filled, "skipped": skipped, "failed": failed,
        "screenshot": None, "details": results,
        "ai_required": []
    }


# ═══════════════════════════════════════════════════════════
# Phase 1b: 类目关键词
# ═══════════════════════════════════════════════════════════

def _fill_category_keyword(target, task):
    name = task.get('product', {}).get('name', '')
    if not name:
        return None

    keywords = ['洗衣机', '冰箱', '空调', '电视', '热水器', '油烟机', '电饭煲',
                '微波炉', '烤箱', '风扇', '取暖器', '净水器', '洗碗机', '消毒柜']
    kw = None
    for k in keywords:
        if k in name:
            kw = k; break
    if not kw:
        kw = name[-4:] if len(name) >= 4 else name

    print(f"  [商品类目] filling keyword: {kw}", file=sys.stderr)

    # 3秒预检: 如果类目已通过推荐引擎出现则跳过手动填充
    end = time.time() + 3
    while time.time() < end:
        r = _raw_iframe_eval(target,
            "var inp=document.querySelector('input[placeholder*=\" > \"]');"
            "if(inp){var v=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')"
            ".get.call(inp);if(v&&v.indexOf(' > ')>0)return'EXISTS';}"
            "return'wait'")
        if 'EXISTS' in str(r):
            print(f"  [商品类目] already exists, skip keyword fill", file=sys.stderr)
            return None
        time.sleep(0.3)

    safe_kw = js_escape(kw)

    # 填关键词 (无 IIFE, _raw_iframe_eval 已提供 document 作用域)
    _raw_iframe_eval(target,
        "var inps=document.querySelectorAll('input[placeholder]');"
        "var catInp=inps[2];"
        "if(!catInp)return'NI';"
        "catInp.focus();catInp.click();"
        "var desc=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');"
        f"desc.set.call(catInp,'{safe_kw}');"
        "catInp.dispatchEvent(new InputEvent('input',{bubbles:true,composed:true,"
        f"data:'{safe_kw}',inputType:'insertText'}}));"
        "catInp.dispatchEvent(new Event('change',{bubbles:true,composed:true}));"
        "return'ok'")

    # 轮询 popup → 匹配 → 点击
    JS_SCAN = (
        "var kw='" + js_escape(kw) + "';"
        "var ps=document.querySelectorAll('.boo-poptip-popper');"
        "var candidate=null,candidateTexts='';"
        "for(var pi=0;pi<ps.length;pi++){"
        "if(!ps[pi].offsetParent)continue;"
        "var spans=ps[pi].querySelectorAll('span');"
        "var s='';var matchIdx=-1;"
        "for(var i=0;i<spans.length;i++){"
        "var t=spans[i].textContent.trim();"
        "if(t.length>=2&&t.length<=50)s+=(s?'|':'')+t;"
        "if(t===kw||(kw.length>=2&&t.indexOf(kw)>=0))matchIdx=i;}"
        "if(matchIdx>=0){candidate={pi:pi,idx:matchIdx,texts:s};break;}"
        "if(!candidate&&s.length>0){candidateTexts=s;}}"
        "return candidate?JSON.stringify(candidate):('WAIT:'+candidateTexts)")

    end = time.time() + 30
    clicked = False
    while time.time() < end and not clicked:
        r = _raw_iframe_eval(target, JS_SCAN)
        if not r or r == '[]':
            time.sleep(0.5); continue
        if str(r).startswith('WAIT'):
            time.sleep(0.5); continue
        try:
            info = json.loads(str(r))
            pi = info.get('pi', -1)
            match_idx = info.get('idx', -1)
        except:
            time.sleep(0.5); continue
        if pi < 0 or match_idx < 0:
            time.sleep(0.5); continue
        r2 = _raw_iframe_eval(target,
            "var ps=document.querySelectorAll('.boo-poptip-popper');"
            f"var p=ps[{pi}];"
            "var spans=p.querySelectorAll('span');var items=[];"
            "for(var i=0;i<spans.length;i++){"
            "var t=spans[i].textContent.trim();"
            "if(t.length>=2&&t.length<=50)items.push(spans[i]);}"
            f"if(items.length<={match_idx})return'NI';"
            f"items[{match_idx}].click();return'clicked'")
        if 'clicked' in str(r2):
            print(f"  [商品类目] clicked '{kw}'", file=sys.stderr)
            clicked = True; break
        time.sleep(0.5)

    if not clicked:
        return f"category_keyword: dropdown not found for '{kw}'"

    # 轮询 undo
    end = time.time() + 15
    while time.time() < end:
        r = _raw_iframe_eval(target,
            "var btn=document.querySelector('.undo-edit');"
            "if(!btn)return'wait';btn.click();return'clicked'")
        if 'clicked' in str(r):
            print(f"  [商品类目] undo clicked", file=sys.stderr)
            return "category_keyword: clicked ✓"
        time.sleep(0.5)

    return "category_keyword: selected but undo not found"


# ═══════════════════════════════════════════════════════════
# Phase 1: 文本字段
# ═══════════════════════════════════════════════════════════

def _fill_text(target, field_map, task):
    label = field_map['label']
    sel_spec, source = field_map['selector'], field_map['source']
    max_len = field_map.get('max_len', 999)

    val = extract_value(task, source)
    if not val:
        return ("skipped", f"{label}: no data")
    val = val[:max_len]
    safe_val = js_escape(val)

    print(f"  [{label}] filling: {val[:40]}", file=sys.stderr)
    sel = resolve_selector(target, sel_spec)
    js = (
        f"var el=document.querySelector('{sel}');"
        f"if(!el)return'NF';"
        f"el.focus();"
        f"var desc=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');"
        f"if(desc&&desc.set)desc.set.call(el,'{safe_val}');"
        f"else el.value='{safe_val}';"
        f"el.dispatchEvent(new InputEvent('input',{{bubbles:true,data:'{safe_val}'}}));"
        f"el.dispatchEvent(new Event('change',{{bubbles:true}}));"
        f"el.dispatchEvent(new Event('blur',{{bubbles:true}}));"
        f"return el.value.length")
    result = _raw_iframe_eval(target, js)
    if 'NF' in str(result):
        return ("failed", f"{label}: selector [{sel_spec}]")
    return ("filled", f"{label}: {val}")


# ═══════════════════════════════════════════════════════════
# Phase 3: 规格表格
# ═══════════════════════════════════════════════════════════

def _fill_table_row(target, field_map, task):
    label = field_map['label']
    columns = field_map.get('columns', [])
    print(f"  [{label}] filling spec table ({len(columns)} columns)", file=sys.stderr)

    filled_cols, failed_cols = [], []
    for col in columns:
        col_label = col.get('label', '')
        col_idx = col.get('col', 0)
        source = col.get('source', '')
        max_len = col.get('max_len', 999)
        unit = col.get('unit', '')  # 可选单位, 如 "千克(kg)" / "克(g)"

        val = extract_value(task, source)
        if not val:
            continue
        val = val[:max_len]
        safe_val = js_escape(val)
        print(f"    [{col_label}] col={col_idx} val={val[:30]}", file=sys.stderr)

        input_sel = 'input[type="text"]' if col_idx == 3 else 'input'
        js = (
            f"var row=document.querySelector('table tbody tr');"
            f"if(!row)return'NO_ROW';"
            f"var cell=row.cells[{col_idx}];if(!cell)return'NO_CELL';"
            f"var el=cell.querySelector('{input_sel}');"
            f"if(!el)return'NF';"
            f"el.focus();"
            f"var desc=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');"
            f"if(desc&&desc.set)desc.set.call(el,'{safe_val}');"
            f"else el.value='{safe_val}';"
            f"el.dispatchEvent(new InputEvent('input',{{bubbles:true,data:'{safe_val}'}}));"
            f"el.dispatchEvent(new Event('change',{{bubbles:true}}));"
            f"return el.value.length")
        result = _raw_iframe_eval(target, js)

        # 重量单位选择: 分步执行，等Vue响应后再设单位
        if unit and 'NF' not in str(result) and 'NO_ROW' not in str(result) and 'NO_CELL' not in str(result):
            time.sleep(0.4)
            unit_safe = json.dumps(unit, ensure_ascii=True)
            unit_js = (
                f"var row=document.querySelector('table tbody tr');"
                f"if(!row)return'NO_ROW';"
                f"var cell=row.cells[{col_idx}];"
                f"var vu=cell.querySelector('[selectkey]');"
                f"if(!vu||!vu.__vue__||!vu.__vue__.value)return'NV';"
                f"vu.__vue__.value.unit={unit_safe};"
                f"return'ok'")
            u_result = _raw_iframe_eval(target, unit_js)
            print(f"    [{col_label}] unit={'ok' if 'ok' in str(u_result) else repr(u_result)[:40]}", file=sys.stderr)

        if 'NF' in str(result) or 'NO_ROW' in str(result) or 'NO_CELL' in str(result):
            failed_cols.append(col_label)
        else:
            filled_cols.append(col_label)

    if not filled_cols and not failed_cols:
        return ("skipped", f"{label}: no data")
    if failed_cols:
        return ("filled", f"{label}: {len(filled_cols)}/{len(columns)} cols (failed: {','.join(failed_cols)})")
    return ("filled", f"{label}: {len(filled_cols)} cols")


# ═══════════════════════════════════════════════════════════
# 品牌提取
# ═══════════════════════════════════════════════════════════

# 已知美的子品牌关键词 → 品牌名
SUB_BRAND_MAP = {
    '华凌': '华凌',
    '小天鹅': '小天鹅',
    '东芝': '东芝',
    'COLMO': 'COLMO',
    'colmo': 'COLMO',
    'Comfee': 'Comfee',
    'comfee': 'Comfee',
}

def _extract_brand(name):
    """从商品名称中提取品牌: 优先匹配子品牌, 默认'美的'"""
    for keyword, brand in SUB_BRAND_MAP.items():
        if keyword in name:
            return brand
    return '美的'


# ═══════════════════════════════════════════════════════════
# 品牌搜索
# ═══════════════════════════════════════════════════════════

def _fill_brand_search(target, brand):
    """品牌字段: category-attrs-brand 搜索级联选择器.
    输入关键词 → 等待下拉 → 点击匹配项.
    """
    safe_brand = js_escape(brand)
    print(f"  [品牌] searching: {brand}", file=sys.stderr)

    # 1. 输入关键词
    r = _raw_iframe_eval(target,
        "var inp=document.querySelector('.category-attrs-brand input');"
        "if(!inp)return'NI';"
        "inp.focus();inp.click();"
        "var desc=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');"
        f"desc.set.call(inp,'{safe_brand}');"
        f"inp.dispatchEvent(new InputEvent('input',{{bubbles:true,data:'{safe_brand}'}}));"
        f"inp.dispatchEvent(new Event('change',{{bubbles:true}}));"
        "return'ok'")
    if 'NI' in str(r):
        print(f"  [品牌] no input found", file=sys.stderr)
        return False

    # 2. 轮询下拉并点击匹配项
    end = time.time() + 10
    while time.time() < end:
        r2 = _raw_iframe_eval(target,
            f"var kw='{safe_brand}';"
            "var ps=document.querySelectorAll('.boo-poptip-popper');"
            "for(var i=0;i<ps.length;i++){{"
            "if(!ps[i].offsetParent)continue;"
            "var items=ps[i].querySelectorAll('.boo-cascader-item,.menuItem,li');"
            "for(var j=0;j<items.length;j++){{"
            "var t=items[j].textContent.trim();"
            "if(t.indexOf(kw)>-1){{items[j].click();return'clicked:'+t;}}"
            "}}}}"
            "return'wait'")
        if 'clicked' in str(r2):
            print(f"  [品牌] clicked: {r2}", file=sys.stderr)
            return True
        time.sleep(0.3)

    print(f"  [品牌] dropdown timeout for '{brand}'", file=sys.stderr)
    return False


# ═══════════════════════════════════════════════════════════
# Phase 2: 商品属性
# ═══════════════════════════════════════════════════════════

def _wait_for_attributes(target, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        r = _raw_iframe_eval(target,
            "var sels=document.querySelectorAll('.category-attr-selector');"
            "var texts=document.querySelectorAll('.category-attr-text');"
            "var structs=document.querySelectorAll('.category-attr-structured-container');"
            "var count=sels.length+texts.length+structs.length;"
            "if(count>=3)return'FOUND:'+count;"
            "return'wait'")
        if 'FOUND' in str(r):
            print(f"  [商品属性] {r}", file=sys.stderr)
            return
        time.sleep(0.5)
    print(f"  [商品属性] attr fields not appeared (timeout)", file=sys.stderr)


def _fill_attributes(target, task):
    """v2.0: 使用 mt_attr_mapping.json 层级映射填充类目属性。
    结构: L1=子类目路由(subcategories), L2=字段映射(mappings).
    未匹配字段写入 pending_mappings.json 供 LLM 后台解析.
    """
    # ── 0. 获取当前三级类目名 (从类目 input 中提取) ──
    cat_js = (
        "var inp=document.querySelector('input[placeholder*=\" > \"]');"
        "if(inp){var v=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value')"
        ".get.call(inp);var parts=v.split(' > ');return parts[parts.length-1]||''}"
        "return''")
    cat_raw = _raw_iframe_eval(target, cat_js)
    category_name = str(cat_raw).strip() if cat_raw else ''

    # ── 0b. 加载映射表(优先v2.0层级, fallback v1.0平铺) ──
    mapping_file = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                'mappings', 'mt_attr_mapping.json')
    attr_mapping = {}; sub_category_name = ''
    shared = {}
    if os.path.exists(mapping_file):
        with open(mapping_file, encoding='utf-8') as f:
            data = json.load(f)
        shared = data.get('_shared', {})
        # _shared 全局生效: 无论类目是否在映射表中都加载
        for sk, sv in shared.items():
            if isinstance(sv, dict):
                attr_mapping[sv.get('form_label', sk)] = sv
        cats = data.get('categories', {})
        if category_name in cats:
            cat_config = cats[category_name]
            sub_cat_field = cat_config.get('sub_category_field', '')
            default_sub = cat_config.get('default_sub', '')
            # 确定子类目
            sub_cat = default_sub
            if sub_cat_field:
                # 1) 从param_map查
                sub_src = cat_config.get('_sub_source_key', sub_cat_field)
                params = task.get('product', {}).get('params', [])
                params_map = {p['key']: p['value'] for p in params}
                for p in params:
                    if p.get('key', '') == sub_src:
                        sub_cat = p.get('value', sub_cat); break
                # 2) 从表单field label查
                if sub_cat == default_sub:
                    sc_label = cat_config.get('_sub_form_label', sub_cat_field)
                    for m in cat_config.get('subcategories', {}).get(default_sub, {}).get('mappings', []):
                        if m.get('form_label') == sc_label:
                            sv = params_map.get(m.get('source_key', ''))
                            if sv and m.get('value_map', {}).get(sv):
                                sub_cat = m['value_map'][sv]; break
            sub_cat = cat_config.get('sub_category_value_map', {}).get(sub_cat, sub_cat)
            sub_cat_mappings = cat_config.get('subcategories', {}).get(sub_cat, {}).get('mappings', [])
            # 合并子类目映射 (覆盖 _shared 同名条目)
            attr_mapping.update({m['form_label']: m for m in sub_cat_mappings})
            sub_category_name = sub_cat
        print(f"  [商品属性] category='{category_name}', sub='{sub_category_name}', "
              f"mappings={len(attr_mapping)}", file=sys.stderr)

    # ── 1. 扫描表单字段 ──
    scan_js = (
        "var texts=Array.from(document.querySelectorAll('.category-attr-text'))"
        ".map(function(el,i){var layout=el.closest('.form-item-layout');"
        "if(!layout)return null;var lab=layout.querySelector('.label span');"
        "return {t:'text',l:lab?lab.textContent.trim():'',i:i};});"
        "var sels=Array.from(document.querySelectorAll('.category-attr-selector'))"
        ".map(function(el,i){var layout=el.closest('.form-item-layout');"
        "if(!layout)return null;var lab=layout.querySelector('.label span');"
        "var src=el.__vue__&&el.__vue__.source?el.__vue__.source:[];"
        "var opts=src.map(function(s){return s.name||s.label||''}).filter(Boolean);"
        "return {t:'select',l:lab?lab.textContent.trim():'',i:i,opts:opts};});"
        "var structs=Array.from(document.querySelectorAll('.category-attr-structured-container'))"
        ".map(function(el,i){var layout=el.closest('.form-item-layout');"
        "if(!layout)return null;var lab=layout.querySelector('.label span');"
        "var units=el.querySelectorAll('.category-attr-structured-unit');"
        "var unitKeys=[];units.forEach(function(u){unitKeys.push(u.getAttribute('_attrskey')||'');});"
        "return {t:'structured',l:lab?lab.textContent.trim():'',i:i,unitKeys:unitKeys};});"
        "return JSON.stringify(texts.concat(sels).concat(structs))")
    result = _raw_iframe_eval(target, scan_js)
    try:
        all_fields = json.loads(result) if result else []
    except:
        all_fields = []

    # 品牌字段单独扫描 (.category-attrs-brand 不在 category-attr-* 体系内)
    brand_js = (
        "var el=document.querySelector('.category-attrs-brand');"
        "if(!el)return'NO_BRAND';"
        "var layout=el.closest('.form-item-layout');"
        "var lab=layout?layout.querySelector('.label span'):null;"
        "var inp=el.querySelector('input');"
        "return JSON.stringify({t:'brand_search',l:lab?lab.textContent.trim():'品牌',"
        "placeholder:inp?inp.placeholder:'',i:-1})")
    brand_result = _raw_iframe_eval(target, brand_js)
    try:
        brand_field = json.loads(brand_result) if brand_result and brand_result != 'NO_BRAND' else None
    except:
        brand_field = None

    attr_fields = [f for f in all_fields if f and f.get('l') and f['l'] != '类目属性']
    if not attr_fields:
        return ("skipped", "no attribute fields found")

    labels = [f['l'] for f in attr_fields if f['l']]
    print(f"  [商品属性] found {len(labels)} fields: {labels}", file=sys.stderr)

    # ── 2. 构建源数据 ──
    params = task.get('product', {}).get('params', [])
    param_map = {p['key']: p['value'] for p in params}
    
    # 识别能力列表分组: 将 能力名称/能力数值/能力单位 按出现的顺序分组
    # 避免 flat dict 中多组能力被覆盖
    capability_groups = []
    _cg = {}
    for p in params:
        k = p.get('key', '')
        v = p.get('value', '')
        if k == '能力名称':
            if _cg:
                capability_groups.append(_cg)
            _cg = {'name': v}
        elif k == '能力数值' and _cg:
            _cg['value'] = v
        elif k == '能力单位' and _cg:
            _cg['unit'] = v
    if _cg:
        capability_groups.append(_cg)
    if capability_groups:
        print(f"  [商品属性] 能力分组: {json.dumps(capability_groups, ensure_ascii=False)}", file=sys.stderr)
    
    name = task.get('product', {}).get('name', '')
    if name:
        m = re.search(r'[A-Z]+[\d\-]+[A-Z]*', name)
        if m:
            param_map['型号'] = m.group()
        # 品牌提取: 优先子品牌, 默认"美的"
        brand = _extract_brand(name)
        param_map['品牌名称'] = brand
        print(f"  [商品属性] 品牌={brand}", file=sys.stderr)

    filled_count = 0
    unmatched = []

    # ── 品牌字段特殊处理 (category-attrs-brand 搜索级联) ──
    if brand_field:
        brand_val = param_map.get('品牌名称', '')
        if brand_val:
            bf_result = _fill_brand_search(target, brand_val)
            if bf_result:
                filled_count += 1
                print(f"    [品牌] → {brand_val}", file=sys.stderr)

    for af in attr_fields:
        label = af['l']; ftype = af['t']; idx = af['i']
        if not label:
            continue

        mapping = attr_mapping.get(label, {})

        if ftype == 'text':
            matched_val = None
            if mapping:
                matched_val = param_map.get(mapping.get('source_key', ''))
            if not matched_val:
                for pkey, pval in param_map.items():
                    if pkey in label or label in pkey:
                        matched_val = pval; break
            if not matched_val:
                unmatched.append({'label': label, 'type': 'text', 'reason': 'no_source_match'})
                continue

            # ── 通用 transform 管道 ──
            transform = mapping.get('transform', '') if mapping else ''
            if transform and matched_val:
                # dim:N → 提取所有数字, 取第 N 个 (兼容 "525×515×910" 和 "长525*宽515*高910" 两种格式)
                if transform.startswith('dim:'):
                    try:
                        idx = int(transform.split(':')[1])
                        nums = re.findall(r'\d+(?:\.\d+)?', matched_val)
                        if idx < len(nums):
                            matched_val = nums[idx]
                    except ValueError:
                        pass

            safe_val = js_escape(matched_val)
            js = (
                f"var el=document.querySelectorAll('.category-attr-text')[{idx}];"
                f"if(!el||!el.__vue__)return'NV';"
                f"var vue=el.__vue__;"
                f"vue.value='{safe_val}';"
                f"if(typeof vue.attrHandleBlur==='function')vue.attrHandleBlur();"
                f"return'ok'")
            r = _raw_iframe_eval(target, js)
            if 'ok' in str(r):
                filled_count += 1
                print(f"    [{label}] = {matched_val[:30]} (text)", file=sys.stderr)

        elif ftype == 'select':
            source_val = param_map.get(mapping.get('source_key', ''), '') if mapping else ''
            value_map = mapping.get('value_map', {}) if mapping else {}
            default_val = mapping.get('default', '') if mapping else ''
            target_val = value_map.get(source_val) or default_val

            if not target_val:
                unmatched.append({'label': label, 'type': 'select',
                                 'reason': f'no_map:{source_val}',
                                 'select_opts': af.get('opts', [])})
                continue

            js_open = (
                f"var sel=document.querySelectorAll('.category-attr-selector')[{idx}];"
                f"if(!sel||!sel.__vue__)return'NS';"
                f"var src=sel.__vue__.source;"
                f"if(!Array.isArray(src)||!src.length)return'NO_OPTS';"
                f"var defv='{js_escape(target_val)}';"
                f"var matchedIdx=-1;"
                f"for(var k=0;k<src.length;k++){{"
                f"if(src[k].name===defv){{matchedIdx=k;break;}}}}"
                f"if(matchedIdx<0){{"
                f"var _gn=function(s){{var m=s.match(/[0-9]+/);if(m)return m[0];"
                f"var cn={{'一':'1','二':'2','三':'3','四':'4','五':'5'}};"
                f"for(var k in cn){{if(s.indexOf(k)>=0)return cn[k];}}return'';}};"
                f"var tn=_gn(defv);if(tn){{"
                f"for(var k=0;k<src.length;k++){{if(_gn(src[k].name||'')===tn){{matchedIdx=k;break;}}}}"
                f"}}}}"
                f"if(matchedIdx<0)return'NO_MATCH';"
                f"var input=sel.closest('.form-item-layout').querySelector('input');"
                f"if(!input)return'NI';"
                f"sel.dispatchEvent(new MouseEvent('mouseenter',{{bubbles:true}}));"
                f"sel.dispatchEvent(new MouseEvent('mouseover',{{bubbles:true}}));"
                f"sel.scrollIntoView({{block:'center'}});"
                f"input.focus();input.click();"
                f"return'match:'+matchedIdx")
            r = _raw_iframe_eval(target, js_open)
            if not r or not str(r).startswith('match:'):
                unmatched.append({'label': label, 'type': 'select', 'reason': f'no_option:{target_val}',
                                 'select_opts': af.get('opts', [])})
                continue
            match_idx = int(str(r).split(':')[1])
            time.sleep(0.4)

            js_click = (
                f"var popper=null;"
                f"var ps=document.querySelectorAll('.boo-poptip-popper');"
                f"for(var i=0;i<ps.length;i++){{if(ps[i].offsetParent!==null){{popper=ps[i];break;}}}}"
                f"if(!popper)return'NP';"
                f"var items=popper.querySelectorAll('.menuItem');"
                f"if(!items||items.length<={match_idx})return'NI:'+items.length;"
                f"items[{match_idx}].click();return'ok'")
            r2 = _raw_iframe_eval(target, js_click)
            if 'ok' in str(r2):
                filled_count += 1
                print(f"    [{label}] = {target_val} (select, src={source_val})", file=sys.stderr)
            else:
                unmatched.append({'label': label, 'type': 'select', 'reason': 'click_failed'})

        elif ftype == 'structured':
            # structured 字段: 数值+单位组合 (如 容量=60L → 数值=60, 单位=L)
            source_val = param_map.get(mapping.get('source_key', ''), '') if mapping else ''
            if not source_val:
                # 也尝试从产品名/参数中模糊匹配
                for pkey, pval in param_map.items():
                    if label in pkey or pkey in label:
                        source_val = pval; break
            if not source_val:
                unmatched.append({'label': label, 'type': 'structured', 'reason': 'no_source_match'})
                continue

            # 解析数值+单位: "60L"→(60,"L"), "60升"→(60,"升"), "60"→(60,"")
            match = re.match(r'([\d.]+)\s*([^\d\s]*)', str(source_val))
            if not match:
                unmatched.append({'label': label, 'type': 'structured', 'reason': f'parse_fail:{source_val}'})
                continue
            num_val = match.group(1)
            unit_val = match.group(2) or ''

            # 单位映射
            unit_map = mapping.get('unit_map', {}) if mapping else {}
            mapped_unit = unit_map.get(unit_val, unit_val)
            safe_num = js_escape(num_val)
            safe_unit = js_escape(mapped_unit)

            # 先填数值 (unit-0: text input)
            js_fill_num = (
                f"var cont=document.querySelectorAll('.category-attr-structured-container')[{idx}];"
                f"if(!cont)return'NC';"
                f"var units=cont.querySelectorAll('.category-attr-structured-unit');"
                f"if(units.length<1)return'NU';"
                f"var unit0=units[0];var inp=unit0.querySelector('input');"
                f"if(!inp)return'NI';"
                f"var desc=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');"
                f"desc.set.call(inp,'{safe_num}');"
                f"inp.dispatchEvent(new InputEvent('input',{{bubbles:true}}));"
                f"inp.dispatchEvent(new Event('change',{{bubbles:true}}));"
                f"return'ok'")
            r = _raw_iframe_eval(target, js_fill_num)

            if 'ok' not in str(r):
                unmatched.append({'label': label, 'type': 'structured', 'reason': f'fill_num_failed:{r}'})
                continue

            # 再填单位 (unit-1: hidden input/select, 需触发Vue更新)
            if mapped_unit and idx is not None:
                time.sleep(0.3)
                js_fill_unit = (
                    f"var cont=document.querySelectorAll('.category-attr-structured-container')[{idx}];"
                    + "if(!cont)return'NC';"
                    + "var units=cont.querySelectorAll('.category-attr-structured-unit');"
                    + "if(units.length<2)return'NU2';"
                    + "var unit1=units[1];"
                    + "if(unit1.__vue__){"
                    + f"unit1.__vue__.value='{safe_unit}';"
                    + "if(typeof unit1.__vue__.attrHandleBlur==='function')unit1.__vue__.attrHandleBlur();"
                    + "}else{"
                    + "var inp2=unit1.querySelector('input');"
                    + "if(inp2){"
                    + "var d2=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value');"
                    + f"d2.set.call(inp2,'{safe_unit}');"
                    + "inp2.dispatchEvent(new InputEvent('input',{bubbles:true}));"
                    + "inp2.dispatchEvent(new Event('change',{bubbles:true}));"
                    + "}else return'NI2';}"
                    + "return'ok'")
                r2 = _raw_iframe_eval(target, js_fill_unit)
                if 'ok' in str(r2):
                    filled_count += 1
                    print(f"    [{label}] = {num_val}{mapped_unit} (structured)", file=sys.stderr)
                else:
                    unmatched.append({'label': label, 'type': 'structured',
                                     'reason': f'fill_unit_failed:{r2}'})
            else:
                filled_count += 1
                print(f"    [{label}] = {num_val} (structured, no unit)", file=sys.stderr)

    # ── 3. 写入 pending ──
    if unmatched and category_name:
        _write_pending_attr(category_name, sub_category_name, unmatched, param_map, name,
                            capability_groups=capability_groups)

    if filled_count > 0:
        return ("filled", f"attribute: {filled_count}/{len(attr_fields)} fields")
    return ("skipped", f"attribute: {len(unmatched)} unmatched, 0 filled")


def _write_pending_attr(category, sub_category, unmatched, param_map, product_name, capability_groups=None):
    """未匹配属性字段写入 pending_mappings.json"""
    # 已知无源数据的字段, 不写入pending (不浪费LLM token)
    SKIP_FIELDS = {'文字详情', '3C认证证书编号'}
    
    pending_file = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), 'mappings', 'pending_mappings.json')
    try:
        if os.path.exists(pending_file):
            with open(pending_file, encoding='utf-8') as f:
                pending = json.load(f)
        else:
            pending = []
    except:
        pending = []

    ts = int(time.time() * 1000000)
    existing_keys = {(e.get('category',''), e.get('sub_category',''), e.get('field_label','')) for e in pending}

    written = 0
    for i, u in enumerate(unmatched):
        label = u['label']
        if label in SKIP_FIELDS:
            continue  # 已知无效字段, 不写入
        
        key = (category, sub_category, label)
        if key in existing_keys:
            continue  # 去重: 同品类同子类目同字段不再写入
        existing_keys.add(key)

        entry = {
            "id": f"pmattr_{ts}_{i}",
            "type": "attr_mapping",
            "category": category,
            "sub_category": sub_category,
            "field_label": label,
            "field_type": u['type'],
            "reason": u.get('reason', 'unmatched'),
            "product_name": product_name,
            "select_opts": u.get('select_opts', []),
            "source_keys": list(param_map.keys()),  # 步骤1 LLM: 属性名匹配
            "params": param_map,  # 步骤2 LLM: 子选项值匹配 (拿到 source_key 后取 params[key])
            "capability_groups": capability_groups or [],  # 能力名称/数值/单位 分组, 保留多组关联关系
            "created_at": time.strftime('%Y-%m-%dT%H:%M:%S'),
            "resolved": False
        }
        pending.append(entry)
        written += 1

    if written > 0:
        with open(pending_file, 'w', encoding='utf-8') as f:
            json.dump(pending, f, ensure_ascii=False, indent=2)
    print(f"  [商品属性] wrote {written} pending entries (skipped {len(unmatched)-written})", file=sys.stderr)


# ═══════════════════════════════════════════════════════════
# 后置动作 & 店内分类 & 图片
# ═══════════════════════════════════════════════════════════

def _do_post_actions(target, field_map):
    actions = field_map.get('post_actions', [])
    results = []
    for action in actions:
        atype = action.get('type', '')
        if atype == 'wait_meituan_category':
            try:
                time.sleep(1.0)
                timeout = action.get('timeout', 20)
                poll = action.get('poll', 0.5)
                # 先点击 iframe 内空白处触发页面推荐检查
                _raw_iframe_eval(target,
                    "document.body.click();return'body clicked'")
                time.sleep(0.3)
                end = time.time() + timeout
                while time.time() < end:
                    r = _raw_iframe_eval(target,
                        "var btn=document.querySelector('.undo-edit');"
                        "if(!btn)return'wait';btn.click();return'clicked'")
                    if 'clicked' in str(r):
                        results.append("category_recommend: clicked \u2713")
                        time.sleep(1.0); break
                    time.sleep(poll)
                else:
                    results.append("category_recommend: no button (timeout)")
            except Exception as e:
                results.append(f"wait_meituan_category err: {e}")
    return results


def _fill_boo_select(target, field_map, task):
    label = field_map['label']
    source = field_map.get('source', '')
    print(f"  [{label}] boo-select: source={source}", file=sys.stderr)

    cat = _raw_iframe_eval(target,
        "var els=document.querySelectorAll('.category-path .tags .tag');"
        "var r=[];els.forEach(function(e){r.push(e.textContent.trim().split('×')[0].trim());});"
        "return JSON.stringify(r)")
    try:
        cat_tags = json.loads(cat) if cat else []
    except:
        cat_tags = []

    if not cat_tags:
        return ("skipped", f"{label}: no category tags to match")

    print(f"  [{label}] category tags: {cat_tags}", file=sys.stderr)
    keyword = cat_tags[-1]
    return _boo_select_search(target, keyword, field_map, label)


def _boo_select_search(target, keyword, field_map, label):
    kw_escaped = ''.join(f'\\u{ord(c):04x}' for c in keyword)

    r = _raw_iframe_eval(target,
        "var sel=document.querySelector('.boo-select');"
        "if(!sel)return'NO_SELECT';sel.click();return'opened'")
    print(f"  [{label}] open select: {r}", file=sys.stderr)
    time.sleep(0.3)

    r2 = _raw_iframe_eval(target,
        f"var inp=document.querySelector('.boo-select-dropdown input[type=\"text\"], "
        f".boo-select-dropdown .boo-input input');"
        f"if(!inp){{var dd=document.querySelector('.boo-select-dropdown');"
        f"if(!dd)return'NO_DROPDOWN';inp=dd.querySelector('input');}}"
        f"if(!inp)return'NO_INPUT';"
        f"inp.focus();inp.value='{kw_escaped}';"
        f"inp.dispatchEvent(new Event('input',{{bubbles:true}}));"
        f"inp.dispatchEvent(new Event('change',{{bubbles:true}}));"
        f"return 'ok'")
    print(f"  [{label}] type kw: {r2}", file=sys.stderr)

    if 'NO_DROPDOWN' in str(r2) or 'NO_INPUT' in str(r2):
        return ("skipped", f"{label}: dropdown not found")

    time.sleep(0.5)
    escaped_kw = js_escape(keyword)
    poll_js = (
        f"var kw='{escaped_kw}';var MAX=3000,P=100,w=0;"
        "var tid=setInterval(function(){w+=P;"
        "var items=document.querySelectorAll('.boo-select-item, .boo-select-dropdown .boo-select-item');"
        "if(!items.length)items=document.querySelectorAll('.boo-select-dropdown li');"
        "for(var j=0;j<items.length;j++){"
        "var t=(items[j].textContent||'').trim();"
        "if(t.indexOf(kw)>-1&&items[j].offsetParent!==null){"
        "items[j].click();clearInterval(tid);"
        "window.__wb_select='clicked:'+t.substring(0,20);return;}}"
        "if(w>=MAX){clearInterval(tid);window.__wb_select='timeout';}},P);return'poll'")
    _raw_iframe_eval(target, poll_js)
    time.sleep(0.3)

    check = _raw_iframe_eval(target, "return window.__wb_select||null")
    if check and 'clicked' in str(check):
        return ("filled", f"{label}: {check}")
    return ("skipped", f"{label}: no match for '{keyword}'")


def _fill_category(target, field_map, task):
    return ("skipped", "category: not yet implemented")


# ═══════════════════════════════════════════════════════════
# Phase 6: 图片上传
# ═══════════════════════════════════════════════════════════

def _fill_images(target, field_map, task):
    """图片上传 v2 — 可靠方案:
    1. Vue handleUploadClick 打开弹窗
    2. 等待弹窗内容加载
    3. 在 iframe 内创建新鲜 file input (绕过 Vue 受控 input 的 setFiles 兼容问题)
    4. CDP DOM.setFileInputFiles 注入文件
    5. 获取 File 对象, 调用 Vue uploader.processAndUploadFile 逐个上传
    6. 轮询等待图片出现, 确认/关闭弹窗
    """
    label = field_map['label']
    source = field_map.get('source', 'images_mainThumb')
    max_n = field_map.get('max', 10)

    if source == 'images_mainThumb':
        paths = get_local_paths(task, 'mainThumb', max_n)
    elif source == 'images_detail':
        return ("skipped", f"{label}: use _fill_detail_images")
    else:
        paths = get_local_paths(task, source, max_n)

    if not paths:
        return ("skipped", f"{label}: no local images")

    paths = paths[:max_n]
    abs_paths = [os.path.abspath(p).replace('\\', '/') for p in paths]
    print(f"  [{label}] uploading {len(abs_paths)} images (v2: fresh input + Vue method)", file=sys.stderr)

    # === Step 1: 打开上传弹窗 ===
    # v3.2: 先清理子组件中的旧空占位 (防止残留污染)
    pre_clean = _raw_iframe_eval(target,
        "var add=document.querySelector('.product-picture-add');"
        "if(!add||!add.__vue__)return'NO_VUE';"
        "var vs=add.__vue__.valueSelf||[];"
        "var valid=[],cleaned=0;"
        "for(var i=0;i<vs.length;i++){"
        "  if(vs[i].src&&vs[i].src.length>10){valid.push(vs[i]);}"
        "  else{cleaned++;}"
        "}"
        "add.__vue__.valueSelf.splice(0,vs.length);"
        "for(var i=0;i<valid.length;i++){add.__vue__.valueSelf.push(valid[i]);}"
        "add.__vue__.value.splice(0,add.__vue__.value.length);"
        "for(var i=0;i<valid.length;i++){add.__vue__.value.push(valid[i].src);}"
        "return JSON.stringify({cleaned:cleaned,kept:valid.length})")
    print(f"  [{label}] pre-clean: {pre_clean}", file=sys.stderr)

    r = _raw_iframe_eval(target,
        "var btn=document.querySelector('.product-picture-add');"
        "if(!btn||!btn.__vue__)return'NO_VUE';"
        "btn.__vue__.handleUploadClick();return'opened'")
    if 'NO_VUE' in str(r):
        return ("failed", f"{label}: cannot find Vue component")
    print(f"  [{label}] modal opened", file=sys.stderr)
    time.sleep(1.0)  # v3.4: 增加等待时间确保弹窗 DOM 完全渲染

    # === Step 1b: 切换到"本地上传"标签 ===
    # 弹窗默认打开"在线图库", #fileInput 在本地上传标签 (v-if 渲染)
    # 使用索引访问 (tabs[1]=本地上传) 避免 CDP for+中文比较返回空的问题
    # 弹窗完全渲染需要时间, 加最多 3 次重试
    r_tab = 'NO_MODAL'
    for tab_retry in range(4):
        if tab_retry > 0:
            time.sleep(0.5)
        r_tab = _raw_iframe_eval(target,
            "var modal=document.querySelector('.boo-modal-wrap');"
            "if(!modal)return'NO_MODAL';"
            "var tabs=modal.querySelectorAll('.boo-tabs-tab');"
            "if(tabs.length<2)return JSON.stringify({tabs:tabs.length});"
            "var localTab=tabs[1];"  # index 1 = 本地上传 (index 0 = 在线图库)
            "localTab.scrollIntoView({block:'center'});"
            "localTab.dispatchEvent(new MouseEvent('mouseenter',{bubbles:true}));"
            "localTab.dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));"
            "localTab.click();"
            "return'clicked'")
        if 'clicked' in str(r_tab):
            break
    print(f"  [{label}] switch to local upload tab: {r_tab}", file=sys.stderr)
    time.sleep(0.8)  # Vue v-if 渲染需要时间

    # === Step 2: 等待#fileInput出现 (最多 8s) ===
    # 切换"本地上传"标签后, Vue v-if 渲染需要时间
    for _ in range(16):
        time.sleep(0.5)
        chk = _raw_iframe_eval(target,
            "var fi=document.getElementById('fileInput');"
            "return fi?'ready':''")
        if 'ready' in str(chk):
            break
    print(f"  [{label}] modal content ready", file=sys.stderr)

    # === Step 3: 逐个文件上传 ===
    uploaded = 0
    failed_files = 0
    temp_id = '_mt_upload_tmp'
    uploaded_srcs = []

    try:
        for i, fp in enumerate(abs_paths):
            if not os.path.isfile(fp):
                print(f"  [{label}] file not found: {fp}", file=sys.stderr)
                failed_files += 1
                continue
            _raw_iframe_eval(target,
                "var old=document.getElementById('{tid}');if(old)old.remove();"
                "var inp=document.createElement('input');inp.type='file';inp.id='{tid}';"
                "inp.style.cssText='position:absolute;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;pointer-events:none;';"
                "document.body.appendChild(inp);return'created'".format(tid=temp_id))
            for _ in range(3):
                result = cdp_set_files(target, '#' + temp_id, [fp], iframe_selector='#hashframe')
                if result.get('success'): break
                time.sleep(0.3)
            if not result.get('success'):
                print(f"  [{label}] setFiles failed for {fp}: {result}", file=sys.stderr)
                failed_files += 1
                continue
            time.sleep(1.0)  # 上传间隔
            start_result = _raw_iframe_eval(target,
                ("try{{"
                 "var inp=document.getElementById('{tid}');"
                 "if(!inp||!inp.files||!inp.files[0])return'NF';"
                 "var fi=document.querySelector('#fileInput');"
                 "if(!fi)return'NO_FILEINPUT';"
                 "var p=fi;while(p&&!p.__vue__)p=p.parentElement;"
                 "if(!p||!p.__vue__||!p.__vue__.processAndUploadFile)return'NO_VM';"
                 "var uv=p.__vue__;"
                 "var addBtn=document.querySelector('.product-picture-add');"
                 "var cp=addBtn;while(cp&&!cp.__vue__)cp=cp.parentElement;"
                 "if(!cp||!cp.__vue__)return'NO_ADD_VUE';"
                 "var pv=cp.__vue__;"
                 "uv.loading=true;"
                 "if(!pv.valueSelf)pv.valueSelf=[];"
                 "if(!pv.value)pv.value=[];"
                 "var li=pv.valueSelf.length;"
                 "pv.valueSelf.push({{src:'',poor:true,errorTips:'uploading'}});"
                 "pv.value.push('');"
                 "try{{uv.processAndUploadFile(inp.files[0]).then("
                 "function(r){{"
                 "  if(r&&r.valid&&r.src){{"
                 "    pv.valueSelf[li].src=r.src;"
                 "    pv.valueSelf[li].poor=false;"
                 "    pv.valueSelf[li].errorTips='';"
                 "    pv.value[li]=r.src;"
                 "  }}else{{"
                 "    pv.valueSelf[li].errorTips=r?r.message||'no_valid':'no_result';"
                 "    pv.valueSelf[li].poor=false;"
                 "  }}"
                 "  uv.loading=false;"
                 "}},"
                 "function(err){{"
                 "  pv.valueSelf[li].errorTips=err?err.message||'rejected':'err';"
                 "  pv.valueSelf[li].poor=false;"
                 "  uv.loading=false;"
                 "}});"
                 "return'started:'+li;"
                 "}}catch(e){{return'PAUF_THROW:'+e.message;}}"
                 "}}catch(e){{return'SETUP_ERR:'+e.message;}}").format(tid=temp_id))
            if 'started:' in str(start_result):
                uploaded += 1
                print(f"  [{label}] file[{i}] upload started", file=sys.stderr)
            else:
                print(f"  [{label}] file[{i}] start failed: {start_result}", file=sys.stderr)
                failed_files += 1
    finally:
        _raw_iframe_eval(target,
            "var tmp=document.getElementById('{tid}');if(tmp)tmp.remove();return'cleaned'".format(tid=temp_id))

    # === Step 4: 等待上传完成 ===
    if uploaded > 0:
        print(f"  [{label}] polling for {uploaded} upload results...", file=sys.stderr)
        end = time.time() + 30; attempt = 0
        last_done = -1
        last_failed = -1
        while time.time() < end:
            poll = _raw_iframe_eval(target,
                "var vu=document.querySelector('.product-picture-add');"
                "if(!vu||!vu.__vue__)return'{err:\"NO_VUE\"}';"
                "var vs=vu.__vue__.valueSelf||[];"
                "var done=0, failed=0, urls=[];"
                "for(var i=0;i<vs.length;i++){"
                "  if(vs[i].poor)continue;"
                "  if(vs[i].src&&vs[i].src.length>10){done++;urls.push(vs[i].src);}"
                "  else failed++;}"
                "return JSON.stringify({done:done,failed:failed,total:vs.length,urls:urls})")
            try: poll_data = json.loads(poll) if poll else {}
            except: poll_data = {}
            completed = poll_data.get('done', 0)
            failed = poll_data.get('failed', 0)
            if completed != last_done or failed != last_failed:
                last_done, last_failed = completed, failed
                print(f"  [{label}]  poll: {completed}/{poll_data.get('total',0)} vs-items done (failed: {failed})", file=sys.stderr)
            if completed + failed >= uploaded:
                uploaded_srcs = poll_data.get('urls', []); break
            time.sleep(0.5 if attempt < 8 else 1.0); attempt += 1
        else:
            poll2 = _raw_iframe_eval(target,
                "var vu=document.querySelector('.product-picture-add');if(!vu||!vu.__vue__)return'[]';"
                "var vs=vu.__vue__.valueSelf||[];var urls=[];"
                "for(var i=0;i<vs.length;i++){if(vs[i].src&&vs[i].src.length>10&&!vs[i].poor)urls.push(vs[i].src);}"
                "return JSON.stringify(urls)")
            try: uploaded_srcs = json.loads(poll2) if poll2 else []
            except: uploaded_srcs = []
            print(f"  [{label}]  timeout, collected {len(uploaded_srcs)}/{uploaded}", file=sys.stderr)

    # === 关闭弹窗 (必须在 Step 5 之前, 否则父组件重渲染会销毁子组件 Vue 实例导致 handleModalHide 失效) ===
    hide_result = _raw_iframe_eval(target,
        "var add=document.querySelector('.product-picture-add');"
        # 方式1: 子组件 handleModalHide (原始实例, modalVisible=true 时有效)
        "if(add&&add.__vue__&&typeof add.__vue__.handleModalHide==='function'){"
        "try{add.__vue__.handleModalHide();return'hidden'}catch(e){}"
        "}"
        # 方式2: 直接找 boo-modal-wrap 关闭 (兜底, modal 是 Teleport 到 body 的)
        "var modal=document.querySelector('.boo-modal-wrap');"
        "if(modal&&modal.__vue__){"
        "try{modal.__vue__.visible=false;return'direct_hidden'}catch(e){}"
        "}"
        "return'NO_HIDE'")
    print(f"  [{label}] modal hide: {hide_result}", file=sys.stderr)
    time.sleep(0.5)  # 等待关闭动画和 DOM 清理

    # === Step 5: 写父组件 ProductPictureV3 (渲染 .picture-box 的权威数据源) ===
    # v3.3: 不再尝试清理 child valueSelf (会被父组件prop更新覆盖)
    # 直接构建 products 从 poll 收集的 CDN URL, 写父组件即可触发渲染
    if uploaded_srcs:
        set_val = _raw_iframe_eval(target,
            "var pc=document.querySelector('.product-picture-container');"
            "if(!pc)return'NO_PC';"
            "var pp=pc;while(pp&&!pp.__vue__)pp=pp.parentElement;"
            "if(!pp||!pp.__vue__)return'NO_PARENT_VUE';"
            "var urlList=" + json.dumps(uploaded_srcs, ensure_ascii=False) + ";"
            "var products=[];"
            "for(var i=0;i<urlList.length;i++){"
            "  products.push({src:urlList[i],url:urlList[i]});"
            "}"
            "pp.__vue__.value=products;"
            "pp.__vue__.showList=true;"
            "return JSON.stringify({n:products.length,show:pp.__vue__.showList})")
        print(f"  [{label}] sync parent: {set_val}", file=sys.stderr)
    else:
        print("  [{label}] no images to set", file=sys.stderr)

    # 重置 loading
    _raw_iframe_eval(target,
        "var fi=document.querySelector('#fileInput');"
        "if(fi){var p=fi;while(p&&!p.__vue__)p=p.parentElement;"
        "if(p&&p.__vue__)p.__vue__.loading=false;}"
        "return'done'")

    if uploaded > 0:
        return ("filled", f"{label}: {uploaded}/{len(paths)}张 \u2713")
    return ("failed", f"{label}: 0/{len(paths)}张 uploaded")

def _fill_detail_images(target, field_map, task):
    label = field_map['label']
    source = field_map.get('source', 'images_detail')
    max_n = field_map.get('max', 14)

    urls = task.get('images_detail', [])
    if not urls:
        return ("skipped", f"{label}: no detail image URLs")

    urls = urls[:max_n]
    print(f"  [{label}] injecting {len(urls)} detail images via Vue pics", file=sys.stderr)

    pics_json = json.dumps([{"src": u} for u in urls], ensure_ascii=False)
    js_code = (
        "var uc=document.querySelector('.uploader-container');"
        "if(!uc)return'NO_UPLOADER';"
        "var vm=uc.parentElement.parentElement.__vue__;"
        "if(!vm)return'NO_VM';"
        "try{vm.pics=" + pics_json + ";return'ok:'+vm.pics.length;}"
        "catch(e){return'err:'+e.message;}")
    result = _raw_iframe_eval(target, js_code)
    n = 0
    try:
        if 'ok:' in str(result):
            n = int(str(result).split(':')[1])
    except:
        n = len(urls)
    if n > 0:
        return ("filled", f"{label}: {n}张 \u2713")
    return ("failed", f"{label}: {result}")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python strategies.meituan_flash.py <task.json>"}))
        sys.exit(1)
    try:
        result = fill_form(sys.argv[1], dry_run='--dry-run' in sys.argv)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}, ensure_ascii=False))
