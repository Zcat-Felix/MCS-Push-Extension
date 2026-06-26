# 美团图片上传调试报告 — v3.2 (2026-06-24)

## 调试环境
- 目标页面: 美团闪购 addDetail 表单
- 调试工具: MCP Server (:5200) + CDP Proxy (:3456)
- 测试图片: 3 张来自 cache/images/mainThumb/ (72KB - 158KB)
- 调试脚本: debug_upload.py (逐步骤 CDP eval + 轮询 + 截图)

---

## 调试闭环
```
截图 → CDP eval(Vue状态) → 分析DOM/组件关系 → 修改代码 → 重新验证
```
共进行 **2 轮完整闭环**。

---

## 最终根因分析

### Bug #1 (核心): `pv.valueSelf = validItems` 被 Vue watcher 逆转
**症状**: Step 5 同步后 child 的 valueSelf 在 2 秒内回退到 stale 状态  
**原因**: 子组件 `.product-picture-add` 有 `innerValue` computed + watcher, 直接 array assignment 在某些时序下被覆盖  
**修复**: 使用 `splice(0, len)` 清除 + `push()` 逐个添加, 确保 Vue2 响应式正确追踪

### Bug #2: 空占位符污染导致 li 索引偏移
**症状**: 上传成功的 CDN URL 写入 `valueSelf[1]` 而非 `valueSelf[0]`, 0 号位留空占位  
**原因**: 上次失败调用残留 `{src:"", poor:false, errorTips:""}`  
**修复**: Step 1 (打开弹窗前) 增加 pre-clean 步骤清理空占位

### Bug #3: Vue 父子组件独立
**症状**: 写入父组件 ProductPictureV3.value 不会自动同步到子组件 valueSelf  
**原因**: `.product-picture-add.$parent === ProductPictureV3`, 但子组件的 `valueSelf` 是本地状态, 不随父 `value` prop 自动更新  
**结论**: 需要分别写入父组件 (value + showList) 和子组件 (valueSelf + value)

### Bug #4 (v3.1 残留): _mt_srcs 跨作用域
**症状**: `.then()` 回调中 `document._mt_srcs[idx] = r.src` 写入后, 轮询 eval 找不到  
**原因**: CDP eval 包装后的 `document` 作用和 .then() 异步回调上下文可能不同  
**已修复 (v3.1)**: 改为轮询 valueSelf

---

## 代码修改清单

### `meituan_flash.py` — 3 处关键修改

| # | 位置 | 修改 |
|---|------|------|
| 1 | Step 1 (新增) | 打开弹窗前 pre-clean 子组件 valueSelf 空占位 |
| 2 | Step 5 | `pv.valueSelf=validItems` → `pv.valueSelf.splice()+push()` |
| 3 | Step 1b | 标签切换从 `Array.find+中文` 改为 `tabs[1]` 索引 |

### 新增文件
- `debug_upload.py`: 可复用的上传调试脚本, 逐步骤执行 + 详细日志

---

## 验证结果

| 验证点 | 状态 |
|--------|------|
| 上传单张图片 | ✅ CDN URL 获取成功 |
| 上传后 valueSelf 更新 | ✅ .then() 回调正确写入 |
| 父组件 ProductPictureV3.value | ✅ `[{src, url}]` 格式正确 |
| 父组件 showList | ✅ true |
| pre-clean 空占位 | ✅ 上传前清理干净 |
| splice 替代 assignment | ✅ 子组件状态不逆转 |
| 图片在 .picture-box 渲染 | ✅ 可见 |
| 多张上传稳定性 | ⚠️ 需端到端测试 |

---

## 下一步建议

1. 运行 `fill_engine.py` 端到端测试 (3张图片全部上传)
2. 验证多图上传的并发安全性
3. 检查上传失败时的错误处理和重试逻辑
4. 验证 `handleModalConfirm` vs `handleModalHide` 对最终表单数据的影响
5. `debug_upload.py` 可保留为持续调试工具
