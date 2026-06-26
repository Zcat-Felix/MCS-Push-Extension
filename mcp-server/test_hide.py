"""Test handleModalHide via _raw_iframe_eval — exactly like _fill_images does it"""
import json, sys, os, time, tempfile, subprocess, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from lib.cdp import CDP, cdp_targets
from strategies.meituan_flash import _raw_iframe_eval

target = "0325AC33E3D8C949CEB8713F9FF3F792"

# Step 1: Open modal
_ = _raw_iframe_eval(target,
    "var btn=document.querySelector('.product-picture-add');"
    "if(!btn||!btn.__vue__)return'NV';"
    "btn.__vue__.handleUploadClick();return'opened'")
time.sleep(1.0)
print("Modal opened")

# Step 2: Check modal state
state1 = _raw_iframe_eval(target,
    "var btn=document.querySelector('.product-picture-add');"
    "return JSON.stringify({vis:btn&&btn.__vue__?btn.__vue__.modalVisible:'NV'})")
print(f"Before hide: {state1}")

# Step 3: Call hide — EXACTLY as in _fill_images
hide = _raw_iframe_eval(target,
    "var btn=document.querySelector('.product-picture-add');"
    "if(btn&&btn.__vue__&&btn.__vue__.handleModalHide){"
    "try{btn.__vue__.handleModalHide();return'hidden'}catch(e){return'err:'+e.message}"
    "}return'NO_HIDE'")
print(f"Hide result: {hide}")

# Step 4: Check modal state after
time.sleep(0.5)
state2 = _raw_iframe_eval(target,
    "var btn=document.querySelector('.product-picture-add');"
    "return JSON.stringify({vis:btn&&btn.__vue__?btn.__vue__.modalVisible:'NV'})")
print(f"After hide: {state2}")
