@echo off
REM MCP Task Server - Auto-deploy launcher
REM Detects Node.js 18+, auto-downloads if missing
title MCP Task Server (port 5200)

powershell -NoExit -ExecutionPolicy Bypass -File "%~dp0start.ps1"
