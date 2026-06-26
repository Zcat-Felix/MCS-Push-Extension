"""美团图片上传 debug 脚本 v2 — 简化版, 逐个步骤输出"""
import json, sys, time, os, tempfile, subprocess
sys.path.insert(0, os.path.dirname(__file__))

from strategies.meituan_flash import _raw_iframe_eval, MT_DOMAIN
from lib.cdp import cdp_targets, cdp_set_files, CDP
from lib.utils import get_local_paths

def _mcp_set_files(target, selector, files, iframe_selector=None):
    """通过 MCP Server (:5200) setFiles (支持 iframe)"""
    body = json.dumps({
        'selector': selector,
        'files': files,
        'iframeSelector': iframe_selector
    })
    tf = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8')
    try:
        tf.write(body)
        tf.close()
        r = subprocess.run(
            ['curl', '-s', '-X', 'POST', f'{CDP}/setFiles?target={target}',
             '-H', 'Content-Type: application/json', '--data-binary', f'@{tf.name}'],
            capture_output=True, text=True, timeout=30, encoding='utf-8')
        return json.loads(r.stdout)
    finally:
        os.unlink(tf.name)

def debug_img_upload():
    # Find target
    targets = cdp_targets()
    target = None
    for t in targets:
        if MT_DOMAIN in t.get('url','') and t.get('attached'):
            target = t['targetId']
            break
    if not target:
        print("ERROR: no attached Meituan tab found")
        return
    print(f"TARGET: {target}")

    # Load task
    task_path = os.path.join(os.path.dirname(__file__), 'tasks', 'task_1782272867423_0cjwan.json')
    with open(task_path) as f:
        task = json.load(f)

    paths = get_local_paths(task, 'mainThumb', 10)
    print(f"LOCAL PATHS ({len(paths)}):")
    abs_paths = [os.path.abspath(p).replace('\\', '/') for p in paths[:3]]
    for i, p in enumerate(abs_paths):
        print(f"  [{i}] {p}  exists={os.path.isfile(p)}  size={os.path.getsize(p) if os.path.isfile(p) else 'N/A'}")

    if not paths or not all(os.path.isfile(p) for p in abs_paths):
        print("FAIL: no valid local paths!")
        return

    temp_id = '_mt_debug_tmp'

    # =========== STEP 1: 初始状态 ===========
    print("\n========== STEP 1: 初始状态 ==========")
    s1 = _raw_iframe_eval(target, (
        'var add=document.querySelector(".product-picture-add");'
        'var pc=document.querySelector(".product-picture-container");'
        'var r={hasAdd:!!add,hasPc:!!pc,iframe:document.URL.substring(0,80)};'
        'if(add&&add.__vue__){r.valueSelf=add.__vue__.valueSelf;r.value=add.__vue__.value;r.modal=add.__vue__.modalVisible;}'
        'if(pc){var p=pc;while(p&&!p.__vue__)p=p.parentElement;if(p&&p.__vue__){r.pValue=p.__vue__.value;r.pShow=p.__vue__.showList;}}'
        'return JSON.stringify(r)'))
    print(f"  状态: {s1}")

    # =========== STEP 2: 打开弹窗 ===========
    print("\n========== STEP 2: 打开弹窗 ==========")
    s2 = _raw_iframe_eval(target,
        'var btn=document.querySelector(".product-picture-add");'
        'if(!btn||!btn.__vue__)return"NO_VUE";'
        'btn.__vue__.handleUploadClick();return"opened"')
    print(f"  结果: {s2}")
    time.sleep(1.0)

    # 验证弹窗
    s2b = _raw_iframe_eval(target,
        'var add=document.querySelector(".product-picture-add");'
        'return JSON.stringify({modal:add&&add.__vue__?add.__vue__.modalVisible:"NV"})')
    print(f"  弹窗状态: {s2b}")

    # =========== STEP 3: 切换到本地上传标签 ===========
    print("\n========== STEP 3: 切换标签 ==========")
    s3 = _raw_iframe_eval(target, (
        'var m=document.querySelector(".boo-modal-wrap");'
        'if(!m)return"NO_MODAL";'
        'var ts=m.querySelectorAll(".boo-tabs-tab");'
        'return JSON.stringify({count:ts.length, t0:ts[0]?ts[0].textContent.trim():null, t1:ts[1]?ts[1].textContent.trim():null})'))
    print(f"  标签: {s3}")

    s3b = _raw_iframe_eval(target, (
        'var m=document.querySelector(".boo-modal-wrap");'
        'var ts=m.querySelectorAll(".boo-tabs-tab");'
        'if(ts.length<2)return"FEW";'
        'ts[1].scrollIntoView({block:"center"});'
        'ts[1].dispatchEvent(new MouseEvent("mouseenter",{bubbles:true}));'
        'ts[1].dispatchEvent(new MouseEvent("mousedown",{bubbles:true}));'
        'ts[1].click();return"clicked"'))
    print(f"  切换结果: {s3b}")
    time.sleep(1.0)

    # 验证切换
    s3c = _raw_iframe_eval(target, (
        'var m=document.querySelector(".boo-modal-wrap");if(!m)return"NO_MODAL";'
        'var ts=m.querySelectorAll(".boo-tabs-tab");'
        'for(var i=0;i<ts.length;i++){if(ts[i].classList.contains("boo-tabs-tab-active")){'
        'return JSON.stringify({active:ts[i].textContent.trim(),idx:i})}} return"?"'))
    print(f"  当前标签: {s3c}")

    # =========== STEP 4: 等待 fileInput ===========
    print("\n========== STEP 4: 等待 fileInput ==========")
    for wi in range(16):
        time.sleep(0.5)
        chk = _raw_iframe_eval(target,
            'var fi=document.getElementById("fileInput");'
            'if(!fi)return"";'
            'return JSON.stringify({found:true,visible:fi.offsetParent!==null})')
        if 'found' in str(chk):
            print(f"  fileInput ready ({wi*0.5}s): {chk}")
            break
    else:
        print("  WARN: fileInput not found!")

    # 检查 uploader Vue
    s4b = _raw_iframe_eval(target, (
        'var fi=document.getElementById("fileInput");'
        'if(!fi)return"NO_FI";'
        'var p=fi;while(p&&!p.__vue__)p=p.parentElement;'
        'if(!p||!p.__vue__)return JSON.stringify({hasParent:!!p});'
        'var vu=p.__vue__;'
        'return JSON.stringify({hasPAUF:!!vu.processAndUploadFile,loading:vu.loading,'
        '  uploadUrl:vu.uploadUrl||"none",accept:vu.accept||"none"})'))
    print(f"  uploader Vue: {s4b}")

    # =========== STEP 5: 上传文件 ==========
    print("\n========== STEP 5: 上传文件 ==========")
    fp = abs_paths[0]
    print(f"  File: {fp}")

    # 5a: 创建临时 input
    s5a = _raw_iframe_eval(target,
        f'var old=document.getElementById("{temp_id}");if(old)old.remove();'
        f'var inp=document.createElement("input");inp.type="file";inp.id="{temp_id}";'
        f'inp.style.cssText="position:absolute;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;pointer-events:none;";'
        f'document.body.appendChild(inp);return"created"')
    print(f"  5a create: {s5a}")

    # 5b: setFiles (via MCP Server for iframe support)
    s5b = _mcp_set_files(target, '#' + temp_id, [fp], iframe_selector='#hashframe')
    print(f"  5b setFiles: {json.dumps(s5b, ensure_ascii=False)}")

    if not s5b.get('success'):
        print("  5b FAILED - trying retry...")
        time.sleep(1)
        s5b = _mcp_set_files(target, '#' + temp_id, [fp], iframe_selector='#hashframe')
        print(f"  5b retry: {json.dumps(s5b, ensure_ascii=False)}")
        if not s5b.get('success'):
            print("  5b FAILED PERMANENTLY")
            return

    time.sleep(0.5)

    # 5c: 验证文件已注入
    s5c = _raw_iframe_eval(target,
        f'var inp=document.getElementById("{temp_id}");'
        f'if(!inp)return"NO_INPUT";'
        f'var fc=inp.files?inp.files.length:0;'
        f'var fn=inp.files&&fc?inp.files[0].name:"none";'
        f'var fs=inp.files&&fc?inp.files[0].size:0;'
        f'return JSON.stringify({{files:fc,name:fn,size:fs}})')
    print(f"  5c verify: {s5c}")

    # 5d: 启动上传 (单行 JS, 避免 f-string {{}} 地狱)
    print("  5d Starting upload...")
    upload_js = (
        'var inp=document.getElementById("' + temp_id + '");'
        'if(!inp||!inp.files||!inp.files[0])return JSON.stringify({err:"NF"});'
        # Get uploader Vue
        'var fi=document.getElementById("fileInput");'
        'if(!fi)return JSON.stringify({err:"NO_FI"});'
        'var p=fi;while(p&&!p.__vue__)p=p.parentElement;'
        'if(!p||!p.__vue__||!p.__vue__.processAndUploadFile)return JSON.stringify({err:"NO_VM"});'
        'var uv=p.__vue__;'
        # Get product-picture-add Vue
        'var add=document.querySelector(".product-picture-add");'
        'var cp=add;while(cp&&!cp.__vue__)cp=cp.parentElement;'
        'if(!cp||!cp.__vue__)return JSON.stringify({err:"NO_ADD"});'
        'var pv=cp.__vue__;'
        # Set loading + placeholder
        'uv.loading=true;'
        'if(!pv.valueSelf)pv.valueSelf=[];'
        'if(!pv.value)pv.value=[];'
        'var li=pv.valueSelf.length;'
        'pv.valueSelf.push({src:"",poor:true,errorTips:"debug_uploading"});'
        'pv.value.push("");'
        # Store result flag
        'window._mt_dbg_url=null;'
        'window._mt_dbg_err=null;'
        'window._mt_dbg_done=false;'
        # Start upload with .then()
        'uv.processAndUploadFile(inp.files[0]).then(function(r){'
        '  window._mt_dbg_done=true;'
        '  if(r&&r.valid&&r.src){'
        '    window._mt_dbg_url=r.src;'
        '    if(pv.valueSelf[li]){'
        '      pv.valueSelf[li].src=r.src;'
        '      pv.valueSelf[li].poor=false;'
        '      pv.valueSelf[li].errorTips="";'
        '      pv.value[li]=r.src;'
        '    }'
        '  }else{'
        '    window._mt_dbg_err=r?r.message||JSON.stringify(r).substring(0,200):"no_result";'
        '    if(pv.valueSelf[li]){'
        '      pv.valueSelf[li].errorTips=r?r.message||"no_result":"no_result";'
        '      pv.valueSelf[li].poor=false;'
        '    }'
        '  }'
        '  uv.loading=false;'
        '},function(err){'
        '  window._mt_dbg_done=true;'
        '  window._mt_dbg_err="REJ:"+(err?err.message||String(err):"unknown");'
        '  if(pv.valueSelf[li]){'
        '    pv.valueSelf[li].errorTips=err?err.message||"rejected":"rejected";'
        '    pv.valueSelf[li].poor=false;'
        '  }'
        '  uv.loading=false;'
        '});'
        'return JSON.stringify({started:true,li:li})')
    s5d = _raw_iframe_eval(target, upload_js)
    print(f"  5d result: {s5d}")

    # =========== STEP 6: 轮询等待 ==========
    print("\n========== STEP 6: 轮询等待上传 ==========")
    for pi in range(45):
        time.sleep(1.0)
        poll = _raw_iframe_eval(target, (
            'var done=window._mt_dbg_done||false;'
            'var url=window._mt_dbg_url||null;'
            'var err=window._mt_dbg_err||null;'
            'var add=document.querySelector(".product-picture-add");'
            'var vs=add&&add.__vue__?add.__vue__.valueSelf||[]:[];'
            'var ls="";'
            'if(vs.length>0){var last=vs[vs.length-1];ls=last.src?last.src.substring(0,50):"EMPTY";}'
            'return JSON.stringify({done:done,url:url?url.substring(0,80):null,err:err,'
            '  vsLen:vs.length,lastSrc:ls})'))
        # Extract and print simplified
        try:
            pd = json.loads(poll) if poll else {}
        except:
            pd = {}
        status = "WAIT"
        if pd.get('done'):
            if pd.get('url'):
                status = "SUCCESS"
            else:
                status = "ERROR"
        print(f"  poll[{pi:02d}] {status} | done={pd.get('done',False)} len={pd.get('vsLen',0)} lastSrc={pd.get('lastSrc','-')}")

        if pd.get('done') and pd.get('url'):
            print(f"\n  >>> UPLOAD SUCCESS: {pd['url']}")
            break
        if pd.get('done') and pd.get('err'):
            print(f"\n  >>> UPLOAD FAILED: {pd['err']}")
            break

        if pi >= 20:
            # Extra check: maybe window._mt_dbg_done is not set but valueSelf has src
            if pd.get('lastSrc') and pd['lastSrc'] != 'EMPTY' and len(pd.get('lastSrc','')) > 10:
                print(f"\n  >>> UPLOAD LIKELY DONE (src in valueSelf but _mt_dbg_done not set)")
                break
    else:
        print("\n  >>> TIMEOUT - checking final state...")
        final_check = _raw_iframe_eval(target,
            'var add=document.querySelector(".product-picture-add");'
            'if(!add||!add.__vue__)return"NO_ADD";'
            'var vs=add.__vue__.valueSelf||[];'
            'var vl=add.__vue__.value||[];'
            'return JSON.stringify({vsLen:vs.length,vsLast:vs.length?JSON.stringify(vs[vs.length-1]):"null",vl:vl})')
        print(f"  Final check: {final_check}")

    # =========== STEP 7: 同步双组件 ==========
    print("\n========== STEP 7: 同步双组件 ==========")
    s7 = _raw_iframe_eval(target, (
        'var pc=document.querySelector(".product-picture-container");'
        'if(!pc)return"NO_PC";'
        'var pp=pc;while(pp&&!pp.__vue__)pp=pp.parentElement;'
        'if(!pp||!pp.__vue__)return"NO_PP";'
        'var add=document.querySelector(".product-picture-add");'
        'var cp=add;while(cp&&!cp.__vue__)cp=cp.parentElement;'
        'if(!cp||!cp.__vue__)return"NO_CP";'
        'var pv=cp.__vue__;'
        # Clean
        'var valid=[];var cleaned=0;'
        'for(var i=0;i<(pv.valueSelf||[]).length;i++){'
        '  if(pv.valueSelf[i].src&&pv.valueSelf[i].src.length>10){valid.push(pv.valueSelf[i]);}'
        '  else{cleaned++;}'
        '}'
        'pv.valueSelf=valid;'
        'pv.value=valid.map(function(item){return item.src;});'
        # Parent
        'var prods=[];'
        'for(var i=0;i<pv.value.length;i++){prods.push({src:pv.value[i],url:pv.value[i]});}'
        'pp.__vue__.value=prods;'
        'pp.__vue__.showList=true;'
        'return JSON.stringify({valid:valid.length,cleaned:cleaned,parentLen:prods.length,showList:pp.__vue__.showList})'))
    print(f"  7 同步: {s7}")

    # =========== STEP 8: 关闭弹窗 ==========
    print("\n========== STEP 8: 关闭弹窗 ==========")
    s8 = _raw_iframe_eval(target,
        'var btn=document.querySelector(".product-picture-add");'
        'if(btn&&btn.__vue__&&btn.__vue__.handleModalHide){'
        '  try{btn.__vue__.handleModalHide();return"hidden"}catch(e){return"err:"+e.message}'
        '}return"NO_HIDE"')
    print(f"  8 hide: {s8}")

    # Reset loading
    _raw_iframe_eval(target,
        'var fi=document.getElementById("fileInput");'
        'if(fi){var p=fi;while(p&&!p.__vue__)p=p.parentElement;'
        'if(p&&p.__vue__)p.__vue__.loading=false;}return"ok"')

    # =========== FINAL: 最终状态 ==========
    print("\n========== FINAL: 最终状态 ==========")
    time.sleep(0.5)
    s_final = _raw_iframe_eval(target, (
        'var add=document.querySelector(".product-picture-add");'
        'var pc=document.querySelector(".product-picture-container");'
        'var r={};'
        'if(add&&add.__vue__){r.valueSelf=add.__vue__.valueSelf;r.value=add.__vue__.value;}'
        'if(pc){var p=pc;while(p&&!p.__vue__)p=p.parentElement;'
        '  if(p&&p.__vue__){r.pValue=p.__vue__.value;r.pShow=p.__vue__.showList;}}'
        'r.visibleImgs=document.querySelectorAll(".picture-box img").length;'
        'return JSON.stringify(r)'))
    print(f"  最终: {s_final}")


if __name__ == '__main__':
    debug_img_upload()
