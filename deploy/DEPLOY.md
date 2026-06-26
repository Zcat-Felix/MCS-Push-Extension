# 部署迁移指南 (DEPLOY.md)

将美云销图片下载器项目部署到另一台 Windows 电脑的完整步骤。

---

## 一、前置环境（启动器会自动处理）

启动 MCP 服务器时，`start.bat` → `start.ps1` 会自动完成以下检测：

| 依赖 | 自动处理方式 |
|------|-------------|
| **Node.js 18+** | 检测系统 PATH → 不存在则从 nodejs.org 下载到 `_runtime/node/` |
| **Python 3.8+** | 检测系统 PATH → 不存在则从 python.org 下载到 `_runtime/python/`（embeddable 包） |
| **curl** | `lib/cdp.py` 依赖 curl 发送 CDP 请求（传送含中文的 JS 代码），Windows 10 1803+ 自带 |

> 如果自动下载失败（网络受限等），请手动安装 Node.js 18+ 和 Python 3.8+。

---

## 二、快速部署

### 步骤 A：清理运行时数据（可选但推荐）

在拷贝之前，运行 `deploy\clean-before-deploy.ps1`（右键 → 使用 PowerShell 运行），清理以下运行时文件：

| 目录 | 内容 | 大小 |
|------|------|------|
| `mcp-server/tasks/*.json` | 历史任务记录（含硬编码路径） | ~80KB |
| `mcp-server/cache/images/` | 图片缓存 | ~15MB |

> 也可以直接删除这两个目录，`start.ps1` 启动时会自动重建。

### 步骤 B：拷贝项目

将整个 `midea-extension` 文件夹复制到目标电脑任意位置（例如 `D:\Apps\midea-extension`）。

### 步骤 B：加载 Chrome 扩展

1. 打开 **Edge**（推荐）或 **Chrome**
2. 访问 `edge://extensions`（Chrome: `chrome://extensions`）
3. 开启右上角 **开发者模式**
4. 点击 **加载已解压的扩展** → 选择 `midea-extension` 文件夹
5. 确认扩展图标出现在工具栏

### 步骤 C：启动 MCP 服务器

**方式 1（推荐）：双击 `start.bat`**  
进入 `midea-extension\mcp-server\`，双击 `start.bat`。首次运行会自动检测/下载 Node.js，然后启动服务。

**方式 2：创建桌面快捷方式**  
将 `deploy\启动MCP服务器.bat` 复制到桌面，用记事本打开，将 `YOUR_PROJECT_PATH` 替换为实际路径，然后双击。

> 服务启动后控制台会显示 `MCP Task Server running on port 5200`。**不要关闭这个窗口**。

### 步骤 D：开启浏览器远程调试

**Edge**（推荐）：
1. 打开 `edge://inspect`
2. 左侧栏点击 **Remote debugging**
3. 勾选 **"Allow remote debugging for this browser instance"**
4. 确认状态显示 `Server running at: 127.0.0.1:9222`

**Chrome**（备用）：
1. 打开 `chrome://inspect/#devices`
2. 确认显示 `Server running at: 127.0.0.1:49727`

> MCP 服务器启动后会自动扫描这些端口，无需手动配置端口号。

### 步骤 E：验证

1. 打开任意美云销页面（如 `sales-expedite-ga.midea.com`）
2. 点击扩展图标 → 弹出窗口应显示"当前是美云销商品页面"
3. 点击"扫描图片"检验是否正常识别
4. 展开悬浮面板 → 点击"派发" → 确认控制台无报错

---

## 三、自动检测能力说明

### Node.js + Python 自动下载

`start.bat` → `start.ps1` 的检测流程：

```
start.bat
  └─ start.ps1
       ├─ 检测 node --version >= 18
       │    ├─ 满足 → 直接用系统 Node
       │    └─ 不满足 → 检测 _runtime/node/node.exe
       │         ├─ 存在且 >= 18 → 使用本地运行时
       │         └─ 不存在或过期 → 下载 v18.20.4 → 解压到 _runtime/node/
       │
       ├─ 检测 python --version >= 3.8
       │    ├─ 满足 → 直接用系统 Python
       │    ├─ 检测 _runtime/python/python.exe
       │    │    ├─ 存在且 >= 3.8 → 使用本地运行时
       │    │    └─ 不存在或过期 → 下载 embeddable 包 → 解压到 _runtime/python/
       │    └─ 设置 PYTHON_CMD 环境变量
       │
       └─ 使用检测到的 node 运行 server.mjs
```

下载的运行时存放在 `mcp-server/_runtime/` 下，不会影响系统环境。
- Node.js: `_runtime/node/`
- Python: `_runtime/python/`

### CDP 端口自动扫描

`server.mjs` 的 `probeBrowser` 函数：

1. 尝试 `config.json` 中配置的端口（如 Edge:9222）
2. 若失败且 `auto_scan: true`，遍历 `scan_ports` 列表
3. 找到第一个可达浏览器即连接

常见扫描端口：`9222`, `49727`, `9229`, `9230`

---

## 四、配置文件说明

| 文件 | 用途 | 需要修改的场景 |
|------|------|---------------|
| `mappings/config.json` | 浏览器配置、端口、Python 路径 | 浏览器路径不同、CDP 端口非标准 |
| `mcp-server/start.ps1` | Node.js 检测 + 自动下载 | 需要修改 Node 下载版本 |
| `deploy/启动MCP服务器.bat` | 桌面快捷方式模板 | 修改 YOUR_PROJECT_PATH |

### config.json 示例

```json
{
  "python": "python",
  "browsers": [
    {
      "name": "Edge",
      "cdp_port": 9222,
      "auto_scan": true,
      "scan_ports": [9222, 9229, 9230],
      "path": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"
    }
  ]
}
```

- `python`: Python 可执行文件命令（默认 `python`，也可是完整路径）
- `auto_scan`: 配置端口失败时是否自动扫描 `scan_ports`

---

## 五、常见问题

| 问题 | 原因 | 解决 |
|------|------|------|
| `3000 failed to parse` | MCP 服务未启动 | 双击 `start.bat` 启动服务 |
| `connect ECONNREFUSED 127.0.0.1:9222` | 浏览器未开启远程调试 | 打开 `edge://inspect` 勾选允许远程调试 |
| `Uncaught SyntaxError: Cannot use import statement` | Node.js 版本 < 18 | 手动安装 Node.js 18+ |
| `没有可打包的图片` | 页面未正确识别 | 刷新页面后重新扫描 |
| 派发后页面无反应 | CDP 连接断开或浏览器标签页未激活 | 查看 MCP 控制台是否有报错 |
