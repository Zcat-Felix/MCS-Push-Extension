<#
.SYNOPSIS
  部署前清理脚本 — 删除运行时数据，减少拷贝体积
#>

$BaseDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 清理的任务文件
$tasksDir = Join-Path $BaseDir "mcp-server\tasks"
if (Test-Path $tasksDir) {
    Remove-Item "$tasksDir\*.json" -Force -ErrorAction SilentlyContinue
    Write-Host "[clean] 已清空 tasks/ 任务文件" -ForegroundColor Green
}

# 清理的图片缓存
$cacheDir = Join-Path $BaseDir "mcp-server\cache"
if (Test-Path $cacheDir) {
    Remove-Item "$cacheDir\*" -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "[clean] 已清空 cache/ 图片缓存" -ForegroundColor Green
}

# 可选：清除 node_modules（拷贝新机器后会自动 npm install）
$nmDir = Join-Path $BaseDir "mcp-server\node_modules"
if (Test-Path $nmDir) {
    Write-Host "[clean] node_modules/ 存在（23MB），建议保留以加快部署" -ForegroundColor Cyan
}

Write-Host "[clean] 清理完成！可以安全拷贝到目标电脑了。" -ForegroundColor Green
