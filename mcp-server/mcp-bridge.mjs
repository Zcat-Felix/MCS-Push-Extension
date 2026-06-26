// MCP 协议桥 — stdio 传输，将 WorkBuddy MCP 请求代理到 HTTP 服务
// 用法: node mcp-bridge.mjs
// 需要 @modelcontextprotocol/sdk

import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';

const HTTP_BASE = 'http://localhost:5200';

async function httpGet(path) {
  try {
    const resp = await fetch(`${HTTP_BASE}${path}`, { signal: AbortSignal.timeout(5000) });
    return await resp.json();
  } catch (e) {
    return { error: e.message };
  }
}

async function httpPost(path, body) {
  try {
    const resp = await fetch(`${HTTP_BASE}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15000)
    });
    return await resp.json();
  } catch (e) {
    return { error: e.message };
  }
}

const server = new Server(
  { name: 'midea-cdp', version: '1.0.0' },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'health',
      description: '检查 MCP 服务与 CDP 连接状态',
      inputSchema: { type: 'object', properties: {} }
    },
    {
      name: 'reconnect',
      description: '手动触发 CDP 重新连接 Edge 浏览器',
      inputSchema: { type: 'object', properties: {} }
    },
    {
      name: 'targets',
      description: '列举 Edge 浏览器中所有已打开的页面标签',
      inputSchema: { type: 'object', properties: {} }
    }
  ]
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name } = request.params;
  switch (name) {
    case 'health': {
      const data = await httpGet('/health');
      return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
    }
    case 'reconnect': {
      const data = await httpPost('/reconnect');
      return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
    }
    case 'targets': {
      const data = await httpGet('/targets');
      return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
    }
    default:
      throw new Error(`未知工具: ${name}`);
  }
});

const transport = new StdioServerTransport();
await server.connect(transport);
