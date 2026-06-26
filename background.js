// 美云销图片下载器 - 后台服务脚本
// 处理 ZIP 打包下载和扩展生命周期

// 加载 JSZip 库（MV3 Service Worker 兼容）
importScripts('jszip.min.js');

// ====== 运行时兼容性检查 ======
(function checkCompatibility() {
    if (!chrome || !chrome.runtime) {
        console.error('Chrome Extension API 不可用');
        return;
    }
    const requiredAPIs = ['downloads', 'storage', 'runtime', 'tabs'];
    requiredAPIs.forEach(api => {
        if (!chrome[api]) {
            console.error(`chrome.${api} API 不可用，插件功能可能受限`);
        }
    });
    if (typeof JSZip === 'undefined') {
        console.error('JSZip 库加载失败，ZIP 打包功能不可用');
    }
    console.log('美云销图片下载器 - 后台服务已启动');
})();

// 监听安装事件
chrome.runtime.onInstalled.addListener((details) => {
    try {
        console.log('美云销图片下载器已安装', details.reason);
        if (details.reason === 'install') {
            console.log('首次安装，初始化设置');
            chrome.storage.local.set({
                autoHighQuality: true,
                categorizeFolders: true,
                showProgress: true,
                version: '3.2'
            }).catch(err => console.error('存储默认配置失败:', err));
            chrome.tabs.create({
                url: 'welcome.html'
            }).catch(err => console.error('打开欢迎页面失败:', err));
        } else if (details.reason === 'update') {
            console.log('扩展已更新');
        }
    } catch (e) {
        console.error('安装事件处理失败:', e);
    }
});

// ====== 监听来自 content script 的消息 ======
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    try {
        if (request.action === 'generateZip') {
            handleGenerateZip(request, sender)
                .then(result => sendResponse(result))
                .catch(error => sendResponse({ success: false, error: error.message }));
            return true; // 异步响应
        }

        if (request.action === 'fetchImage') {
            handleFetchImage(request.url)
                .then(data => sendResponse({ success: true, data: data }))
                .catch(error => sendResponse({ success: false, error: error.message }));
            return true;
        }

        if (request.action === 'saveParams') {
            handleSaveParams(request, sender)
                .then(result => sendResponse(result))
                .catch(error => sendResponse({ success: false, error: error.message }));
            return true;
        }
    } catch (e) {
        console.error('消息处理失败:', e);
        sendResponse({ success: false, error: e.message });
    }
});

// ====== 获取图片二进制数据（供 content script 调用） ======
async function handleFetchImage(url) {
    const response = await fetch(url, { mode: 'cors', credentials: 'omit' });
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    const arrayBuffer = await response.arrayBuffer();
    // 转为 base64 字符串传递
    const bytes = new Uint8Array(arrayBuffer);
    const chunks = [];
    for (let i = 0; i < bytes.length; i += 8192) {
        chunks.push(String.fromCharCode(...bytes.slice(i, i + 8192)));
    }
    return btoa(chunks.join(''));
}

// ====== 核心：生成 ZIP 并触发下载 ======
async function handleGenerateZip(request, sender) {
    const { images, productInfo } = request;
    const tabId = sender?.tab?.id;

    if (typeof JSZip === 'undefined') {
        throw new Error('JSZip 库未加载，无法生成压缩包');
    }
    if (!images || (!images.mainThumb && !images.detail)) {
        throw new Error('没有可打包的图片');
    }

    const zip = new JSZip();
    const mainThumbFolder = zip.folder('主副图');
    const detailFolder = zip.folder('商品详情图');

    const mainThumbList = images.mainThumb || [];
    const detailList = images.detail || [];
    const totalCount = mainThumbList.length + detailList.length;
    let fetchedCount = 0;
    const errors = [];

    // 推送进度到 content script
    function sendProgress(current, total) {
        if (!tabId) return;
        chrome.tabs.sendMessage(tabId, {
            action: 'downloadProgress',
            current: current,
            total: total
        }, (response) => {
            if (chrome.runtime.lastError) {
                // content script 可能尚未注入或已卸载，静默忽略
                console.log('[MideaExt BG] 进度推送失败（content script 未就绪）:', chrome.runtime.lastError.message);
            }
        });
    }

    // 打包主副图（按数组顺序，保持 DOM 顺序）
    for (let i = 0; i < mainThumbList.length; i++) {
        const img = mainThumbList[i];
        try {
            const blob = await fetchImageAsBlob(img.url);
            const filename = generateFileName(img, 'mainThumb', i + 1);
            mainThumbFolder.file(filename, blob, { binary: true });
            fetchedCount++;
            console.log(`主副图 [${i + 1}/${mainThumbList.length}]: ${filename} (总进度 ${fetchedCount}/${totalCount})`);
            sendProgress(fetchedCount, totalCount);
        } catch (e) {
            console.error(`获取主副图失败 [${i + 1}/${mainThumbList.length}]: ${img.url}`, e.message);
            errors.push({ url: img.url, error: e.message });
            // 不中断：继续下一张
            sendProgress(fetchedCount, totalCount);
        }
    }

    // 打包商品详情图（按数组顺序，保持 DOM 顺序）
    for (let i = 0; i < detailList.length; i++) {
        const img = detailList[i];
        try {
            const blob = await fetchImageAsBlob(img.url);
            const filename = generateFileName(img, 'detail', i + 1);
            detailFolder.file(filename, blob, { binary: true });
            fetchedCount++;
            console.log(`详情图 [${i + 1}/${detailList.length}]: ${filename} (总进度 ${fetchedCount}/${totalCount})`);
            sendProgress(fetchedCount, totalCount);
        } catch (e) {
            console.error(`获取详情图失败 [${i + 1}/${detailList.length}]: ${img.url}`, e.message);
            errors.push({ url: img.url, error: e.message });
            // 不中断：继续下一张
            sendProgress(fetchedCount, totalCount);
        }
    }

    if (fetchedCount === 0) {
        throw new Error('所有图片下载失败，无法生成压缩包');
    }

    // 生成 ZIP Blob
    const zipBlob = await zip.generateAsync({
        type: 'blob',
        compression: 'DEFLATE',
        compressionOptions: { level: 6 }
    }, (metadata) => {
        // JSZip 内置进度（压缩阶段）
        if (tabId && metadata.percent) {
            chrome.tabs.sendMessage(tabId, {
                action: 'downloadProgress',
                current: totalCount,
                total: totalCount,
                compressing: true,
                percent: Math.round(metadata.percent)
            }, () => {
                if (chrome.runtime.lastError) {
                    // content script 可能已卸载，静默忽略
                }
            });
        }
    });

    // 构建文件名
    const productCode = productInfo?.code || 'unknown';
    const productName = sanitizeFilename(productInfo?.name || '商品');
    const timestamp = Date.now();
    const zipFilename = `${productCode}_${productName}_${timestamp}.zip`;

    // 将 Blob 转为 data URL 触发放下载
    const reader = new FileReader();
    return new Promise((resolve, reject) => {
        reader.onload = async () => {
            try {
                if (!chrome.downloads) {
                    reject(new Error('浏览器下载 API 不可用'));
                    return;
                }

                const downloadId = await chrome.downloads.download({
                    url: reader.result,
                    filename: zipFilename,
                    saveAs: false
                });

                resolve({
                    success: true,
                    downloadId: downloadId,
                    total: totalCount,
                    fetched: fetchedCount,
                    errors: errors,
                    filename: zipFilename
                });
            } catch (e) {
                reject(e);
            }
        };
        reader.onerror = () => reject(new Error('生成下载文件失败'));
        reader.readAsDataURL(zipBlob);
    });
}

// ====== 工具函数 ======

/** 从 URL 获取图片为 Blob */
async function fetchImageAsBlob(url) {
    const response = await fetch(url, { mode: 'cors', credentials: 'omit' });
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
    }
    return response.blob();
}

/** 生成压缩包内的文件名 */
function generateFileName(img, category, index) {
    // 从 URL 提取原始文件名
    let originalName = 'image.jpg';
    try {
        const urlObj = new URL(img.url);
        const pathname = urlObj.pathname;
        originalName = pathname.split('/').pop() || 'image.jpg';
    } catch (e) {}

    // 清理文件名，移除非法字符
    let cleanName = originalName.replace(/[<>:"/\\|?*]/g, '_');
    // 移除 OSS 参数
    cleanName = cleanName.replace(/\?.*$/, '');

    // 如果去参数后没有扩展名，补上
    if (!cleanName.includes('.') || cleanName.endsWith('.')) {
        cleanName += '.jpg';
    }

    const prefix = category === 'mainThumb' ? 'mt' : 'de';
    return `${prefix}_${String(index).padStart(3, '0')}_${cleanName}`;
}

/** 清理文件名中的非法字符 */
function sanitizeFilename(name) {
    return name.replace(/[<>:"/\\|?*\x00-\x1f]/g, '_').trim().substring(0, 80) || '商品图片';
}

// ====== 保存商品参数为 JSON 文件 ======
async function handleSaveParams(request, sender) {
    const { groups, productInfo } = request;

    if (!groups || groups.length === 0) {
        throw new Error('没有可保存的参数数据');
    }

    const jsonStr = JSON.stringify(groups, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });

    const productCode = productInfo?.code || 'unknown';
    const productName = sanitizeFilename(productInfo?.name || '商品');
    const timestamp = Date.now();
    const filename = `${productCode}_${productName}_params_${timestamp}.json`;

    const reader = new FileReader();
    return new Promise((resolve, reject) => {
        reader.onload = async () => {
            try {
                if (!chrome.downloads) {
                    reject(new Error('浏览器下载 API 不可用'));
                    return;
                }
                const downloadId = await chrome.downloads.download({
                    url: reader.result,
                    filename: filename,
                    saveAs: false
                });
                resolve({ success: true, downloadId, filename });
            } catch (e) {
                reject(e);
            }
        };
        reader.onerror = () => reject(new Error('生成 JSON 文件失败'));
        reader.readAsDataURL(blob);
    });
}

// ====== 标签页监控 ======
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
    try {
        if (changeInfo.status === 'complete' && tab.url) {
            const mideaPatterns = ['midea.com', 'smartmidea.net'];
            if (mideaPatterns.some(pattern => tab.url.includes(pattern))) {
                console.log('检测到美云销页面:', tab.url);
            }
        }
    } catch (e) {
        console.error('标签页更新处理失败:', e);
    }
});

chrome.action.onClicked.addListener((tab) => {
    try {
        console.log('扩展图标被点击');
    } catch (e) {
        console.error('图标点击处理失败:', e);
    }
});
