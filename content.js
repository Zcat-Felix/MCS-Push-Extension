// 美云销图片下载器 - 内容脚本
// 直接在页面中运行，用于扫描图片并协调 ZIP 打包下载

// 支持的图片域名（新旧美云销域名）
const MIDEA_DOMAINS = [
    'midea.com',
    'signin.midea.com',
    'sales.midea.com',
    'sales-expedite-ga.midea.com',
    'smartmidea.net',
    'dsdcp.smartmidea.net',
    'mcsp-aliyun-dsdcp-ga'
];

// OSS 图片处理参数正则
const OSS_PARAM_REGEX = /\?.*?(?:x-oss-process|imageMogr2|image_process|imageView|imageResize).*$/i;

// 无关图片 URL 关键词（logo / 图标 / 背景 / UI 装饰）
const IRRELEVANT_URL_KEYWORDS = [
    'logo', 'icon', 'bg', 'background', 'banner', 'avatar',
    'arrow', 'btn', 'button', 'tab', 'menu', 'nav', 'header',
    'footer', 'spinner', 'loading', 'placeholder', 'default',
    'thumb_', '/icons/', '/assets/', 'favicon'
];

// 无关图片 DOM 类名关键词
const IRRELEVANT_CLASS_KEYWORDS = [
    'logo', 'icon', 'avatar', 'btn', 'button', 'tab',
    'nav', 'menu', 'header', 'footer', 'spinner', 'loading'
];

// 图片分类器
class MideaImageClassifier {
    constructor() {
        this.images = {
            main: [],   // 主图
            thumb: [],  // 副图/缩略图
            detail: []   // 商品详情图
        };
    }
    
    // 判断URL是否属于美云销图片
    isMideaImage(url) {
        try {
            const urlObj = new URL(url);
            const hostname = urlObj.hostname;
            return MIDEA_DOMAINS.some(domain => hostname.includes(domain) || url.includes(domain));
        } catch (e) {
            return MIDEA_DOMAINS.some(domain => url.includes(domain));
        }
    }
    
    // 去掉OSS参数，获取原图URL
    getOriginalImageUrl(url) {
        return url.replace(OSS_PARAM_REGEX, '');
    }
    
    // 扫描页面图片，返回三类（兼容 popup 显示）
    // 按 DOM 顺序排列：主副图按页面显示顺序，详情图按 DOM 顺序
    scanImages() {
        console.log('开始扫描美云销页面图片...');
        this.images = { main: [], thumb: [], detail: [] };
        
        const allImages = Array.from(document.querySelectorAll('img'));
        console.log(`找到 ${allImages.length} 个图片元素`);
        
        // 先过滤：仅保留美云销域名的图片
        const mideaImages = allImages.filter(img => {
            const src = img.src || img.getAttribute('data-src') || '';
            return src && this.isMideaImage(src);
        });
        console.log(`域名过滤后 ${mideaImages.length} 个美云销图片`);
        
        // 再过滤：去掉无关图片（logo/图标/背景等）
        const relevantImages = mideaImages.filter(img => this._isRelevantImage(img));
        console.log(`相关性过滤后 ${relevantImages.length} 个商品图片`);
        
        // 按 DOM 出现顺序分类，同一归一化 URL 只保留尺寸最大的那张
        // 主图通常先出现（.mainImg 中），缩略图后出现（.Img_li 中），
        // 主图的 naturalWidth 更大，因此优先保留先出现的大尺寸版本
        const seen = new Map(); // normalizedUrl → { type, imgElement }
        relevantImages.forEach(img => {
            const src = img.src || img.getAttribute('data-src') || '';
            const originalSrc = this.getOriginalImageUrl(src);
            const type = this.classifyImage(img, src);

            if (seen.has(originalSrc)) {
                const existing = seen.get(originalSrc);
                // 同一 URL 出现多次时，保留尺寸更大的那张
                const newW = img.naturalWidth || 0;
                const oldW = existing.img.naturalWidth || 0;
                if (newW > oldW) {
                    // 新图片更大，替换：从旧分类中移除，加入新分类
                    const oldType = existing.type;
                    const idx = this.images[oldType].indexOf(originalSrc);
                    if (idx >= 0) this.images[oldType].splice(idx, 1);
                    this.images[type].push(originalSrc);
                    seen.set(originalSrc, { type, img });
                    console.log(`[去重-替换] ${originalSrc.slice(-50)}: ${oldType}(${oldW}px) → ${type}(${newW}px)`);
                }
                return;
            }

            seen.set(originalSrc, { type, img });
            this.images[type].push(originalSrc);
        });
        
        console.log('扫描完成:', {
            main: this.images.main.length,
            thumb: this.images.thumb.length,
            detail: this.images.detail.length
        });
        return this.images;
    }
    
    // 判断图片是否与商品相关（过滤 logo / 图标 / 背景等无关图片）
    // 返回 true = 保留；false = 过滤掉
    _isRelevantImage(img) {
        const src = (img.src || img.getAttribute('data-src') || '').toLowerCase();
        const classList = (img.className || '').toLowerCase();
        const alt = (img.alt || '').toLowerCase();
        const tag = img.tagName;

        // 1. URL 关键词过滤
        for (const kw of IRRELEVANT_URL_KEYWORDS) {
            if (src.includes(kw)) {
                console.log(`[过滤] URL关键词 "${kw}": ${src.slice(0, 100)}`);
                return false;
            }
        }

        // 2. DOM 类名关键词过滤
        for (const kw of IRRELEVANT_CLASS_KEYWORDS) {
            if (classList.includes(kw)) {
                console.log(`[过滤] 类名关键词 "${kw}": class="${img.className.slice(0, 80)}", src=${src.slice(0, 80)}`);
                return false;
            }
        }

        // 3. alt 属性过滤
        if (alt === 'logo' || alt.includes('图标') || alt.includes('icon')) {
            console.log(`[过滤] alt属性: alt="${img.alt}", src=${src.slice(0, 80)}`);
            return false;
        }

        // 4. 尺寸过滤：有 naturalWidth/Height 时，小于 80x80 的极可能是图标
        //    注意：naturalWidth=0 表示图片尚未加载，此时不应过滤（异步渲染场景）
        const w = img.naturalWidth || 0;
        const h = img.naturalHeight || 0;
        if (w > 0 && h > 0 && (w < 80 || h < 80)) {
            console.log(`[过滤] 尺寸过小 ${w}x${h}: src=${src.slice(0, 80)}`);
            return false;
        }

        // 5. 父元素检测：排除明显是UI组件的
        let parent = img.parentElement;
        let depth = 0;
        while (parent && parent !== document.body) {
            const pClass = (parent.className || '').toLowerCase();
            const pId = (parent.id || '').toLowerCase();
            if (pClass.includes('logo') || pClass.includes('header') ||
                pClass.includes('footer') || pClass.includes('nav') ||
                pId.includes('logo') || pId.includes('header')) {
                console.log(`[过滤] 父元素 ${depth}层: class="${parent.className.slice(0, 60)}", id="${parent.id}", src=${src.slice(0, 80)}`);
                return false;
            }
            parent = parent.parentElement;
            depth++;
            if (depth > 8) break; // 最多向上查 8 层，防止死循环
        }

        // 保留：输出 debug 日志方便排查
        console.log(`[保留] ${tag} ${w}x${h}: ${src.slice(0, 100)}`);
        return true;
    }
    
    // ============================================================
    // 图片分类：基于美云销真实 DOM 结构精确判断
    // ============================================================
    // 分类优先级（严格按 DOM 容器，不依赖尺寸猜测）：
    //   1. 在 .swiperBox 内 → main（.mainImg）或 thumb（.Img_li）
    //   2. 在 .product-imgs 内 → detail
    //   3. URL 含 x-oss-process → detail（兜底）
    //   4. 默认 → thumb
    //
    // 保证：.swiperBox 内的图片绝不会分到 detail
    //        .product-imgs 内的图片绝不会分到 main/thumb
    classifyImage(imgElement, imgUrl) {
        const inSwiper = this._hasAncestorWithClass(imgElement, 'swiperBox');
        const inProductImgs = this._hasAncestorWithClass(imgElement, 'product-imgs');

        // 优先级1：主图/缩略图区域（.swiperBox 容器内）
        if (inSwiper) {
            // .Img_li 内的是缩略图
            if (this._hasAncestorWithClass(imgElement, 'Img_li')) {
                return 'thumb';
            }
            // .mainImg 内或不在 .Img_li 中的 → 主图
            return 'main';
        }

        // 优先级2：详情图区域（.product-imgs 容器内）
        if (inProductImgs) {
            return 'detail';
        }

        // 优先级3：URL 特征兜底（跨页面或动态插入的图片）
        if (imgUrl.includes('x-oss-process')) {
            return 'detail';
        }
        // 详情图 URL 特征（mcsp-ic-product 域）
        if (imgUrl.includes('mcsp-ic-product') || imgUrl.includes('/ic-product/')) {
            return 'detail';
        }

        // 优先级4：默认归为副图（仅 swiperBox 外且无详图特征）
        return 'thumb';
    }

    // 检查元素是否在某类名祖先容器内（可穿透 micro-app Shadow DOM）
    _hasAncestorWithClass(element, className) {
        let current = element;
        let depth = 0;
        while (current && depth < 20) {
            // 先向上遍历当前 DOM 树
            let parent = current.parentElement;
            while (parent && depth < 20) {
                if (parent.classList && parent.classList.contains(className)) return true;
                const cls = parent.className;
                if (cls && typeof cls === 'string' && cls.split(/\s+/).includes(className)) return true;
                parent = parent.parentElement;
                depth++;
            }
            // 穿透 Shadow DOM 边界：检查 shadow host 是否匹配目标类，再继续向上
            try {
                const root = current.getRootNode ? current.getRootNode() : null;
                if (root && root.host && root !== document) {
                    current = root.host.parentElement;
                    if (!current) break;
                    continue;
                }
            } catch(e) { /* Shadow DOM 不可访问 */ }
            break;
        }
        return false;
    }
    
    // ============================================================
    // 商品参数提取（基于 innerText，可穿透微前端 Shadow DOM）
    // ============================================================
    extractProductParams() {
        const text = document.body.innerText || '';

        // 用"商品编码"作为主锚点，兼容所有商品
        let anchorIdx = text.search(/商品编码/);
        if (anchorIdx < 0) {
            // 兜底：找长数字串
            anchorIdx = text.search(/\d{10,}/);
        }

        if (anchorIdx < 0) {
            return { success: false, error: '未找到商品参数区域，请确认当前为商品详情页' };
        }

        // 取锚点前一小段 + 后一大段
        const start = Math.max(0, anchorIdx - 80);
        const section = text.slice(start, anchorIdx + 1500);

        // 拆行并过滤空行
        const lines = section.split('\n').map(l => l.trim()).filter(l => l.length > 0);

        // 找起始位置：第一个包含"商品信息"的行
        let startIdx = lines.findIndex(l => l.includes('商品信息') || l.includes('商品编码'));
        if (startIdx < 0) startIdx = 0;

        const sectionLabels = ['商品信息', '能效信息', '规格信息', '其他参数'];
        // 子分组标签：美云销某些品类会嵌套子分组，也当断点处理
        const subSectionPattern = /(规格信息|机规格信息|外机规格|内机规格|套机规格)$/;
        const groups = [];
        let currentGroup = null;

        for (let i = startIdx; i < lines.length; i++) {
            const line = lines[i];

            // 检查是否遇到分组/子分组标签
            if (sectionLabels.includes(line) || subSectionPattern.test(line)) {
                if (currentGroup && Object.keys(currentGroup.items).length > 0) {
                    groups.push(currentGroup);
                }
                // 子分组挂在最近的section名下
                const displayName = sectionLabels.includes(line) ? line : line;
                currentGroup = { name: displayName, items: {} };
                continue;
            }

            if (!currentGroup) {
                // 还没进入分组，跳过
                continue;
            }

            // key-value 交替解析：当前行是 key，下一行是 value（除非下一行也是分组标签）
            const nextLine = (i + 1 < lines.length) ? lines[i + 1] : '';
            // 过滤面板UI元素和无效key
            const isInvalidKey = /^(帮助|反馈|立即购买|加入购物车|购物车|保存|取消|提交|确认|下载|打包|派发|导出|目标|站点|京东|📥|📋|🚀|▶|正在|URL)/.test(line) ||
                                  /^(帮助|反馈|立即|加入|购物|保存|取消|提交|确认|下载|打包|派发|导出|目标|站点|京东|📥|📋|🚀)/.test(nextLine) ||
                                  line.length > 25 ||
                                  /^\d+(\.\d+)?$/.test(line);
            if (nextLine && !sectionLabels.includes(nextLine) && nextLine !== line && !isInvalidKey) {
                currentGroup.items[line] = nextLine;
                i++; // 跳过value行
            }
        }

        if (currentGroup && Object.keys(currentGroup.items).length > 0) {
            groups.push(currentGroup);
        }

        if (groups.length === 0) {
            return { success: false, error: '未能解析出商品参数' };
        }

        return {
            success: true,
            groups: groups,
            totalParams: groups.reduce((sum, g) => sum + Object.keys(g.items).length, 0)
        };
    }
    
    _extractProductCode() {
        const url = window.location.href;
        const match = url.match(/productCode=([A-Za-z0-9]+)/);
        if (match) return match[1];
        // 尝试从页面元素获取
        const codeEl = document.querySelector('[class*="productCode"], [class*="product-code"], .product-code, .sku-code');
        if (codeEl) return codeEl.textContent.trim();
        return 'unknown';
    }
    
    _extractProductName() {
        const text = document.body.innerText || '';
        const lines = text.split('\n').filter(l => l.trim());
        const title = document.title;
        const warehousePattern = /(仓库|物流|云仓|仓储|库房)/;

        // 如果 title 不是"美云销"，优先用它
        if (title && title !== '美云销' && !/^(首页|登录|美云销)$/.test(title) && !warehousePattern.test(title)) {
            return title.replace(/[-–—]\s*美云销.*$/, '').replace(/[-–—]\s*Midea.*$/, '').trim();
        }

        // 策略1：找包含产品型号的行（字母数字组合，如 MB80G6, KFR-35GW/B2, F80-33Q7Max）
        const modelPattern = /[A-Z]{1,}[-\/]?\d{2,}[A-Z]?/;
        for (const line of lines) {
            if (modelPattern.test(line) && line.length < 120 &&
                !warehousePattern.test(line) &&
                !/下载|打包|价格|建议|购买|购物车|帮助|编码|零售返利/.test(line)) {
                return line.trim().slice(0, 100);
            }
        }

        // 策略2：找长文本行（>10字，含中文，不含价格/UI词/仓库词）
        for (const line of lines) {
            if (line.length > 10 && line.length < 120 &&
                /[\u4e00-\u9fa5]/.test(line) &&
                !/^[¥0-9.,\s]+$/.test(line) &&
                !/立即购买|加入购物车|下载|打包|价格|建议零售价|帮助|反馈/.test(line) &&
                !/经销商|有限公司|商贸|公司/.test(line) &&
                !warehousePattern.test(line) &&
                !/零售返利/.test(line)) {
                return line.trim().slice(0, 100);
            }
        }

        return '商品图片';
    }
    
    extractProductInfo() {
        return {
            code: this._extractProductCode(),
            name: this._extractProductName()
        };
    }
    
    // 将扫描结果合并为两类，供 ZIP 打包使用
    // 主副图优先：已出现在主副图中的 URL 不再重复放入详情图
    // 注意：同一张图片可能以不同 URL 形式出现（带 OSS 参数 vs 原图），需归一化去重
    getImagesForZip() {
        // 主副图 URL 归一化（去掉 OSS 参数）后存入 Set
        const mainThumbUrlsNormalized = new Set();
        const mainThumb = [];

        this.images.main.forEach(url => {
            mainThumbUrlsNormalized.add(this.getOriginalImageUrl(url));
            mainThumb.push({ url, subType: 'main' });
        });
        this.images.thumb.forEach(url => {
            mainThumbUrlsNormalized.add(this.getOriginalImageUrl(url));
            mainThumb.push({ url, subType: 'thumb' });
        });

        // 详情图去重：归一化后与主副图比对，避免同一张图以不同 URL 形式重复出现
        const detail = this.images.detail
            .filter(url => !mainThumbUrlsNormalized.has(this.getOriginalImageUrl(url)))
            .map(url => ({ url, subType: 'detail' }));
        return { mainThumb, detail };
    }
}

// 消息处理锁：防止 popup 和悬浮按钮同时操作
let isOperationInProgress = false;

// 创建分类器实例
let classifier = null;
try {
    classifier = new MideaImageClassifier();
} catch (e) {
    console.error('分类器初始化失败:', e);
}

// 监听来自popup的消息
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    console.log('收到消息:', request.action);
    
    if (!classifier) {
        sendResponse({ success: false, error: '插件组件未正确初始化，请刷新页面后重试' });
        return;
    }

    // 进度更新（来自 background，不需要响应）
    if (request.action === 'downloadProgress') {
        updateProgress(request.current, request.total);
        // 更新标题显示第X张/共Y张
        const title = request.compressing
            ? `正在压缩打包 (${request.percent || 0}%)...`
            : `正在下载第 ${request.current}/${request.total} 张...`;
        const titleEl = document.getElementById('midea-progress-title');
        if (titleEl) titleEl.textContent = title;
        return;
    }

    // 操作锁：防止与悬浮按钮同时触发
    if (isOperationInProgress) {
        sendResponse({ success: false, error: '正在处理中，请稍候再试' });
        return;
    }
    
    switch (request.action) {
        case 'scanImages':
            try {
                isOperationInProgress = true;
                const images = classifier.scanImages();
                sendResponse({
                    success: true,
                    images: images,
                    total: images.main.length + images.thumb.length + images.detail.length
                });
            } catch (error) {
                console.error('扫描失败:', error);
                sendResponse({
                    success: false,
                    error: error.message || '扫描过程发生未知错误'
                });
            } finally {
                isOperationInProgress = false;
            }
            break;

        case 'downloadImages':
            isOperationInProgress = true;

            // 收集图片，合并为主副图 + 详情图两类
            const imagesForZip = classifier.getImagesForZip();
            const productInfo = classifier.extractProductInfo();
            const dlTotal = (imagesForZip.mainThumb?.length || 0) + (imagesForZip.detail?.length || 0);
            showProgress(`正在打包下载 (${dlTotal} 张图片)...`);

            // 向 background 发送生成 ZIP 的请求
            chrome.runtime.sendMessage({
                action: 'generateZip',
                images: imagesForZip,
                productInfo: productInfo
            }, (result) => {
                isOperationInProgress = false;
                hideProgress();
                if (chrome.runtime.lastError) {
                    sendResponse({ success: false, error: chrome.runtime.lastError.message });
                } else {
                    sendResponse(result);
                }
            });
            return true; // 异步响应

        case 'extractParams':
            try {
                isOperationInProgress = true;
                const result = classifier.extractProductParams();
                sendResponse(result);
            } catch (error) {
                console.error('参数提取失败:', error);
                sendResponse({ success: false, error: error.message || '参数提取过程发生未知错误' });
            } finally {
                isOperationInProgress = false;
            }
            break;

        case 'popupOpened':
            // popup 已打开，降低悬浮按钮透明度避免遮挡
            try {
                const btn = document.getElementById('midea-fab-btn');
                if (btn) btn.style.opacity = '0.4';
            } catch (e) {}
            sendResponse({ success: true });
            break;

        case 'popupClosed':
            // popup 已关闭，恢复悬浮按钮
            try {
                const btn = document.getElementById('midea-fab-btn');
                if (btn) btn.style.opacity = '1';
            } catch (e) {}
            sendResponse({ success: true });
            break;
            
        default:
            sendResponse({
                success: false,
                error: '未知操作: ' + request.action
            });
    }
});

// 页面加载完成后自动扫描
window.addEventListener('load', () => {
    setTimeout(() => {
        // 检查是否是美云销页面
        if (window.location.href.includes('midea.com') || 
            window.location.href.includes('smartmidea.net')) {
            console.log('美云销页面加载完成，准备扫描');
            
            // 可以在这里添加自动扫描逻辑
            // classifier.scanImages();
        }
    }, 2000);
});

// 监听URL变化（SPA页面）
try {
    let lastUrl = location.href;
    new MutationObserver(() => {
        try {
            const url = location.href;
            if (url !== lastUrl) {
                lastUrl = url;
                if (url.includes('midea.com') || url.includes('smartmidea.net')) {
                    console.log('URL变化，重新准备扫描');
                }
            }
        } catch (e) {
            console.error('MutationObserver 回调错误:', e);
        }
    }).observe(document, { subtree: true, childList: true });
} catch (e) {
    console.error('MutationObserver 初始化失败:', e);
}

console.log('美云销图片下载器 - 内容脚本已加载');

// ============================================================
// 页面悬浮面板模块 — 可展开上滑面板
// ============================================================
(function injectFloatingPanel() {
    'use strict';

    // 防止重复注入
    if (document.getElementById('midea-ext-panel')) return;

    const CSS = `
        /* ========================================
           自然韵律 (Natural Rhythm) — 悬浮面板设计
           暖白 · 森林绿 · 克制的阴影与动效
           ======================================== */

        /* 遮罩层 */
        #midea-ext-backdrop {
            position: fixed !important;
            top: 0 !important; left: 0 !important;
            width: 100% !important; height: 100% !important;
            background: rgba(0,0,0,0.18) !important;
            z-index: 2147483646 !important;
            opacity: 0 !important;
            pointer-events: none !important;
            transition: opacity 0.2s ease !important;
        }
        #midea-ext-backdrop.show {
            opacity: 1 !important;
            pointer-events: auto !important;
        }

        /* 上滑面板 */
        #midea-ext-panel {
            position: fixed !important;
            bottom: 88px !important;
            right: 24px !important;
            z-index: 2147483647 !important;
            width: 312px !important;
            background: #fff !important;
            border-radius: 14px !important;
            box-shadow: 0 4px 24px rgba(0,0,0,0.08), 0 1px 3px rgba(0,0,0,0.04) !important;
            padding: 16px !important;
            font-family: system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif !important;
            color: #1f2937 !important;
            opacity: 0 !important;
            transform: translateY(10px) !important;
            pointer-events: none !important;
            transition: opacity 0.2s ease, transform 0.2s ease !important;
        }
        #midea-ext-panel.show {
            opacity: 1 !important;
            transform: translateY(0) !important;
            pointer-events: auto !important;
        }
        #midea-ext-panel * {
            box-sizing: border-box !important;
            font-family: inherit !important;
        }

        /* 面板行 */
        .midea-panel-row {
            display: flex !important;
            align-items: center !important;
            padding: 8px 0 !important;
            gap: 10px !important;
        }
        .midea-panel-label {
            flex: 1 !important;
            font-size: 13px !important;
            font-weight: 530 !important;
            color: #1f2937 !important;
        }
        .midea-panel-action-btn {
            padding: 6px 14px !important;
            background: #2d6a4f !important;
            color: #fff !important;
            border: none !important;
            border-radius: 7px !important;
            font-size: 12px !important;
            font-weight: 530 !important;
            cursor: pointer !important;
            transition: background 0.15s, transform 0.1s !important;
            flex-shrink: 0 !important;
            white-space: nowrap !important;
        }
        .midea-panel-action-btn:hover {
            background: #1b4332 !important;
            transform: translateY(-1px) !important;
        }
        .midea-panel-action-btn:active { transform: scale(0.97) !important; }
        .midea-panel-action-btn:disabled {
            opacity: 0.45 !important;
            cursor: not-allowed !important;
            transform: none !important;
        }
        .midea-panel-action-btn .midea-btn-spinner {
            display: inline-block !important;
            width: 12px !important; height: 12px !important;
            border: 2px solid rgba(255,255,255,0.35) !important;
            border-top-color: #fff !important;
            border-radius: 50% !important;
            animation: midea-spin 0.65s linear infinite !important;
            vertical-align: middle !important;
        }

        /* 分隔线 */
        .midea-panel-divider {
            height: 1px !important;
            background: #f3f4f6 !important;
            margin: 8px 0 10px !important;
        }

        /* 派发任务区域标题 */
        .midea-panel-section-title {
            font-size: 12px !important;
            font-weight: 600 !important;
            color: #6b7280 !important;
            margin-bottom: 8px !important;
            text-transform: uppercase !important;
            letter-spacing: 0.04em !important;
        }

        /* 派发行 */
        .midea-dispatch-row {
            display: flex !important;
            align-items: center !important;
            padding: 8px 12px !important;
            margin-bottom: 8px !important;
            background: #f0fdf4 !important;
            border-radius: 10px !important;
            border: 1px solid #d1fae5 !important;
        }
        .midea-dispatch-label {
            flex: 1 !important;
            font-size: 13px !important;
            font-weight: 530 !important;
            color: #1f2937 !important;
        }
        .midea-dispatch-icon {
            width: 22px !important;
            height: 22px !important;
            flex-shrink: 0 !important;
            object-fit: contain !important;
            border-radius: 3px !important;
        }
        .midea-dispatch-btn {
            padding: 5px 14px !important;
            background: #2d6a4f !important;
            color: #fff !important;
            border: none !important;
            border-radius: 7px !important;
            font-size: 12px !important;
            font-weight: 530 !important;
            cursor: pointer !important;
            transition: background 0.15s, transform 0.1s !important;
            white-space: nowrap !important;
        }
        .midea-dispatch-btn:hover {
            background: #1b4332 !important;
            transform: translateY(-1px) !important;
        }
        .midea-dispatch-btn:active { transform: scale(0.97) !important; }
        .midea-dispatch-btn:disabled {
            opacity: 0.45 !important;
            cursor: not-allowed !important;
            transform: none !important;
        }
        .midea-dispatch-btn .midea-btn-spinner {
            display: inline-block !important;
            width: 12px !important; height: 12px !important;
            border: 2px solid rgba(255,255,255,0.35) !important;
            border-top-color: #fff !important;
            border-radius: 50% !important;
            animation: midea-spin 0.65s linear infinite !important;
            vertical-align: middle !important;
        }

        /* 悬浮按钮 */
        #midea-ext-fab {
            position: fixed !important;
            bottom: 20px !important;
            right: 20px !important;
            z-index: 2147483647 !important;
            font-family: system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif !important;
        }
        .midea-fab-btn {
            width: 48px !important;
            height: 48px !important;
            border-radius: 50% !important;
            background: #ffffff !important;
            color: #fff !important;
            border: 1.5px solid #e5e7eb !important;
            cursor: pointer !important;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08) !important;
            display: flex !important;
            align-items: center !important;
            justify-content: center !important;
            transition: transform 0.15s ease, box-shadow 0.15s ease, opacity 0.2s !important;
            user-select: none !important;
            padding: 0 !important;
            line-height: 1 !important;
            overflow: hidden !important;
        }
        .midea-fab-btn:hover {
            transform: translateY(-1px) scale(1.06) !important;
            box-shadow: 0 6px 20px rgba(0,0,0,0.12) !important;
        }
        .midea-fab-btn:active { transform: scale(0.94) !important; }
        .midea-fab-btn.faded { opacity: 0.35 !important; }
        .midea-fab-btn img {
            width: 40px !important;
            height: 40px !important;
            border-radius: 50% !important;
            object-fit: cover !important;
        }

        @keyframes midea-spin { to { transform: rotate(360deg); } }

        /* 进度条 */
        #midea-ext-progress {
            position: fixed !important;
            bottom: 88px !important;
            right: 24px !important;
            z-index: 2147483647 !important;
            width: 312px !important;
            background: #fff !important;
            border-radius: 12px !important;
            box-shadow: 0 4px 24px rgba(0,0,0,0.08), 0 1px 3px rgba(0,0,0,0.04) !important;
            padding: 14px 16px !important;
            display: none !important;
            font-family: system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif !important;
            color: #1f2937 !important;
        }
        #midea-ext-progress.show { display: block !important; }
        .midea-progress-title {
            font-size: 13px !important;
            font-weight: 530 !important;
            margin-bottom: 8px !important;
            color: #1f2937 !important;
        }
        .midea-progress-bar-bg {
            width: 100% !important;
            height: 6px !important;
            background: #f3f4f6 !important;
            border-radius: 3px !important;
            overflow: hidden !important;
        }
        .midea-progress-bar-fill {
            height: 100% !important;
            width: 0%;
            background: #2d6a4f !important;
            border-radius: 3px !important;
            transition: width 0.12s ease !important;
        }
        .midea-progress-info {
            font-size: 12px !important;
            color: #6b7280 !important;
            margin-top: 4px !important;
            text-align: right !important;
        }

        /* Toast */
        .midea-toast {
            position: fixed !important;
            bottom: 146px !important;
            right: 24px !important;
            z-index: 2147483647 !important;
            padding: 10px 16px !important;
            border-radius: 8px !important;
            font-size: 13px !important;
            font-weight: 500 !important;
            color: #fff !important;
            opacity: 0 !important;
            transform: translateY(6px) !important;
            transition: opacity 0.25s, transform 0.25s !important;
            pointer-events: none !important;
            max-width: 312px !important;
            word-break: break-all !important;
        }
        .midea-toast.show { opacity: 1 !important; transform: translateY(0) !important; }
        .midea-toast.success { background: #065f46 !important; }
        .midea-toast.error   { background: #991b1b !important; }
        .midea-toast.info    { background: #1e40af !important; }
    `;

    // 注入样式
    const styleEl = document.createElement('style');
    styleEl.textContent = CSS;
    (document.head || document.documentElement).appendChild(styleEl);

    // ====== 创建 DOM 结构 ======

    // 遮罩层
    const backdrop = document.createElement('div');
    backdrop.id = 'midea-ext-backdrop';
    document.body.appendChild(backdrop);

    // 上滑面板
    const panel = document.createElement('div');
    panel.id = 'midea-ext-panel';
    panel.innerHTML = ''
        + '<div class="midea-panel-row">'
        +   '<span class="midea-panel-label">下载商品图片</span>'
        +   '<button class="midea-panel-action-btn" id="midea-btn-download">'
        +     '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px">'
        +       '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>'
        +     '</svg>下载'
        +   '</button>'
        + '</div>'
        + '<div class="midea-panel-row">'
        +   '<span class="midea-panel-label">导出商品参数</span>'
        +   '<button class="midea-panel-action-btn" id="midea-btn-export">'
        +     '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:4px">'
        +       '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>'
        +     '</svg>导出'
        +   '</button>'
        + '</div>'
        + '<div class="midea-panel-divider"></div>'
        + '<div class="midea-panel-section-title">派发任务</div>'
        + '<div class="midea-dispatch-row">'
        +   '<img class="midea-dispatch-icon" src="' + chrome.runtime.getURL('icons/jd-icon.png') + '" alt="">'
        +   '<span class="midea-dispatch-label">京东秒送</span>'
        +   '<button class="midea-dispatch-btn" id="midea-btn-dispatch-jd">'
        +     '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:3px">'
        +       '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>'
        +     '</svg>派发'
        +   '</button>'
        + '</div>'
        + '<div class="midea-dispatch-row">'
        +   '<img class="midea-dispatch-icon" src="' + chrome.runtime.getURL('icons/mt-icon.png') + '" alt="">'
        +   '<span class="midea-dispatch-label">美团闪购</span>'
        +   '<button class="midea-dispatch-btn" id="midea-btn-dispatch-mt">'
        +     '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-2px;margin-right:3px">'
        +       '<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>'
        +     '</svg>派发'
        +   '</button>'
        + '</div>';
    document.body.appendChild(panel);

    // 悬浮按钮
    const fabWrapper = document.createElement('div');
    fabWrapper.id = 'midea-ext-fab';
    fabWrapper.innerHTML = '<button class="midea-fab-btn" id="midea-fab-btn" title="展开操作面板"><img src="' + chrome.runtime.getURL('icons/mcsp-logo-lightblue.png') + '" alt="MCSP"></button>';
    document.body.appendChild(fabWrapper);

    // 进度条（供 showProgress / updateProgress / hideProgress 使用）
    const progressBar = document.createElement('div');
    progressBar.id = 'midea-ext-progress';
    progressBar.innerHTML = ''
        + '<div class="midea-progress-title" id="midea-progress-title">正在下载图片...</div>'
        + '<div class="midea-progress-bar-bg">'
        +   '<div class="midea-progress-bar-fill" id="midea-progress-fill" style="width:0%"></div>'
        + '</div>'
        + '<div class="midea-progress-info" id="midea-progress-info">0 / 0</div>';
    document.body.appendChild(progressBar);

    // Toast 容器
    const toast = document.createElement('div');
    toast.className = 'midea-toast';
    toast.id = 'midea-ext-toast';
    document.body.appendChild(toast);

    // ====== 内部工具函数 ======
    let panelOpen = false;

    function showToast(msg, type, duration) {
        type = type || 'info';
        duration = duration || 3000;
        toast.textContent = msg;
        toast.className = 'midea-toast ' + type + ' show';
        clearTimeout(toast._timer);
        toast._timer = setTimeout(function() { toast.classList.remove('show'); }, duration);
    }

    function openPanel() {
        panelOpen = true;
        backdrop.classList.add('show');
        panel.classList.add('show');
        var fb = document.getElementById('midea-fab-btn');
        if (fb) fb.classList.add('faded');
    }

    function closePanel() {
        panelOpen = false;
        backdrop.classList.remove('show');
        panel.classList.remove('show');
        var fb = document.getElementById('midea-fab-btn');
        if (fb) fb.classList.remove('faded');
    }

    function togglePanel() {
        if (isOperationInProgress) return;
        if (panelOpen) { closePanel(); } else { openPanel(); }
    }

    // 按钮 loading 态（替换为旋转器）
    function setBtnLoading(btn, loading) {
        if (!btn) return;
        if (loading) {
            btn.disabled = true;
            btn._origHTML = btn.innerHTML;
            btn.innerHTML = '<span class="midea-btn-spinner"></span>';
        } else {
            btn.disabled = false;
            if (btn._origHTML !== undefined) btn.innerHTML = btn._origHTML;
        }
    }

    // JSON 下载
    function downloadJSON(data, filename) {
        var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' });
        var url = URL.createObjectURL(blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function() { URL.revokeObjectURL(url); }, 100);
    }

    // 扁平化参数数组
    function flattenParams(groups) {
        var result = [];
        if (!groups) return result;
        groups.forEach(function(group) {
            Object.keys(group.items).forEach(function(key) {
                result.push({ key: key, value: group.items[key], group: group.name });
            });
        });
        return result;
    }

    // ====== 核心操作 ======

    // 1) 下载商品图片（复用原有扫描 + 打包流程）
    async function handleDownloadImages() {
        if (isOperationInProgress) return;
        if (!classifier) {
            showToast('插件未正确初始化，请刷新页面', 'error');
            return;
        }

        closePanel();

        isOperationInProgress = true;
        var btn = document.getElementById('midea-btn-download');
        setBtnLoading(btn, true);
        showToast('正在扫描页面图片...', 'info');

        var images = null;
        var total = 0;
        var MAX_CLICK_RETRY = 4;
        var CLICK_RETRY_INTERVAL = 600;

        for (var i = 0; i <= MAX_CLICK_RETRY; i++) {
            try {
                images = classifier.scanImages();
            } catch (e) {
                showToast('扫描失败：' + e.message, 'error');
                isOperationInProgress = false;
                setBtnLoading(btn, false);
                return;
            }
            total = images.main.length + images.thumb.length + images.detail.length;
            if (total > 0) break;
            if (i < MAX_CLICK_RETRY) {
                showToast('未检测到图片，正在重试（' + (i + 1) + '/' + MAX_CLICK_RETRY + '）...', 'info', 800);
                await new Promise(function(r) { setTimeout(r, CLICK_RETRY_INTERVAL); });
            }
        }

        if (total === 0) {
            showToast('未找到商品图片，请确认当前为商品详情页', 'error', 4000);
            isOperationInProgress = false;
            setBtnLoading(btn, false);
            return;
        }

        showToast(
            '找到 ' + total + ' 张图片（主副图 ' + (images.main.length + images.thumb.length)
            + ' + 详情图 ' + images.detail.length + '），正在打包...',
            'info'
        );

        // 触发全局进度条
        showProgress('正在打包下载 (' + total + ' 张图片)...');

        var imagesForZip = classifier.getImagesForZip();
        var productInfo = classifier.extractProductInfo();

        chrome.runtime.sendMessage({
            action: 'generateZip',
            images: imagesForZip,
            productInfo: productInfo
        }, function(result) {
            isOperationInProgress = false;
            setBtnLoading(btn, false);

            if (chrome.runtime.lastError) {
                hideProgress();
                showToast('下载失败：' + chrome.runtime.lastError.message, 'error');
                return;
            }

            if (result && result.success) {
                var msg = result.errors && result.errors.length > 0
                    ? '打包完成！' + result.fetched + '/' + result.total + ' 张（' + result.errors.length + ' 张失败）'
                    : '打包完成！共 ' + result.fetched + ' 张图片';
                showToast(msg, 'success', 5000);
                setTimeout(hideProgress, 800);
            } else {
                hideProgress();
                showToast('打包失败：' + (result && result.error ? result.error : '未知错误'), 'error');
            }
        });
    }

    // 2) 导出商品参数 → JSON 下载
    function handleExportParams() {
        if (isOperationInProgress) return;
        if (!classifier) {
            showToast('插件未正确初始化，请刷新页面', 'error');
            return;
        }

        isOperationInProgress = true;
        var btn = document.getElementById('midea-btn-export');
        setBtnLoading(btn, true);

        try {
            var paramsResult = classifier.extractProductParams();
            if (!paramsResult.success) {
                showToast(paramsResult.error || '未能提取商品参数', 'error');
                isOperationInProgress = false;
                setBtnLoading(btn, false);
                return;
            }

            var productInfo = classifier.extractProductInfo();
            var exportData = {
                product: {
                    code: productInfo.code,
                    name: productInfo.name
                },
                params: paramsResult.groups,
                exportedAt: new Date().toISOString(),
                sourceUrl: window.location.href
            };

            var filename = (productInfo.code !== 'unknown' ? productInfo.code : 'product') + '-params.json';
            downloadJSON(exportData, filename);

            showToast('参数导出成功：' + paramsResult.totalParams + ' 项', 'success', 4000);
            closePanel();
        } catch (e) {
            showToast('导出失败：' + e.message, 'error');
        } finally {
            isOperationInProgress = false;
            setBtnLoading(btn, false);
        }
    }

    // 3) 派发任务 → POST localhost:5200
    async function handleDispatch(targetSite) {
        if (isOperationInProgress) return;
        if (!classifier) {
            showToast('插件未正确初始化，请刷新页面', 'error');
            return;
        }

        isOperationInProgress = true;

        var dispatchBtnId = targetSite === 'jd_instant' ? 'midea-btn-dispatch-jd' : 'midea-btn-dispatch-mt';
        var label = targetSite === 'jd_instant' ? '京东秒送' : '美团闪购';
        var btn = document.getElementById(dispatchBtnId);
        setBtnLoading(btn, true);

        showToast('正在收集数据并派发到 ' + label + '...', 'info');

        try {
            // 扫描图片 — 分类主副图和详情图
            var imageData = classifier.scanImages();
            var mainThumbUrls = [].concat(imageData.main, imageData.thumb).map(function(u) { return u; });
            var detailUrls = [].concat(imageData.detail).map(function(u) { return u; });
            var allImageUrls = mainThumbUrls.concat(detailUrls);

            // 提取参数
            var paramsResult = classifier.extractProductParams();
            var productInfo = classifier.extractProductInfo();
            var flatParams = paramsResult.success ? flattenParams(paramsResult.groups) : [];

            // 兜底：如果从页面提取的名称异常（仓库信息/空/默认值），从 params 重建
            var badNamePattern = /(仓库|物流|云仓|仓储|库房|商品图片)/;
            if (!productInfo.name || badNamePattern.test(productInfo.name)) {
                var brand = flatParams.find(function(p) { return p.key.indexOf('品牌') >= 0; });
                var model = flatParams.find(function(p) { return p.key.indexOf('型号') >= 0; });
                if (brand || model) {
                    productInfo.name = (brand ? brand.value : '') + (brand && model ? ' ' : '') + (model ? model.value : '');
                    productInfo.name = productInfo.name.trim();
                    console.log('[midea-ext] rebuilt product name from params:', productInfo.name);
                }
            }

            // 目标URL（按平台使用默认地址）
            var targetUrl = targetSite === 'meituan_flash'
                ? 'https://shangoue.meituan.com/#/reuse/sc/product/views/merchant/product/addDetail'
                : 'https://store.jddj.com/v3/product/instantPublish?pageSource=5';

            var body = {
                product: {
                    code: productInfo.code,
                    name: productInfo.name,
                    params: flatParams
                },
                images: allImageUrls,
                images_mainThumb: mainThumbUrls,
                images_detail: detailUrls,
                target_site: targetSite,
                target_url: targetUrl
            };

            var resp = await fetch('http://localhost:5200/submit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });

            if (!resp.ok) {
                throw new Error('HTTP ' + resp.status + ' ' + resp.statusText);
            }

            var result = null;
            try { result = await resp.json(); } catch (ex) { /* 忽略解析错误 */ }

            showToast('派发成功！', 'success', 4000);
            closePanel();
        } catch (e) {
            showToast('派发失败：' + e.message, 'error', 5000);
        } finally {
            isOperationInProgress = false;
            setBtnLoading(btn, false);
        }
    }

    // ====== 事件绑定 ======
    var fabBtn = document.getElementById('midea-fab-btn');
    fabBtn.addEventListener('click', togglePanel);
    backdrop.addEventListener('click', closePanel);

    // 面板按钮
    document.getElementById('midea-btn-download').addEventListener('click', handleDownloadImages);
    document.getElementById('midea-btn-export').addEventListener('click', handleExportParams);
    document.getElementById('midea-btn-dispatch-jd').addEventListener('click', function() {
        handleDispatch('jd_instant');
    });
    document.getElementById('midea-btn-dispatch-mt').addEventListener('click', function() {
        handleDispatch('meituan_flash');
    });

    // 阻止面板内部点击冒泡到遮罩
    panel.addEventListener('click', function(e) { e.stopPropagation(); });

    // ====== 初始扫描（异步渲染重试 + MutationObserver 持续监听） ======
    (function initButtonState() {
        if (!classifier) return;

        var retryCount = 0;
        var MAX_RETRY = 10;
        var RETRY_INTERVAL = 500;
        var retryTimer = null;
        var obs = null;

        function startObserver() {
            if (obs) return;
            try {
                obs = new MutationObserver(function(mutations) {
                    var hasNewImg = mutations.some(function(m) {
                        return m.addedNodes && Array.prototype.slice.call(m.addedNodes).some(function(n) {
                            return n.tagName === 'IMG' || (n.querySelectorAll && n.querySelectorAll('img').length > 0);
                        });
                    });
                    if (hasNewImg) {
                        console.log('[MideaExt] DOM变化检测到新图片，重新扫描...');
                        try {
                            var imgs = classifier.scanImages();
                            var t = imgs.main.length + imgs.thumb.length + imgs.detail.length;
                            if (t > 0) {
                                console.log('[MideaExt] 检测到 ' + t + ' 张商品图片');
                                if (obs) { obs.disconnect(); obs = null; }
                            }
                        } catch (ex) {}
                    }
                });
                obs.observe(document.body, { childList: true, subtree: true });
                console.log('[MideaExt] MutationObserver 已启动，监听异步图片加载');
            } catch (e) {
                console.error('[MideaExt] MutationObserver 启动失败:', e);
            }
        }

        function doScan() {
            try {
                var imgs = classifier.scanImages();
                var t = imgs.main.length + imgs.thumb.length + imgs.detail.length;
                if (t > 0) {
                    console.log('[MideaExt] 初始扫描成功：找到 ' + t + ' 张商品图片');
                    if (obs) { obs.disconnect(); obs = null; }
                    return true;
                }
            } catch (e) {
                console.warn('[MideaExt] 初始扫描异常:', e.message);
            }
            return false;
        }

        function scheduleRetry() {
            retryCount++;
            if (retryCount >= MAX_RETRY) {
                console.log('[MideaExt] 已重试 ' + MAX_RETRY + ' 次，启动持续监听');
                startObserver();
                return;
            }
            console.log('[MideaExt] 第 ' + retryCount + '/' + MAX_RETRY + ' 次重试扫描...');
            retryTimer = setTimeout(function() {
                if (!doScan()) scheduleRetry();
            }, RETRY_INTERVAL);
        }

        if (!doScan()) {
            console.log('[MideaExt] 首次扫描未找到图片，启动重试机制...');
            scheduleRetry();
        } else {
            startObserver();
        }
    })();

})();

// ====== 全局进度条控制（供 onMessage 和面板 IIFE 内部共同引用） ======
function showProgress(title) {
    const el = document.getElementById('midea-ext-progress');
    if (!el) return;
    document.getElementById('midea-progress-title').textContent = title || '正在下载图片...';
    document.getElementById('midea-progress-fill').style.width = '0%';
    document.getElementById('midea-progress-info').textContent = '0 / 0';
    el.classList.add('show');
}

function updateProgress(current, total) {
    const fill = document.getElementById('midea-progress-fill');
    const info = document.getElementById('midea-progress-info');
    const pct = total > 0 ? Math.round((current / total) * 100) : 0;
    if (info) info.textContent = `${current} / ${total}`;
    if (fill) {
        // 使用 requestAnimationFrame 确保每次更新都在独立帧中渲染，
        // 避免浏览器批量合并多次样式变更导致进度条跳帧或"提前走完"
        requestAnimationFrame(() => {
            fill.style.width = `${pct}%`;
        });
    }
}

function hideProgress() {
    const el = document.getElementById('midea-ext-progress');
    if (el) el.classList.remove('show');
}
