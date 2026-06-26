"""填表引擎 v4 — 站点路由 + 策略分发
用法: python fill_engine.py <task_json_file> [--skip-nav] [--site jd_instant|meituan_flash]
"""
import json, sys, os

# 确保脚本所在目录在 sys.path（兼容 embeddable Python 等非标准安装）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 禁用 .pyc 缓存（确保始终使用最新源码）
sys.dont_write_bytecode = True
# 清理可能过期的 .pyc 文件
for root, dirs, files in os.walk(os.path.dirname(__file__)):
    for f in files:
        if f.endswith('.pyc'):
            try: os.remove(os.path.join(root, f))
            except: pass

from strategies.jd_instant import fill_form as fill_jd_instant


def fill_form(task_file, dry_run=False, skip_nav=False):
    """统一入口：根据任务中的 site 字段路由到对应策略"""
    task = json.load(open(task_file, encoding='utf-8'))
    site = task.get('target_site', 'jd_instant')

    if site == 'meituan_flash':
        try:
            from strategies.meituan_flash import fill_form as fill_meituan_flash
            return fill_meituan_flash(task_file, dry_run=dry_run, skip_nav=skip_nav)
        except ImportError:
            return {"success": False, "need_ai": True, "error": "meituan_flash strategy not yet implemented"}

    # 默认: 京东秒送
    return fill_jd_instant(task_file, dry_run=dry_run, skip_nav=skip_nav)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python fill_engine.py <task.json> [--skip-nav] [--site jd_instant|meituan_flash]"}))
        sys.exit(1)

    skip_nav = '--skip-nav' in sys.argv
    try:
        result = fill_form(sys.argv[1], dry_run='--dry-run' in sys.argv, skip_nav=skip_nav)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        import traceback
        print(json.dumps({"error": str(e), "type": type(e).__name__, "trace": traceback.format_exc().split(chr(10))[-3:]}, ensure_ascii=False))
