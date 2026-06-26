"""Extract and dump the exact upload JS that _fill_images generates"""
import json

temp_id = '_mt_upload_tmp'

js_parts = (
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
)

# Concatenate (Python implicit concatenation)
full_str = ''.join(js_parts)
print("=== BEFORE .format() ===")
print(repr(full_str[:200]))
print()

# Apply .format()
formatted = full_str.format(tid=temp_id)
print("=== AFTER .format(tid=_mt_upload_tmp) ===")
print(formatted[:300])
print("...")
print(formatted[-200:])
print()

# Check for unmatched { or }
import re
braces = re.findall(r'[{}]', formatted)
opens = braces.count('{')
closes = braces.count('}')
print(f"Unmatched braces? opens={opens} closes={closes}")

# Test: eval in JS
print("\n=== FULL JS (formatted) ===")
print(formatted)
