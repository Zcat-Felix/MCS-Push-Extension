"""Test: run fill_engine, immediately check image persistence after finish"""
import json, sys, os, time, subprocess
sys.path.insert(0, os.path.dirname(__file__))
from strategies.meituan_flash import fill_form, _raw_iframe_eval, MT_DOMAIN, IFRAME_ID
from lib.cdp import CDP, cdp_targets
import urllib.request

target = "E150316C280057CBF6B32901CDF63506"

# Clean state
_raw_iframe_eval(target,
    "var add=document.querySelector('.product-picture-add');"
    "var cp=add;while(cp&&!cp.__vue__)cp=cp.parentElement;var pv=cp.__vue__;"
    "pv.valueSelf.splice(0,pv.valueSelf.length);pv.value.splice(0,pv.value.length);"
    "var pc=document.querySelector('.product-picture-container');"
    "var pp=pc;while(pp&&!pp.__vue__)pp=pp.parentElement;"
    "pp.__vue__.value=[];pp.__vue__.showList=false;return'ok'")
print("Cleaned")

# Run fill_engine in the same process
task_file = os.path.join(os.path.dirname(__file__), 'tasks', 'task_1782273590542_b894s0.json')
result = fill_form(task_file, skip_nav=True)
print(f"fill_form result: success={result.get('success')}, filled={result.get('filled')}, failed={result.get('failed')}")

# IMMEDIATELY check state
time.sleep(1)
state = _raw_iframe_eval(target,
    "var pc=document.querySelector('.product-picture-container');"
    "var pp=pc;while(pp&&!pp.__vue__)pp=pp.parentElement;"
    "var r={};"
    "if(pp&&pp.__vue__){r.valLen=(pp.__vue__.value||[]).length;r.show=pp.__vue__.showList;"
    "  if(pp.__vue__.value.length)r.firstVal=pp.__vue__.value[0].src.substring(0,60);}"
    "r.imgs=document.querySelectorAll('.picture-box img').length;"
    "return JSON.stringify(r)")
print(f"\nImmediate check: {state}")

# Check again after delay
for i in range(3):
    time.sleep(2)
    state = _raw_iframe_eval(target,
        "var pc=document.querySelector('.product-picture-container');"
        "var pp=pc;while(pp&&!pp.__vue__)pp=pp.parentElement;"
        "return JSON.stringify({valLen:(pp.__vue__.value||[]).length,show:pp.__vue__.showList,imgs:document.querySelectorAll('.picture-box img').length})")
    print(f"  delay[{i}] {state}")
