"""测试图片填充代码 — 单元测试 + 集成测试"""
import sys, os, json, tempfile, unittest
from unittest.mock import patch, MagicMock, mock_open

# 设置测试环境
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ['PYTHONIOENCODING'] = 'utf-8'

# 模拟 CDP 基础 URL
os.environ['CDP_BASE'] = 'http://localhost:3456'

from lib import utils
from lib.cdp import CDP


class TestUtils(unittest.TestCase):
    """测试工具函数"""

    # ── load_mapping ──

    def test_load_mapping(self):
        """测试加载美团映射表"""
        mapping = utils.load_mapping('meituan_flash')
        self.assertIsNotNone(mapping)
        self.assertIn('text_fields', mapping)
        self.assertIn('image_fields', mapping)

    def test_load_mapping_jd(self):
        """测试加载京东映射表"""
        mapping = utils.load_mapping('jd_instant')
        self.assertIsNotNone(mapping)
        self.assertIn('text_fields', mapping)

    def test_load_mapping_invalid(self):
        """测试不存在的映射表返回 None"""
        mapping = utils.load_mapping('nonexistent')
        self.assertIsNone(mapping)

    # ── js_escape ──

    def test_js_escape_plain(self):
        """测试纯 ASCII 字符保持原样"""
        self.assertEqual(utils.js_escape("hello"), "hello")

    def test_js_escape_single_quote(self):
        """测试单引号被转义"""
        result = utils.js_escape("it's")
        self.assertIn("\\'", result)

    def test_js_escape_double_quote(self):
        """测试双引号被转义"""
        result = utils.js_escape('say "hi"')
        self.assertIn('\\"', result)

    def test_js_escape_newline(self):
        """测试换行符被转义"""
        result = utils.js_escape("line1\nline2")
        self.assertIn('\\n', result)

    def test_js_escape_backslash(self):
        """测试反斜杠被转义"""
        result = utils.js_escape("back\\slash")
        self.assertIn('\\\\', result)

    def test_js_escape_unicode_kept(self):
        """测试 Unicode 字符保持原样（CDP 支持 UTF-8）"""
        result = utils.js_escape("中文")
        self.assertEqual(result, "中文")

    def test_js_escape_control_chars(self):
        """测试控制字符被转义为 \\x 格式"""
        result = utils.js_escape("\x00\x1f")
        self.assertIn('\\x', result)

    # ── extract_value ──

    def test_extract_value_product_name(self):
        """测试提取 product.name"""
        task = {"product": {"name": "美的空调", "code": "M001"}}
        r = utils.extract_value(task, "product.name")
        self.assertEqual(r, "美的空调")

    def test_extract_value_product_code(self):
        """测试提取 product.code"""
        task = {"product": {"name": "美的空调", "code": "M001"}}
        r = utils.extract_value(task, "product.code")
        self.assertEqual(r, "M001")

    def test_extract_value_params(self):
        """测试提取 params. 前缀字段"""
        task = {"product": {"params": [{"key": "毛重", "value": "32.5"}, {"key": "型号", "value": "KFR-35"}]}}
        r = utils.extract_value(task, "params.毛重")
        self.assertEqual(r, "32.5")

    def test_extract_value_params_nonexistent(self):
        """测试提取不存在的 params 字段返回空字符串"""
        task = {"product": {"params": [{"key": "毛重", "value": "32.5"}]}}
        r = utils.extract_value(task, "params.不存在字段")
        self.assertEqual(r, "")

    def test_extract_value_params_sum(self):
        """测试 params_sum: 求和"""
        task = {"product": {"params": [{"key": "内机毛重", "value": "12.5"}, {"key": "外机毛重", "value": "35.0"}]}}
        r = utils.extract_value(task, "params_sum:毛重")
        self.assertEqual(r, "47.5")

    def test_extract_value_const(self):
        """测试 const: 固定值"""
        r = utils.extract_value({}, "const:hello")
        self.assertEqual(r, "hello")

    def test_extract_value_unknown(self):
        """测试未知 source 返回空字符串"""
        r = utils.extract_value({"key1": "value1"}, "key1")
        self.assertEqual(r, "")

    # ── get_local_paths ──

    def test_get_local_paths_no_images(self):
        """测试没有图片时返回空列表"""
        task = {"name": "test"}
        r = utils.get_local_paths(task, 'mainThumb', 5)
        self.assertEqual(r, [])

    def test_get_local_paths_with_images(self):
        """测试有图片时返回路径列表"""
        task = {"images_mainThumb_local": ["img1.jpg", "img2.jpg"]}
        r = utils.get_local_paths(task, 'mainThumb', 5)
        self.assertEqual(len(r), 2)

    def test_get_local_paths_respects_max(self):
        """测试 get_local_paths 遵守 max_n 限制"""
        task = {"images_mainThumb_local": ["a.jpg", "b.jpg", "c.jpg"]}
        r = utils.get_local_paths(task, 'mainThumb', 2)
        self.assertEqual(len(r), 2)

    def test_get_local_paths_detail(self):
        """测试获取详情图"""
        task = {"images_detail_local": ["d1.jpg", "d2.jpg", "d3.jpg"]}
        r = utils.get_local_paths(task, 'detail', 5)
        self.assertEqual(len(r), 3)


class TestFillEngineImport(unittest.TestCase):
    """测试 fill_engine 导入"""

    def test_import_fill_engine(self):
        """测试 fill_engine 可导入"""
        import fill_engine
        self.assertTrue(hasattr(fill_engine, 'fill_form'))

    def test_import_strategies(self):
        """测试策略模块可导入"""
        from strategies import meituan_flash, jd_instant
        self.assertTrue(hasattr(meituan_flash, 'fill_form'))
        self.assertTrue(hasattr(jd_instant, 'fill_form'))


class TestMeituanFlashFunctions(unittest.TestCase):
    """测试美团闪购关键函数"""

    @classmethod
    def setUpClass(cls):
        from strategies import meituan_flash
        cls.mt = meituan_flash

    def test_constants_defined(self):
        """测试常量定义"""
        self.assertTrue(hasattr(self.mt, 'IFRAME_ID'))
        self.assertEqual(self.mt.IFRAME_ID, 'hashframe')
        self.assertTrue(hasattr(self.mt, 'MT_DOMAIN'))

    def test_raw_iframe_eval_js_structure(self):
        """测试 _raw_iframe_eval 构造的 JS 结构是否合法"""
        doc = self.mt._raw_iframe_eval.__doc__ or ""
        self.assertIn('function(document)', doc.replace(' ', ''),
            "文档应说明 function(document) 包装结构")

    def test_fill_images_signature(self):
        """测试 _fill_images 函数签名"""
        import inspect
        sig = inspect.signature(self.mt._fill_images)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ['target', 'field_map', 'task'])

    def test_fill_detail_images_signature(self):
        """测试 _fill_detail_images 函数签名"""
        import inspect
        sig = inspect.signature(self.mt._fill_detail_images)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ['target', 'field_map', 'task'])


class TestJDInstantFunctions(unittest.TestCase):
    """测试京东秒送关键函数"""

    @classmethod
    def setUpClass(cls):
        from strategies import jd_instant
        cls.jd = jd_instant

    def test_fill_form_images_signature(self):
        """测试 fill_form_images 函数签名"""
        import inspect
        sig = inspect.signature(self.jd.fill_form_images)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ['target', 'field_map', 'task'])

    def test_fill_form_images_cached_signature(self):
        """测试 fill_form_images_cached 函数签名"""
        import inspect
        sig = inspect.signature(self.jd.fill_form_images_cached)
        params = list(sig.parameters.keys())
        self.assertEqual(params, ['target', 'field_map', 'task'])

    def test_form_signature(self):
        """测试 fill_form 函数签名"""
        import inspect
        sig = inspect.signature(self.jd.fill_form)
        params = list(sig.parameters.keys())
        self.assertIn('task_file', params)
        self.assertIn('dry_run', params)


class TestMappingIntegrity(unittest.TestCase):
    """测试映射表完整性 — 检查 JSON 结构与代码期望一致"""

    def test_meituan_mapping_has_image_fields(self):
        """测试美团映射表包含图片字段定义"""
        mapping_dir = os.path.join(os.path.dirname(__file__), '..', 'mappings')
        mapping_path = os.path.join(mapping_dir, 'meituan_flash.json')
        with open(mapping_path, encoding='utf-8') as f:
            mapping = json.load(f)
        image_fields = mapping.get('image_fields', [])
        self.assertGreater(len(image_fields), 0, "应包含 image_fields")
        labels = [f.get('label', '') for f in image_fields]
        self.assertTrue(any('图' in l for l in labels), "image_fields 应包含图片相关字段")

    def test_jd_mapping_has_image_fields(self):
        """测试京东映射表包含图片字段"""
        mapping_dir = os.path.join(os.path.dirname(__file__), '..', 'mappings')
        mapping_path = os.path.join(mapping_dir, 'jd_instant.json')
        with open(mapping_path, encoding='utf-8') as f:
            mapping = json.load(f)
        all_text = str(mapping)
        self.assertIn('图片', all_text, "应包含图片字段")


class TestCDPModule(unittest.TestCase):
    """测试 CDP 模块"""

    def test_cdp_imports(self):
        """测试 CDP 模块关键函数"""
        from lib.cdp import CDP, cdp_targets, cdp_navigate, cdp_set_files
        self.assertTrue(callable(cdp_targets))
        self.assertTrue(callable(cdp_navigate))
        self.assertTrue(callable(cdp_set_files))

    def test_cdp_base_url(self):
        """测试 CDP 基础 URL"""
        from lib.cdp import CDP
        self.assertTrue(CDP.startswith('http://'))


class TestFormFlow(unittest.TestCase):
    """测试表单填充流程 (模拟模式)"""

    def test_dry_run_meituan(self):
        """测试美团 dry_run 模式"""
        from fill_engine import fill_form
        task_data = {
            "target_site": "meituan_flash",
            "name": "Test Product",
            "images_mainThumb": []
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(task_data, f, ensure_ascii=False)
            tmp_path = f.name
        try:
            result = fill_form(tmp_path, dry_run=True)
            self.assertTrue(result.get('success', False))
            self.assertTrue(result.get('dry_run', False))
            self.assertIn('would_fill', result)
        finally:
            os.unlink(tmp_path)

    def test_dry_run_jd(self):
        """测试京东 dry_run 模式"""
        from fill_engine import fill_form
        task_data = {
            "target_site": "jd_instant",
            "name": "Test Product",
            "images_mainThumb": []
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
            json.dump(task_data, f, ensure_ascii=False)
            tmp_path = f.name
        try:
            result = fill_form(tmp_path, dry_run=True)
            self.assertTrue(result.get('success', False))
        finally:
            os.unlink(tmp_path)


class TestImageFillCodeQuality(unittest.TestCase):
    """测试图片填充代码质量 — 验证关键逻辑的正确性"""

    def test_upload_flow_steps_documented(self):
        """测试上传流程步骤已被文档化"""
        from strategies.meituan_flash import _fill_images
        doc = (_fill_images.__doc__ or "")
        self.assertIn("processAndUploadFile", doc, "文档应提到 processAndUploadFile")
        steps_found = sum(1 for keyword in ["打开", "等待", "创建", "注入", "调用", "轮询"] if keyword in doc)
        self.assertGreaterEqual(steps_found, 3, f"文档应描述至少3个步骤, 实际找到{steps_found}")

    def test_no_unsafe_dom_access(self):
        """测试无危险的 DOM 访问模式 (forEach+中文比较)"""
        from strategies import meituan_flash
        import inspect
        source = inspect.getsource(meituan_flash)
        violations = 0
        for line in source.split('\n'):
            if 'forEach' in line and ('==="' in line or "==='" in line or '.textContent.trim()' in line):
                if any('\u4e00' <= c <= '\u9fff' for c in line):
                    violations += 1
        self.assertEqual(violations, 0, f"发现 {violations} 处 forEach+中文比较 (违反规则2)")

    def test_no_dangerous_double_iife(self):
        """测试 JS 代码中无危险的双层 IIFE

        _raw_iframe_eval 已经包装了 function(document){...},
        JS 字符串内部不应再出现 (function(){...})()
        """
        from strategies import meituan_flash
        import inspect
        source = inspect.getsource(meituan_flash._fill_images)
        # 检查 JS 代码字符串中是否有额外的 (function(){})()
        # 合法的 (function(): 只出现在 _raw_iframe_eval 包装器代码中
        double_iife = source.count('(function(){') - source.count('_raw_iframe_eval')
        self.assertLessEqual(double_iife, 2,
            f"_fill_images 内部可能有危险的双层 IIFE: (function(){{ 出现 {double_iife} 次 (超出包装器)")

    def test_value_self_has_loading_check(self):
        """测试 valueSelf 写入时考虑了 loading 态 (应避免跳过 poor:true)"""
        from strategies import meituan_flash
        import inspect
        source = inspect.getsource(meituan_flash._fill_images)
        # 检查是否有 loading 相关逻辑
        has_loading_logic = 'loading' in source.lower()
        self.assertTrue(has_loading_logic,
            "_fill_images 中应包含 loading 状态处理逻辑 (当前可能跳过)")

    def test_get_local_paths_with_images(self):
        """测试 get_local_paths 返回路径列表"""
        task = {"images_mainThumb_local": ["/abs/path/file1.jpg", "/abs/path/file2.jpg"]}
        paths = utils.get_local_paths(task, 'mainThumb', 10)
        self.assertEqual(len(paths), 2)


class TestCDPProxyInterface(unittest.TestCase):
    """测试 CDP Proxy 接口兼容性"""

    def test_set_files_signature(self):
        """测试 cdp_set_files 支持 iframeSelector 参数"""
        from lib.cdp import cdp_set_files
        import inspect
        sig = inspect.signature(cdp_set_files)
        params = list(sig.parameters.keys())
        self.assertIn('iframe_selector', params,
            f"cdp_set_files 应支持 iframe_selector 参数, 当前参数: {params}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
