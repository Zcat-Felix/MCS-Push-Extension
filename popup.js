// 美云销图片下载器 · 弹出窗口脚本
// 设计系统：自然韵律 — 暖白 · 森林绿 · 克制的动效

document.addEventListener('DOMContentLoaded', function () {

    // ========== DOM 元素 ==========
    const statusDot      = document.getElementById('statusDot');
    const pageStatus     = document.getElementById('pageStatus');
    const currentUrl     = document.getElementById('currentUrl');
    const mainCount      = document.getElementById('mainCount');
    const thumbCount     = document.getElementById('thumbCount');
    const detailCount    = document.getElementById('detailCount');
    const scanBtn        = document.getElementById('scanBtn');
    const downloadBtn    = document.getElementById('downloadBtn');
    const exportParamsBtn = document.getElementById('exportParamsBtn');
    const settingsTrigger = document.getElementById('settingsTrigger');
    const settingsPanel  = document.getElementById('settingsPanel');
    const loadingArea    = document.getElementById('loadingArea');
    const progress       = document.getElementById('progress');
    const errorMessage   = document.getElementById('errorMessage');
    const successMessage = document.getElementById('successMessage');

    // 设置开关
    const autoHighQuality  = document.getElementById('autoHighQuality');
    const categorizeFolders = document.getElementById('categorizeFolders');
    const showProgressOpt  = document.getElementById('showProgress');

    // ========== 状态 ==========
    let currentImages = { main: [], thumb: [], detail: [] };
    let isScanning    = false;
    let isDownloading = false;
    let isExporting   = false;

    // ========== 初始化 ==========
    init();

    async function init() {
        // 加载保存的设置
        try {
            const s = await chrome.storage.local.get([
                'autoHighQuality', 'categorizeFolders', 'showProgress'
            ]);
            autoHighQuality.checked  = s.autoHighQuality !== false;
            categorizeFolders.checked = s.categorizeFolders !== false;
            showProgressOpt.checked   = s.showProgress !== false;
        } catch (e) { /* 非关键 */ }

        // 检测当前标签页
        try {
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (tab && tab.url) {
                currentUrl.textContent = tab.url;
                if (isMideaUrl(tab.url)) {
                    setStatus('on', '当前是美云销商品页面');
                    scanBtn.disabled = false;
                    setTimeout(() => scanImages(), 400);
                } else {
                    setStatus('off', '请在美云销商品详情页使用');
                    scanBtn.disabled = true;
                }
            } else {
                setStatus('off', '无法读取当前页面');
                scanBtn.disabled = true;
            }
        } catch (e) {
            setStatus('off', '无法获取标签页信息');
            scanBtn.disabled = true;
        }

        // 通知 content script
        try {
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (tab && tab.id && isMideaUrl(tab.url)) {
                chrome.tabs.sendMessage(tab.id, { action: 'popupOpened' });
            }
        } catch (e) { /* 非关键 */ }
    }

    // ========== 工具 ==========

    function isMideaUrl(url) {
        return /midea\.com|smartmidea\.net|signin\.midea\.com|sales\.midea\.com/.test(url);
    }

    function setStatus(state, text) {
        statusDot.className = 'status-dot ' + (state === 'on' ? 'on' : 'off');
        pageStatus.innerHTML = text;
    }

    function setCount(el, n) {
        el.textContent = n;
        el.className = 'stat-value' + (n === 0 ? ' zero' : '');
    }

    function showMessage(type, msg) {
        errorMessage.style.display   = 'none';
        successMessage.style.display = 'none';
        if (type === 'error') {
            errorMessage.textContent = msg;
            errorMessage.style.display = 'block';
            errorMessage.className = 'message error';
        } else {
            successMessage.textContent = msg;
            successMessage.style.display = 'block';
            successMessage.className = 'message ' + (type === 'info' ? 'info' : 'success');
        }
        clearTimeout(showMessage._t);
        showMessage._t = setTimeout(() => {
            errorMessage.style.display   = 'none';
            successMessage.style.display = 'none';
        }, 3500);
    }

    function setBtnState(btn, disabled, text) {
        btn.disabled = disabled;
        if (text) btn.innerHTML = text;
    }

    // ========== 扫描图片 ==========
    async function scanImages() {
        if (isScanning) return;
        isScanning = true;
        setBtnState(scanBtn, true, '<span class="btn-icon">⊙</span>扫描中…');

        try {
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (!tab || !tab.id) { showMessage('error', '无法获取当前标签页'); return; }

            const response = await sendToTab(tab.id, { action: 'scanImages' });
            if (response && response.success) {
                currentImages = response.images;
                const total = currentImages.main.length
                            + currentImages.thumb.length
                            + currentImages.detail.length;

                setCount(mainCount,   currentImages.main.length);
                setCount(thumbCount,  currentImages.thumb.length);
                setCount(detailCount, currentImages.detail.length);

                if (total > 0) {
                    setBtnState(downloadBtn, false,
                        '<span class="btn-icon">↓</span>下载（' + total + ' 张）');
                    showMessage('success', '找到 ' + total + ' 张商品图片');
                } else {
                    setBtnState(downloadBtn, true, '<span class="btn-icon">↓</span>下载图片');
                    showMessage('info', '未发现商品图片，可尝试刷新页面后重试');
                }
            } else {
                showMessage('error', response?.error || '扫描未成功，请确认当前是商品详情页');
            }
        } catch (e) {
            showMessage('error', '扫描出错：' + e.message);
        } finally {
            isScanning = false;
            setBtnState(scanBtn, false, '<span class="btn-icon">⊙</span>扫描图片');
        }
    }

    // ========== 下载图片 ==========
    async function downloadImages() {
        if (isDownloading) return;
        const total = currentImages.main.length
                    + currentImages.thumb.length
                    + currentImages.detail.length;
        if (total === 0) { showMessage('info', '请先扫描页面图片'); return; }

        isDownloading = true;
        setBtnState(downloadBtn, true, '<span class="btn-icon">↓</span>打包中…');
        loadingArea.style.display = 'block';
        progress.style.width = '0%';

        try {
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

            // 保存设置
            await chrome.storage.local.set({
                autoHighQuality:  autoHighQuality.checked,
                categorizeFolders: categorizeFolders.checked,
                showProgress:     showProgressOpt.checked
            });

            // 发送下载请求
            const response = await sendToTab(tab.id, { action: 'downloadImages' });

            // 模拟进度（打包在后台进行）
            let sim = 0;
            const iv = setInterval(() => {
                sim += Math.floor(Math.random() * 8) + 2;
                if (sim > 94) sim = 94;
                progress.style.width = sim + '%';
            }, 180);

            if (response && response.success) {
                clearInterval(iv);
                progress.style.width = '100%';
                setTimeout(() => {
                    loadingArea.style.display = 'none';
                    const err = (response.errors && response.errors.length > 0)
                        ? '（' + response.errors.length + ' 张失败）' : '';
                    showMessage('success',
                        '打包完成，共 ' + (response.fetched || total) + ' 张图片' + err);
                    setBtnState(downloadBtn, false,
                        '<span class="btn-icon">↓</span>重新打包');
                }, 600);
            } else {
                clearInterval(iv);
                throw new Error(response?.error || '打包失败');
            }
        } catch (e) {
            loadingArea.style.display = 'none';
            showMessage('error', '下载出错：' + e.message);
            setBtnState(downloadBtn, false,
                '<span class="btn-icon">↓</span>下载（' + total + ' 张）');
        } finally {
            isDownloading = false;
        }
    }

    // ========== 导出参数 ==========
    async function exportParams() {
        if (isExporting) return;
        isExporting = true;
        setBtnState(exportParamsBtn, true, '<span class="btn-icon">⏏</span>提取中…');

        try {
            const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
            if (!tab || !tab.id) { showMessage('error', '无法获取当前标签页'); return; }

            // 提取参数
            const resp = await sendToTab(tab.id, { action: 'extractParams' });
            if (!resp || !resp.success) {
                showMessage('error', resp?.error || '未提取到商品参数');
                return;
            }

            // 获取商品信息
            const urlMatch = tab.url.match(/productCode=(\d+)/);
            const code = urlMatch ? urlMatch[1] : 'unknown';
            const name = tab.title.replace(/[-–—]\s*美云销.*$/, '').trim() || '商品';

            // 触发后台保存
            const saveResp = await new Promise(resolve => {
                chrome.runtime.sendMessage({
                    action: 'saveParams',
                    groups: resp.groups,
                    productInfo: { code, name }
                }, r => {
                    if (chrome.runtime.lastError) {
                        resolve({ success: false, error: chrome.runtime.lastError.message });
                    } else { resolve(r); }
                });
            });

            if (saveResp && saveResp.success) {
                showMessage('success', '导出成功，共 ' + (resp.totalParams || 0) + ' 项参数');
            } else {
                showMessage('error', saveResp?.error || '保存失败');
            }
        } catch (e) {
            showMessage('error', '导出出错：' + e.message);
        } finally {
            isExporting = false;
            setBtnState(exportParamsBtn, false, '<span class="btn-icon">⏏</span>导出商品参数');
        }
    }

    // ========== 设置面板 ==========
    function toggleSettings() {
        const open = settingsPanel.style.display === 'block';
        settingsPanel.style.display = open ? 'none' : 'block';
        settingsTrigger.classList.toggle('open', !open);
    }

    async function saveSettings() {
        await chrome.storage.local.set({
            autoHighQuality:  autoHighQuality.checked,
            categorizeFolders: categorizeFolders.checked,
            showProgress:     showProgressOpt.checked
        });
    }

    // ========== 发送消息辅助 ==========
    function sendToTab(tabId, message) {
        return new Promise(resolve => {
            chrome.tabs.sendMessage(tabId, message, result => {
                if (chrome.runtime.lastError) {
                    resolve({ success: false, error: '无法连接页面，请刷新后重试' });
                } else { resolve(result); }
            });
        });
    }

    // ========== 事件绑定 ==========
    scanBtn.addEventListener('click', scanImages);
    downloadBtn.addEventListener('click', downloadImages);
    exportParamsBtn.addEventListener('click', exportParams);
    settingsTrigger.addEventListener('click', toggleSettings);

    autoHighQuality.addEventListener('change', saveSettings);
    categorizeFolders.addEventListener('change', saveSettings);
    showProgressOpt.addEventListener('change', saveSettings);

    // Esc 关闭设置面板
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && settingsPanel.style.display === 'block') {
            toggleSettings();
        }
    });

});
