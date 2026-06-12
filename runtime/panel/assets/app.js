// -*- coding: utf-8 -*-
// WNMP Panel App - Sidebar + Main Content Layout
// Views: loading-view / error-view / init-view / dashboard-view / log-view / settings-view / about-view

(function () {
    'use strict';

    // --- Timeout config per action type (ms) ---
    var ACTION_TIMEOUT = {
        'start_env': 300000,
        'init_env':  300000,
        'restart_env': 300000,
        'stop_env':   120000,
        'open_site':    10000,
        'start_nginx': 60000,
        'stop_nginx': 60000,
        'restart_nginx': 60000,
        'reload_nginx': 60000,
        'start_php': 60000,
        'stop_php': 60000,
        'restart_php': 60000,
        'start_mysql': 120000,
        'stop_mysql': 120000,
        'restart_mysql': 120000,
        'install_autostart': 60000,
        'uninstall_autostart': 60000,
        'reset_config': 180000
    };
    var STATUS_TIMEOUT = 5000;        // 后续轮询超时
    var STATUS_FIRST_TIMEOUT = 10000; // 首次加载超时（稍长，容忍冷启动）

    // --- State ---
    var statusTimer = null;
    var actionRunning = false;
    var currentActionComponent = null;  // 当前正在操作的组件名 nginx/php/mysql，用于轮询期间保护 busy 状态
    var currentEnvActionRunning = false;  // 环境级操作(start_env/stop_env/restart_env)执行中，保护全部卡片 busy 灰态
    var currentInitialized = null;
    var mysqlPasswordHidden = false;  // 用户点击"我已复制并保存，关闭"后为 true
    var firstLoadDone = false;
    var firstLoadFailCount = 0;  // 首次加载连续失败次数
    var currentLogTab = 'runtime';
    var currentNav = 'overview';
    var lastStatusData = null;

    // --- 版本缓存：避免状态轮询重渲染清掉版本结果 ---
    // queried: 用户是否点过查看版本，点过后按钮文案保持"刷新版本"
    var componentVersionCache = {
        nginx: { loading: false, version: null, error: null, queried: false },
        php:   { loading: false, version: null, error: null, queried: false },
        mysql: { loading: false, version: null, error: null, queried: false }
    };

    // --- Heartbeat state ---
    var clientId = null;
    var heartbeatInterval = 5000;
    var heartbeatTimer = null;
    var panelExitOnClose = true;

    // --- Config editor state ---
    var currentConfigName = 'nginx';
    var configContentLoaded = '';  // 当前加载的原始内容，用于比较

    // --- Environment info state ---
    var envInfoCache = null;           // 缓存的环境信息数据
    var envInfoSignature = '';         // 缓存签名，避免无变化时重渲染
    var envInfoLoading = false;        // 加载中标记
    var envInfoLastLoadTime = 0;       // 上次加载完成时间戳，用于节流

    // --- DOM helpers ---
    // IE11 兼容：qsa 支持 root 参数，使用 WNMPCompat.toArray 兼容 IE11 NodeList
    function qsa(sel, root) { return WNMPCompat.toArray((root || document).querySelectorAll(sel)); }
    function qs(sel) { return document.querySelector(sel); }

    // --- IE11 兼容：closest 事件代理 helper，兼容文本节点 ---
    function closestTarget(e, selector) { return WNMPCompat.closest(e.target || e.srcElement, selector); }

    // --- Flash Toast 统一提示 ---
    var FLASH_TOAST_MAX = 5; // 队列上限
    var FLASH_TOAST_DEFAULTS = {
        success: 3500,
        info:    3500,
        warning: 5500,
        error:   8000
    };
    var FLASH_TOAST_ICONS = {
        success: '\u2713', // ✓
        error:   '\u2717', // ✗
        warning: '!',
        info:    'i'
    };

    /**
     * 统一 Flash Toast 提示函数
     * @param {string} message  提示文本（支持 HTML）
     * @param {string} type     success | error | warning | info
     * @param {object} options  可选: { duration: ms, raw: bool(不转义HTML) }
     */
    function showFlash(message, type, options) {
        type = type || 'info';
        options = options || {};
        var container = document.getElementById('flash-toast-container');
        if (!container) return;

        // 队列上限：优先移除最旧的非 error toast；若全为 error 则移除最旧 error，确保总数不超限
        var toasts = container.querySelectorAll('.flash-toast:not(.flash-toast-out)');
        if (toasts.length >= FLASH_TOAST_MAX) {
            var removed = false;
            for (var i = 0; i < toasts.length; i++) {
                if (!toasts[i].classList.contains('toast-error')) {
                    _removeToast(toasts[i]);
                    removed = true;
                    break;
                }
            }
            // 全部都是 error 时，移除最旧的一条 error
            if (!removed && toasts.length > 0) {
                _removeToast(toasts[0]);
            }
        }

        var duration = options.duration != null ? options.duration : FLASH_TOAST_DEFAULTS[type];

        var el = document.createElement('div');
        el.className = 'flash-toast toast-' + type;
        el.setAttribute('role', 'alert');

        var iconChar = FLASH_TOAST_ICONS[type] || FLASH_TOAST_ICONS.info;
        var bodyHtml = options.raw ? message : escHtml(message);

        el.innerHTML =
            '<i class="flash-toast-icon">' + escHtml(iconChar) + '</i>' +
            '<div class="flash-toast-body">' + bodyHtml + '</div>' +
            '<button class="flash-toast-close" title="' + escHtml(i18n.t('toast.close')) + '" aria-label="' + escHtml(i18n.t('toast.close_aria')) + '">&times;</button>';

        // 关闭按钮
        var closeBtn = el.querySelector('.flash-toast-close');
        closeBtn.addEventListener('click', function () { _removeToast(el); });

        container.appendChild(el);

        // 自动关闭定时器
        if (duration > 0) {
            el._flashTimer = setTimeout(function () { _removeToast(el); }, duration);
        }
    }

    function _removeToast(el) {
        if (!el || el.classList.contains('flash-toast-out')) return;
        if (el._flashTimer) { clearTimeout(el._flashTimer); el._flashTimer = null; }
        el.classList.add('flash-toast-out');
        el.addEventListener('animationend', function () {
            if (el.parentNode) el.parentNode.removeChild(el);
        });
    }

    // --- View switching ---
    var CONTENT_VIEWS = ['loading-view', 'error-view', 'init-view', 'dashboard-view', 'log-view', 'settings-view', 'about-view'];

    function hideAllContentViews() {
        CONTENT_VIEWS.forEach(function (role) {
            var el = qs('[data-role="' + role + '"]');
            if (el) el.style.display = 'none';
        });
    }

    function showContentView(role) {
        var el = qs('[data-role="' + role + '"]');
        // log-view 需要 flex 布局，其他视图使用 block
        if (el) el.style.display = (role === 'log-view') ? 'flex' : 'block';
    }

    function showLoadingView() {
        hideAllContentViews();
        showContentView('loading-view');
        updateTopbar('overview', null);
    }

    function showErrorView(message) {
        hideAllContentViews();
        showContentView('error-view');
        var msgEl = qs('[data-role="error-message"]');
        if (msgEl) msgEl.textContent = message || i18n.t('error.message');
        updateTopbar('overview', null);
    }

    function showInitView() {
        hideAllContentViews();
        showContentView('init-view');
        // 初始化中时显示 initializing，失败时显示 failed，否则显示 uninitialized
        var overall = 'uninitialized';
        if (lastStatusData) {
            if (lastStatusData.initializing) overall = 'initializing';
            else if (lastStatusData.init_phase === 'failed') overall = 'failed';
        }
        updateTopbar('overview', overall);
    }

    function showDashboardView() {
        hideAllContentViews();
        showContentView('dashboard-view');
        updateTopbar('overview', lastStatusData ? lastStatusData.overall : null);
        // 环境按钮只在 dashboard 内且已初始化时显示
        var toolbar = qs('[data-role="action-toolbar"]');
        if (toolbar) toolbar.style.display = currentInitialized ? 'flex' : 'none';
        // 进入首页时加载环境信息模块（签名变化或缓存为空时才重渲染）
        loadEnvironmentInfo(false);
    }

    function showLogView() {
        hideAllContentViews();
        showContentView('log-view');
        updateTopbar('logs', lastStatusData ? lastStatusData.overall : null);
        fetchLog(currentLogTab);
    }

    function showSettingsView() {
        hideAllContentViews();
        showContentView('settings-view');
        updateTopbar('settings', null);
        doAutostartStatus();
        // 首次进入设置页时自动加载 Nginx 主配置，避免空白 textarea
        if (!configContentLoaded) {
            loadConfigFile(currentConfigName || 'nginx');
        }
    }

    function showAboutView() {
        hideAllContentViews();
        showContentView('about-view');
        updateTopbar('about', null);
        loadPanelVersion(); // 进入关于页面时异步加载 Panel 版本信息
    }

    function updateTopbar(nav, overallState) {
        currentNav = nav;
        var titleMap = { 'overview': i18n.t('topbar.overview'), 'logs': i18n.t('topbar.logs'), 'settings': i18n.t('topbar.settings'), 'about': i18n.t('topbar.about') };
        var titleEl = qs('[data-role="topbar-title"]');
        if (titleEl) titleEl.textContent = titleMap[nav] || i18n.t('topbar.overview');

        // 更新顶部副标题
        var subtitleEl = qs('[data-role="topbar-subtitle"]');
        if (subtitleEl) subtitleEl.textContent = i18n.t('topbar.subtitle');

        var badgeEl = qs('[data-role="overall-badge"]');
        if (badgeEl) {
            var stateMap = {
                'running': i18n.t('state.running'), 'stopped': i18n.t('state.stopped'), 'partial': i18n.t('state.partial'),
                'uninitialized': i18n.t('state.uninitialized'), 'unknown': i18n.t('state.unknown'), 'error': i18n.t('state.error'),
                'external': i18n.t('state.external'), 'pending_reload': i18n.t('state.pending_reload'),
                'initializing': i18n.t('state.initializing'), 'failed': i18n.t('state.failed'),
                'starting': i18n.t('state.starting')
            };
            var stateText = stateMap[overallState] || '--';
            // 更新 badge-text 子元素，保留 badge-dot
            var badgeTextEl = badgeEl.querySelector('.badge-text');
            if (badgeTextEl) {
                badgeTextEl.textContent = stateText;
            }
            badgeEl.className = 'overall-badge badge-' + (overallState || 'unknown');
        }

        qsa('.nav-item').forEach(function (item) {
            // IE11 兼容：使用 WNMPCompat.toggleClass 替代 classList.toggle 第二参数
            WNMPCompat.toggleClass(item, 'active', item.getAttribute('data-nav') === nav);
        });
    }

    // --- 内联 SVG 图标（离线，不依赖 CDN/字体文件） ---
    var SERVICE_ICONS = {
        nginx: '<svg viewBox="0 0 64 64" aria-hidden="true" focusable="false" class="svc-svg svc-svg-nginx"><path d="M32 4 56 18v28L32 60 8 46V18L32 4Z" fill="currentColor"/><path d="M21 44V20h7.2l8.9 13.7V20H44v24h-7.1L28 30.2V44h-7Z" fill="#fff"/></svg>',
        php: '<svg viewBox="0 0 64 64" aria-hidden="true" focusable="false" class="svc-svg svc-svg-php"><ellipse cx="32" cy="32" rx="27" ry="17" fill="currentColor"/><path d="M15 38 19 24h7.1c3.5 0 5.2 1.6 4.5 4.5-.7 3-3.1 4.5-7 4.5h-2.8l-1.4 5H15Zm7-9h2.5c1.3 0 2.1-.5 2.4-1.5.3-1-.2-1.5-1.5-1.5H23l-1 3Zm10.5 9 3.8-14h4l-1.4 5h4.2l1.4-5h4l-3.8 14h-4l1.5-5.4H38L36.5 38h-4Zm16 0 3.8-14h7c3.5 0 5.2 1.6 4.5 4.5-.7 3-3.1 4.5-7 4.5H54l-1.4 5h-4.1Zm6.9-9h2.5c1.3 0 2.1-.5 2.4-1.5.3-1-.2-1.5-1.5-1.5h-2.4l-1 3Z" fill="#fff"/></svg>',
        mysql: '<svg viewBox="0 0 64 64" aria-hidden="true" focusable="false" class="svc-svg svc-svg-mysql"><path d="M12 18c0-6.1 8.9-11 20-11s20 4.9 20 11v28c0 6.1-8.9 11-20 11s-20-4.9-20-11V18Z" fill="currentColor"/><path d="M52 18c0 6.1-8.9 11-20 11s-20-4.9-20-11" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round"/><path d="M52 32c0 6.1-8.9 11-20 11s-20-4.9-20-11" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" opacity=".9"/><path d="M52 46c0 6.1-8.9 11-20 11s-20-4.9-20-11" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" opacity=".9"/></svg>'
    };

    function getServiceIcon(service) {
        return SERVICE_ICONS[service] || '';
    }

    // --- 状态中文映射（新卡片 service-badge 用） --- // i18n: 改用 i18n.t('card_state.xxx')
    var STATE_TEXT_MAP = {
        'running': 'card_state.running', 'stopped': 'card_state.stopped', 'external': 'card_state.external',
        'unknown': 'card_state.unknown', 'partial': 'card_state.partial', 'error': 'card_state.error',
        'pending_reload': 'card_state.pending_reload', 'starting': 'state.starting'
    };

    // --- 单组件卡片 HTML 生成（四区域布局：Header / Metrics / Version / Actions） ---
    function buildServiceCardHTML(svc, st) {
        var iconClass = svc;
        var svcName = svc === 'php' ? 'PHP-CGI' : (svc === 'nginx' ? 'Nginx' : 'MySQL');
        var stateClass = st.state || 'unknown';
        var stateText = i18n.t(STATE_TEXT_MAP[st.state]) || st.state || '--';

        // 构建指标区
        var metricsHTML = '';
        if (svc === 'nginx') {
            metricsHTML = buildNginxMetrics(st);
        } else {
            metricsHTML = buildPortMetrics(st);
        }

        // 构建版本行（从缓存读取，状态轮询不会清掉）
        var versionHTML = buildVersionRow(svc);

        // 构建按钮区
        var actionsHTML = buildServiceActions(svc, st);

        return '<div class="module-card" data-service="' + svc + '">' +
            '<div class="module-card__header">' +
                '<div class="module-card__title-wrap">' +
                    '<span class="module-card__icon ' + iconClass + '">' + getServiceIcon(svc) + '</span>' +
                    '<span class="module-card__name">' + svcName + '</span>' +
                '</div>' +
                '<span class="module-card__badge ' + stateClass + '" data-field="state"><span class="badge-dot"></span>' + escHtml(stateText) + '</span>' +
            '</div>' +
            '<div class="module-card__metrics" data-role="' + svc + '-metrics-area">' +
                metricsHTML +
            '</div>' +
            versionHTML +
            '<div class="module-card__actions">' +
                actionsHTML +
            '</div>' +
        '</div>';
    }

    // Nginx 指标：HTTP 端口状态、HTTPS 端口状态、运行状态、配置状态（2x2 网格）
    function buildNginxMetrics(st) {
        var html = '';
        var isDirty = st.config_dirty || st.config_pending_reload;

        // HTTP 端口状态
        var httpPort = '--', httpStatus = '--', httpClass = '';
        var httpsPort = '--', httpsStatus = '--', httpsClass = '';

        if (st.ports && st.ports.length) {
            st.ports.forEach(function (p) {
                if (p.name === 'HTTP' || p.name === 'http') {
                    httpPort = p.port;
                    if (!p.enabled) { httpStatus = i18n.t('metric.disabled'); httpClass = ''; }
                    else if (p.open) { httpStatus = i18n.t('metric.open'); httpClass = 'ok'; }
                    else if (isDirty) { httpStatus = i18n.t('metric.pending'); httpClass = 'warn'; }
                    else { httpStatus = i18n.t('metric.closed'); httpClass = 'error'; }
                } else if (p.name === 'HTTPS' || p.name === 'https') {
                    httpsPort = p.port;
                    if (!p.enabled) { httpsStatus = i18n.t('metric.disabled'); httpsClass = ''; }
                    else if (p.open) { httpsStatus = i18n.t('metric.open'); httpsClass = 'ok'; }
                    else if (isDirty) { httpsStatus = i18n.t('metric.pending'); httpsClass = 'warn'; }
                    else { httpsStatus = i18n.t('metric.closed'); httpsClass = 'error'; }
                }
            });
        }

        // 运行状态
        var runText = i18n.t(STATE_TEXT_MAP[st.state]) || st.state || '--';
        var runClass = (st.state === 'running') ? 'ok' : (st.state === 'stopped') ? 'unknown' : (st.state === 'error' || st.state === 'external') ? 'error' : 'warn';

        // 配置状态
        var configText, configClass;
        if (isDirty && st.state === 'pending_reload') {
            configText = i18n.t('metric.pending'); configClass = 'warn';
        } else if (isDirty && st.state === 'stopped') {
            configText = i18n.t('metric.startup_apply'); configClass = 'warn';
        } else if (isDirty) {
            configText = i18n.t('metric.pending'); configClass = 'warn';
        } else {
            configText = i18n.t('metric.applied'); configClass = 'ok';
        }

        html += metricItem(i18n.t('metric.http_port'), httpPort + ' / ' + httpStatus, httpClass);
        html += metricItem(i18n.t('metric.https_port'), httpsPort + ' / ' + httpsStatus, httpsClass);
        html += metricItem(i18n.t('metric.run_state'), runText, runClass);
        html += metricItem(i18n.t('metric.config_state'), configText, configClass);

        return html;
    }

    // PHP/MySQL 指标：端口、端口开放、运行状态、配置状态（2x2 网格，固定四项对齐）
    function buildPortMetrics(st) {
        var html = '';
        var portText = (st.port !== undefined && st.port !== null) ? String(st.port) : '--';
        var portOpenText, portOpenClass;
        if (st.port_open === true) { portOpenText = i18n.t('metric.yes'); portOpenClass = 'ok'; }
        else if (st.port_open === false) { portOpenText = i18n.t('metric.no'); portOpenClass = 'error'; }
        else { portOpenText = '--'; portOpenClass = 'unknown'; }

        var runText = i18n.t(STATE_TEXT_MAP[st.state]) || st.state || '--';
        var runClass = (st.state === 'running') ? 'ok' : (st.state === 'stopped') ? 'unknown' : (st.state === 'error' || st.state === 'external') ? 'error' : 'warn';

        // 配置状态：PHP/MySQL 如有 config_dirty 则显示需重启生效，否则显示已应用或未检测
        var isDirty = st.config_dirty || st.config_pending_reload;
        var configText, configClass;
        if (isDirty && st.state === 'running') {
            configText = i18n.t('metric.need_restart'); configClass = 'warn';
        } else if (isDirty && st.state === 'stopped') {
            configText = i18n.t('metric.startup_apply'); configClass = 'warn';
        } else if (isDirty) {
            configText = i18n.t('metric.need_restart'); configClass = 'warn';
        } else if (st.state === 'running' || st.state === 'stopped') {
            configText = i18n.t('metric.applied'); configClass = 'ok';
        } else {
            configText = i18n.t('metric.not_detected'); configClass = 'unknown';
        }

        html += metricItem(i18n.t('metric.port'), portText, '');
        html += metricItem(i18n.t('metric.port_open'), portOpenText, portOpenClass);
        html += metricItem(i18n.t('metric.run_state'), runText, runClass);
        html += metricItem(i18n.t('metric.config_state'), configText, configClass);

        return html;
    }

    // 三行信息行的小图标 SVG（metric-row 使用）
    var _metricIcons = {
        run_state: '<svg viewBox="0 0 16 16" width="14" height="14"><circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/><path d="M6 5.5l4 2.5-4 2.5z" fill="currentColor"/></svg>',
        config_state: '<svg viewBox="0 0 16 16" width="14" height="14"><path d="M2 3h12v1.5H2zm0 4.25h12v1.5H2zm0 4.25h12v1.5H2z" fill="currentColor"/></svg>',
        port: '<svg viewBox="0 0 16 16" width="14" height="14"><path d="M6 1v2H3v10h10V3h-3V1h2a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V2a1 1 0 0 1 1-1h2z" fill="currentColor"/></svg>'
    };

    // 指标单元（module-card 2x2 网格使用，label + value 结构）
    function metricItem(label, value, valueClass) {
        return '<div class="module-card__metric-cell">' +
            '<div class="module-card__metric-label">' + escHtml(label) + '</div>' +
            '<div class="module-card__metric-value ' + (valueClass || '') + '">' + escHtml(value) + '</div>' +
        '</div>';
    }

    // 版本行（module-card 版本区，从 componentVersionCache 读取）
    function buildVersionRow(svc) {
        var cache = componentVersionCache[svc];
        // 版本标签：PHP-CGI 卡片显示"PHP-CGI 版本"
        var label = svc === 'php' ? i18n.t('version.php') : (svc === 'nginx' ? i18n.t('version.nginx') : i18n.t('version.mysql'));
        var valueClass = 'module-card__version-value';
        var valueText = i18n.t('version.not_queried');
        var titleAttr = '';  // 版本 value 的 title 属性，鼠标悬停显示完整版本

        if (cache) {
            if (cache.loading) {
                valueText = i18n.t('version.querying');
                valueClass += ' version-loading';
            } else if (cache.version) {
                valueText = cache.version;
                titleAttr = ' title="' + escHtml(cache.version) + '"';  // 完整版本文本写入 title
            } else if (cache.error) {
                valueText = cache.error;
                valueClass += ' version-error';
            }
        }

        return '<div class="module-card__version" data-role="' + svc + '-version-row">' +
            '<span class="module-card__version-label">' + escHtml(label) + i18n.t('punct.colon') + '</span>' +
            '<span class="' + valueClass + '"' + titleAttr + '>' + escHtml(valueText) + '</span>' +
        '</div>';
    }

    // 按钮区（左侧启动/停止/重启，右侧查看版本）
    function buildServiceActions(svc, st) {
        var isNginx = (svc === 'nginx');
        // 查看版本按钮文案：查询后改为"刷新版本"
        var verCache = componentVersionCache[svc];
        var verBtnText = (verCache && verCache.queried) ? i18n.t('version.refresh') : i18n.t('version.view');

        var html = '<div class="module-card__actions-left">' +
            '<button data-action="start_' + svc + '" class="btn-module btn-module-start">' + escHtml(i18n.t('btn.start')) + '</button>' +
            '<button data-action="stop_' + svc + '" class="btn-module btn-module-stop">' + escHtml(i18n.t('btn.stop')) + '</button>' +
            '<button data-action="restart_' + svc + '" class="btn-module btn-module-restart">' + escHtml(i18n.t('btn.restart')) + '</button>';
        if (isNginx) {
            html += '<button data-action="reload_nginx" class="btn-module btn-module-restart" style="display:none">' + escHtml(i18n.t('btn.reload')) + '</button>';
        }
        html += '</div>';
        html += '<button data-role="btn-version" data-version-component="' + svc + '" class="btn-module btn-module-version">' + escHtml(verBtnText) + '</button>';
        return html;
    }

    // --- 组件按钮状态管理 ---
    function updateComponentButtons(svc, state, running, configDirty, configPendingReload) {
        var card = qs('[data-service="' + svc + '"]');
        if (!card) return;

        // 环境级操作执行中，不覆盖任何卡片的 is-busy 状态和按钮禁用
        if (currentEnvActionRunning) return;

        // 轮询保护：当前正在操作的组件，不覆盖 is-busy 状态和按钮禁用
        if (actionRunning && currentActionComponent === svc) return;

        var startBtn = card.querySelector('[data-action="start_' + svc + '"]');
        var stopBtn = card.querySelector('[data-action="stop_' + svc + '"]');
        var restartBtn = card.querySelector('[data-action="restart_' + svc + '"]');
        var reloadBtn = card.querySelector('[data-action="reload_' + svc + '"]');

        if (!startBtn || !stopBtn || !restartBtn) return;

        // 移除可能残留的 is-busy（非当前操作组件）
        card.classList.remove('is-busy');

        // Nginx 重载按钮：running/partial/pending_reload 状态下，config_dirty 或 config_pending_reload 为 true 时显示
        if (reloadBtn) {
            if (svc === 'nginx' && (state === 'running' || state === 'partial' || state === 'pending_reload') && (configDirty || configPendingReload)) {
                reloadBtn.style.display = '';
                reloadBtn.disabled = false;
            } else {
                reloadBtn.style.display = 'none';
                reloadBtn.disabled = true;
            }
        }

        if (state === 'running' || state === 'pending_reload') {
            startBtn.disabled = true;
            stopBtn.disabled = false;
            restartBtn.disabled = false;
        } else if (state === 'stopped') {
            startBtn.disabled = false;
            stopBtn.disabled = true;
            restartBtn.disabled = true;
        } else if (state === 'partial') {
            // 部分运行：允许停止和重启
            startBtn.disabled = true;
            stopBtn.disabled = false;
            restartBtn.disabled = false;
        } else if (state === 'external') {
            // 端口被占用：不允许启停操作
            startBtn.disabled = true;
            stopBtn.disabled = true;
            restartBtn.disabled = true;
        } else {
            restartBtn.disabled = false;
            startBtn.disabled = !!running;
            stopBtn.disabled = !running;
        }
    }

    // --- Heartbeat ---
    function initHeartbeat() {
        if (!clientId) {
            clientId = 'c_' + Date.now() + '_' + Math.random().toString(36).substr(2, 6);
            try { sessionStorage.setItem('wnmp_client_id', clientId); } catch (e) {}
        }

        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/panel/config', true);
        xhr.timeout = 3000;
        xhr.onload = function () {
            if (xhr.status === 200) {
                try {
                    var cfg = JSON.parse(xhr.responseText);
                    if (cfg.success) {
                        panelExitOnClose = cfg.panel_exit_on_close;
                        heartbeatInterval = (cfg.heartbeat_interval || 5) * 1000;
                    }
                } catch (e) {}
            }
            startHeartbeat();
        };
        xhr.onerror = function () { startHeartbeat(); };
        xhr.ontimeout = function () { startHeartbeat(); };
        xhr.send();
    }

    function startHeartbeat() {
        if (heartbeatTimer) clearInterval(heartbeatTimer);
        if (!panelExitOnClose) return;

        sendHeartbeat();

        heartbeatTimer = setInterval(function () {
            sendHeartbeat();
        }, heartbeatInterval);

        window.addEventListener('pagehide', onUnload);
        window.addEventListener('beforeunload', onUnload);

        // 页面从后台切回前台或获得焦点时，立即发送心跳并刷新状态
        document.addEventListener('visibilitychange', function () {
            if (document.visibilityState === 'visible') {
                sendHeartbeat();
                refreshStatus();
            }
        });
        window.addEventListener('focus', function () {
            // 获得焦点时也立即心跳+刷新，覆盖从其它程序切回的场景
            sendHeartbeat();
            refreshStatus();
        });
    }

    function sendHeartbeat() {
        if (!clientId) return;
        try {
            var xhr = new XMLHttpRequest();
            xhr.open('POST', '/api/panel/heartbeat', true);
            xhr.setRequestHeader('Content-Type', 'application/json');
            xhr.timeout = 3000;
            xhr.send(JSON.stringify({ client_id: clientId }));
        } catch (e) {}
    }

    // client-close 布尔锁：防止 pagehide + beforeunload 重复上报
    var clientCloseSent = false;

    function onUnload(e) {
        // pagehide 且 persisted=true 表示页面进入 bfcache（标签页切到后台），不应发送 client-close
        if (e && e.type === 'pagehide' && e.persisted) return;
        if (!clientId) return;
        // 布尔锁：首次上报后置 true，后续事件直接 return
        if (clientCloseSent) return;
        clientCloseSent = true;
        try {
            // 使用 Blob 设置 Content-Type，确保 sendBeacon 发送 JSON
            var data = JSON.stringify({ client_id: clientId });
            var blob = new Blob([data], { type: 'application/json' });
            navigator.sendBeacon('/api/panel/client-close', blob);
        } catch (e) {
            try {
                var xhr = new XMLHttpRequest();
                xhr.open('POST', '/api/panel/client-close', false);
                xhr.setRequestHeader('Content-Type', 'application/json');
                xhr.send(JSON.stringify({ client_id: clientId }));
            } catch (e2) {}
        }
    }

    // --- Version query ---
    function queryVersion(component) {
        var card = qs('[data-service="' + component + '"]');
        if (!card) return;

        var btn = card.querySelector('[data-role="btn-version"][data-version-component="' + component + '"]');

        // 设置缓存为 loading 状态，标记 queried=true（用户已发起查询）
        componentVersionCache[component] = { loading: true, version: null, error: null, queried: true };

        // 立即更新卡片内版本行显示"查询中..."
        updateVersionRowInCard(component);

        if (btn) { btn.disabled = true; btn.textContent = i18n.t('version.querying'); }

        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/versions?component=' + component, true);
        xhr.timeout = 10000;
        xhr.onload = function () {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    var info = data.versions && data.versions[component];
                    if (info && info.version) {
                        // 成功：缓存版本
                        componentVersionCache[component] = { loading: false, version: info.version, error: null, queried: true };
                    } else if (info && info.error) {
                        // 失败：缓存错误
                        componentVersionCache[component] = { loading: false, version: null, error: info.error, queried: true };
                    } else {
                        componentVersionCache[component] = { loading: false, version: null, error: i18n.t('version.query_failed'), queried: true };
                    }
                } catch (e) {
                    componentVersionCache[component] = { loading: false, version: null, error: i18n.t('action.response_parse_error'), queried: true };
                }
            } else {
                componentVersionCache[component] = { loading: false, version: null, error: 'HTTP ' + xhr.status, queried: true };
            }
            // 更新卡片内版本行
            updateVersionRowInCard(component);
            // 恢复按钮
            if (btn) { btn.disabled = false; btn.textContent = i18n.t('version.refresh'); }
        };
        xhr.onerror = function () {
            componentVersionCache[component] = { loading: false, version: null, error: i18n.t('version.network_error'), queried: true };
            updateVersionRowInCard(component);
            if (btn) { btn.disabled = false; btn.textContent = i18n.t('version.refresh'); }
            showFlash(getVersionLabel(component) + i18n.t('version.network_error'), 'error');
        };
        xhr.ontimeout = function () {
            componentVersionCache[component] = { loading: false, version: null, error: i18n.t('version.timeout'), queried: true };
            updateVersionRowInCard(component);
            if (btn) { btn.disabled = false; btn.textContent = i18n.t('version.refresh'); }
            showFlash(getVersionLabel(component) + i18n.t('version.timeout'), 'error');
        };
        xhr.send();
    }

    // 版本标签文案
    function getVersionLabel(svc) {
        return svc === 'php' ? i18n.t('version.php') : (svc === 'nginx' ? i18n.t('version.nginx') : i18n.t('version.mysql'));
    }

    // 仅更新卡片内版本行 DOM，不重建整个卡片
    function updateVersionRowInCard(svc) {
        var row = qs('[data-role="' + svc + '-version-row"]');
        if (!row) return;
        var newRow = document.createElement('div');
        newRow.innerHTML = buildVersionRow(svc);
        var newEl = newRow.firstElementChild;
        if (newEl && row.parentNode) {
            row.parentNode.replaceChild(newEl, row);
        }
    }

    // --- Panel version loader (About page) ---
    function loadPanelVersion() {
        var nameEl = qs('[data-role="about-panel-name"]');
        var versionEl = qs('[data-role="about-panel-version"]');
        var buildDateEl = qs('[data-role="about-build-date"]');
        var rootDirEl = qs('[data-role="about-root-dir"]');
        var portEl = qs('[data-role="about-panel-port"]');  // Panel 端口信息移至关于页面
        // 关键路径新增元素
        var configDirEl = qs('[data-role="about-config-dir"]');
        var logsDirEl = qs('[data-role="about-logs-dir"]');
        var wwwDirEl = qs('[data-role="about-www-dir"]');
        var vhostsDirEl = qs('[data-role="about-vhosts-dir"]');

        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/panel-version', true);
        xhr.timeout = 5000;
        xhr.onload = function () {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    if (data.success) {
                        // 按文本插入，防止 HTML 注入
                        if (nameEl) nameEl.textContent = data.panel_name || 'WNMP Runtime Panel';
                        if (versionEl) versionEl.textContent = data.panel_version || 'unknown';
                        if (buildDateEl) buildDateEl.textContent = data.build_date || i18n.t('about.dev_build');
                        // 根目录：后端返回 root_dir，始终显示完整绝对路径，title 悬停同样显示完整路径
                        var rootDir = data.root_dir || '';
                        if (rootDirEl) {
                            rootDirEl.textContent = rootDir || '--';
                            rootDirEl.title = rootDir || '';
                        }
                        // Panel 端口：从当前浏览器地址获取，不是路径，不需要 title
                        if (portEl) {
                            try { var port = window.location.port; if (port) portEl.textContent = port; else portEl.textContent = '--'; } catch (e) { portEl.textContent = '--'; }
                            // Panel 端口不需要 title 属性，移除可能残留的 title
                            portEl.removeAttribute('title');
                        }
                        // 关键路径：默认显示相对路径（如 config\），完整绝对路径放 title 悬停提示
                        if (rootDir) {
                            // 统一使用反斜杠（Windows 路径风格）
                            var sep = '\\';
                            if (rootDir.indexOf('/') !== -1 && rootDir.indexOf('\\') === -1) {
                                sep = '/';
                            }
                            function joinFull(base, rel) {
                                return base + sep + rel.replace(/[/\\]/g, sep);
                            }
                            // 配置目录：显示 config\，title 为完整绝对路径
                            if (configDirEl) {
                                configDirEl.textContent = 'config' + sep;
                                configDirEl.title = joinFull(rootDir, 'config');
                            }
                            // 运行日志：显示 logs\，title 为完整绝对路径
                            if (logsDirEl) {
                                logsDirEl.textContent = 'logs' + sep;
                                logsDirEl.title = joinFull(rootDir, 'logs');
                            }
                            // 默认站点目录：显示 www\，title 为完整绝对路径
                            if (wwwDirEl) {
                                wwwDirEl.textContent = 'www' + sep;
                                wwwDirEl.title = joinFull(rootDir, 'www');
                            }
                            // Nginx 站点配置目录：显示 config\nginx\vhosts\，title 为完整绝对路径
                            if (vhostsDirEl) {
                                // vhosts 相对路径使用反斜杠
                                var vhostsRel = 'config\\nginx\\vhosts';
                                vhostsRel = vhostsRel.replace(/[/\\]/g, sep);
                                vhostsDirEl.textContent = vhostsRel + sep;
                                // 完整绝对路径
                                var vhostsFull = rootDir + sep + 'config' + sep + 'nginx' + sep + 'vhosts';
                                if (sep === '/') {
                                    vhostsFull = rootDir + '/config/nginx/vhosts';
                                }
                                vhostsDirEl.title = vhostsFull;
                            }
                        }
                    } else {
                        showFlash(i18n.t('panel_version.load_failed'), 'error');
                    }
                } catch (e) {
                    showFlash(i18n.t('panel_version.load_failed'), 'error');
                }
            } else {
                showFlash(i18n.t('panel_version.load_failed'), 'error');
            }
        };
        xhr.onerror = function () {
            showFlash(i18n.t('panel_version.load_failed'), 'error');
        };
        xhr.ontimeout = function () {
            showFlash(i18n.t('panel_version.load_failed'), 'error');
        };
        xhr.send();
    }

    // --- Config file editor ---
    function loadConfigFile(name) {
        currentConfigName = name;
        var textarea = qs('[data-role="config-textarea"]');
        var statusEl = qs('[data-role="config-editor-status"]');
        var saveBtn = qs('[data-role="btn-config-save"]');
        var reloadBtn = qs('[data-role="btn-config-reload"]');
        var runtimeHint = qs('[data-role="config-runtime-hint"]');

        if (textarea) { textarea.value = i18n.t('log.loading'); textarea.disabled = true; }
        if (statusEl) statusEl.textContent = '';
        if (saveBtn) saveBtn.disabled = true;
        if (reloadBtn) reloadBtn.disabled = true;

        // runtime.ini 编辑时显示说明提示区，其他配置隐藏
        if (runtimeHint) {
            runtimeHint.style.display = (name === 'runtime') ? 'block' : 'none';
        }

        // 更新 tab 激活状态
        qsa('.config-tab').forEach(function (tab) {
            // IE11 兼容：使用 WNMPCompat.toggleClass 替代 classList.toggle 第二参数
            WNMPCompat.toggleClass(tab, 'active', tab.getAttribute('data-config-name') === name);
        });

        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/config-file?name=' + encodeURIComponent(name), true);
        xhr.timeout = 5000;
        xhr.onload = function () {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    if (data.success) {
                        configContentLoaded = data.content || '';
                        if (textarea) { textarea.value = configContentLoaded; textarea.disabled = false; }
                        if (saveBtn) saveBtn.disabled = false;
                        if (reloadBtn) reloadBtn.disabled = false;
                        if (statusEl) statusEl.textContent = '';
                    } else {
                        if (textarea) { textarea.value = ''; textarea.disabled = true; }
                        // 改用 Toast 提示加载失败
                        var msg = data.message || i18n.t('action.execute_failed');
                        if (msg.indexOf('不存在') >= 0 || msg.indexOf('not found') >= 0) {
                            msg = i18n.t('config.not_generated');
                        }
                        showFlash(msg, 'warning');
                    }
                } catch (e) {
                    if (textarea) { textarea.value = ''; textarea.disabled = true; }
                    showFlash(i18n.t('config.parse_error'), 'error');
                }
            } else if (xhr.status === 404) {
                if (textarea) { textarea.value = ''; textarea.disabled = true; }
                showFlash(i18n.t('config.not_generated'), 'warning');
            } else {
                if (textarea) { textarea.value = ''; textarea.disabled = true; }
                showFlash(i18n.t('config.load_error') + xhr.status, 'error');
            }
        };
        xhr.onerror = function () {
            if (textarea) { textarea.value = ''; textarea.disabled = true; }
            showFlash(i18n.t('config.network_error_detail'), 'error');
        };
        xhr.ontimeout = function () {
            if (textarea) { textarea.value = ''; textarea.disabled = true; }
            showFlash(i18n.t('config.timeout_detail'), 'error');
        };
        xhr.send();
    }

    function saveConfigFile() {
        var textarea = qs('[data-role="config-textarea"]');
        var statusEl = qs('[data-role="config-editor-status"]');
        var saveBtn = qs('[data-role="btn-config-save"]');

        if (!textarea || textarea.disabled) return;

        if (saveBtn) saveBtn.disabled = true;
        // 旧 status 文本清空，改用 Toast 提示
        if (statusEl) statusEl.textContent = '';

        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/config-file', true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.timeout = 45000;
        xhr.onload = function () {
            if (saveBtn) saveBtn.disabled = false;
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    if (data.success) {
                        configContentLoaded = textarea.value;
                        // 改用 Toast 提示保存结果，合并备份信息避免重复提示
                        var saveMsg = i18n.translateBackendMessage(data.message) || i18n.t('config.saved');
                        if (data.backup_path) {
                            saveMsg += i18n.t('config.backup_path') + data.backup_path;
                        }
                        showFlash(saveMsg, 'success');
                        // runtime.ini 保存不影响任何组件状态，不触发 refreshStatus
                        // 组件配置保存后刷新状态，让 affected_component 卡片显示 config_dirty
                        if (data.affected_component || data.config_dirty) {
                            // 清空环境信息缓存签名，确保保存配置后环境信息状态刷新
                            envInfoSignature = '';
                            refreshStatus();
                        }
                    } else {
                        // 优先显示后端返回的 message（含 nginx -t 错误摘要等）
                        showFlash(i18n.translateBackendMessage(data.message) || i18n.t('config.save_failed'), 'error');
                    }
                } catch (e) {
                    showFlash(i18n.t('action.response_parse_error'), 'error');
                }
            } else {
                // 非 200 状态码，尝试解析后端错误消息
                var errMsg = 'HTTP ' + xhr.status;
                try {
                    var errData = JSON.parse(xhr.responseText);
                    if (errData && errData.message) errMsg = errData.message;
                } catch (e2) { /* ignore */ }
                showFlash(errMsg, 'error');
            }
        };
        xhr.onerror = function () {
            if (saveBtn) saveBtn.disabled = false;
            showFlash(i18n.t('config.save_network_error'), 'error');
        };
        xhr.ontimeout = function () {
            if (saveBtn) saveBtn.disabled = false;
            showFlash(i18n.t('config.save_timeout'), 'error');
        };
        xhr.send(JSON.stringify({ name: currentConfigName, content: textarea.value }));
    }

    // --- Environment Info Module ---
    // 独立模块，不混入 renderDashboard 三卡片逻辑

    function loadEnvironmentInfo(forceRefresh) {
        // 加载环境信息数据并渲染。forceRefresh 时忽略缓存签名和节流。
        if (envInfoLoading) return;
        // 节流：非强制刷新且签名未失效时，10 秒内不重复请求
        var signatureInvalid = !envInfoSignature;
        if (!forceRefresh && !signatureInvalid && envInfoLastLoadTime && (Date.now() - envInfoLastLoadTime < 10000)) return;

        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/environment-info', true);
        xhr.timeout = 5000;
        envInfoLoading = true;
        xhr.onload = function () {
            envInfoLoading = false;
            envInfoLastLoadTime = Date.now();
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    if (data.success) {
                        envInfoCache = data;
                        renderEnvironmentInfo(data, forceRefresh);
                    }
                } catch (e) {
                    // 静默失败，不影响主流程
                }
            }
        };
        xhr.onerror = function () { envInfoLoading = false; envInfoLastLoadTime = Date.now(); };
        xhr.ontimeout = function () { envInfoLoading = false; envInfoLastLoadTime = Date.now(); };
        xhr.send();
    }

    function renderEnvironmentInfo(data, forceRefresh) {
        var container = qs('[data-role="env-info-container"]');
        if (!container) return;

        var modules = data.modules || {};

        // 签名比较：状态无变化时跳过重渲染（除非强制刷新，如语言切换）
        var sig = '';
        ['nginx', 'php', 'mysql'].forEach(function (key) {
            var m = modules[key];
            if (m) sig += key + ':' + (m.status || '') + ';';
        });
        if (!forceRefresh && sig === envInfoSignature) return;
        envInfoSignature = sig;

        var isEn = (typeof i18n !== 'undefined' && i18n.getLang && i18n.getLang() === 'en-US');

        // 标题区
        var html = '<div class="env-info-panel">';
        html += '<div class="env-info-header">';
        html += '<h2 class="env-info-title">' + escHtml(i18n.t('env_info.module_title')) + '</h2>';
        html += '<p class="env-info-subtitle">' + escHtml(i18n.t('env_info.subtitle')) + '</p>';
        html += '</div>';
        html += '<div class="env-info-grid">';

        // 三个模块卡片
        ['nginx', 'php', 'mysql'].forEach(function (modKey) {
            var mod = modules[modKey];
            if (!mod) return;

            var statusClass = mod.status || 'unknown';
            var statusText = i18n.t('env_info.status_' + statusClass) || statusClass;

            html += '<div class="env-info-card">';
            // 卡片头：标题 + 状态
            html += '<div class="env-info-card-header">';
            html += '<span class="env-info-card-title">' + escHtml(mod.title || modKey) + '</span>';
            html += '<span class="env-info-status ' + escHtml(statusClass) + '"><span class="badge-dot"></span>' + escHtml(statusText) + '</span>';
            html += '</div>';

            // 配置项列表
            html += '<div class="env-info-items">';
            var items = mod.items || [];
            items.forEach(function (item) {
                var label = isEn ? (item.label_en || item.label) : item.label;
                var desc = isEn ? (item.description_en || item.description) : item.description;
                // 路径显示：相对路径，反斜杠风格
                var displayPath = (item.path || '').replace(/\//g, '\\');
                // 目录类型追加 *.conf 提示
                if (item.kind === 'directory') displayPath += '\\*.conf';
                var absPath = (item.abs_path || '').replace(/\//g, '\\');
                if (item.kind === 'directory') absPath += '\\*.conf';

                html += '<div class="env-info-item">';
                html += '<div class="env-info-item-label">' + escHtml(label) + '</div>';
                html += '<span class="env-info-path" title="' + escHtml(absPath) + '">' + escHtml(displayPath) + '</span>';
                if (desc) {
                    html += '<div class="env-info-item-desc">' + escHtml(desc) + '</div>';
                }
                html += '</div>';
            });
            html += '</div>';

            // 操作按钮
            html += '<div class="env-info-actions">';
            var actions = mod.actions || [];
            actions.forEach(function (action) {
                var actionLabel = isEn ? (action.label_en || action.label) : action.label;
                var btnClass = action.type === 'edit_config' ? 'btn-edit' : 'btn-open';
                html += '<button class="env-info-button ' + btnClass + '" data-env-action="' + escHtml(action.type) + '"';
                if (action.edit_key) html += ' data-edit-key="' + escHtml(action.edit_key) + '"';
                if (action.open_key) html += ' data-open-key="' + escHtml(action.open_key) + '"';
                html += '>' + escHtml(actionLabel) + '</button>';
            });
            html += '</div>';

            html += '</div>'; // .env-info-card
        });

        html += '</div>'; // .env-info-grid
        html += '</div>'; // .env-info-panel

        container.innerHTML = html;
    }

    // --- Status refresh ---
    function refreshStatus() {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/status', true);
        // 首次加载用更长超时，后续轮询用短超时
        xhr.timeout = firstLoadDone ? STATUS_TIMEOUT : STATUS_FIRST_TIMEOUT;
        xhr.setRequestHeader('Accept', 'application/json');
        xhr.onload = function () {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    firstLoadFailCount = 0;  // 成功时重置失败计数
                    applyStatus(data);
                } catch (e) {
                    if (!firstLoadDone) showErrorView(i18n.t('error.status_parse'));
                }
            } else {
                if (!firstLoadDone) showErrorView('HTTP ' + xhr.status);
            }
        };
        xhr.onerror = function () {
            if (!firstLoadDone) {
                showErrorView(i18n.t('error.network'));
            }
            // 非首次加载时静默重试
        };
        xhr.ontimeout = function () {
            if (!firstLoadDone) {
                firstLoadFailCount++;
                if (firstLoadFailCount >= 3) {
                    // 连续 3 次首次状态请求失败，显示真正网络错误
                    showErrorView(i18n.t('error.network'));
                } else {
                    // 首次加载超时，显示检测中提示（非硬错误），自动重试
                    showErrorView(i18n.t('error.status_detecting'));
                    setTimeout(function () { refreshStatus(); }, 3000);
                }
            }
            // 非首次加载时静默重试，不覆盖当前视图
        };
        xhr.send();
    }

    // 明确状态集合：这些状态不会被 unknown 保护覆盖
    var _DEFINITE_STATES = {'running': true, 'stopped': true, 'external': true, 'partial': true, 'error': true, 'pending_reload': true};

    // 基于 data 和 prevStatusData 构造安全状态数据，防止临时 unknown 污染缓存
    function _buildSafeStatusData(data, prevStatusData) {
        if (!data || !data.initialized) return data;
        // 首次加载没有 prevStatusData，直接使用原始数据
        if (!prevStatusData || !prevStatusData.initialized) return data;

        var safeData = WNMPCompat.assign({}, data);
        var changed = false;
        // 兼容中英文旧后缀的正则
        var _notRefreshedRe = / \(状态未刷新\)$| \(not refreshed\)$/;
        ['nginx', 'php', 'mysql'].forEach(function (svc) {
            var newSt = data[svc];
            var prevSt = prevStatusData[svc];
            var notRefreshedSuffix = i18n.t('status.not_refreshed');
            // 组件字段缺失：保留上一轮该组件状态
            if (!newSt && prevSt) {
                safeData[svc] = WNMPCompat.assign({}, prevSt, { message: (prevSt.message || '').replace(_notRefreshedRe, '') + notRefreshedSuffix });
                changed = true;
                return;
            }
            // 新状态为 unknown 且上一轮是明确状态：保留上一轮状态，追加"状态未刷新"
            if (newSt && newSt.state === 'unknown' && prevSt && prevSt.state && _DEFINITE_STATES[prevSt.state]) {
                safeData[svc] = WNMPCompat.assign({}, prevSt, { message: (prevSt.message || '').replace(_notRefreshedRe, '') + notRefreshedSuffix });
                changed = true;
                return;
            }
            // 新状态是明确状态、上一轮也是 unknown、或首次加载：使用新数据
            safeData[svc] = newSt;
        });

        // 组件状态保护触发时，基于 safeData 重新计算 overall
        if (changed) {
            var components = [safeData.nginx, safeData.php, safeData.mysql].filter(Boolean);
            var hasError = components.some(function (c) { return c.state === 'error'; });
            var hasExternal = components.some(function (c) { return c.state === 'external'; });
            var hasUnknown = components.some(function (c) { return c.state === 'unknown'; });
            var allRunning = components.length === 3 && components.every(function (c) { return c.state === 'running' || c.state === 'pending_reload'; });
            var allStopped = components.length === 3 && components.every(function (c) { return c.state === 'stopped'; });
            var hasPendingReload = components.some(function (c) { return c.state === 'pending_reload'; });
            if (hasError) safeData.overall = 'error';
            else if (hasExternal) safeData.overall = 'external';
            else if (hasUnknown) safeData.overall = 'unknown';
            else if (allRunning) safeData.overall = hasPendingReload ? 'pending_reload' : 'running';
            else if (allStopped) safeData.overall = 'stopped';
            else safeData.overall = 'partial';
        }
        return safeData;
    }

    function applyStatus(data) {
        if (data.success === false) {
            if (!firstLoadDone) showErrorView(data.message || i18n.t('error.status_fetch'));
            return;
        }

        firstLoadDone = true;
        // 先构造 safeStatusData（保护 unknown 不污染缓存），再写入 lastStatusData
        var prevStatusData = lastStatusData;
        var safeData = _buildSafeStatusData(data, prevStatusData);
        lastStatusData = safeData;
        var initialized = !!safeData.initialized;
        var initializing = !!safeData.initializing;
        var starting = !!safeData.starting;

        // 无论当前在哪个页面，都更新 currentInitialized 和开机自启动门控
        // initializing 仅在 initialized=false 时有效；starting 仅在 initialized=true 时有效
        currentInitialized = initialized && !initializing;
        updateAutostartGate();
        // 使用 safeData.overall，避免卡片稳定而顶部显示 unknown
        updateTopbar(currentNav, safeData.overall);

        // 非 overview 页面：只更新按钮状态，不切换视图
        if (currentNav !== 'overview') {
            if (initialized && !initializing) {
                ['nginx', 'php', 'mysql'].forEach(function (svc) {
                    if (safeData[svc]) updateComponentButtons(svc, safeData[svc].state, safeData[svc].running, safeData[svc].config_dirty, safeData[svc].config_pending_reload);
                });
            }
            return;
        }

        // overview 页面逻辑：严格区分初始化和启动
        // 初始化页条件：initialized=false 且 initializing=true（仅首次初始化）
        // dashboard 条件：initialized=true（无论 starting 与否）
        if (!initialized && initializing) {
            showInitView();
            renderInitView(safeData);
        } else if (initialized) {
            showDashboardView();
            renderDashboard(safeData);
        } else {
            // 未初始化且未在初始化中
            showInitView();
            renderInitView(safeData);
        }
    }

    // 单组件卡片更新：单组件动作成功后只更新 affected_component 对应卡片
    // 不覆盖其它模块状态，不调用 applyStatus
    function updateComponentCard(component, status) {
        if (!component || !status) return;
        var grid = qs('[data-role="services-grid"]');
        if (!grid) return;

        // 环境级操作执行中，不重建任何卡片
        if (currentEnvActionRunning) return;

        // 轮询保护：当前正在操作的组件，不重建卡片
        if (actionRunning && currentActionComponent === component) return;

        // 清除签名缓存，确保下次 renderDashboard 不会跳过
        lastDashboardSignature = '';
        // 清空环境信息缓存签名，确保服务动作后环境信息状态刷新
        envInfoSignature = '';

        // 更新 lastStatusData 中对应组件的数据
        if (lastStatusData && lastStatusData[component]) {
            lastStatusData[component] = status;
        }

        // 重新渲染该组件卡片
        var oldCard = grid.querySelector('[data-service="' + component + '"]');
        var newCardHTML = buildServiceCardHTML(component, status);
        var tmp = document.createElement('div');
        tmp.innerHTML = newCardHTML;
        var newCard = tmp.firstElementChild;

        if (oldCard) {
            grid.replaceChild(newCard, oldCard);
        } else {
            grid.appendChild(newCard);
        }

        // 更新按钮状态
        updateComponentButtons(component, status.state, status.running, status.config_dirty, status.config_pending_reload);

        // 基于 lastStatusData 缓存重算 overall，避免单组件动作后顶部状态滞后
        if (lastStatusData && lastStatusData.nginx && lastStatusData.php && lastStatusData.mysql) {
            var components = [lastStatusData.nginx, lastStatusData.php, lastStatusData.mysql];
            var hasError = components.some(function (c) { return c.state === 'error'; });
            var hasExternal = components.some(function (c) { return c.state === 'external'; });
            var hasUnknown = components.some(function (c) { return c.state === 'unknown'; });
            var allRunning = components.every(function (c) { return c.state === 'running' || c.state === 'pending_reload'; });
            var allStopped = components.every(function (c) { return c.state === 'stopped'; });
            var hasPendingReload = components.some(function (c) { return c.state === 'pending_reload'; });
            if (hasError) lastStatusData.overall = 'error';
            else if (hasExternal) lastStatusData.overall = 'external';
            else if (hasUnknown) lastStatusData.overall = 'unknown';
            else if (allRunning) lastStatusData.overall = hasPendingReload ? 'pending_reload' : 'running';
            else if (allStopped) lastStatusData.overall = 'stopped';
            else lastStatusData.overall = 'partial';
            updateTopbar(currentNav, lastStatusData.overall);
        }
    }

    function renderInitView(data) {
        var initializing = data && data.initializing;
        var initPhase = data && data.init_phase;
        var initFailed = initPhase === 'failed';
        var msgEl = qs('[data-role="init-message"]');
        if (msgEl) {
            if (initFailed && data.message) {
                // 初始化失败：显示失败原因
                msgEl.textContent = i18n.t('init.failed_message', { message: data.message });
            } else if (initializing && data.message) {
                // 初始化中：显示后端返回的阶段文案
                var translated = i18n.translateBackendMessage(data.message);
                msgEl.textContent = translated;
            } else if (data && data.message) {
                var translated = i18n.translateBackendMessage(data.message);
                if (i18n.getLang() !== 'zh-CN' && translated === data.message) {
                    msgEl.textContent = i18n.t('init.message');
                } else {
                    msgEl.textContent = translated;
                }
            } else {
                msgEl.textContent = i18n.t('init.message');
            }
        }
        // 更新初始化详情区：失败时显示失败提示+重试，初始化中时显示当前阶段，否则显示完整步骤列表
        var detailsEl = qs('[data-role="init-details"]');
        if (detailsEl) {
            if (initFailed) {
                // 初始化失败：显示失败提示和重试说明
                detailsEl.innerHTML =
                    '<div class="init-phase-indicator init-failed-indicator">' +
                    i18n.t('init.failed_detail') +
                    '</div>';
            } else if (initializing && initPhase) {
                // 初始化中：显示当前阶段
                detailsEl.innerHTML =
                    '<div class="init-phase-indicator">' +
                    i18n.t('init.current_phase', { phase: i18n.t('init.phase.' + initPhase, initPhase) }) +
                    '</div>';
            } else {
                detailsEl.innerHTML =
                    i18n.t('init.detail') + '<br>' +
                    i18n.t('init.detail.1') + '<br>' +
                    i18n.t('init.detail.2') + '<br>' +
                    i18n.t('init.detail.3') + '<br>' +
                    i18n.t('init.detail.4') + '<br>' +
                    i18n.t('init.detail.5');
            }
        }
        // 渲染未初始化状态的模块卡片
        renderInitModules(data);
    }

    // 渲染未初始化时的模块卡片（Nginx/PHP/MySQL），显示待初始化状态和端口信息
    // 端口信息优先从 API status 数据读取，若不可用则从 runtime.ini 配置文件读取
    var _runtimePortCache = null; // 缓存 runtime.ini 端口信息，避免重复请求

    function renderInitModules(data) {
        var grid = qs('[data-role="init-modules-grid"]');
        if (!grid) return;

        // 从 API 数据或默认值获取端口信息
        var portInfo = {
            nginx: { http: '--', https: '--' },
            php: { port: '--' },
            mysql: { port: '--' }
        };

        // 尝试从 data 中读取端口（API 返回的 status 数据可能包含端口信息）
        if (data) {
            if (data.nginx && data.nginx.ports && data.nginx.ports.length) {
                data.nginx.ports.forEach(function (p) {
                    if (p.name === 'HTTP' || p.name === 'http') portInfo.nginx.http = p.port || '--';
                    if (p.name === 'HTTPS' || p.name === 'https') portInfo.nginx.https = p.port || '--';
                });
            }
            if (data.php && data.php.port !== undefined && data.php.port !== null) portInfo.php.port = data.php.port;
            if (data.mysql && data.mysql.port !== undefined && data.mysql.port !== null) portInfo.mysql.port = data.mysql.port;
        }

        // 如果 API 未返回端口信息，尝试从 runtime.ini 缓存读取
        var hasPortData = (portInfo.nginx.http !== '--' || portInfo.php.port !== '--' || portInfo.mysql.port !== '--');
        if (!hasPortData && _runtimePortCache) {
            portInfo = _runtimePortCache;
        }

        var html = '';
        // Nginx 卡片
        html += buildInitModuleCard('nginx', 'Nginx', portInfo.nginx.http + ' / ' + portInfo.nginx.https);
        // PHP 卡片
        html += buildInitModuleCard('php', 'PHP-CGI', String(portInfo.php.port));
        // MySQL 卡片
        html += buildInitModuleCard('mysql', 'MySQL', String(portInfo.mysql.port));

        grid.innerHTML = html;

        // 如果没有端口数据且没有缓存，异步从 runtime.ini 读取
        if (!hasPortData && !_runtimePortCache) {
            _fetchRuntimePorts();
        }
    }

    // 从 runtime.ini 配置文件读取默认端口信息
    function _fetchRuntimePorts() {
        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/config-file?name=runtime', true);
        xhr.timeout = 5000;
        xhr.onload = function () {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    if (data.success && data.content) {
                        var ports = _parseRuntimePorts(data.content);
                        if (ports) {
                            _runtimePortCache = ports;
                            // 重新渲染模块卡片
                            var grid = qs('[data-role="init-modules-grid"]');
                            if (grid && currentNav === 'overview' && !currentInitialized) {
                                renderInitModules(lastStatusData);
                            }
                        }
                    }
                } catch (e) {}
            }
        };
        xhr.onerror = function () {};
        xhr.ontimeout = function () {};
        xhr.send();
    }

    // 解析 runtime.ini 内容，提取端口配置
    function _parseRuntimePorts(content) {
        var ports = {
            nginx: { http: '--', https: '--' },
            php: { port: '--' },
            mysql: { port: '--' }
        };
        var lines = content.split('\n');
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i].trim();
            if (line.indexOf('#') === 0 || line.indexOf(';') === 0) continue;
            var eqIdx = line.indexOf('=');
            if (eqIdx < 0) continue;
            var key = line.substring(0, eqIdx).trim().toUpperCase();
            var val = line.substring(eqIdx + 1).trim();
            if (key === 'HTTP_PORT') ports.nginx.http = val || '--';
            else if (key === 'HTTPS_PORT') ports.nginx.https = val || '--';
            else if (key === 'PHP_CGI_PORT') ports.php.port = val || '--';
            else if (key === 'MYSQL_PORT') ports.mysql.port = val || '--';
        }
        return ports;
    }

    // 构建未初始化状态的模块卡片 HTML
    function buildInitModuleCard(svc, svcName, portValue) {
        var stateText = i18n.t('card_state.pending_init');
        return '<div class="service-card" data-service="' + svc + '">' +
            '<div class="service-card-head">' +
                '<div class="service-title-wrap">' +
                    '<span class="service-icon ' + svc + '">' + getServiceIcon(svc) + '</span>' +
                    '<span class="service-name">' + escHtml(svcName) + '</span>' +
                '</div>' +
                '<span class="service-badge pending_init"><span class="badge-dot"></span>' + escHtml(stateText) + '</span>' +
            '</div>' +
            '<div class="service-metrics">' +
                '<div class="metric-row"><span class="metric-icon">' + _metricIcons.run_state + '</span><span class="metric-label">' + escHtml(i18n.t('metric.run_state')) + '</span><span class="metric-value">' + escHtml(i18n.t('metric.not_started')) + '</span></div>' +
                '<div class="metric-row"><span class="metric-icon">' + _metricIcons.config_state + '</span><span class="metric-label">' + escHtml(i18n.t('metric.config_state')) + '</span><span class="metric-value">' + escHtml(i18n.t('metric.not_generated')) + '</span></div>' +
                '<div class="metric-row"><span class="metric-icon">' + _metricIcons.port + '</span><span class="metric-label">' + escHtml(i18n.t('metric.port')) + '</span><span class="metric-value">' + escHtml(portValue) + '</span></div>' +
            '</div>' +
        '</div>';
    }

    // 生成 dashboard 状态签名，用于判断是否需要重建卡片
    function getDashboardSignature(data) {
        var sig = '';
        ['nginx', 'php', 'mysql'].forEach(function (svc) {
            var st = data[svc];
            if (!st) return;
            sig += svc + ':' + (st.state || '') + ',' + (!!st.running) + ',' + (st.port || '') + ',' +
                   (!!st.port_open) + ',' + (!!st.config_dirty) + ',' + (!!st.config_pending_reload) + ';';
        });
        return sig;
    }
    var lastDashboardSignature = '';

    function renderDashboard(data) {
        var grid = qs('[data-role="services-grid"]');
        if (!grid) return;

        // 环境级操作执行中，跳过卡片重渲染，避免覆盖 busy 灰态
        if (currentEnvActionRunning) return;

        // 签名比较：状态无变化时跳过整卡重建，避免覆盖 busy 灰态和 hover 等交互状态
        var sig = getDashboardSignature(data);
        if (sig === lastDashboardSignature) return;
        lastDashboardSignature = sig;

        // 逐组件替换卡片，而非 innerHTML 全量覆盖，避免 busy 组件卡片消失
        ['nginx', 'php', 'mysql'].forEach(function (svc) {
            var st = data[svc];
            if (!st) return;
            // 轮询保护：当前正在操作的组件，保留旧卡片和 is-busy 状态，不重建
            if (actionRunning && currentActionComponent === svc) return;

            var oldCard = grid.querySelector('[data-service="' + svc + '"]');
            var newCardHTML = buildServiceCardHTML(svc, st);
            var tmp = document.createElement('div');
            tmp.innerHTML = newCardHTML;
            var newCard = tmp.firstElementChild;

            if (oldCard) {
                grid.replaceChild(newCard, oldCard);
            } else {
                grid.appendChild(newCard);
            }
        });

        // 渲染完成后更新按钮状态
        ['nginx', 'php', 'mysql'].forEach(function (svc) {
            var st = data[svc];
            if (!st) return;
            // 轮询保护：当前正在操作的组件，跳过按钮更新
            if (actionRunning && currentActionComponent === svc) return;
            updateComponentButtons(svc, st.state, st.running, st.config_dirty, st.config_pending_reload);
        });
    }

    // renderNginxPorts 已废弃，Nginx 端口指标由 buildNginxMetrics 统一渲染

    // --- MySQL 密码一次性模态框显示 ---
    function showMysqlPassword(password) {
        var modal = qs('[data-role="mysql-password-modal"]');
        var pwdValue = qs('[data-role="mysql-pwd-value-modal"]');
        if (!modal || !pwdValue || mysqlPasswordHidden) return;

        if (password) {
            pwdValue.textContent = password;
            // IE11 兼容：清空 inline display，由 CSS is-visible class 控制显示
            // 现代浏览器 .is-visible -> display:flex；IE11 fallback -> display:block + absolute 居中
            modal.style.display = '';
            modal.classList.add('is-visible');
        }
    }

    function escHtml(str) {
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // --- Action execution ---
    function doAction(action) {
        if (actionRunning) return;
        actionRunning = true;

        var initBtn = qs('[data-role="btn-init-env"]');
        var isInitAction = (action === 'init_env');
        var isAutostartAction = (action === 'install_autostart' || action === 'uninstall_autostart');
        var isComponentAction = ['start_nginx','stop_nginx','restart_nginx','reload_nginx',
            'start_php','stop_php','restart_php','start_mysql','stop_mysql','restart_mysql'].indexOf(action) >= 0;

        if (isInitAction && initBtn) {
            initBtn.disabled = true;
            // 只更新按钮内 span 文本，保留 SVG 图标
            var initBtnSpan = initBtn.querySelector('span');
            if (initBtnSpan) initBtnSpan.textContent = i18n.t('btn.initting');
            else initBtn.textContent = i18n.t('btn.initting');
            // 立即切换到初始化中视图
            lastStatusData = { initialized: false, initializing: true, init_phase: 'preparing_config', overall: 'initializing', message: i18n.t('init.phase.preparing_config') };
            showInitView();
            renderInitView(lastStatusData);
        } else if (isAutostartAction) {
            disableAutostartButtons(true);
            // 执行中不再写入旧提示块
        } else if (isComponentAction) {
            disableComponentButtons(action, true);
            // "执行中..." 不再显示 Toast，避免闪烁
        } else {
            disableEnvButtons(true);
            // 环境级操作影响全部模块，禁用所有卡片按钮
            currentEnvActionRunning = true;
            disableAllCardButtons(true);
            // "执行中..." 不再显示 Toast，避免闪烁
        }

        var xhr = new XMLHttpRequest();
        xhr.open('POST', '/api/action', true);
        xhr.setRequestHeader('Content-Type', 'application/json');
        xhr.timeout = ACTION_TIMEOUT[action] || 120000;
        xhr.onload = function () {
            actionRunning = false;
            if (isInitAction && initBtn) { initBtn.disabled = false; var _s = initBtn.querySelector('span'); if (_s) _s.textContent = i18n.t('btn.init_env'); else initBtn.textContent = i18n.t('btn.init_env'); }
            else if (isAutostartAction) { disableAutostartButtons(false); }
            else if (isComponentAction) { disableComponentButtons(action, false); }
            else { disableEnvButtons(false); currentEnvActionRunning = false; disableAllCardButtons(false); lastDashboardSignature = ''; }

            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    if (data.busy) {
                        var busyMsg;
                        if (isInitAction) {
                            busyMsg = i18n.t('action.busy_init');
                        } else if (isComponentAction) {
                            busyMsg = i18n.t('action.busy_component');
                        } else {
                            busyMsg = i18n.t('action.busy');
                        }
                        if (isInitAction) showInitResult(false, busyMsg);
                        else if (isAutostartAction) showAutostartResult(false, busyMsg);
                        else showActionResult({ action: action, success: false, message: busyMsg }, false);
                    } else {
                        if (isInitAction) {
                            // 只要响应里带 mysql_root_password，不管 success 是 true 还是 false，都先显示密码
                            if (data.mysql_root_password) {
                                showMysqlPassword(data.mysql_root_password);
                            }
                            if (data.success) {
                                // 初始化成功：统一走 applyStatus，确保 lastStatusData/topbar/cache 同步
                                var snapshot = data.status_snapshot;
                                if (snapshot) {
                                    applyStatus(snapshot);
                                } else {
                                    refreshStatus();
                                }
                            } else {
                                // 初始化失败，但密码可能已生成，提示用户保存
                                var failMsg = i18n.translateBackendMessage(data.message) || i18n.t('action.init_fail');
                                if (data.mysql_root_password) {
                                    failMsg = i18n.t('action.init_fail_with_pwd');
                                }
                                showInitResult(false, failMsg);
                            }
                        } else if (isAutostartAction) {
                            handleAutostartResponse(action, data);
                        } else {
                            showActionResult(data, false);
                            // 单组件动作：只更新 affected_component 对应卡片，不覆盖其它模块
                            // 环境级动作：全量刷新
                            if (data.affected_component && data.component_status) {
                                updateComponentCard(data.affected_component, data.component_status);
                            } else if (data.status_snapshot) {
                                applyStatus(data.status_snapshot);
                            } else {
                                refreshStatus();
                            }
                        }
                    }
                } catch (e) {
                    if (isInitAction) showInitResult(false, i18n.t('action.response_parse_error'));
                    else if (isAutostartAction) showAutostartResult(false, i18n.t('action.response_parse_error'));
                    else showActionResult({ action: action, success: false, message: i18n.t('action.response_parse_error') }, false);
                    refreshStatus();
                }
            } else {
                if (isInitAction) showInitResult(false, 'HTTP ' + xhr.status);
                else if (isAutostartAction) showAutostartResult(false, 'HTTP ' + xhr.status);
                else showActionResult({ action: action, success: false, message: 'HTTP ' + xhr.status }, false);
                refreshStatus();
            }
        };
        xhr.onerror = function () {
            actionRunning = false;
            if (isInitAction && initBtn) { initBtn.disabled = false; var _s2 = initBtn.querySelector('span'); if (_s2) _s2.textContent = i18n.t('btn.init_env'); else initBtn.textContent = i18n.t('btn.init_env'); showInitResult(false, i18n.t('action.network_error')); }
            else if (isAutostartAction) { disableAutostartButtons(false); showAutostartResult(false, i18n.t('action.network_error_short')); }
            else if (isComponentAction) { disableComponentButtons(action, false); showActionResult({ action: action, success: false, message: i18n.t('action.network_error') }, false); }
            else { disableEnvButtons(false); currentEnvActionRunning = false; disableAllCardButtons(false); lastDashboardSignature = ''; showActionResult({ action: action, success: false, message: i18n.t('action.network_error') }, false); }
        };
        xhr.ontimeout = function () {
            actionRunning = false;
            if (isInitAction && initBtn) { initBtn.disabled = false; var _s3 = initBtn.querySelector('span'); if (_s3) _s3.textContent = i18n.t('btn.init_env'); else initBtn.textContent = i18n.t('btn.init_env'); showInitResult(false, i18n.t('action.timeout')); }
            else if (isAutostartAction) { disableAutostartButtons(false); showAutostartResult(false, i18n.t('action.timeout')); }
            else if (isComponentAction) { disableComponentButtons(action, false); showActionResult({ action: action, success: false, message: i18n.t('action.timeout') }, false); }
            else { disableEnvButtons(false); currentEnvActionRunning = false; disableAllCardButtons(false); lastDashboardSignature = ''; showActionResult({ action: action, success: false, message: i18n.t('action.timeout') }, false); }
        };
        xhr.send(JSON.stringify({ action: action }));
    }

    // 设置指定组件卡片内所有按钮的禁用状态，并切换 is-busy class
    function setComponentButtonsDisabled(svc, disabled) {
        var card = qs('[data-service="' + svc + '"]');
        if (!card) return;
        // 禁用/启用所有 action 按钮和版本按钮
        qsa('button[data-action]', card).forEach(function (btn) { btn.disabled = disabled; });
        qsa('button[data-role="btn-version"]', card).forEach(function (btn) { btn.disabled = disabled; });
        // 切换 is-busy class
        if (disabled) {
            card.classList.add('is-busy');
        } else {
            card.classList.remove('is-busy');
        }
    }

    function disableComponentButtons(action, disabled) {
        var svc = action.replace(/^(start|stop|restart|reload)_/, '');
        setComponentButtonsDisabled(svc, disabled);
        // 记录当前操作组件，轮询期间保护 busy 状态
        if (disabled) {
            currentActionComponent = svc;
        } else {
            currentActionComponent = null;
            // 操作结束，清除签名缓存，确保下一轮轮询能正常刷新卡片
            lastDashboardSignature = '';
        }
    }

    function disableEnvButtons(disabled) {
        var toolbar = qs('[data-role="action-toolbar"]');
        if (toolbar) qsa('button[data-action]', toolbar).forEach(function (btn) { btn.disabled = disabled; });
    }

    // 环境级操作时禁用/启用所有卡片内的按钮（含查看版本）
    function disableAllCardButtons(disabled) {
        ['nginx', 'php', 'mysql'].forEach(function (svc) {
            var card = qs('[data-service="' + svc + '"]');
            if (card) {
                qsa('button[data-action], button[data-role="btn-version"]', card).forEach(function (btn) { btn.disabled = disabled; });
                if (disabled) card.classList.add('is-busy');
                else card.classList.remove('is-busy');
            }
        });
    }

    function disableAutostartButtons(disabled) {
        qsa('[data-action="install_autostart"],[data-action="uninstall_autostart"]').forEach(function (btn) { btn.disabled = disabled; });
    }

    // 未初始化时禁用"启用开机自启动"按钮并显示提示
    // 已初始化后根据 autostart state 更新按钮状态
    // 需求九：state=enabled 禁用启用、允许关闭；not_found 允许启用、禁用关闭；
    // disabled/invalid 允许启用和关闭；error 允许刷新，启用/关闭不禁用但显示检测失败提示
    var lastAutostartState = null;

    function updateAutostartGate() {
        var installBtn = qs('[data-action="install_autostart"]');
        var uninstallBtn = qs('[data-action="uninstall_autostart"]');
        var gateHint = qs('[data-role="autostart-gate-hint"]');
        if (!installBtn) return;

        // 未初始化优先级最高：无论 autostart 状态如何，启用按钮必须禁用
        if (!currentInitialized) {
            installBtn.disabled = true;
            if (uninstallBtn) uninstallBtn.disabled = false; // 关闭可以在未初始化时允许
            if (gateHint) gateHint.style.display = 'block';
            return;
        }

        // 已初始化：隐藏未初始化提示
        if (gateHint) gateHint.style.display = 'none';

        // 根据 autostart state 调整按钮
        if (lastAutostartState === 'enabled') {
            installBtn.disabled = true;   // 已启用，无需再启用
            if (uninstallBtn) uninstallBtn.disabled = false;
        } else if (lastAutostartState === 'not_found') {
            installBtn.disabled = false;  // 未启用，可以启用
            if (uninstallBtn) uninstallBtn.disabled = true; // 没有任务，无需关闭
        } else if (lastAutostartState === 'disabled' || lastAutostartState === 'invalid') {
            installBtn.disabled = false;  // 已创建但禁用/配置异常，可以重新启用
            if (uninstallBtn) uninstallBtn.disabled = false; // 也可以关闭
        } else if (lastAutostartState === 'timeout') {
            // 超时状态：不禁用按钮，允许用户稍后重试
            installBtn.disabled = false;
            if (uninstallBtn) uninstallBtn.disabled = false;
        } else if (lastAutostartState === 'conflict') {
            // 冲突状态：允许关闭（删除冲突任务），允许重新启用
            installBtn.disabled = false;
            if (uninstallBtn) uninstallBtn.disabled = false;
        } else {
            // error 或未知状态，不禁用按钮，让用户可以重试
            installBtn.disabled = false;
            if (uninstallBtn) uninstallBtn.disabled = false;
        }
    }

    function showInitResult(success, message) {
        // 改用 Flash Toast 提示初始化结果；动态文本先 escHtml 转义，再拼接固定 HTML 链接
        var msg = escHtml(message);
        if (!success) {
            // 使用 i18n 格式化日志链接，避免中文全角括号在英文环境显示
            var logLinks = i18n.t('action.log_links', {
                runtime: '<a class="log-link" data-goto-log="runtime" style="color:#2563eb;text-decoration:underline;cursor:pointer">' + escHtml(i18n.t('action.runtime_log')) + '</a>',
                action: '<a class="log-link" data-goto-log="action" style="color:#2563eb;text-decoration:underline;cursor:pointer">' + escHtml(i18n.t('action.action_log')) + '</a>'
            });
            msg += logLinks;
        }
        showFlash(msg, success ? 'success' : 'error', { raw: true });
    }

    function showActionResult(data, silent) {
        // 改用 Flash Toast 提示操作结果；动态文本先 escHtml 转义，再拼接固定 HTML 链接
        if (silent) return; // "执行中..." 状态不再显示提示，避免闪烁

        var actionNames = {
            'start_env': i18n.t('action_name.start_env'), 'init_env': i18n.t('action_name.init_env'), 'stop_env': i18n.t('action_name.stop_env'),
            'restart_env': i18n.t('action_name.restart_env'), 'open_site': i18n.t('action_name.open_site'),
            'start_nginx': i18n.t('action_name.start_nginx'), 'stop_nginx': i18n.t('action_name.stop_nginx'), 'restart_nginx': i18n.t('action_name.restart_nginx'), 'reload_nginx': i18n.t('action_name.reload_nginx'),
            'start_php': i18n.t('action_name.start_php'), 'stop_php': i18n.t('action_name.stop_php'), 'restart_php': i18n.t('action_name.restart_php'),
            'start_mysql': i18n.t('action_name.start_mysql'), 'stop_mysql': i18n.t('action_name.stop_mysql'), 'restart_mysql': i18n.t('action_name.restart_mysql'),
            'reset_config': i18n.t('action_name.reset_config')
        };
        var name = actionNames[data.action] || escHtml(data.action);
        // 使用格式化 key，避免英文单词粘连
        var msg = escHtml(i18n.t(data.success ? 'action.result_success' : 'action.result_failed', { name: name }));
        // 优先显示后端 message，转义后再拼接；翻译已知后端消息
        var translatedMsg = i18n.translateBackendMessage(data.message);
        if (data.message && data.message !== '执行中...' && data.message !== i18n.t('backend.执行中...') && data.message !== i18n.t('btn.initting')) msg += ' - ' + escHtml(translatedMsg);
        if (data.duration_ms) msg += ' (' + escHtml(String(data.duration_ms)) + 'ms)';
        if (!data.success) {
            // 使用 i18n 格式化日志链接，避免中文全角括号在英文环境显示
            var logLinks = i18n.t('action.log_links', {
                runtime: '<a class="log-link" data-goto-log="runtime" style="color:#2563eb;text-decoration:underline;cursor:pointer">' + escHtml(i18n.t('action.runtime_log')) + '</a>',
                action: '<a class="log-link" data-goto-log="action" style="color:#2563eb;text-decoration:underline;cursor:pointer">' + escHtml(i18n.t('action.action_log')) + '</a>'
            });
            msg += logLinks;
        }
        showFlash(msg, data.success ? 'success' : 'error', { raw: true });
    }

    // --- Autostart ---
    // 公共函数：根据 state 和详情更新自启动 UI 状态
    function updateAutostartUI(state, info) {
        var statusEl = qs('[data-role="autostart-status"]');
        var detailEl = qs('[data-role="autostart-detail"]');
        info = info || {};

        if (statusEl) {
            if (state === 'enabled') {
                statusEl.textContent = i18n.t('settings.autostart_enabled');
                statusEl.className = 'autostart-status badge-running';
            } else if (state === 'disabled') {
                statusEl.textContent = i18n.t('settings.autostart_disabled');
                statusEl.className = 'autostart-status badge-stopped';
            } else if (state === 'not_found') {
                statusEl.textContent = i18n.t('settings.autostart_not_found');
                statusEl.className = 'autostart-status badge-stopped';
            } else if (state === 'invalid') {
                statusEl.textContent = i18n.t('settings.autostart_invalid');
                statusEl.className = 'autostart-status badge-error';
            } else if (state === 'timeout') {
                statusEl.textContent = i18n.t('settings.autostart_timeout');
                statusEl.className = 'autostart-status badge-error';
            } else if (state === 'conflict') {
                statusEl.textContent = i18n.t('settings.autostart_conflict');
                statusEl.className = 'autostart-status badge-error';
            } else {
                statusEl.textContent = i18n.t('settings.autostart_detect_failed');
                statusEl.className = 'autostart-status badge-error';
            }
        }

        if (detailEl) {
            var html = '';
            if (info.warning) html += '<div class="msg-error" style="margin-top:4px;font-size:12px">' + escHtml(info.warning) + '</div>';
            if (info.error) html += '<div class="msg-error" style="margin-top:4px;font-size:12px">' + escHtml(i18n.t('settings.autostart_detect_error')) + escHtml(info.error) + '</div>';
            detailEl.innerHTML = html;
            detailEl.style.display = html ? 'block' : 'none';
        }

        lastAutostartState = state;
        updateAutostartGate();
    }

    function doAutostartStatus() {
        var statusEl = qs('[data-role="autostart-status"]');
        var detailEl = qs('[data-role="autostart-detail"]');
        if (statusEl) statusEl.textContent = i18n.t('settings.autostart_detecting');
        if (detailEl) { detailEl.innerHTML = ''; detailEl.style.display = 'none'; }

        var xhr = new XMLHttpRequest();
        xhr.open('GET', '/api/autostart/status', true);
        xhr.timeout = 15000;
        xhr.onload = function () {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    var state = data.state || 'error';
                    updateAutostartUI(state, data);
                } catch (e) {
                    if (statusEl) { statusEl.textContent = i18n.t('settings.autostart_detect_failed'); statusEl.className = 'autostart-status badge-error'; }
                }
            } else {
                if (statusEl) { statusEl.textContent = i18n.t('settings.autostart_detect_failed'); statusEl.className = 'autostart-status badge-error'; }
            }
        };
        xhr.onerror = function () { if (statusEl) { statusEl.textContent = i18n.t('settings.autostart_network_error'); statusEl.className = 'autostart-status badge-error'; } };
        xhr.ontimeout = function () { if (statusEl) { statusEl.textContent = i18n.t('settings.autostart_timeout'); statusEl.className = 'autostart-status badge-error'; } };
        xhr.send();
    }

    function handleAutostartResponse(action, data) {
        // 改用 Flash Toast 提示开机自启动操作结果；动态文本先 escHtml 转义
        var msg = escHtml(i18n.translateBackendMessage(data.message) || (data.success ? i18n.t('action.execute_complete') : i18n.t('action.execute_failed')));
        if (!data.success) {
            if (data.message && (data.message.indexOf('管理员权限') >= 0 || data.message.indexOf('Administrator') >= 0)) {
                msg += i18n.t('action.autostart_admin');
            }
            // 使用 i18n 格式化日志链接
            var logLinks = i18n.t('action.log_links', {
                runtime: '<a class="log-link" data-goto-log="runtime" style="color:#2563eb;text-decoration:underline;cursor:pointer">' + escHtml(i18n.t('action.runtime_log')) + '</a>',
                action: '<a class="log-link" data-goto-log="action" style="color:#2563eb;text-decoration:underline;cursor:pointer">' + escHtml(i18n.t('action.action_log')) + '</a>'
            });
            msg += logLinks;
        }
        showFlash(msg, data.success ? 'success' : 'error', { raw: true });

        if (data.success && action === 'install_autostart') {
            // 安装成功：优先使用响应中的 autostart_status 更新 UI，否则乐观更新
            if (data.autostart_status && data.autostart_status.state) {
                updateAutostartUI(data.autostart_status.state, data.autostart_status);
            } else {
                // 乐观更新 UI 为 enabled
                var statusEl = qs('[data-role="autostart-status"]');
                if (statusEl) {
                    statusEl.textContent = i18n.t('settings.autostart_enabled');
                    statusEl.className = 'autostart-status badge-running';
                }
                lastAutostartState = 'enabled';
                updateAutostartGate();
            }
            // 延迟 2 秒后刷新真实状态
            setTimeout(doAutostartStatus, 2000);
        } else {
            doAutostartStatus();
        }
    }

    function showAutostartResult(success, message) {
        // 改用 Flash Toast 提示开机自启动操作结果
        showFlash(message, success ? 'success' : 'error');
    }

    // --- Log view ---
    function fetchLog(type) {
        currentLogTab = type;
        var pre = qs('[data-role="log-pre"]');
        if (!pre) return;
        pre.textContent = i18n.t('log.loading');

        qsa('.log-tab').forEach(function (tab) {
            // IE11 兼容：使用 WNMPCompat.toggleClass 替代 classList.toggle 第二参数
            WNMPCompat.toggleClass(tab, 'active', tab.getAttribute('data-log-tab') === type);
        });

        var apiUrl = type === 'action' ? '/api/logs/action?lines=200' : '/api/logs/runtime?lines=200';
        var xhr = new XMLHttpRequest();
        xhr.open('GET', apiUrl, true);
        xhr.timeout = 5000;
        xhr.onload = function () {
            if (xhr.status === 200) {
                try {
                    var data = JSON.parse(xhr.responseText);
                    if (data.success) {
                        pre.textContent = data.content || i18n.t('log.empty');
                    } else {
                        pre.textContent = data.message || i18n.t('log.unavailable');
                    }
                } catch (e) { pre.textContent = i18n.t('log.parse_error'); }
            } else { pre.textContent = i18n.t('log.fetch_error') + xhr.status; }
        };
        xhr.onerror = function () { pre.textContent = i18n.t('log.network_error'); };
        xhr.ontimeout = function () { pre.textContent = i18n.t('log.timeout'); };
        xhr.send();
    }

    // --- Event delegation ---
    document.addEventListener('click', function (e) {
        // 语言切换按钮
        var langBtn = closestTarget(e, '.lang-switch-btn');
        if (langBtn) {
            var lang = langBtn.getAttribute('data-lang');
            if (lang && typeof i18n !== 'undefined' && i18n.setLang) {
                i18n.setLang(lang);
                // 语言切换后清空渲染签名缓存，强制重渲染首页卡片
                lastDashboardSignature = '';
                // 语言切换后强制重渲染环境信息模块
                envInfoSignature = '';
                envInfoCache = null;
                // 切换语言后刷新动态渲染的文案
                if (lastStatusData && lastStatusData.initialized) {
                    renderDashboard(lastStatusData);
                } else if (lastStatusData && !lastStatusData.initialized) {
                    // 未初始化状态：重新渲染初始化视图
                    renderInitView(lastStatusData);
                }
                updateTopbar(currentNav, lastStatusData ? lastStatusData.overall : null);
                // 语言切换时不重新加载配置文件和日志，避免覆盖用户未保存的编辑内容
                // 配置文件内容、日志内容本身不需要翻译
                // 重新刷新设置页动态状态（只读接口，不触发写操作）
                if (currentNav === 'settings') doAutostartStatus();
                // 语言切换后强制刷新环境信息模块
                if (currentNav === 'overview' && currentInitialized) {
                    loadEnvironmentInfo(true);
                }
            }
            return;
        }

        // Sidebar navigation
        var navItem = closestTarget(e, '.nav-item');
        if (navItem) {
            e.preventDefault();
            var nav = navItem.getAttribute('data-nav');
            if (nav === 'overview') {
                if (!firstLoadDone) showLoadingView();
                else if (!currentInitialized) { showInitView(); renderInitView(lastStatusData || { message: i18n.t('init.message') }); }
                else { showDashboardView(); if (lastStatusData) renderDashboard(lastStatusData); }
            } else if (nav === 'logs') { showLogView(); }
            else if (nav === 'settings') { showSettingsView(); }
            else if (nav === 'about') { showAboutView(); }
            return;
        }

        // Action buttons
        var actionBtn = closestTarget(e, 'button[data-action]');
        if (actionBtn && !actionBtn.disabled) {
            var action = actionBtn.getAttribute('data-action');
            // 重置配置：二次确认，取消不执行
            if (action === 'reset_config') {
                if (!confirm(i18n.t('confirm.reset_config'))) {
                    return;
                }
            }
            if (action) doAction(action);
            return;
        }

        // Autostart refresh button (GET /api/autostart/status, not via action lock)
        var autostartRefreshBtn = closestTarget(e, '[data-role="btn-autostart-refresh"]');
        if (autostartRefreshBtn && !autostartRefreshBtn.disabled) {
            doAutostartStatus();
            return;
        }

        // Version buttons
        var versionBtn = closestTarget(e, '[data-role="btn-version"]');
        if (versionBtn && !versionBtn.disabled) {
            var component = versionBtn.getAttribute('data-version-component');
            if (component) queryVersion(component);
            return;
        }

        // Config editor tabs
        var configTab = closestTarget(e, '.config-tab');
        if (configTab) {
            var configName = configTab.getAttribute('data-config-name');
            if (configName) loadConfigFile(configName);
            return;
        }

        // Config save
        if (closestTarget(e, '[data-role="btn-config-save"]')) {
            saveConfigFile();
            return;
        }

        // Config reload
        if (closestTarget(e, '[data-role="btn-config-reload"]')) {
            loadConfigFile(currentConfigName);
            return;
        }

        // MySQL password: copy (modal)
        if (closestTarget(e, '[data-role="btn-copy-pwd-modal"]')) {
            var pwdValueEl = qs('[data-role="mysql-pwd-value-modal"]');
            if (pwdValueEl) {
                var text = pwdValueEl.textContent;
                // 密码已清空（用户已隐藏），不再复制
                if (!text) {
                    showFlash(i18n.t('toast.pwd_hidden'), 'warning');
                    return;
                }
                try {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        navigator.clipboard.writeText(text);
                    } else {
                        var ta = document.createElement('textarea');
                        ta.value = text;
                        ta.style.position = 'fixed';
                        ta.style.left = '-9999px';
                        document.body.appendChild(ta);
                        ta.select();
                        document.execCommand('copy');
                        document.body.removeChild(ta);
                    }
                    showFlash(i18n.t('toast.copied'), 'success');
                } catch (e2) {
                    showFlash(i18n.t('toast.copy_failed'), 'error');
                }
            }
            return;
        }

        // MySQL password: hide (modal) — 清空 DOM 中密码文本，防止残留
        if (closestTarget(e, '[data-role="btn-hide-pwd-modal"]')) {
            mysqlPasswordHidden = true;
            var modal = qs('[data-role="mysql-password-modal"]');
            var pwdVal = qs('[data-role="mysql-pwd-value-modal"]');
            if (pwdVal) pwdVal.textContent = ''; // 清空密码，不留 DOM 残留
            if (modal) { modal.style.display = 'none'; modal.classList.remove('is-visible'); }
            return;
        }

        // Log links
        var logLink = closestTarget(e, '[data-goto-log]');
        if (logLink) {
            e.preventDefault();
            showLogView();
            fetchLog(logLink.getAttribute('data-goto-log'));
            return;
        }

        // Log tab switching
        var logTab = closestTarget(e, '.log-tab');
        if (logTab) {
            fetchLog(logTab.getAttribute('data-log-tab'));
            return;
        }

        // Refresh log
        if (closestTarget(e, '[data-role="btn-refresh-log"]')) {
            fetchLog(currentLogTab);
            return;
        }

        // Retry
        if (closestTarget(e, '[data-role="btn-retry"]')) {
            showLoadingView();
            refreshStatus();
            return;
        }

        // 环境信息模块按钮：编辑配置 / 打开目录
        var envActionBtn = closestTarget(e, '[data-env-action]');
        if (envActionBtn) {
            var envActionType = envActionBtn.getAttribute('data-env-action');
            if (envActionType === 'edit_config') {
                var editKey = envActionBtn.getAttribute('data-edit-key');
                if (editKey) {
                    // 跳转到设置页配置编辑，加载对应配置文件
                    currentConfigName = editKey;
                    configContentLoaded = '';  // 清空缓存，强制重新加载
                    showSettingsView();
                    loadConfigFile(editKey);
                }
            } else if (envActionType === 'open_dir') {
                var openKey = envActionBtn.getAttribute('data-open-key');
                if (openKey) {
                    var openXhr = new XMLHttpRequest();
                    openXhr.open('POST', '/api/open-directory', true);
                    openXhr.setRequestHeader('Content-Type', 'application/json');
                    openXhr.timeout = 8000;
                    openXhr.onload = function () {
                        if (openXhr.status === 200) {
                            try {
                                var result = JSON.parse(openXhr.responseText);
                                if (result.success) {
                                    showFlash(i18n.t('env_info.dir_opened'), 'success');
                                } else {
                                    showFlash(result.message || i18n.t('env_info.dir_open_failed'), 'warning');
                                }
                            } catch (e2) {
                                showFlash(i18n.t('env_info.dir_open_failed'), 'error');
                            }
                        } else {
                            showFlash(i18n.t('env_info.dir_open_failed'), 'error');
                        }
                    };
                    openXhr.onerror = function () {
                        showFlash(i18n.t('env_info.dir_open_failed'), 'error');
                    };
                    openXhr.ontimeout = function () {
                        showFlash(i18n.t('env_info.dir_open_failed'), 'error');
                    };
                    openXhr.send(JSON.stringify({ open_key: openKey }));
                }
            }
            return;
        }

        // Error view log links
        if (closestTarget(e, '[data-role="link-runtime-log"]')) {
            e.preventDefault();
            showLogView();
            fetchLog('runtime');
            return;
        }
        if (closestTarget(e, '[data-role="link-action-log"]')) {
            e.preventDefault();
            showLogView();
            fetchLog('action');
            return;
        }
    });

    // --- Sidebar version info (from /api/panel-version) ---
    var sidebarVersionEl = qs('[data-role="sidebar-version"]');
    if (sidebarVersionEl) {
        // 默认显示，版本号加载后覆盖
        sidebarVersionEl.textContent = i18n.t('sidebar.panel') + 'v--';
        var verXhr = new XMLHttpRequest();
        verXhr.open('GET', '/api/panel-version', true);
        verXhr.timeout = 5000;
        verXhr.onload = function () {
            if (verXhr.status === 200) {
                try {
                    var verData = JSON.parse(verXhr.responseText);
                    if (verData.success && verData.panel_version) {
                        sidebarVersionEl.textContent = i18n.t('sidebar.panel') + 'v' + verData.panel_version;
                    }
                } catch (e) {}
            }
        };
        verXhr.onerror = function () {};
        verXhr.ontimeout = function () {};
        verXhr.send();
    }

    // --- Init ---
    // 应用 i18n 到所有 data-i18n 标记的 DOM 元素
    if (typeof i18n !== 'undefined' && i18n.applyI18n) i18n.applyI18n();

    try { clientId = sessionStorage.getItem('wnmp_client_id'); } catch (e) {}

    refreshStatus();
    statusTimer = setInterval(refreshStatus, 3000);
    initHeartbeat();

})();
