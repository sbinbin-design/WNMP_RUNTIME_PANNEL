// -*- coding: utf-8 -*-
// WNMP Panel IE11 兼容层 — 纯 ES5，不引入任何第三方库
// 提供 Element.prototype.matches / closest、Object.assign 的 polyfill，
// 并暴露 window.WNMPCompat 工具集供 app.js / i18n.js 使用。

(function () {
    'use strict';

    // ---- Element.prototype.matches polyfill ----
    if (typeof Element !== 'undefined' && !Element.prototype.matches) {
        Element.prototype.matches =
            Element.prototype.msMatchesSelector ||
            Element.prototype.webkitMatchesSelector ||
            function (selector) {
                var el = this;
                var doc = (el.document || el.ownerDocument);
                if (!doc) return false;
                var elems = doc.querySelectorAll(selector);
                for (var i = 0; i < elems.length; i++) {
                    if (elems[i] === el) return true;
                }
                return false;
            };
    }

    // ---- Element.prototype.closest polyfill ----
    if (typeof Element !== 'undefined' && !Element.prototype.closest) {
        Element.prototype.closest = function (selector) {
            var el = this;
            while (el && el.nodeType === 1) {
                if (el.matches(selector)) return el;
                el = el.parentElement;
            }
            return null;
        };
    }

    // ---- Object.assign polyfill ----
    if (typeof Object.assign !== 'function') {
        Object.assign = function (target) {
            if (target == null) {
                throw new TypeError('Cannot convert undefined or null to object');
            }
            var to = Object(target);
            for (var i = 1; i < arguments.length; i++) {
                var nextSource = arguments[i];
                if (nextSource != null) {
                    for (var key in nextSource) {
                        if (Object.prototype.hasOwnProperty.call(nextSource, key)) {
                            to[key] = nextSource[key];
                        }
                    }
                }
            }
            return to;
        };
    }

    // ---- WNMPCompat 工具集 ----

    /**
     * closest(target, selector) — 兼容文本节点与无原生 closest 的浏览器
     * 如果 target 是文本节点(nodeType===3)，先取 parentNode；
     * 然后用 matches/msMatchesSelector 逐级 parentElement 向上查找。
     */
    function closest(target, selector) {
        if (!target) return null;
        // 文本节点兼容：IE 点击事件 e.target 可能是文本节点
        var node = target;
        if (node.nodeType === 3) {
            node = node.parentNode;
        }
        if (!node || node.nodeType !== 1) return null;
        // 优先使用原生 closest（若 polyfill 已生效也可走此分支）
        if (typeof node.closest === 'function') {
            return node.closest(selector);
        }
        // fallback：手动逐级向上查找
        while (node && node.nodeType === 1) {
            var matches = node.matches || node.msMatchesSelector;
            if (matches && matches.call(node, selector)) return node;
            node = node.parentElement;
        }
        return null;
    }

    /**
     * toggleClass(el, className, enabled)
     * 不依赖 classList.toggle 第二个参数；enabled 为 true 时 add，为 false 时 remove。
     */
    function toggleClass(el, className, enabled) {
        if (!el) return;
        if (enabled) {
            if (!el.classList.contains(className)) el.classList.add(className);
        } else {
            if (el.classList.contains(className)) el.classList.remove(className);
        }
    }

    /**
     * assign(target, ...sources) — Object.assign 的显式包装
     * 优先使用原生（或上面已安装的 polyfill），确保行为一致。
     */
    function assign(target) {
        return Object.assign.apply(Object, arguments);
    }

    /**
     * toArray(list) — 将类数组对象转为真正的数组
     * 兼容 IE11 不支持 [].slice.call(NodeList) 的场景
     */
    function toArray(list) {
        if (!list) return [];
        // IE11 下 NodeList 不支持 slice，手动遍历
        if (Array.isArray(list)) return list;
        var result = [];
        try {
            result = Array.prototype.slice.call(list);
        } catch (e) {
            for (var i = 0; i < list.length; i++) {
                result.push(list[i]);
            }
        }
        return result;
    }

    // ---- 暴露到全局 ----
    window.WNMPCompat = {
        closest: closest,
        toggleClass: toggleClass,
        assign: assign,
        toArray: toArray
    };
})();
