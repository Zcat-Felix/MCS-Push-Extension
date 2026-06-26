"""Direct test of cdp_set_files with exact fill_engine parameters"""
import json, sys, os, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from lib.cdp import CDP

target = "E150316C280057CBF6B32901CDF63506"
temp_id = "_mt_upload_tmp"
fp = "C:/Users/admin/Desktop/midea-extension/mcp-server/cache/images/mainThumb/df5cd46a136a4eeb9f116dfd2178d7da.jpg"
iframe_sel = "#hashframe"
selector = "#" + temp_id

body = json.dumps({
    'selector': selector,
    'files': [fp],
    'iframeSelector': iframe_sel
}).encode()

print("BODY:", body)
print("URL:", f"{CDP}/setFiles?target={target}")

req = urllib.request.Request(f"{CDP}/setFiles?target={target}", data=body, method='POST')
req.add_header('Content-Type', 'application/json')

try:
    resp = urllib.request.urlopen(req, timeout=30)
    raw = resp.read()
    print("STATUS:", resp.status)
    print("RAW:", repr(raw[:500]))
    decoded = raw.decode()
    print("DECODED:", repr(decoded[:500]))
    result = json.loads(decoded)
    print("RESULT:", result)
except urllib.error.HTTPError as e:
    print("HTTPERROR:", e.code, e.reason)
    print("BODY:", e.read().decode()[:500])
except Exception as e:
    import traceback
    print("ERROR:", e)
    traceback.print_exc()
