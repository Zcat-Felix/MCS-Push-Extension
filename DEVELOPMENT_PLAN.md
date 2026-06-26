# 美团闪购商家端 — 拓展开发计划

> **项目**: midea-extension 表单自动填写插件  
> **当前**: 京东秒送 (jd_instant) 稳定运行  
> **目标**: 新增美团闪购 (meituan_flash) 商品发布表单填写  
> **监工**: Senior Developer (高级开发工程师) @ 主 agent  
> **开始**: 2026-06-16  
> **状态**: 🚧 开发中 (Phase 4 进行中, 核心字段已覆盖)

---

## 📊 已完成分析

| 项目 | 详情 | 状态 |
|------|------|------|
| 页面框架 | React 外壳 + Vue2/iView(boo-) iframe | ✅ |
| 表单 URL | `#/reuse/sc/product/views/merchant/product/addDetail` | ✅ |
| iframe ID | `#hashframe` (同源, contentDocument 可访问) | ✅ |
| 表单字段 | 27 个字段（完整映射见下方） | ✅ |
| 类目数据 | 128 条 家用电器 (mt_category_table.json) | ✅ |
| 架构方案 | 入口+策略文件夹 | ✅ |
| CDP 端口 | MCP Server :5200（单实例，无冲突） | ✅ |

---

## 🏗️ 架构重构 (Phase 0)

### 目标目录结构

```
mcp-server/
├── fill_engine.py              # [修改] 精简为入口路由 (~50行)
├── lib/
│   ├── __init__.py             # [新增]
│   ├── cdp.py                  # [新增] CDP 操作函数
│   └── utils.py                # [新增] 工具函数
├── strategies/
│   ├── __init__.py             # [新增] 导出 fill_* 函数
│   ├── jd_instant.py           # [新增] 京东秒送全套策略 (迁移自 fill_engine.py)
│   └── meituan_flash.py        # [新增] 美团闪购全套策略
├── mappings/
│   ├── jd_instant.json         # [现有]
│   ├── jd_category_kw.json     # [现有]
│   ├── mt_meituan.json         # [新增] 美团字段映射
│   └── mt_category_table.json  # [新增] 美团类目数据 (128条)
└── server.mjs                  # [现有, 无需改动]
```

### 职责边界

```
fill_engine.py:
  - 接收任务 JSON → 解析 site 参数 → 路由到对应策略
  - 不做任何站点特定的填充逻辑

lib/cdp.py:
  - 所有 CDP HTTP 操作封装 (eval, click, navigate, upload 等)

lib/utils.py:
  - js_escape, extract_value, get_local_paths 等通用工具

strategies/jd_instant.py:
  - 京东秒送的完整 fill_form 实现 (fill_engine.py 现有逻辑原样搬入)
  - 不做架构调整, import 路径改为 lib.*

strategies/meituan_flash.py:
  - 美团闪购的完整 fill_form 实现
  - 从 Phase 1 开始逐字段实现
```

### Phase 0 完成标准
- [ ] 京东秒送功能不受影响（回归测试通过）
- [ ] `python fill_engine.py test_task.json` 仍然正常工作
- [ ] import 路径全部正确

---

## 🔧 美团闪购字段映射

| # | 表单字段 | 组件类型 | 选择器/定位 | 难度 |
|---|---------|---------|-----------|------|
| 1 | 商品名称 | boo-input | `input[placeholder*='规范命名']` | 🟢 |
| 2 | 商品类目 | withSearch tags | 推荐: body.click()→undo; 手动: 关键词→popup | ✅ |
| 3 | 商品卖点 | boo-input | skip | ⏭️ 跳过 |
| 4 | 卖点展示期 | boo-radio-group | skip | ⏭️ 跳过 |
| 5 | 文字详情 | textarea | skip | ⏭️ 跳过 |
| 6 | 店内分类 | boo-select | `input[placeholder*='请输入或点击选择']` | 🟡 |
| 7 | 规格名称 | table input | 规格表格第1列 | 🟡 |
| 8 | 条形码 | table input | 规格表格第2列 | 🟡 |
| 9 | 总部价格 | boo-input-number | 规格表格第3列 | ⏭️ 跳过 |
| 10 | 库存 | boo-input-number | 规格表格第4列 | ⏭️ 跳过 |
| 11 | 毛重 | boo-input-number | 规格表格第5列 | 🟡 |
| 12 | 毛重单位 | boo-select | 规格表格第5列 select | 🟡 |
| 13 | 店内码/货号 | boo-input | 规格表格第6列 | 🟡 |
| 14 | 起购数 | boo-input-number | 规格表格第7列 | 🟡 |
| 15 | 货架码/位置 | boo-input | skip | ⏭️ 跳过 |
| 16 | 发货模式 | boo-radio | skip (非必填) | ⏭️ 跳过 |
| 17 | 可售时间 | boo-radio-group | skip (非必填) | ⏭️ 跳过 |
| 18 | 商品属性 | category-attr-text/selector | text: vue.value+attrHandleBlur; select: hover→click→menuItem | ✅ |
| 19 | 上/下架 | boo-radio-group | 点击 "上架"/"下架" | 🟡 |
| 20 | 商品图片 | handleImageAddV3 | 父链遍历到ProductPicture + Vue方法注入 | ✅ |
| 21 | 关联门店 | boo-select | 顶部第一个 boo-select | 🔴 |

---

## 📋 Phase 1-7: 逐字段实现

### Phase 1: 简单文本字段 🟢
> **子 agent**: `mt-fe-text` (general-purpose, lite)
- [ ] 商品名称 (boo-input)
- [ ] 商品卖点 (boo-input)
- [ ] 文字详情 (textarea)
- **关键**: Vue `dispatchEvent('input')` + `dispatchEvent('change')`
- **验证**: CDP eval 检查 input.value 是否生效

### Phase 2: Radio 组 🟡
> **子 agent**: `mt-fe-radio` (general-purpose, lite)
- [ ] 卖点展示期 (全时段/指定时段)
- [ ] 发货模式 (现货直发/预售)
- [ ] 可售时间 (全时段/周期性/指定时间)
- [ ] 上/下架
- **关键**: 点击 boo-radio 的 label → 触发 Vue 响应

### Phase 3: 规格表格 🟡
> **子 agent**: `mt-fe-table` (general-purpose)
- [ ] 9 列表格逐格定位填充
- [ ] 毛重单位 boo-select 联动
- [ ] "商品没有条形码？" 点击处理
- **关键**: 用 th 文本定位列索引 → td input

### Phase 4: boo-select 下拉 🟡
> **子 agent**: `mt-fe-select` (general-purpose)
- [ ] 店内分类
- [ ] 关联门店
- **关键**: click → input 搜索 → wait dropdown → click match

### Phase 5: 商品类目 🔴
> **子 agent**: `mt-fe-category` (general-purpose, reasoning)
- [ ] 关键词搜索输入
- [ ] 等待下拉建议加载
- [ ] 点击匹配的类目项
- [ ] 验证 tag 已生成
- **关键**: 用 mt_category_table.json 的 L3 类目名作为搜索词

### Phase 6: 商品图片 🔴
> **子 agent**: `mt-fe-images` (general-purpose, reasoning)
- [ ] MutationObserver 监听 file input 创建
- [ ] setFiles 注入文件
- [ ] 验证缩略图生成
- **关键**: 文件 input 是动态创建的，需先点击上传区

### Phase 7: 端到端集成
> **主 agent 直接操作**
- [ ] MCP Server /submit 支持 site 参数
- [ ] Chrome 插件 popup 「派发到美团闪购」按钮
- [ ] 完整任务 JSON 端到端测试
- [ ] 京东秒送回归测试

---

## 🤖 子 Agent 调度表

| Agent 名 | 职责 | Phase | 类型 | 模式 |
|----------|------|-------|------|------|
| `mt-fe-text` | 简单文本字段填充 | P1 | general-purpose | lite |
| `mt-fe-radio` | Radio 组填充 | P2 | general-purpose | lite |
| `mt-fe-table` | 规格表格填充 | P3 | general-purpose | default |
| `mt-fe-select` | boo-select 下拉填充 | P4 | general-purpose | default |
| `mt-fe-category` | 类目搜索填充 | P5 | general-purpose | reasoning |
| `mt-fe-images` | 图片上传填充 | P6 | general-purpose | reasoning |

---

## 📊 进度追踪

```
Phase 0: [██████████] 100%  ✅ 架构重构完成
Phase 1: [██████████] 100%  ✅ 商品名称 (卖点/文字详情→skip_fields)
Phase 2: [··········] 0%   Radio 组 → skip_fields
Phase 3: [██████████] 100%  ✅ 规格表格 (3列: 条形码/毛重/货号)
Phase 4: [█████·····] 50%   boo-select (店内分类部分完成)
Phase 5: [██████████] 100%  ✅ 商品类目 (推荐+手动双路径)
Phase 6: [██████████] 100%  ✅ 商品图片 (主图+详情)
Phase 7: [██████····] 60%   端到端集成 (插件派发已通, 全流程待测)
────────────────────────────────────────────
总进度:  模拟可视化进度条
```

---

## 📁 关键文件路径

| 文件 | 路径 |
|------|------|
| fill_engine.py | `C:\Users\admin\Desktop\midea-extension\mcp-server\fill_engine.py` |
| jd_instant.json | `C:\Users\admin\Desktop\midea-extension\mcp-server\mappings\jd_instant.json` |
| jd_category_kw.json | `C:\Users\admin\Desktop\midea-extension\mcp-server\mappings\jd_category_kw.json` |
| mt_category_table.json | `C:\Users\admin\Desktop\midea-extension\mcp-server\mappings\mt_category_table.json` |
| server.mjs | `C:\Users\admin\Desktop\midea-extension\mcp-server\server.mjs` |
| MCP Server | `http://localhost:5200` |
| 闪购 tab | `shangoue.meituan.com`, target `4799064FF0498D569C89BBD138370A70` |
| 京东 tab | `store.jddj.com`, target `FCD4A1E7CBB0B1D5235CA170F26F84C7` |

---

## ⚠️ 注意事项

1. **不跳转页面**: 美团页面的 hash 路由不要随意 change，用户手动导航
2. **iframe 上下文**: 所有 CDP eval 需通过 `#hashframe` 的 contentDocument
3. **京东不受影响**: Phase 0 重构只做代码搬移，不改变逻辑
4. **类目仅 128 条**: 只用家用电器类目，不用批量创建模板的 2274 条
5. **图片上传特殊**: 需要有人先在表单页面上点击过上传区，才能找到 file input

---
## 🔍 代码审查 (2026-06-18)

> 审查范围: `server.mjs` / `strategies/meituan_flash.py` / `fill_engine.py` / `scripts/resolve_mappings.py` / `lib/cdp.py`

### 🔴 Blocker

| # | 问题 | 状态 | 方案 |
|---|------|------|------|
| 1 | `_fill_images`: iframe setFiles 失败 + Vue 受控 input JS 不可读 | ✅ 已修复 (v2) | Vue弹窗→新鲜input→setFiles→processAndUploadFile |
| 2 | `_fill_category_keyword`: 3s 预检 + 30s 轮询竞态 | ⚠️ 待处理 | 预检改为轮询 undo-edit；timeout 从 mapping 配置 |
| 3 | `_fill_attributes`: `_shared` 加载后被空子类目映射弱化 | ⚠️ 待处理 | sub_category 为空时 fallback category_name；校验 sub_cat_mappings 非空 |

### 🟡 Suggestion

| # | 问题 | 状态 |
|---|------|------|
| 4 | `_parse_llm_json`: 无法处理 LLM 纯文本 `"skip"` | ⚠️ 待处理 |
| 5 | `call_llm`: 无重试机制 (urllib 异常直接返回 None) | ⚠️ 待处理 |
| 6 | `_fill_images`: 每次 _raw_iframe_eval 后不检查 iframe 是否存在 | ✅ 已随 v2 重写消除 |
| 7 | `_reset_form`: 只清第一行规格 + 品牌未清 | ⚠️ 待处理 |
| 8 | `fill_engine.py`: 每次 cold start `os.walk` 全目录删 .pyc | ⚠️ 待处理 |

### 💭 Nit

| # | 问题 | 状态 |
|---|------|------|
| 9 | `category_clicked` 一个布尔值承载 4 种状态 | ⚠️ 待处理 |
| 10 | `resolve_all`: 每轮结束写全量 pending 文件 (IO 频率) | ⚠️ 待处理 |
| 11 | `_extract_brand`: SUB_BRAND_MAP 硬编码无 fallback 日志 | ⚠️ 待处理 |
| 12 | `_fill_table_row`: `params_sum:` 前缀 source 无文档 | ⚠️ 待处理 |
