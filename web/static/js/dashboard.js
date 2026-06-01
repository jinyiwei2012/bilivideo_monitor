const API_BASE = '/api/v1';
let authToken = '';
let currentUser = null;
let ws = null;
let selectedBvid = null;
let trendChart = null;

function init() {
    checkStoredToken();
    bindEvents();
    updateClock();
    setInterval(updateClock, 10000);
    refreshAll();
    connectWebSocket();
}

function checkStoredToken() {
    const stored = localStorage.getItem('bili_monitor_token');
    if (stored) {
        authToken = stored;
        loadUserInfo();
    }
    updateAuthUI();
}

function bindEvents() {
    document.getElementById('auth-btn').addEventListener('click', toggleAuthModal);
    document.getElementById('auth-submit').addEventListener('click', doLogin);
    document.getElementById('auth-cancel').addEventListener('click', hideAuthModal);
    document.getElementById('refresh-btn').addEventListener('click', refreshAll);

    document.getElementById('add-btn').addEventListener('click', addVideo);
    document.getElementById('add-bvid').addEventListener('keydown', e => { if (e.key === 'Enter') addVideo(); });

    document.getElementById('search-input').addEventListener('input', debounce(searchVideos, 400));
    document.getElementById('search-field').addEventListener('change', searchVideos);

    document.getElementById('sort-by').addEventListener('change', loadVideos);
    document.getElementById('sort-order').addEventListener('change', loadVideos);

    document.getElementById('detail-close').addEventListener('click', closeDetail);

    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });
}

function updateAuthUI() {
    const btn = document.getElementById('auth-btn');
    const info = document.getElementById('user-info');
    if (currentUser) {
        btn.textContent = '退出';
        btn.className = 'btn btn-sm';
        info.textContent = currentUser.username + (currentUser.is_admin ? ' [管理员]' : '');
        info.style.color = 'var(--primary)';
    } else {
        btn.textContent = '登录/注册';
        btn.className = 'btn btn-sm btn-primary';
        info.textContent = '未登录';
        info.style.color = 'var(--text-secondary)';
    }
}

function authHeaders() {
    const headers = {};
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
    return headers;
}

async function api(path, options = {}) {
    const headers = { ...authHeaders(), ...(options.headers || {}) };
    const res = await fetch(API_BASE + path, { ...options, headers });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || '请求失败');
    }
    return res.json();
}

async function loadUserInfo() {
    try {
        const data = await api('/auth/me');
        currentUser = data.user;
        updateAuthUI();
    } catch (e) {
        authToken = '';
        currentUser = null;
        localStorage.removeItem('bili_monitor_token');
        updateAuthUI();
    }
}

async function loadStats() {
    try {
        const data = await api('/stats');
        document.getElementById('stat-videos').textContent = data.total_videos || 0;
        document.getElementById('stat-records').textContent = data.total_records || 0;
        document.getElementById('stat-views').textContent = formatNumber(data.total_views || 0);
        document.getElementById('stat-ws').textContent = data.ws_connections || 0;
    } catch (e) { console.error('加载统计失败:', e); }
}

async function loadVideos() {
    const sortBy = document.getElementById('sort-by').value;
    const order = document.getElementById('sort-order').value;
    try {
        const data = await api(`/videos?sort_by=${sortBy}&order=${order}&limit=50`);
        renderVideoGrid(data.videos || []);
        document.getElementById('result-count').textContent = `共 ${data.total} 个视频`;
    } catch (e) {
        document.getElementById('video-grid').innerHTML = `<div class="empty-state">加载失败: ${e.message}</div>`;
    }
}

function renderVideoGrid(videos) {
    const grid = document.getElementById('video-grid');
    if (!videos.length) {
        grid.innerHTML = '<div class="empty-state">暂无监控视频</div>';
        return;
    }
    grid.innerHTML = videos.map(v => `
        <div class="video-card" onclick="openDetail('${escapeHtml(v.bvid)}')">
            <div class="vc-title">${escapeHtml(v.title || v.bvid)}</div>
            <div class="vc-meta">
                <span>${escapeHtml(v.owner_name || '—')}</span>
                <span>BV ${escapeHtml(v.bvid)}</span>
            </div>
            <div class="vc-stats">
                <div class="vc-stat"><span class="vc-stat-val">${formatNumber(v.view_count)}</span><span class="vc-stat-lbl">播放</span></div>
                <div class="vc-stat"><span class="vc-stat-val">${formatNumber(v.like_count)}</span><span class="vc-stat-lbl">点赞</span></div>
                <div class="vc-stat"><span class="vc-stat-val">${formatNumber(v.favorite_count)}</span><span class="vc-stat-lbl">收藏</span></div>
            </div>
        </div>
    `).join('');
}

async function openDetail(bvid) {
    selectedBvid = bvid;
    document.getElementById('detail-panel').classList.remove('hidden');
    try {
        const video = await api(`/videos/${bvid}`);
        renderDetailInfo(video);
    } catch (e) {}
    const activeTab = document.querySelector('.tab-btn.active')?.dataset.tab || 'info';
    if (activeTab === 'chart') loadChart();
    if (activeTab === 'predictions') loadPredictions();
    if (activeTab === 'milestones') loadMilestones();
}

function renderDetailInfo(video) {
    document.getElementById('detail-title').textContent = video.title || video.bvid;
    const info = document.getElementById('detail-info');
    const fields = [
        ['BV号', video.bvid], ['播放量', formatNumber(video.view_count)],
        ['点赞', formatNumber(video.like_count)], ['投币', formatNumber(video.coin_count)],
        ['收藏', formatNumber(video.favorite_count)], ['分享', formatNumber(video.share_count)],
        ['弹幕', formatNumber(video.danmaku_count)], ['评论', formatNumber(video.reply_count)],
        ['在线观看', formatNumber(video.viewers_total)], ['播赞比', (video.like_view_ratio || 0).toFixed(4)],
        ['UP主', video.owner_name || '—'], ['时长', formatDuration(video.duration)],
        ['发布时间', video.pubdate || '—'],
    ];
    info.innerHTML = fields.map(([label, value]) => `
        <div class="info-item"><div class="info-label">${label}</div><div class="info-value">${value}</div></div>
    `).join('');
}

async function loadChart() {
    if (!selectedBvid) return;
    try {
        const data = await api(`/videos/${selectedBvid}/records?limit=500`);
        const records = data.records || [];
        if (!records.length) { document.getElementById('tab-chart').innerHTML = '<p class="empty-state">暂无监控数据</p>'; return; }
        const labels = records.map(r => {
            const d = new Date(r.timestamp);
            return `${d.getMonth()+1}/${d.getDate()} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
        });
        const views = records.map(r => r.view_count);

        if (trendChart) trendChart.destroy();
        const ctx = document.getElementById('trend-chart');
        if (!ctx) return;
        trendChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels,
                datasets: [{
                    label: '播放量', data: views,
                    borderColor: '#58a6ff', backgroundColor: 'rgba(88,166,255,0.08)',
                    fill: true, tension: 0.3, pointRadius: 0,
                }],
            },
            options: {
                responsive: true, maintainAspectRatio: false,
                interaction: { intersect: false, mode: 'index' },
                plugins: { legend: { labels: { color: '#8b949e' } } },
                scales: {
                    x: { ticks: { color: '#8b949e', maxTicksLimit: 10 }, grid: { color: '#2a3040' } },
                    y: { ticks: { color: '#8b949e', callback: v => formatNumber(v) }, grid: { color: '#2a3040' } },
                },
            },
        });
    } catch (e) { console.error('加载图表失败:', e); }
}

async function loadPredictions() {
    if (!selectedBvid) return;
    try {
        const data = await api(`/videos/${selectedBvid}/predictions?limit=50`);
        const preds = data.predictions || [];
        if (!preds.length) {
            document.getElementById('predictions-list').innerHTML = '<div class="empty-state">暂无预测数据<br><small>请通过 GUI 客户端生成预测</small></div>';
            return;
        }
        document.getElementById('predictions-list').innerHTML = preds.map(p => `
            <div class="pred-item">
                <div class="pred-algo">${escapeHtml(p.algorithm || p.algorithm_id)}</div>
                <div class="pred-threshold">目标: ${formatNumber(p.target_threshold)} 播放</div>
                <div class="pred-time">预计: ${p.predicted_time || '—'}</div>
                <div class="pred-confidence">置信度: ${((p.confidence || 0) * 100).toFixed(0)}%</div>
            </div>
        `).join('');
    } catch (e) {}
}

async function loadMilestones() {
    if (!selectedBvid) return;
    try {
        const data = await api(`/videos/${selectedBvid}/milestones`);
        const ms = data.milestones || [];
        document.getElementById('milestones-list').innerHTML = ms.length
            ? ms.map(m => `<div class="milestone-item"><div class="ms-period">${escapeHtml(m.period)}</div><div class="ms-views">${formatNumber(m.view_count)} 播放</div></div>`).join('')
            : '<div class="empty-state">暂无里程碑数据</div>';
    } catch (e) {}
}

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    document.querySelector(`[data-tab="${tab}"]`).classList.add('active');
    document.getElementById(`tab-${tab}`).classList.add('active');
    if (tab === 'chart') loadChart();
    if (tab === 'predictions') loadPredictions();
    if (tab === 'milestones') loadMilestones();
}

function closeDetail() {
    document.getElementById('detail-panel').classList.add('hidden');
    selectedBvid = null;
    if (trendChart) { trendChart.destroy(); trendChart = null; }
}

async function searchVideos() {
    const keyword = document.getElementById('search-input').value.trim();
    const field = document.getElementById('search-field').value;
    if (!keyword) { loadVideos(); return; }
    try {
        const data = await api(`/search?keyword=${encodeURIComponent(keyword)}&field=${field}&limit=50`);
        renderVideoGrid(data.results || []);
        document.getElementById('result-count').textContent = `搜索 "${keyword}": ${data.total} 个结果`;
    } catch (e) {}
}

async function addVideo() {
    const input = document.getElementById('add-bvid');
    const bvid = input.value.trim();
    if (!bvid) { showToast('请输入 BV 号', 'error'); return; }
    if (!authToken) { showToast('请先登录', 'error'); showAuthModal(); return; }
    try {
        const data = await api(`/videos?bvid=${encodeURIComponent(bvid)}`, { method: 'POST' });
        showToast(`已添加: ${data.title || bvid}`, 'success');
        input.value = '';
        loadVideos(); loadStats();
    } catch (e) { showToast(`添加失败: ${e.message}`, 'error'); }
}

async function removeVideo(bvid) {
    if (!authToken) { showToast('请先登录', 'error'); showAuthModal(); return; }
    if (!confirm(`确认移除视频 ${bvid}？`)) return;
    try {
        await api(`/videos/${bvid}`, { method: 'DELETE' });
        showToast(`已移除 ${bvid}`, 'success');
        if (selectedBvid === bvid) closeDetail();
        loadVideos(); loadStats();
    } catch (e) { showToast(`移除失败: ${e.message}`, 'error'); }
}

async function triggerPredict() {
    if (!selectedBvid) return;
    if (!authToken) { showToast('请先登录', 'error'); showAuthModal(); return; }
    try {
        showToast('正在预测...', 'info');
        const data = await api(`/videos/${selectedBvid}/predict`, { method: 'POST' });
        showToast(`预测完成: ${formatNumber(data.result.prediction)}`, 'success');
        loadPredictions();
    } catch (e) { showToast(`预测失败: ${e.message}`, 'error'); }
}

async function refreshAll() {
    await Promise.all([loadStats(), loadVideos()]);
}

// ── 认证相关 ──────────────────────────────────

let authMode = 'login';

function toggleAuthModal() {
    if (currentUser) {
        logout();
        return;
    }
    showAuthModal();
}

function showAuthModal() {
    document.getElementById('auth-modal').classList.remove('hidden');
    document.getElementById('auth-token').value = '';
    document.getElementById('auth-error').classList.add('hidden');
    switchAuthTab('login');
    document.getElementById('auth-username')?.focus();
}

function hideAuthModal() {
    document.getElementById('auth-modal').classList.add('hidden');
}

function switchAuthTab(mode) {
    authMode = mode;
    document.getElementById('login-fields').style.display = mode === 'login' ? 'block' : 'none';
    document.getElementById('register-fields').style.display = mode === 'register' ? 'block' : 'none';
    document.getElementById('account-fields').style.display = mode === 'account' ? 'block' : 'none';
    document.getElementById('auth-error').classList.add('hidden');
    document.getElementById('auth-submit').textContent = mode === 'register' ? '注册' : mode === 'account' ? '更新' : '登录';
}

async function doLogin() {
    const errorEl = document.getElementById('auth-error');

    if (authMode === 'login') {
        const username = document.getElementById('auth-username').value.trim();
        const password = document.getElementById('auth-password').value.trim();

        if (username && password) {
            try {
                const res = await fetch(API_BASE + '/auth/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username, password }),
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || '登录失败');
                setAuth(data.user);
                hideAuthModal();
                showToast(`欢迎, ${data.user.username}`);
            } catch (e) {
                errorEl.classList.remove('hidden');
                errorEl.textContent = e.message;
            }
        } else {
            errorEl.classList.remove('hidden');
            errorEl.textContent = '请填写用户名和密码';
        }
    } else if (authMode === 'register') {
        const username = document.getElementById('reg-username').value.trim();
        const password = document.getElementById('reg-password').value.trim();
        const password2 = document.getElementById('reg-password2').value.trim();

        if (password !== password2) {
            errorEl.classList.remove('hidden');
            errorEl.textContent = '两次密码不一致';
            return;
        }
        try {
            const res = await fetch(API_BASE + '/auth/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password }),
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || '注册失败');
            setAuth(data.user);
            hideAuthModal();
            showToast(`注册成功, 欢迎 ${data.user.username}`);
        } catch (e) {
            errorEl.classList.remove('hidden');
            errorEl.textContent = e.message;
        }
    } else if (authMode === 'account') {
        await doRegenerateApikey();
        hideAuthModal();
    }
}

function setAuth(user) {
    authToken = user.apikey;
    currentUser = user;
    localStorage.setItem('bili_monitor_token', authToken);
    updateAuthUI();
    refreshAll();
}

async function logout() {
    authToken = '';
    currentUser = null;
    localStorage.removeItem('bili_monitor_token');
    updateAuthUI();
    showToast('已退出登录');
    refreshAll();
}

async function doRegenerateApikey() {
    try {
        const data = await api('/auth/apikey/regenerate', { method: 'POST' });
        authToken = data.apikey;
        localStorage.setItem('bili_monitor_token', authToken);
        showToast('API Key 已更新');
    } catch (e) { showToast(`更新失败: ${e.message}`, 'error'); }
}

async function doDeleteAccount() {
    if (!confirm('确认注销账号？所有数据将被删除，此操作不可撤销！')) return;
    try {
        await api('/auth/account', { method: 'DELETE' });
        authToken = '';
        currentUser = null;
        localStorage.removeItem('bili_monitor_token');
        updateAuthUI();
        showToast('账号已注销');
        hideAuthModal();
        refreshAll();
    } catch (e) { showToast(`注销失败: ${e.message}`, 'error'); }
}

function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws`;
    ws = new WebSocket(wsUrl);
    ws.onopen = () => document.getElementById('ws-status').className = 'status-dot connected';
    ws.onclose = () => { document.getElementById('ws-status').className = 'status-dot disconnected'; setTimeout(connectWebSocket, 5000); };
    ws.onmessage = (event) => {
        try { const msg = JSON.parse(event.data); if (msg.type === 'monitor_update') { loadVideos(); loadStats(); } } catch (e) {}
    };
}

function updateClock() {
    document.getElementById('clock').textContent = new Date().toLocaleString('zh-CN');
}

function showToast(message, type = 'info') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type}`;
    setTimeout(() => toast.classList.add('hidden'), 3000);
}

function formatNumber(n) {
    if (n == null) return '0';
    if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿';
    if (n >= 10000) return (n / 10000).toFixed(1) + '万';
    return n.toLocaleString();
}

function formatDuration(seconds) {
    if (!seconds) return '—';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function debounce(fn, delay) {
    let timer;
    return function (...args) { clearTimeout(timer); timer = setTimeout(() => fn.apply(this, args), delay); };
}

document.addEventListener('DOMContentLoaded', () => {
    init();
});
