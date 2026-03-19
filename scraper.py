#!/usr/bin/env python3
"""
北京二手房监控 - 数据采集脚本 v3（反检测增强版）

核心改进（基于 2026 年反检测最佳实践）：
  1. 使用系统 Chrome（channel="chrome"）而非 Playwright Chromium，
     解决 TLS 指纹（JA3/JA4）不匹配的根本问题
  2. Canvas / WebGL / AudioContext 指纹混淆
  3. 请求头清理，移除自动化特征
  4. 真实人类行为模拟（带步数鼠标、渐进滚动）
  5. Cookie 持久化跨运行复用

降级策略：
  1️⃣ Chrome 采集链家
  2️⃣ Chrome 采集贝壳
  3️⃣ 沿用昨日数据
"""

import json
import os
import re
import sys
import time
import random
import math
from datetime import datetime, timedelta
from pathlib import Path

# ============================================================
# 配置区域
# ============================================================

COMMUNITIES = {
    "利泽西园": {
        "lianjia_id": "1111027374591",
        "district": "wangjing",
        "min_area": 90,
        "max_price": 550,
        "layout_filter": ["2室1厅", "2室2厅", "3室1厅", "3室2厅"],
    },
    "望馨花园": {
        "lianjia_id": "1111027375404",
        "district": "wangjing",
        "min_area": 80,
        "max_price": 550,
        "layout_filter": ["2室1厅", "2室2厅", "3室1厅", "3室2厅"],
    },
    "澳洲康都": {
        "lianjia_id": "1111027375258",
        "district": "wangjing",
        "min_area": 80,
        "max_price": 550,
        "layout_filter": ["2室1厅", "2室2厅", "3室1厅", "3室2厅"],
    },
    "城建集团家属楼": {
        "lianjia_id": "1111027382753",
        "district": "lishuiqiao",
        "min_area": 0,
        "max_price": 99999,
        "layout_filter": ["1室1厅", "1室0厅", "2室1厅", "2室2厅"],
    },
}

NEARBY_PRICE_TOLERANCE = 100
NEARBY_AREA_TOLERANCE = 10
COOKIE_FILE = Path("data_history/.browser_cookies.json")

# ============================================================
# 反检测：指纹混淆脚本
# ============================================================

STEALTH_INIT_SCRIPT = """
// ===== 1. 基础：删除 webdriver 标识 =====
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
delete navigator.__proto__.webdriver;

// ===== 2. 伪造 navigator.plugins =====
Object.defineProperty(navigator, 'plugins', {
    get: () => {
        const plugins = [
            { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format', length: 1 },
            { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '', length: 1 },
            { name: 'Native Client', filename: 'internal-nacl-plugin', description: '', length: 2 },
        ];
        plugins.length = 3;
        return plugins;
    }
});

// ===== 3. 伪造 navigator.mimeTypes =====
Object.defineProperty(navigator, 'mimeTypes', {
    get: () => {
        const mimeTypes = [
            { type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format' },
            { type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' },
        ];
        mimeTypes.length = 2;
        return mimeTypes;
    }
});

// ===== 4. 伪造 chrome 对象 =====
window.chrome = {
    runtime: {
        onInstalled: { addListener: () => {} },
        onMessage: { addListener: () => {} },
        sendMessage: () => {},
        connect: () => ({ onMessage: { addListener: () => {} }, postMessage: () => {} }),
        PlatformOs: { MAC: 'mac', WIN: 'win', ANDROID: 'android', CROS: 'cros', LINUX: 'linux', OPENBSD: 'openbsd' },
    },
    app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' } },
    csi: function() {},
    loadTimes: function() {},
};

// ===== 5. 伪造 Permissions API =====
const originalQuery = window.navigator.permissions?.query;
if (originalQuery) {
    window.navigator.permissions.query = (parameters) => {
        if (parameters.name === 'notifications') {
            return Promise.resolve({ state: 'prompt' });
        }
        return originalQuery.call(window.navigator.permissions, parameters);
    };
}

// ===== 6. 伪造 languages =====
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
Object.defineProperty(navigator, 'language', { get: () => 'zh-CN' });

// ===== 7. Canvas 指纹混淆 =====
const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
HTMLCanvasElement.prototype.toDataURL = function(type) {
    if (this.width > 16 && this.height > 16) {
        const ctx = this.getContext('2d');
        if (ctx) {
            try {
                const imageData = ctx.getImageData(0, 0, Math.min(this.width, 4), Math.min(this.height, 4));
                for (let i = 0; i < imageData.data.length; i += 4) {
                    imageData.data[i] = imageData.data[i] ^ 1;
                }
                ctx.putImageData(imageData, 0, 0);
            } catch(e) {}
        }
    }
    return originalToDataURL.apply(this, arguments);
};

// ===== 8. WebGL 指纹混淆 =====
const getParameterProxy = new Proxy(WebGLRenderingContext.prototype.getParameter, {
    apply: function(target, thisArg, args) {
        const param = args[0];
        // UNMASKED_VENDOR_WEBGL
        if (param === 0x9245) return 'Google Inc. (NVIDIA)';
        // UNMASKED_RENDERER_WEBGL
        if (param === 0x9246) return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Ti Direct3D11 vs_5_0 ps_5_0, D3D11)';
        return Reflect.apply(target, thisArg, args);
    }
});
WebGLRenderingContext.prototype.getParameter = getParameterProxy;
if (typeof WebGL2RenderingContext !== 'undefined') {
    WebGL2RenderingContext.prototype.getParameter = getParameterProxy;
}

// ===== 9. AudioContext 指纹混淆 =====
if (typeof AnalyserNode !== 'undefined') {
    const originalGetFloatFrequencyData = AnalyserNode.prototype.getFloatFrequencyData;
    AnalyserNode.prototype.getFloatFrequencyData = function(array) {
        originalGetFloatFrequencyData.call(this, array);
        for (let i = 0; i < array.length; i++) {
            array[i] += (Math.random() - 0.5) * 0.0001;
        }
    };
}

// ===== 10. 隐藏 Notification.permission =====
if (typeof Notification !== 'undefined') {
    Object.defineProperty(Notification, 'permission', { get: () => 'default' });
}

// ===== 11. 隐藏 CDP 检测 =====
// 删除 Runtime.enable 暴露的属性
if (window.cdc_adoQpoasnfa76pfcZLmcfl_Array) {
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
}
if (window.cdc_adoQpoasnfa76pfcZLmcfl_Promise) {
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
}
if (window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol) {
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
}
// 清理可能暴露 CDP 的属性
for (const key of Object.keys(window)) {
    if (key.match(/^cdc_/)) {
        delete window[key];
    }
}
"""

# ============================================================
# 浏览器创建与反检测
# ============================================================


def create_browser_context(playwright):
    """
    创建高度伪装的浏览器上下文。
    核心：用 channel="chrome" 启动系统 Chrome（而非 Playwright 的 Chromium），
    这样 TLS 指纹（JA3/JA4）与真实 Chrome 一致。
    """
    # 尝试导入 stealth 插件
    try:
        from playwright_stealth import stealth_sync
        has_stealth = True
    except ImportError:
        has_stealth = False
        print("  ℹ️ playwright-stealth 未安装，使用内置反检测")

    # 优先使用系统 Chrome（TLS 指纹一致），回退到 Chromium
    launch_kwargs = dict(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-dev-shm-usage",
            "--disable-accelerated-2d-canvas",
            "--disable-gpu-sandbox",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--window-size=1920,1080",
            "--lang=zh-CN",
        ],
    )

    try:
        browser = playwright.chromium.launch(channel="chrome", **launch_kwargs)
        print("  ✅ 使用系统 Chrome（TLS 指纹一致）")
    except Exception as e:
        print(f"  ⚠️ 系统 Chrome 不可用 ({e})，回退到 Chromium")
        browser = playwright.chromium.launch(**launch_kwargs)

    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        screen={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        color_scheme="light",
        has_touch=False,
        is_mobile=False,
        extra_http_headers={
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "sec-ch-ua": '"Chromium";v="131", "Google Chrome";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Upgrade-Insecure-Requests": "1",
        },
    )

    # 注入反检测脚本
    context.add_init_script(STEALTH_INIT_SCRIPT)

    # 加载持久化 Cookies（如果有）
    if COOKIE_FILE.exists():
        try:
            cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
            if cookies:
                context.add_cookies(cookies)
                print(f"  🍪 已加载 {len(cookies)} 个持久化 Cookie")
        except Exception:
            pass

    return browser, context, has_stealth


def save_cookies(context):
    """保存 Cookies 供下次运行复用"""
    try:
        cookies = context.cookies()
        COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOKIE_FILE.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  🍪 已保存 {len(cookies)} 个 Cookie")
    except Exception as e:
        print(f"  ⚠️ Cookie 保存失败: {e}")


def setup_request_interception(page):
    """拦截并清理请求头，移除自动化特征"""
    def handle_route(route):
        headers = route.request.headers.copy()
        # 移除可能暴露自动化的头部
        for key in list(headers.keys()):
            if key.lower() in ("x-playwright", "x-devtools"):
                del headers[key]
        # 确保 document 请求有正确的 Accept
        if route.request.resource_type == "document":
            headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
        route.continue_(headers=headers)

    page.route("**/*", handle_route)


# ============================================================
# 人类行为模拟
# ============================================================


def random_delay(min_ms=1000, max_ms=3000):
    """模拟人类操作间隔"""
    time.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


def human_mouse_move(page, target_x=None, target_y=None):
    """模拟真实鼠标移动（带曲线路径和随机步数）"""
    vw = page.viewport_size["width"]
    vh = page.viewport_size["height"]
    if target_x is None:
        target_x = random.randint(100, vw - 100)
    if target_y is None:
        target_y = random.randint(100, vh - 100)
    steps = random.randint(10, 30)
    page.mouse.move(target_x, target_y, steps=steps)
    time.sleep(random.uniform(0.05, 0.2))


def human_scroll(page, direction="down", distance=None):
    """模拟人类渐进式滚动"""
    if distance is None:
        distance = random.randint(300, 800)
    scrolled = 0
    while scrolled < distance:
        delta = random.randint(60, 150)
        if direction == "up":
            delta = -delta
        page.mouse.wheel(0, delta)
        scrolled += abs(delta)
        time.sleep(random.uniform(0.05, 0.2))
    time.sleep(random.uniform(0.3, 0.8))


def human_warmup(page):
    """模拟真实用户的浏览预热路径"""
    print("  📡 预热：模拟正常用户浏览...")
    try:
        # 1. 访问首页
        page.goto("https://bj.lianjia.com/", wait_until="domcontentloaded", timeout=25000)
        random_delay(2000, 4000)

        # 2. 随机鼠标移动（3-5次）
        for _ in range(random.randint(3, 5)):
            human_mouse_move(page)
            time.sleep(random.uniform(0.1, 0.4))

        # 3. 渐进式滚动
        human_scroll(page, "down", random.randint(300, 600))
        random_delay(1000, 2000)

        # 4. 点击进入二手房频道
        try:
            ershoufang_link = page.query_selector('a[href*="ershoufang"]')
            if ershoufang_link:
                # 先移动鼠标到链接位置
                box = ershoufang_link.bounding_box()
                if box:
                    human_mouse_move(page, int(box["x"] + box["width"] / 2), int(box["y"] + box["height"] / 2))
                    time.sleep(random.uniform(0.2, 0.5))
                ershoufang_link.click()
            else:
                page.goto("https://bj.lianjia.com/ershoufang/", wait_until="domcontentloaded", timeout=25000)
        except Exception:
            page.goto("https://bj.lianjia.com/ershoufang/", wait_until="domcontentloaded", timeout=25000)

        random_delay(2000, 4000)

        # 5. 在二手房页面也做一些浏览动作
        human_scroll(page, "down", random.randint(200, 400))
        random_delay(1000, 2000)

        # 6. 检查是否正常加载
        title = page.title()
        content_len = len(page.content())
        if "CAPTCHA" not in title and "验证" not in title and content_len > 5000:
            print("  ✅ 预热成功，会话正常")
            return True
        else:
            print(f"  ⚠️ 预热时可能遇到拦截 (title={title[:30]}, content_len={content_len})")
            # 等一等再继续
            random_delay(5000, 8000)
            return False

    except Exception as e:
        print(f"  ⚠️ 预热失败: {e}，继续尝试采集...")
        return False


# ============================================================
# 浏览器采集核心
# ============================================================


def check_captcha(page):
    """检测页面是否是验证码页面"""
    try:
        title = page.title() or ""
        url = page.url or ""
        content_snippet = page.evaluate("document.body?.innerText?.substring(0, 500) || ''") or ""
        indicators = ["CAPTCHA", "captcha", "验证", "verify", "check", "安全验证"]
        full_text = title + url + content_snippet
        return any(ind in full_text for ind in indicators)
    except Exception:
        return False


def wait_for_challenge(page, timeout_sec=15):
    """等待可能的 JS 挑战完成（如 Cloudflare 等）"""
    for i in range(timeout_sec):
        if not check_captcha(page):
            return True
        time.sleep(1)
    return False


def scrape_community_page(page, community_name, community_id, site="lianjia"):
    """
    用浏览器采集小区房源页面。
    site: "lianjia" 或 "ke"
    """
    if site == "lianjia":
        base_url = f"https://bj.lianjia.com/ershoufang/c{community_id}"
        site_label = "链家"
    else:
        base_url = f"https://bj.ke.com/ershoufang/c{community_id}"
        site_label = "贝壳"

    print(f"\n📍 [{site_label}] 正在采集: {community_name}")

    all_listings = []
    max_pages = 3

    for page_num in range(1, max_pages + 1):
        page_url = f"{base_url}/pg{page_num}/"
        print(f"  📄 第{page_num}页: {page_url}")

        try:
            # 导航前随机鼠标移动
            human_mouse_move(page)

            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            random_delay(2000, 4000)

            # 等待可能的 JS 挑战
            if check_captcha(page):
                print(f"  ⏳ 检测到挑战页面，等待...")
                if not wait_for_challenge(page, 15):
                    print(f"  ❌ 挑战未通过，停止采集")
                    break

            # 模拟一些人类行为
            human_scroll(page, "down", random.randint(200, 500))
            random_delay(500, 1000)

            # 等待房源列表出现
            try:
                page.wait_for_selector(
                    ".sellListContent li.clear, ul.sellListContent li, .list-content li",
                    timeout=8000
                )
            except Exception:
                content = page.content()
                if "没有找到" in content or "暂无" in content:
                    print(f"  ℹ️ 该小区暂无在售房源")
                    break
                elif len(content) < 3000:
                    print(f"  ⚠️ 页面内容过少({len(content)} bytes)，可能被拦截")
                    break
                else:
                    print(f"  ℹ️ 未找到标准房源选择器，尝试解析...")

            # 用 JS 解析 DOM 提取房源数据
            listings_data = page.evaluate("""
            () => {
                const results = [];
                const items = document.querySelectorAll(
                    '.sellListContent li.clear, ul.sellListContent li[class*="LOGVIEW"], .list-content li'
                );

                items.forEach(item => {
                    try {
                        const listing = {};

                        // 标题和链接
                        const titleEl = item.querySelector('.title a, .lj-h3 a');
                        if (titleEl) {
                            listing.title = titleEl.textContent.trim();
                            listing.url = titleEl.href;
                            const idMatch = listing.url.match(/(\\d+)\\.html/);
                            if (idMatch) listing.lianjia_id = idMatch[1];
                        }

                        // 房屋信息
                        const infoEl = item.querySelector('.houseInfo, .address');
                        if (infoEl) {
                            const infoText = infoEl.textContent.trim();
                            listing.info_text = infoText;
                            const layoutMatch = infoText.match(/(\\d室\\d厅)/);
                            if (layoutMatch) listing.layout = layoutMatch[1];
                            const areaMatch = infoText.match(/([\\d.]+)平米/);
                            if (areaMatch) listing.area = parseFloat(areaMatch[1]);
                            const parts = infoText.split('|');
                            if (parts.length >= 3) listing.direction = parts[1].trim();
                        }

                        // 楼层位置
                        const posEl = item.querySelector('.positionInfo, .flood');
                        if (posEl) listing.floor = posEl.textContent.trim();

                        // 总价
                        const priceEl = item.querySelector('.totalPrice span, .price-det span');
                        if (priceEl) {
                            const price = parseFloat(priceEl.textContent.trim());
                            if (!isNaN(price)) listing.total_price = price;
                        }

                        // 单价
                        const unitEl = item.querySelector('.unitPrice span');
                        if (unitEl) {
                            const unitText = unitEl.textContent.trim();
                            const unitMatch = unitText.match(/([\\d,]+)/);
                            if (unitMatch) listing.unit_price = parseInt(unitMatch[1].replace(/,/g, ''));
                        }

                        // 关注/挂牌信息
                        const followEl = item.querySelector('.followInfo');
                        if (followEl) {
                            const followText = followEl.textContent.trim();
                            listing.follow_info = followText;
                            const dateMatch = followText.match(/(\\d{4}[.\\-/]\\d{1,2}[.\\-/]\\d{1,2})/);
                            if (dateMatch) listing.listing_date = dateMatch[1].replace(/\\./g, '-');
                        }

                        if (listing.total_price) results.push(listing);
                    } catch(e) {}
                });
                return results;
            }
            """)

            if not listings_data:
                print(f"  ℹ️ 第{page_num}页未解析到房源数据")
                # 如果第一页就没数据，不用翻页了
                if page_num == 1:
                    break
                continue

            for item in listings_data:
                item["community"] = community_name
                item["source"] = site_label
                all_listings.append(item)

            print(f"  ✅ 第{page_num}页获取 {len(listings_data)} 套")

            # 检查是否有下一页
            has_next = page.evaluate("""
            () => {
                const pageBox = document.querySelector('.page-box .page-data, .house-lst-page-box');
                if (pageBox) {
                    try {
                        const data = JSON.parse(pageBox.getAttribute('page-data') || '{}');
                        return data.curPage < data.totalPage;
                    } catch(e) {}
                }
                // 备用：检查"下一页"按钮
                const nextBtn = document.querySelector('.page-box a.next, a.aNxt');
                return nextBtn && !nextBtn.classList.contains('disabled');
            }
            """)

            if not has_next:
                break

            # 翻页间隔
            random_delay(3000, 6000)

        except Exception as e:
            print(f"  ❌ 采集异常: {e}")
            break

    print(f"  📊 [{site_label}] {community_name} 共采集 {len(all_listings)} 套")
    return all_listings


# ============================================================
# 通用：筛选 / 对比 / 格式化
# ============================================================


def filter_listings(listings, config):
    """按筛选条件过滤房源"""
    qualified = []
    nearby = []

    for listing in listings:
        area = listing.get("area", 0)
        price = listing.get("total_price", 0)
        layout = listing.get("layout", "")

        layout_ok = any(l in layout for l in config["layout_filter"]) if layout else True
        if not layout_ok:
            continue

        if area >= config["min_area"] and price <= config["max_price"]:
            qualified.append(listing)
        elif (
            area >= config["min_area"] - NEARBY_AREA_TOLERANCE
            and price <= config["max_price"] + NEARBY_PRICE_TOLERANCE
        ):
            listing["note"] = []
            if price > config["max_price"]:
                listing["note"].append(f"总价超出{int(price - config['max_price'])}万")
            if area < config["min_area"]:
                listing["note"].append(f"面积不足{config['min_area']}㎡")
            listing["note"] = "，".join(listing["note"])
            nearby.append(listing)

    return qualified, nearby


def compare_with_yesterday(today_data, yesterday_file):
    """与昨日数据对比，找出变化"""
    changes = {
        "new_listings": [],
        "removed_listings": [],
        "price_changes": [],
        "total_yesterday": 0,
        "total_today": 0,
    }

    if not os.path.exists(yesterday_file):
        print("  ℹ️ 没有昨日数据，跳过对比")
        return changes

    try:
        with open(yesterday_file, "r", encoding="utf-8") as f:
            yesterday_data = json.load(f)
    except Exception as e:
        print(f"  ⚠️ 读取昨日数据失败: {e}")
        return changes

    yesterday_map = {}
    for cname, cdata in yesterday_data.get("communities", {}).items():
        for listing in cdata.get("listings", []):
            lid = listing.get("id") or listing.get("lianjia_id", "")
            if lid:
                yesterday_map[lid] = listing
    changes["total_yesterday"] = yesterday_data.get("total_qualified", 0)

    today_map = {}
    for cname, cdata in today_data.get("communities", {}).items():
        for listing in cdata.get("listings", []):
            lid = listing.get("id") or listing.get("lianjia_id", "")
            if lid:
                today_map[lid] = listing
    changes["total_today"] = today_data.get("total_qualified", 0)

    for lid, listing in today_map.items():
        if lid not in yesterday_map:
            changes["new_listings"].append(listing)

    for lid, listing in yesterday_map.items():
        if lid not in today_map:
            changes["removed_listings"].append(listing)

    for lid in set(today_map.keys()) & set(yesterday_map.keys()):
        old_price = yesterday_map[lid].get("total_price", 0)
        new_price = today_map[lid].get("total_price", 0)
        if old_price != new_price and old_price > 0 and new_price > 0:
            changes["price_changes"].append({
                "listing": today_map[lid],
                "old_price": old_price,
                "new_price": new_price,
                "diff": new_price - old_price,
            })

    return changes


def build_listing_id(listing):
    """为房源生成一个稳定的ID"""
    if listing.get("lianjia_id"):
        return f"lj-{listing['lianjia_id']}"

    community = listing.get("community", "")
    area = listing.get("area", 0)
    price = listing.get("total_price", 0)

    prefix_map = {
        "利泽西园": "lzxy",
        "望馨花园": "wxxhy",
        "澳洲康都": "azkd",
        "城建集团家属楼": "cjjt",
    }
    prefix = prefix_map.get(community, "other")
    return f"{prefix}-{area}-{price}"


def format_listing_for_save(listing, idx):
    """格式化房源数据用于保存"""
    return {
        "id": build_listing_id(listing),
        "community": listing.get("community", ""),
        "layout": listing.get("layout", ""),
        "area": listing.get("area", 0),
        "direction": listing.get("direction", "-"),
        "unit_price": listing.get("unit_price", 0),
        "total_price": listing.get("total_price", 0),
        "floor": listing.get("floor", "-"),
        "age": listing.get("age", "-"),
        "register_date": listing.get("register_date", "-"),
        "listing_date": listing.get("listing_date", "-"),
    }


# ============================================================
# 主流程
# ============================================================


def main():
    print("=" * 60)
    print("🏠 北京二手房监控 - 数据采集 v3（反检测增强版）")
    print(f"📅 采集时间: {datetime.now().strftime('%Y年%m月%d日 %H:%M')}")
    print("=" * 60)

    # 导入 Playwright
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ 未安装 playwright，请运行: pip install playwright && playwright install chromium")
        sys.exit(1)

    data_dir = Path("data_history")
    data_dir.mkdir(exist_ok=True)

    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    today_file = data_dir / f"{today_str}.json"
    yesterday_file = data_dir / f"{yesterday_str}.json"

    all_data = {
        "date": today_str,
        "source": "",
        "collection_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_qualified": 0,
        "communities": {},
        "nearby_listings": [],
    }

    source_labels = set()

    with sync_playwright() as pw:
        print("\n🚀 启动浏览器...")
        browser, context, has_stealth = create_browser_context(pw)
        page = context.new_page()

        # 应用 stealth 补丁
        if has_stealth:
            from playwright_stealth import stealth_sync
            stealth_sync(page)
            print("  🛡️ Stealth 反检测插件已启用")

        # 设置请求拦截（清理自动化头部）
        setup_request_interception(page)

        # 预热
        warmup_ok = human_warmup(page)

        for community_name, config in COMMUNITIES.items():
            print(f"\n{'='*50}")
            print(f"🏘️ 开始采集: {community_name}")
            print(f"{'='*50}")

            community_id = config["lianjia_id"]
            listings = []

            # 第1级：链家
            listings = scrape_community_page(page, community_name, community_id, site="lianjia")
            if listings:
                source_labels.add("链家")
            else:
                # 第2级：贝壳
                print(f"  ⚡ 链家采集失败，尝试贝壳...")
                random_delay(3000, 5000)
                listings = scrape_community_page(page, community_name, community_id, site="ke")
                if listings:
                    source_labels.add("贝壳")

            if not listings:
                print(f"  ⚠️ {community_name} 所有渠道未获取到数据")

            # 过滤
            qualified, nearby = filter_listings(listings, config)
            formatted = [format_listing_for_save(l, i) for i, l in enumerate(qualified, 1)]

            filter_desc = f"≥{config['min_area']}㎡ | ≤{config['max_price']}万 | {'、'.join(config['layout_filter'])}"
            if config["max_price"] > 9999:
                filter_desc = f"{'、'.join(config['layout_filter'])}（不限面积和总价）"

            all_data["communities"][community_name] = {
                "filter": filter_desc,
                "count": len(formatted),
                "listings": formatted,
            }
            all_data["total_qualified"] += len(formatted)

            for nl in nearby:
                all_data["nearby_listings"].append({
                    "community": nl.get("community", ""),
                    "layout": nl.get("layout", ""),
                    "area": nl.get("area", 0),
                    "direction": nl.get("direction", "-"),
                    "unit_price": nl.get("unit_price", 0),
                    "total_price": nl.get("total_price", 0),
                    "floor": nl.get("floor", "-"),
                    "listing_date": nl.get("listing_date", "-"),
                    "note": nl.get("note", ""),
                })

            # 小区间随机间隔
            random_delay(4000, 8000)

        # 保存 Cookies 供下次运行
        save_cookies(context)

        # 关闭浏览器
        context.close()
        browser.close()

    # 设置来源标签
    all_data["source"] = "、".join(sorted(source_labels)) if source_labels else "采集失败"

    if not source_labels:
        all_data["collection_note"] = "浏览器采集均被拦截"
    else:
        all_data["collection_note"] = ""

    # 如果没采集到数据，沿用昨日
    if all_data["total_qualified"] == 0 and yesterday_file.exists():
        print("\n⚠️ 今日未采集到数据，尝试沿用昨日数据...")
        try:
            with open(yesterday_file, "r", encoding="utf-8") as f:
                yesterday_data = json.load(f)
            if yesterday_data.get("total_qualified", 0) > 0:
                all_data["communities"] = yesterday_data.get("communities", {})
                all_data["total_qualified"] = yesterday_data.get("total_qualified", 0)
                all_data["nearby_listings"] = yesterday_data.get("nearby_listings", [])
                all_data["collection_note"] = "今日采集失败，沿用昨日数据"
                print(f"  ✅ 已沿用昨日 {all_data['total_qualified']} 套数据")
            else:
                all_data["collection_note"] = "今日采集失败，昨日也无数据"
                print("  ⚠️ 昨日也无数据可沿用")
        except Exception as e:
            all_data["collection_note"] = f"今日采集失败，沿用昨日数据时出错: {e}"

    # 对比昨日
    changes = compare_with_yesterday(all_data, str(yesterday_file))

    all_data["changes"] = {
        "new_count": len(changes["new_listings"]),
        "removed_count": len(changes["removed_listings"]),
        "price_change_count": len(changes["price_changes"]),
        "new_listings": [
            {"community": l.get("community", ""), "layout": l.get("layout", ""),
             "area": l.get("area", 0), "total_price": l.get("total_price", 0)}
            for l in changes["new_listings"]
        ],
        "removed_listings": [
            {"community": l.get("community", ""), "layout": l.get("layout", ""),
             "area": l.get("area", 0), "total_price": l.get("total_price", 0)}
            for l in changes["removed_listings"]
        ],
        "price_changes": [
            {"community": pc["listing"].get("community", ""),
             "area": pc["listing"].get("area", 0),
             "old_price": pc["old_price"], "new_price": pc["new_price"]}
            for pc in changes["price_changes"]
        ],
    }

    # 保存
    with open(today_file, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print(f"\n💾 数据已保存: {today_file}")

    # 摘要
    print("\n" + "=" * 60)
    print("📊 采集摘要")
    print(f"  数据来源: {all_data['source']}")
    print(f"  符合条件房源: {all_data['total_qualified']} 套")
    for name, data in all_data["communities"].items():
        print(f"    - {name}: {data['count']} 套")
    if changes["new_listings"]:
        print(f"  🆕 新上线: {len(changes['new_listings'])} 套")
    if changes["removed_listings"]:
        print(f"  ❌ 已下线: {len(changes['removed_listings'])} 套")
    if changes["price_changes"]:
        print(f"  💰 价格变动: {len(changes['price_changes'])} 套")
    if all_data.get("collection_note"):
        print(f"  📝 说明: {all_data['collection_note']}")
    print("=" * 60)

    return all_data


if __name__ == "__main__":
    data = main()
