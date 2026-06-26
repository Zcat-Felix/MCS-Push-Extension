"""Quick test: run _fill_images alone, check state, see if persistence works"""
import json, sys, os, time, subprocess
sys.path.insert(0, os.path.dirname(__file__))
from strategies.meituan_flash import _fill_images, _raw_iframe_eval, _reset_form
from lib.cdp import CDP, cdp_targets

target = "E150316C280057CBF6B32901CDF63506"

# Load task
task_path = os.path.join(os.path.dirname(__file__), 'tasks', 'task_1782273590542_b894s0.json')
with open(task_path) as f:
    task = json.load(f)

field_map = {"label": "商品图片", "source": "images_mainThumb", "max": 10}

# Step 1: Clean state
_r = _raw_iframe_eval(target,
    "var add=document.querySelector('.product-picture-add');"
    "var cp=add;while(cp&&!cp.__vue__)cp=cp.parentElement;var pv=cp.__vue__;"
    "pv.valueSelf.splice(0,pv.valueSelf.length);pv.value.splice(0,pv.value.length);"
    "var pc=document.querySelector('.product-picture-container');"
    "var pp=pc;while(pp&&!pp.__vue__)pp=pp.parentElement;"
    "pp.__vue__.value=[];pp.__vue__.showList=false;return'ok'")
print("Clean state:", _r)

# Step 2: Run _fill_images
print("\n=== Running _fill_images ===")
status, msg = _fill_images(target, field_map, task)
print(f"Result: {status} | {msg}")

# Step 3: Check parent state immediately
print("\n=== Check parent state ===")
for check_i in range(5):
    time.sleep(1.0)
    state = _raw_iframe_eval(target,
        "var pc=document.querySelector('.product-picture-container');"
        "var pp=pc;while(pp&&!pp.__vue__)pp=pp.parentElement;"
        "if(!pp||!pp.__vue__)return'NO_PP';"
        "return JSON.stringify({valLen:(pp.__vue__.value||[]).length,show:pp.__vue__.showList,"
        "  imgs:document.querySelectorAll('.picture-box img').length})")
    print(f"  check[{check_i}] {state}")
