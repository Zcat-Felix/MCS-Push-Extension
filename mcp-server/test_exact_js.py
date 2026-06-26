"""Test the exact upload JS that fill_engine.py generates via _cdp_eval flow"""
import json, tempfile, subprocess, os

# The EXACT JS that fill_engine.py produces for Step 3c
js = ('var inp=document.getElementById("_mt_upload_tmp");if(!inp||!inp.files||!inp.files[0])return"NF";'
      'var fi=document.querySelector("#fileInput");if(!fi)return"NO_FILEINPUT";'
      'var p=fi;while(p&&!p.__vue__)p=p.parentElement;if(!p||!p.__vue__||!p.__vue__.processAndUploadFile)return"NO_VM";'
      'var uv=p.__vue__;var addBtn=document.querySelector(".product-picture-add");'
      'var cp=addBtn;while(cp&&!cp.__vue__)cp=cp.parentElement;if(!cp||!cp.__vue__)return"NO_ADD_VUE";'
      'var pv=cp.__vue__;uv.loading=true;if(!pv.valueSelf)pv.valueSelf=[];if(!pv.value)pv.value=[];'
      'var li=pv.valueSelf.length;pv.valueSelf.push({src:"",poor:true,errorTips:"uploading"});pv.value.push("");'
      'if(!document._mt_srcs)document._mt_srcs=[];var idx=document._mt_srcs.length;document._mt_srcs.push(null);'
      'uv.processAndUploadFile(inp.files[0]).then(function(r){'
      '  if(r&&r.valid&&r.src)document._mt_srcs[idx]=r.src;'
      '  if(pv.valueSelf[li]){pv.valueSelf[li].src=r&&r.valid&&r.src?r.src:"";pv.valueSelf[li].poor=false;pv.valueSelf[li].errorTips="";pv.value[li]=r&&r.valid&&r.src?r.src:"";}'
      '  uv.loading=false;'
      '},function(err){'
      '  document._mt_srcs[idx]="REJ:"+err.message;'
      '  if(pv.valueSelf[li]){pv.valueSelf[li].errorTips=err.message;pv.valueSelf[li].poor=false;}'
      '  uv.loading=false;'
      '});'
      'return"started:"+idx')

# Write to temp file (same as _cdp_eval does)
tf = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8')
tf.write(js)
tf.close()

r = subprocess.run(
    ['curl', '-s', '-X', 'POST', 'http://localhost:5200/eval?target=E150316C280057CBF6B32901CDF63506', '--data-binary', f'@{tf.name}'],
    capture_output=True, text=True, timeout=60, encoding='utf-8')
os.unlink(tf.name)

print("STDOUT:", r.stdout[:500])
print("STDERR:", r.stderr[:200] if r.stderr else "(none)")

try:
    val = json.loads(r.stdout).get('value','')
    print("VALUE:", repr(val))
    print("CONTAINS started:?", 'started:' in str(val))
except Exception as e:
    print("PARSE ERR:", e)
