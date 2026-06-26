import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from strategies.meituan_flash import _raw_iframe_eval

target = "E150316C280057CBF6B32901CDF63506"
temp_id = "_mt_upload_tmp"

# Step 1: create temp input (this works from fill_engine test)
_ = _raw_iframe_eval(target,
    "var old=document.getElementById('{tid}');if(old)old.remove();"
    "var inp=document.createElement('input');inp.type='file';inp.id='{tid}';"
    "inp.style.cssText='position:absolute;left:-9999px;top:-9999px;width:1px;height:1px;opacity:0;pointer-events:none;';"
    "document.body.appendChild(inp);return'created'".format(tid=temp_id))
print("Temp input created")

# Step 2: setFiles via MCP server
import json, urllib.request
from lib.cdp import CDP
body = json.dumps({
    'selector': '#' + temp_id,
    'files': ['C:/Users/admin/Desktop/midea-extension/mcp-server/cache/images/mainThumb/df5cd46a136a4eeb9f116dfd2178d7da.jpg'],
    'iframeSelector': '#hashframe'
}).encode()
req = urllib.request.Request(f"{CDP}/setFiles?target={target}", data=body, method='POST')
req.add_header('Content-Type', 'application/json')
resp = urllib.request.urlopen(req, timeout=30)
result = json.loads(resp.read().decode())
print("setFiles:", result)

import time; time.sleep(0.5)

# Step 3: test upload eval with the EXACT formatted JS from _fill_images
upload_js = (
    "try{"
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
    "var idx=0;"
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
    "return'started:'+idx;"
    "}}catch(e){{return'PAUF_THROW:'+e.message;}}"
    "}catch(e){{return'SETUP_ERR:'+e.message;}}"
).format(tid=temp_id)

print("\n=== Running upload eval ===")
r = _raw_iframe_eval(target, upload_js)
print("RESULT:", repr(r))
