import sys, os, json, traceback
sys.path.insert(0, '.')
os.environ['PYTHONIOENCODING'] = 'utf-8'

from fill_engine import fill_form

try:
    result = fill_form('tasks/task_1781340279819_zxz3oq.json', skip_nav=True)
    out = json.dumps(result, ensure_ascii=False, indent=2)
    print(out)
except Exception as e:
    traceback.print_exc()
    print(json.dumps({"error": str(e), "type": type(e).__name__}))
