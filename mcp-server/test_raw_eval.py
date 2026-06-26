"""Test: trace the exact _raw_iframe_eval call that fill_engine makes for upload"""
import json, sys, os, tempfile, subprocess
sys.path.insert(0, os.path.dirname(__file__))
from strategies.meituan_flash import _raw_iframe_eval

target = "E150316C280057CBF6B32901CDF63506"
temp_id = "_mt_upload_tmp"

# Replicate the exact JS that _fill_images generates
js_code = (
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
    "if(!document._mt_srcs)document._mt_srcs=[];"
    "var idx=document._mt_srcs.length;document._mt_srcs.push(null);"
    "uv.processAndUploadFile(inp.files[0]).then("
    "function(r){{"
    "  if(r&&r.valid&&r.src)document._mt_srcs[idx]=r.src;"
    "  if(pv.valueSelf[li]){{"
    "    pv.valueSelf[li].src=r&&r.valid&&r.src?r.src:'';"
    "    pv.valueSelf[li].poor=false;"
    "    pv.valueSelf[li].errorTips='';"
    "    pv.value[li]=r&&r.valid&&r.src?r.src:'';"
    "  }}"
    "  uv.loading=false;"
    "}},"
    "function(err){{"
    "  document._mt_srcs[idx]='REJ:'+err.message;"
    "  if(pv.valueSelf[li]){{"
    "    pv.valueSelf[li].errorTips=err.message;"
    "    pv.valueSelf[li].poor=false;"
    "  }}"
    "  uv.loading=false;"
    "}}"
    ");"
    "return'started:'+idx"
).format(tid=temp_id)

print("=== Testing _raw_iframe_eval ===")
result = _raw_iframe_eval(target, js_code)
print(f"RESULT: {repr(result)}")
print(f"LEN: {len(str(result))}")
print(f"CONTAINS started: {'started:' in str(result)}")

# Also check if the full wrapper has issues
IFRAME_ID = "hashframe"
CDP = "http://localhost:5200"

full = (
    "(function(){var f=document.querySelector('#" + IFRAME_ID + "');"
    "if(!f||!f.contentDocument)return'NO_IFRAME';"
    "var _d=f.contentDocument;"
    "return (function(document){" + js_code + "})(_d);})()"
)

print("\n=== Wrapped JS snippet (start) ===")
print(full[:200])
print("\n=== Wrapped JS snippet (end) ===")
print(full[-200:])

# Now test the _cdp_eval path directly
tf = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8')
tf.write(full)
tf.close()

r = subprocess.run(
    ['curl', '-s', '-X', 'POST', f'{CDP}/eval?target={target}', '--data-binary', f'@{tf.name}'],
    capture_output=True, text=True, timeout=60, encoding='utf-8')
os.unlink(tf.name)

print("\n=== Direct curl result ===")
print(f"STDOUT: {r.stdout[:300]}")
print(f"STDERR: {r.stderr[:200] if r.stderr else '(none)'}")
