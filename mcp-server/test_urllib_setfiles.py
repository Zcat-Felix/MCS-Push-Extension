"""Quick test: call cdp_set_files via urllib and check response"""
import json, sys, os, urllib.request

CDP = "http://localhost:5200"
target = "E150316C280057CBF6B32901CDF63506"

body = json.dumps({
    'selector': '#_mt_test_quick',
    'files': ['C:/Users/admin/Desktop/midea-extension/mcp-server/cache/images/mainThumb/df5cd46a136a4eeb9f116dfd2178d7da.jpg'],
    'iframeSelector': '#hashframe'
}).encode()

req = urllib.request.Request(f"{CDP}/setFiles?target={target}", data=body, method='POST')
req.add_header('Content-Type', 'application/json')
try:
    resp = urllib.request.urlopen(req, timeout=30)
    raw = resp.read()
    print("RAW bytes (first 300):", repr(raw[:300]))
    print("DECODED:", repr(raw.decode()[:300]))
    print("JSON:", json.loads(raw.decode()))
except Exception as e:
    import traceback
    print("ERROR:", e)
    traceback.print_exc()
