"""美团图片上传渲染诊断 — 上传后立即检查各组件状态"""
import json, sys, os, time, tempfile, subprocess, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from lib.cdp import CDP, cdp_targets, cdp_set_files

target = "E150316C280057CBF6B32901CDF63506"
temp_id = "_mt_diag_tmp"
fp = "C:/Users/admin/Desktop/midea-extension/mcp-server/cache/images/mainThumb/df5cd46a136a4eeb9f116dfd2178d7da.jpg"

def diag_eval(js):
    """Quick eval via MCP Server"""
    tf = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8')
    tf.write(js)
    tf.close()
    r = subprocess.run(
        ['curl', '-s', '-X', 'POST', f'{CDP}/eval?target={target}', '--data-binary', f'@{tf.name}'],
        capture_output=True, text=True, timeout=60, encoding='utf-8')
    os.unlink(tf.name)
    try:
        return json.loads(r.stdout).get('value','')
    except:
        return repr(r.stdout[:200])

def iframe_eval(js):
    """Eval inside iframe"""
    full = ("(function(){var f=document.querySelector('#hashframe');"
            "if(!f||!f.contentDocument)return'NO_IFRAME';"
            "var _d=f.contentDocument;"
            "return (function(document){" + js + "})(_d);})()")
    return diag_eval(full)

def check_state(label):
    state = iframe_eval(
        "var add=document.querySelector('.product-picture-add');"
        "var pc=document.querySelector('.product-picture-container');"
        "var r={};"
        "if(add&&add.__vue__){"
        "  r.vsLen=add.__vue__.valueSelf.length;"
        "  r.vsLast=add.__vue__.valueSelf.length?(add.__vue__.valueSelf[add.__vue__.valueSelf.length-1].src||'empty').substring(0,50):'none';"
        "  r.vLen=add.__vue__.value.length;"
        "}"
        "if(pc){var p=pc;while(p&&!p.__vue__)p=p.parentElement;"
        "  if(p&&p.__vue__){r.pLen=(p.__vue__.value||[]).length;r.pShow=p.__vue__.showList;r.pLast=(p.__vue__.value||[]).length?p.__vue__.value[0].src.substring(0,50):'none';}}"
        "r.picImgs=document.querySelectorAll('.picture-box img').length;"
        "return JSON.stringify(r)")
    print(f"  [{label}] {state}")

# === DIAG STEP 1: Current State ===
print("=== STEP 1: Current State ===")
check_state("initial")

# === DIAG STEP 2: Open Modal + Switch Tab ===
print("\n=== STEP 2: Open Modal ===")
r = iframe_eval(
    "var btn=document.querySelector('.product-picture-add');"
    "if(!btn||!btn.__vue__)return'NV';"
    "btn.__vue__.handleUploadClick();return'opened'")
print(f"  open: {r}")
time.sleep(0.8)

# Switch tab
r = iframe_eval(
    "var m=document.querySelector('.boo-modal-wrap');if(!m)return'NM';"
    "var ts=m.querySelectorAll('.boo-tabs-tab');"
    "if(ts.length<2)return'FEW';"
    "ts[1].scrollIntoView({block:'center'});"
    "ts[1].dispatchEvent(new MouseEvent('mouseenter',{bubbles:true}));"
    "ts[1].dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));"
    "ts[1].click();return'clicked'")
print(f"  tab: {r}")
time.sleep(0.8)

# Wait for fileInput
for _ in range(8):
    time.sleep(0.5)
    chk = iframe_eval("return document.getElementById('fileInput')?'ready':''")
    if 'ready' in str(chk):
        print(f"  fileInput: ready")
        break

# === DIAG STEP 3: Create temp input + setFiles ===
print("\n=== STEP 3: Upload ===")
r = iframe_eval(
    f"var old=document.getElementById('{temp_id}');if(old)old.remove();"
    f"var inp=document.createElement('input');inp.type='file';inp.id='{temp_id}';"
    f"inp.style.cssText='position:absolute;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;pointer-events:none;';"
    f"document.body.appendChild(inp);return'created'")
print(f"  create: {r}")

result = cdp_set_files(target, '#' + temp_id, [fp], iframe_selector='#hashframe')
print(f"  setFiles: {result}")
time.sleep(0.5)

# Verify file
r = iframe_eval(
    f"var inp=document.getElementById('{temp_id}');"
    f"return JSON.stringify({{files:inp&&inp.files?inp.files.length:0,name:inp&&inp.files&&inp.files[0]?inp.files[0].name:'none'}})")
print(f"  verify: {r}")

# === DIAG STEP 4: Upload via processAndUploadFile ===
print("\n=== STEP 4: processAndUploadFile ===")
upload_js = (
    "var inp=document.getElementById('{}');".format(temp_id) +
    "if(!inp||!inp.files||!inp.files[0])return'NF';"
    "var fi=document.querySelector('#fileInput');"
    "if(!fi)return'NO_FI';"
    "var p=fi;while(p&&!p.__vue__)p=p.parentElement;"
    "if(!p||!p.__vue__||!p.__vue__.processAndUploadFile)return'NO_VM';"
    "var uv=p.__vue__;"
    "var add=document.querySelector('.product-picture-add');"
    "var cp=add;while(cp&&!cp.__vue__)cp=cp.parentElement;"
    "if(!cp||!cp.__vue__)return'NO_ADD';"
    "var pv=cp.__vue__;"
    "uv.loading=true;"
    "if(!pv.valueSelf)pv.valueSelf=[];"
    "if(!pv.value)pv.value=[];"
    "var li=pv.valueSelf.length;"
    "pv.valueSelf.push({src:'',poor:true,errorTips:'diag_uploading'});"
    "pv.value.push('');"
    "window._diag_done=false;window._diag_url=null;"
    "uv.processAndUploadFile(inp.files[0]).then(function(r){"
    "  window._diag_done=true;"
    "  if(r&&r.valid&&r.src){"
    "    window._diag_url=r.src;"
    "    if(pv.valueSelf[li]){"
    "      pv.valueSelf[li].src=r.src;"
    "      pv.valueSelf[li].poor=false;"
    "      pv.valueSelf[li].errorTips='';"
    "      pv.value[li]=r.src;"
    "    }"
    "  }else{window._diag_url='INVALID:'+(r?r.message||JSON.stringify(r):'nor')}"
    "  uv.loading=false;"
    "},function(err){"
    "  window._diag_done=true;"
    "  window._diag_url='REJ:'+(err?err.message||String(err):'unk');"
    "  uv.loading=false;"
    "});"
    "return'started:'+li")
r = iframe_eval(upload_js)
print(f"  upload: {r}")

# Poll
print("  polling...")
for pi in range(30):
    time.sleep(1.0)
    poll = iframe_eval(
        "var d=window._diag_done||false;"
        "var u=window._diag_url||null;"
        "if(d&&u)return'done:'+(u.substring(0,80));"
        "if(d)return'done:ERR';"
        "return'wait'")
    print(f"  poll[{pi}]: {poll[:80]}")
    if 'done:' in str(poll):
        break

check_state("after-upload")

# === DIAG STEP 5: Sync both components ===
print("\n=== STEP 5: Sync Components ===")
sync_js = (
    "var pc=document.querySelector('.product-picture-container');"
    "if(!pc)return'NO_PC';"
    "var pp=pc;while(pp&&!pp.__vue__)pp=pp.parentElement;"
    "if(!pp||!pp.__vue__)return'NO_PP';"
    "var add=document.querySelector('.product-picture-add');"
    "var cp=add;while(cp&&!cp.__vue__)cp=cp.parentElement;"
    "if(!cp||!cp.__vue__)return'NO_CP';"
    "var pv=cp.__vue__;"
    "var valid=[];var cleaned=0;"
    "for(var i=0;i<(pv.valueSelf||[]).length;i++){"
    "  if(pv.valueSelf[i].src&&pv.valueSelf[i].src.length>10){valid.push(pv.valueSelf[i]);}"
    "  else{cleaned++;}"
    "}"
    "pv.valueSelf.splice(0,pv.valueSelf.length);"
    "for(var i=0;i<valid.length;i++){pv.valueSelf.push(valid[i]);}"
    "pv.value.splice(0,pv.value.length);"
    "for(var i=0;i<valid.length;i++){pv.value.push(valid[i].src);}"
    "var prods=[];"
    "for(var i=0;i<pv.value.length;i++){prods.push({src:pv.value[i],url:pv.value[i]});}"
    "pp.__vue__.value=prods;"
    "pp.__vue__.showList=true;"
    "return JSON.stringify({valid:valid.length,cleaned:cleaned,parentLen:prods.length})")
r = iframe_eval(sync_js)
print(f"  sync: {r}")

check_state("after-sync")

# === DIAG STEP 6: HandleModalHide ===
print("\n=== STEP 6: HandleModalHide ===")
r = iframe_eval(
    "var btn=document.querySelector('.product-picture-add');"
    "if(btn&&btn.__vue__&&btn.__vue__.handleModalHide){"
    "  try{btn.__vue__.handleModalHide();return'hidden'}catch(e){return'err:'+e.message}"
    "}return'NO_HIDE'")
print(f"  hide: {r}")

# Reset loading
iframe_eval(
    "var fi=document.getElementById('fileInput');"
    "if(fi){var p=fi;while(p&&!p.__vue__)p=p.parentElement;"
    "if(p&&p.__vue__)p.__vue__.loading=false;}return'ok'")

time.sleep(0.5)
check_state("after-hide")

# === DIAG STEP 7: Wait and re-check (check for watcher reset) ===
print("\n=== STEP 7: Delayed check (2s) ===")
time.sleep(2.0)
check_state("delayed-2s")

# === DIAG STEP 8: Check picture-box images ===
print("\n=== STEP 8: picture-box images ===")
r = iframe_eval(
    "var imgs=document.querySelectorAll('.picture-box img');"
    "var urls=[];"
    "for(var i=0;i<Math.min(imgs.length,5);i++)urls.push(imgs[i].src.substring(0,80));"
    "return JSON.stringify({count:imgs.length,urls:urls})")
print(f"  images: {r}")

# === DIAG STEP 9: Check parent Vue $parent chain ===
print("\n=== STEP 9: Vue parent chain ===")
r = iframe_eval(
    "var add=document.querySelector('.product-picture-add');"
    "var cp=add;while(cp&&!cp.__vue__)cp=cp.parentElement;"
    "var pv=cp.__vue__;"
    "var pvParent=pv.$parent;"
    "var ppName=pvParent?pvParent.$options.name||'unnamed':'none';"
    "var ppHasValue=pvParent?'value' in pvParent:false;"
    "var ppVal=pvParent&&pvParent.value?JSON.stringify(pvParent.value).substring(0,200):'none';"
    "return JSON.stringify({parentName:ppName,parentHasValue:ppHasValue,parentValue:ppVal})")
print(f"  chain: {r}")
