# 京东秒送 + 美团闪购 表单自动填写 — 项目主索引

> 生成日期: 2026-06-18 | 版本: v3.1 | 维护: 随重大变更同步更新

## 🤖 模型必读指令

- **每次任务开始**: 先读取本文件了解项目全貌
- **每次完成实质性工作**: 在底部「变更日志」追加本次变更，同步更新对应板块(进度/教训/规则)。**进度变更必须同步更新 `DEVELOPMENT_PLAN.md` + 本文件，两处保持一致。**
- **遇到新坑**: 写入「三、项目教训库」对应分类
- **不改则不问**: 代码/配置修改后直接执行，不等确认
- **编码前检查**: 「二、编码生死规则」全部10条是否遵守
- **清理硬编码值**: 测试用固定值(const:)一经确认即删除，不留余孽
- **禁止自动重启MCP服务**: 改代码不杀MCP进程，告知用户手动双击桌面快捷方式重启。MCP Server 的控制台窗口归用户管理，后台启动会占用端口导致用户无法重启
- **🚨 禁止擅自修改LLM校验规则**: `FORBIDDEN_MAP`、`FORBIDDEN_PATTERNS`、`_validate_level1`、`_validate_level2` 等校验规则必须在用户明确指示后才能修改。校验规则的正确性由用户判断，模型只负责执行。
- **🚨 新字段类型只加框架，不加映射**: 发现新的字段类型（如 structured）时，只扩展 `.py` 的扫描+填充逻辑。禁止向 `mt_attr_mapping.json` 等映射文件写入 hardcoded 映射——映射由 LLM 离线解析自动生成。

---

## 一、项目概览

| 项目 | 说明 |
|------|------|
| **目标** | 自动化填写京东秒送 / 美团闪购的新品上架表单 |
| **架构** | Chrome 扩展采集 → MCP Server(:5200) 任务队列 → CDP 操控 Edge 浏览器自动填表 |
| **入口** | `fill_engine.py` → 按 `target_site` 路由到 `strategies/jd_instant.py` 或 `strategies/meituan_flash.py` |
| **浏览器** | Edge (CDP :9222, HTTP 可用) / Chrome (CDP :49727, 仅 WebSocket) |
| **扩展名** | 美云销图片下载器 v3.3 (Edge Extension) |

### 数据流

```
美云销页面(content.js扫描)
  → popup按钮派发(POST /submit)
  → MCP Server(:5200) 任务队列 + 图片缓存
  → fill_engine.py 路由
  → strategies/{jd_instant,meituan_flash}.py
  → lib/cdp.py (HTTP :5200)
  → Edge 浏览器 CDP WebSocket
```

---

## 二、🚨 编码生死规则 (每次必读)

| # | 规则 | 违反后果 | 来源 |
|---|------|---------|------|
| 1 | JS禁止双层IIFE | `_raw_iframe_eval`已包function, 再加`(function(){})()` → CDP空返回 | 美团开发 |
| 2 | 禁止for循环+中文比较 | for/forEach里`==="中文"` → CDP空返回 → 用index/Array.find | CDP调试 |
| 3 | popup操作分两步 | 打开popup和点击item分开CDP eval, 中间sleep 0.3-0.5s | 美团select |
| 4 | 改.py必清.pyc | `rm -rf __pycache__/` 否则跑旧代码 | 全局教训 |
| 5 | subprocess encoding | 用`encode('utf-8')`不用`encoding='utf-8'`参数 | Python调用 |
| 6 | 弹窗前scrollIntoView | 点上传按钮前必须scrollIntoView({block:'center'}) | JD图片 |
| 7 | MCP改后强杀重启 | PowerShell杀进程+重开, uptime验证 | 服务更新 |
| 8 | 中文JS用subprocess+curl | urllib的Content-Length用字符数导致UTF-8中文截断 | CDP eval |
| 9 | 美团类目推荐需body.click | 被动轮询`.undo-edit`永远等不到 → 先body.click()触发推荐引擎 | 美团类目 |
| 10 | 美团属性select需hover | boo-select依赖mouseenter触发展开 → click前dispatchEvent('mouseenter')+scrollIntoView | 美团属性 |

---

## 三、项目教训库

### 3.1 编码陷阱

| 教训 | 详情 | 修复 |
|------|------|------|
| **双层IIFE导致CDP空返回** | `_raw_iframe_eval` 已包装 `(function(document){...})`, JS内再加一层wrapper → 全部返回空 | 去掉内层IIFE, 直接用return |
| **for/forEach + 中文比较 = 空** | CDP Runtime.evaluate对含中文的循环返回空值 | 用 `Array.from().find/map` 替代, index定位 |
| **Python .pyc缓存** | 修改.py后__pycache__未清 → 跑旧代码 | 每次改后 `rm -rf __pycache__/` |
| **urllib Content-Length陷阱** | urllib用字符数算Content-Length, UTF-8中文=3字节/字 → 数据截断 | 改用 `subprocess.run curl --data-binary @tempfile` |
| **subprocess encoding参数** | `encoding='utf-8'` 参数位置错误 → 解码失败 | 用 `encode('utf-8')` |

### 3.2 CDP 操作陷阱

| 教训 | 详情 | 修复 |
|------|------|------|
| **后台标签页点击无效** | 浏览器对后台tab的点击事件节流 | 先 `Target.activateTarget` 激活 |
| **popup异步渲染** | popup打开和内容渲染分两步, 合并CDP调用会失败 | 分两步eval, 中间sleep 0.3-0.5s |
| **iframe Vue父链偏移** | `_raw_iframe_eval` 内 `document=_d` 导致Vue组件树偏移1层 | 沿父链向上遍历查找方法, 不硬编码深度 |
| **scrollIntoView前置** | 元素不在视口时click不触发事件 | 所有交互前先scrollIntoView({block:'center'}) |
| **iframe HTMLInputElement.prototype 隔离** | iframe 有独立的原型链, 主文档 hook 不生效; Vue 受控 input 的 CDP setFiles 注入后 JS `files=0` | 在 iframe 内创建新鲜 input → setFiles → 提取 File 对象 → 调用 Vue uploader.processAndUploadFile |

### 3.3 前端框架差异

| 框架 | 特点 | 关键操作 |
|------|------|---------|
| **JD: Vue3 + Formily** | 表单值走form.setValues/getValues | `form.setValuesIn('path', val)`, img用setFileInputFiles |
| **美团: React外壳 + Vue2/iView iframe** | 组件库boo-, `__vue__`可访问 | 类目: body.click()触发推荐; 属性: vue.value+attrHandleBlur(); 图片: Vue弹窗+新鲜input+CDP setFiles+processAndUploadFile |

### 3.4 调试经验

| 教训 | 详情 |
|------|------|
| **CDP诊断先于改代码** | 盲目改代码 = 浪费时间; 先用CDP eval查页面DOM/状态 |
| **验证product name提取** | `classifier._extractProductName()` 在Console直接测试 |
| **Chrome CDP端口确认** | `chrome://inspect` → Remote Target; `chrome://version` → 命令行参数 |
| **Edge CDP端口确认** | `edge://inspect` → Remote debugging → "Allow remote debugging" |

### 3.5 商品名提取专项教训

| 教训 | 详情 |
|------|------|
| **modelPattern单字母型号** | `[A-Z]{2,}` 不匹配 F80/B2/G6 → 改为 `[A-Z]{1,}[-\/]?\d{2,}` |
| **仓库行干扰** | 仓库编码(YC0000370757)匹配旧pattern, 且仓库模块DOM在产品信息之前 |
| **scope限定反作用** | 限定20行窗口可能漏掉产品名(产品名远在params区之前) → 全局扫描+关键词过滤更可靠 |
| **策略2漏洞** | 长文本匹配可能命中"零售返利"等促销文案 → 加排除关键词 |
| **最小改动原则** | 从备份版只改3处: modelPattern + warehouse排除 + retail排除 |

---

## 四、模块索引

### 4.1 扩展前端

| 文件 | 路径 | 说明 |
|------|------|------|
| manifest.json | `C:\Users\admin\Desktop\midea-extension\manifest.json` | 扩展配置 v3.3 |
| content.js | `C:\Users\admin\Desktop\midea-extension\content.js` | 页面扫描 + 派发提交 + 悬浮面板 |
| popup.html | `C:\Users\admin\Desktop\midea-extension\popup.html` | 弹出窗口UI |
| popup.js | `C:\Users\admin\Desktop\midea-extension\popup.js` | 弹出窗口逻辑 |
| background.js | `C:\Users\admin\Desktop\midea-extension\background.js` | Service Worker + ZIP下载 |

### 4.2 MCP 服务器

| 文件 | 路径 | 说明 |
|------|------|------|
| server.mjs | `mcp-server/server.mjs` | HTTP :5200, 内建CDP, 任务队列 |
| mcp-bridge.mjs | `mcp-server/mcp-bridge.mjs` | MCP stdio ↔ HTTP 桥接 |
| fill_engine.py | `mcp-server/fill_engine.py` | 填表引擎路由 v4 |
| start.bat | `mcp-server/start.bat` | 启动脚本 |

### 4.3 填表策略

| 文件 | 路径 | 说明 |
|------|------|------|
| 京东策略 | `mcp-server/strategies/jd_instant.py` | 京东秒送全套填充 |
| 美团策略 | `mcp-server/strategies/meituan_flash.py` | 美团闪购全套填充 |

### 4.4 核心库

| 文件 | 路径 | 说明 |
|------|------|------|
| cdp.py | `mcp-server/lib/cdp.py` | CDP HTTP 操作封装 |
| utils.py | `mcp-server/lib/utils.py` | js_escape, extract_value 等 |

### 4.5 字段映射

| 文件 | 路径 | 说明 |
|------|------|------|
| jd_instant.json | `mcp-server/mappings/jd_instant.json` | 京东字段映射 |
| jd_category_kw.json | `mcp-server/mappings/jd_category_kw.json` | 京东类目关键词 (62条) |
| meituan_flash.json | `mcp-server/mappings/meituan_flash.json` | 美团字段映射 |
| mt_category_table.json | `mcp-server/mappings/mt_category_table.json` | 美团类目表 (128条) |
| mt_attr_mapping.json | `mcp-server/mappings/mt_attr_mapping.json` | 美团属性映射 (类目→字段映射) |
| pending_mappings.json | `mcp-server/mappings/pending_mappings.json` | 待解析映射队列 |

### 4.6 记忆文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 项目记忆 | `.workbuddy/memory/MEMORY.md` | 项目长期经验 (编码规则 + 架构) |
| 日日志(0617) | `.workbuddy/memory/2026-06-17.md` | 最新日工作日志 |
| INDEX.md | `INDEX.md` | 本文件 — 项目主索引 |
| DEVELOPMENT_PLAN.md | `DEVELOPMENT_PLAN.md` | 开发计划 (Phase 0-7) + 代码审查结果 |

### 4.7 备份文件

| 目录 | 说明 |
|------|------|
| `E:\美的智慧家\美云销插件备份\v2\` | v2 备份 (content.js 522行原始版本) |

---

## 五、项目进度

### 5.1 京东秒送 (jd_instant)

| 功能 | 状态 | 备注 |
|------|------|------|
| 商品名称 | ✅ 完成 | 文本填充 + Vue value setter |
| 商品类目 | ✅ 完成 | 三级降级(3s自动→1s使用→cascader) |
| 商品品牌 | ✅ 完成 | 三级优先级 + 边界保护 |
| 规格参数 | ✅ 完成 | params_sum毛重求和 |
| 商品图片 | ✅ 完成 | /uploadFiles → setFiles → setValuesIn |
| 图文详情 | ✅ 完成 | 11/14图片容量限制 |

**京东总进度**: 6/6 = 100%

### 5.2 美团闪购 (meituan_flash)

| 功能 | 状态 | 备注 |
|------|------|------|
| 商品名称 | ✅ 完成 | `placeholder:规范命名` selector |
| 商品类目(推荐) | ✅ 完成 | body.click()→undo轮询 |
| 商品类目(手动) | ✅ 完成 | 关键词→遍历popup→点击→undo |
| 规格信息 | ✅ 完成 | 3列表格(条形码/毛重/货号, 价格库存跳过) |
| 商品图片(主图) | ✅ 完成 | v2: Vue弹窗→新鲜input→setFiles→processAndUploadFile |
| 图文详情 | ✅ 完成 | .w-e-text insertHTML |
| 属性(text/select) | ✅ 完成 | mt_attr_mapping.json 配置驱动, 未匹配→pending |
| 店内分类 | ⚠️ 部分 | boo-select搜索, 无类目标签时跳过 |
| MCP Server /submit | ✅ 完成 | 支持 meituan_flash 路由 |
| Chrome 扩展派发 | ✅ 完成 | "美团闪购"按钮 + 自动URL切换 |
| 表单重置 | ✅ 完成 | 每次任务前清理旧类目/名称/表格 |

**美团总进度**: 9/10 核心字段, 1个部分完成

### 5.3 待办事项

| 优先级 | 任务 | 详情 |
|--------|------|------|
| 🔴 P0 | 美团店内分类 | 无类目标签时需手动补填 |
| 🟡 P1 | 插件商品名确认 | 验证 modelPattern 修复后是否稳定 |
| 🟡 P1 | 京东图片上传完整性 | 验证批量上传文件是否全部成功 |
| 🟡 P1 | 确定按钮成功率 | 物理点击 vs JS click 可靠性 |
| 🟢 P2 | 美团端到端测试 | 从插件派发到美团提交全流程 |
| 🟢 P2 | select批量填稳定性 | 多个select连续操作偶发不稳定 |

---

## 六、快速导航

### 想了解 → 看这里

| 需求 | 跳转 |
|------|------|
| 项目整体架构 | [一、项目概览](#一项目概览) |
| 编码时必须遵守的规则 | [二、编码生死规则](#二-编码生死规则-每次必读) |
| 之前踩过的坑 | [三、项目教训库](#三项目教训库) |
| 找某个文件 | [四、模块索引](#四模块索引) |
| 当前进度到哪了 | [五、项目进度](#五项目进度) |
| 京东填表逻辑 | `mcp-server/strategies/jd_instant.py` |
| 美团填表逻辑 | `mcp-server/strategies/meituan_flash.py` |
| 完整开发计划 | [DEVELOPMENT_PLAN.md](DEVELOPMENT_PLAN.md) |
| 最新工作日志 | `.workbuddy/memory/2026-06-17.md` |

---

## 七、变更日志

| 日期 | 变更 | 影响板块 |
|------|------|---------|
| 2026-06-18 | 创建 INDEX.md + 模型必读指令 | 全项目 |
| 2026-06-18 | 移除美团表格价格/库存固定值 | 五、美团进度 |
| 2026-06-18 | 新增 _reset_form() 任务前清理 | meituan_flash.py |
| 2026-06-18 | 图片上传 v2 重写 (Vue弹窗+新鲜input+processAndUploadFile) + 删除legacy + server.mjs新增/hover | 五、3.3、meituan_flash.py |
| 2026-06-22 | 美团图片上传启用 + V3重写: .then()异步收集+PUF+ProductPicture.value写回; _cdp_eval超时15→60s; 修复Python .format()花括号冲突; 祖传Vue父链硬编码改为遍历; 异常处理加固 | 五、3.3、meituan_flash.py、meituan_flash.json |
| 2026-06-22 | 美团图片上传启用 + Vue组件路径修复 (`.uploader.parentElement.__vue__` → `#fileInput.parentElement.parentElement.__vue__`); 清pending_phases; 收窄_type黑洞 | 五、3.3、meituan_flash.py、meituan_flash.json |
| 2026-06-23 | 图片上传v3终版: CDP确认渲染需写双组件(ProductPicture.value+showList=true + .product-picture-add.valueSelf+value); tab切换改用文件方式传入中文JS避免shell编码问题; MEMORY.md新增规则15-17 | 五、3.3、meituan_flash.py、MEMORY.md |
| 2026-06-24 | UI翻新+部署自动化: Impeccable设计系统+Node自动检测+CDP端口扫描+Python路径去硬编码+deploy文档 | 全项目 |
