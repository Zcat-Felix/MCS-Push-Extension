"""CDP 操作 — 通过 MCP Server HTTP API 操控浏览器"""
import json, urllib.request

CDP = "http://localhost:5200"


def cdp_eval(target, js_code):
    # 用 subprocess+curl 避免 urllib 编码问题（含中文的 JS 容易丢 body）
    import subprocess, tempfile, os
    tf = tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8')
    try:
        tf.write(js_code)
        tf.close()
        r = subprocess.run(
            ['curl', '-s', '-X', 'POST', f'{CDP}/eval?target={target}', '--data-binary', f'@{tf.name}'],
            capture_output=True, text=True, timeout=15, encoding='utf-8')
        return json.loads(r.stdout).get('value', '')
    finally:
        os.unlink(tf.name)


def cdp_new_tab(url):
    req = urllib.request.Request(f"{CDP}/new", data=url.encode('utf-8'), method='POST')
    resp = urllib.request.urlopen(req, timeout=20)
    return json.loads(resp.read().decode()).get('targetId', '')


def cdp_targets():
    resp = urllib.request.urlopen(f"{CDP}/targets", timeout=10)
    return json.loads(resp.read().decode())


def cdp_navigate(target, url):
    req = urllib.request.Request(f"{CDP}/navigate?target={target}", data=url.encode('utf-8'), method='POST')
    resp = urllib.request.urlopen(req, timeout=20)
    return json.loads(resp.read().decode())


def cdp_set_files(target, selector, files, iframe_selector=None):
    body = json.dumps({
        'selector': selector,
        'files': files,
        'iframeSelector': iframe_selector
    }).encode()
    req = urllib.request.Request(f"{CDP}/setFiles?target={target}", data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read().decode())


def cdp_upload_files(target, trigger_sel, file_sel, files):
    """Silent upload: setFiles + Vue _vei handler trigger"""
    body = json.dumps({
        'triggerSelector': trigger_sel,
        'fileSelector': file_sel,
        'files': files
    }).encode()
    req = urllib.request.Request(f"{CDP}/uploadFiles?target={target}", data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    resp = urllib.request.urlopen(req, timeout=60)
    return json.loads(resp.read().decode())


def cdp_click_xy(target, x, y):
    """Physical mouse click at coordinates"""
    body = json.dumps({'x': x, 'y': y}).encode()
    req = urllib.request.Request(f"{CDP}/clickXY?target={target}", data=body, method='POST')
    req.add_header('Content-Type', 'application/json')
    urllib.request.urlopen(req, timeout=10)


def cdp_screenshot(target, filepath):
    urllib.request.urlopen(f"{CDP}/screenshot?target={target}&file={filepath}", timeout=15)


def cdp_close(target):
    urllib.request.urlopen(f"{CDP}/close?target={target}", timeout=5)
