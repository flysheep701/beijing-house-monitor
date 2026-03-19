#!/usr/bin/env python3
"""
北京二手房监控 - 数据采集脚本 v2（无头浏览器版）

采集策略：
  使用 Playwright 无头浏览器模拟真实用户访问链家网，
  自动等待页面渲染完成后提取数据，有效绕过 CAPTCHA 反爬验证。

降级策略：
  1️⃣ Playwright 采集链家
  2️⃣ Playwright 采集贝壳
  3️⃣ 采集失败则沿用昨日数据
"""

import json
import os
import re
import sys
import time
import random
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

# ============================================================
# Playwright 浏览器采集
# ============================================================


def create_browser_context(playwright):
    """创建一个伪装良好的浏览器上下文，使用 stealth 模式绕过检测"""
    # 尝试导入 stealth 插件
    try:
        from playwright_stealth import stealth_sync
        has_stealth = True
    except ImportError:
        has_stealth = False
        print("  ℹ️ playwright-stealth 未安装，使用基础伪装模式")

    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--disable-features=VizDisplayCompositor",
            "--window-size=1920,1080",
            "--lang=zh-CN",
        ],
    )

    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        extra_http_headers={
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        },
    )

    # 基础反检测脚本
    context.add_init_script("""
        // 删除 webdriver 标识
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        // 伪造 plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
                { name: 'Native Client', filename: 'internal-nacl-plugin' },
            ]
        });
        Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
        // 伪造 chrome 对象
        window.chrome = {
            runtime: { onInstalled: { addListener: () => {} } },
            app: { isInstalled: false },
        };
        // 伪造 Permissions API
        const originalQuery = window.navigator.permissions?.query;
        if (originalQuery) {
            window.navigator.permissions.query = (parameters) => {
                if (parameters.name === 'notifications') {
                    return Promise.resolve({ state: Notification.permission });
                }
                return originalQuery(parameters);
            };
        }
    """)

    return browser, context, has_stealth


def random_delay(min_ms=1000, max_ms=3000):
    """模拟人类操作间隔"""
    time.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


def scrape_lianjia_with_browser(page, community_name, community_id):
    """
    用 Playwright 浏览器采集链家小区在售房源。
    模拟真实用户访问，等待 JS 渲染完成后解析 DOM。
    """
    url = f"https://bj.lianjia.com/ershoufang/c{community_id}/"
    print(f"\n📍 [浏览器] 正在采集: {community_name}")
    print(f"  🌐 URL: {url}")

    all_listings = []
    max_pages = 3  # 浏览器采集页数适当减少，避免时间过长

    for page_num in range(1, max_pages + 1):
        page_url = f"https://bj.lianjia.com/ershoufang/c{community_id}/pg{page_num}/"
        print(f"  📄 第{page_num}页: {page_url}")

        try:
            # 导航到页面，等待网络空闲
            page.goto(page_url, wait_until="domcontentloaded", timeout=30000)

            # 随机等待，模拟真实用户
            random_delay(2000, 4000)

            # 检查是否触发了验证码
            title = page.title()
            if "CAPTCHA" in title or "验证" in title:
                print(f"  ⚠️ 触发验证码页面，等待后重试...")
                random_delay(5000, 10000)
                page.reload(wait_until="domcontentloaded", timeout=30000)
                random_delay(3000, 5000)
                title = page.title()
                if "CAPTCHA" in title or "验证" in title:
                    print(f"  ❌ 仍然是验证码页面，跳过")
                    break

            # 等待房源列表出现
            try:
                page.wait_for_selector(".sellListContent li.clear, ul.sellListContent li", timeout=10000)
            except Exception:
                # 可能没有房源，或者页面结构不同
                print(f"  ℹ️ 未找到房源列表选择器")
                # 尝试检查是否有其他内容
                content = page.content()
                if "没有找到" in content or "暂无" in content:
                    print(f"  ℹ️ 页面显示暂无房源")
                    break
                elif len(content) < 2000:
                    print(f"  ⚠️ 页面内容过少，可能被拦截")
                    break

            # 解析页面中的房源
            listings_data = page.evaluate("""
            () => {
                const results = [];
                const items = document.querySelectorAll('.sellListContent li.clear, ul.sellListContent li[class*="LOGVIEW"]');

                items.forEach(item => {
                    try {
                        const listing = {};

                        // 标题和链接
                        const titleEl = item.querySelector('.title a');
                        if (titleEl) {
                            listing.title = titleEl.textContent.trim();
                            listing.url = titleEl.href;
                            const idMatch = listing.url.match(/(\\d+)\\.html/);
                            if (idMatch) listing.lianjia_id = idMatch[1];
                        }

                        // 房屋信息
                        const infoEl = item.querySelector('.houseInfo');
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

                        // 楼层
                        const posEl = item.querySelector('.positionInfo');
                        if (posEl) listing.floor = posEl.textContent.trim();

                        // 总价
                        const priceEl = item.querySelector('.totalPrice span');
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

                        // 关注信息
                        const followEl = item.querySelector('.followInfo');
                        if (followEl) listing.follow_info = followEl.textContent.trim();

                        if (listing.total_price) results.push(listing);
                    } catch(e) {}
                });
                return results;
            }
            """)

            if not listings_data:
                print(f"  ℹ️ 第{page_num}页未解析到房源")
                break

            for item in listings_data:
                item["community"] = community_name
                item["source"] = "链家"
                all_listings.append(item)

            print(f"  ✅ 第{page_num}页获取 {len(listings_data)} 套")

            # 检查是否有下一页
            has_next = page.evaluate("""
            () => {
                const pageBox = document.querySelector('.page-box .page-data');
                if (pageBox) {
                    try {
                        const data = JSON.parse(pageBox.getAttribute('page-data') || '{}');
                        return data.curPage < data.totalPage;
                    } catch(e) {}
                }
                return false;
            }
            """)

            if not has_next:
                break

            random_delay(3000, 6000)

        except Exception as e:
            print(f"  ❌ 浏览器采集异常: {e}")
            break

    print(f"  ✅ [浏览器] 共采集到 {len(all_listings)} 套房源")
    return all_listings


def scrape_kecom_with_browser(page, community_name, community_id):
    """用浏览器采集贝壳网小区房源（备用）"""
    url = f"https://bj.ke.com/ershoufang/c{community_id}/"
    print(f"\n📍 [贝壳备用] 正在采集: {community_name}")
    print(f"  🌐 URL: {url}")

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        random_delay(3000, 5000)

        title = page.title()
        if "CAPTCHA" in title or "验证" in title:
            print(f"  ⚠️ 贝壳也触发验证码")
            return []

        # 贝壳网的房源列表选择器
        try:
            page.wait_for_selector(".sellListContent li, .list-content li", timeout=10000)
        except Exception:
            print(f"  ℹ️ 贝壳未找到房源列表")
            return []

        listings_data = page.evaluate("""
        () => {
            const results = [];
            const items = document.querySelectorAll('.sellListContent li, .list-content li');

            items.forEach(item => {
                try {
                    const listing = {};

                    const titleEl = item.querySelector('.title a, .lj-h3 a');
                    if (titleEl) {
                        listing.title = titleEl.textContent.trim();
                        listing.url = titleEl.href;
                        const idMatch = listing.url.match(/(\\d+)\\.html/);
                        if (idMatch) listing.lianjia_id = idMatch[1];
                    }

                    const infoEl = item.querySelector('.houseInfo, .address');
                    if (infoEl) {
                        const text = infoEl.textContent.trim();
                        const layoutMatch = text.match(/(\\d室\\d厅)/);
                        if (layoutMatch) listing.layout = layoutMatch[1];
                        const areaMatch = text.match(/([\\d.]+)平米/);
                        if (areaMatch) listing.area = parseFloat(areaMatch[1]);
                        const parts = text.split('|');
                        if (parts.length >= 3) listing.direction = parts[1].trim();
                    }

                    const posEl = item.querySelector('.positionInfo, .flood');
                    if (posEl) listing.floor = posEl.textContent.trim();

                    const priceEl = item.querySelector('.totalPrice span, .price-det span');
                    if (priceEl) {
                        const price = parseFloat(priceEl.textContent.trim());
                        if (!isNaN(price)) listing.total_price = price;
                    }

                    const unitEl = item.querySelector('.unitPrice span');
                    if (unitEl) {
                        const unitText = unitEl.textContent.trim();
                        const unitMatch = unitText.match(/([\\d,]+)/);
                        if (unitMatch) listing.unit_price = parseInt(unitMatch[1].replace(/,/g, ''));
                    }

                    if (listing.total_price) results.push(listing);
                } catch(e) {}
            });
            return results;
        }
        """)

        for item in listings_data:
            item["community"] = community_name
            item["source"] = "贝壳"

        print(f"  ✅ [贝壳] 采集到 {len(listings_data)} 套")
        return listings_data

    except Exception as e:
        print(f"  ❌ 贝壳采集异常: {e}")
        return []


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
    print("🏠 北京二手房监控 - 数据采集 v2（无头浏览器版）")
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
        print("\n🚀 启动无头浏览器...")
        browser, context, has_stealth = create_browser_context(pw)
        page = context.new_page()

        # 应用 stealth 补丁
        if has_stealth:
            from playwright_stealth import stealth_sync
            stealth_sync(page)
            print("  🛡️ Stealth 反检测已启用")

        # 预热：模拟正常用户的浏览路径，建立可信的 cookie/session
        print("  📡 预热：模拟正常浏览行为...")
        try:
            # 1. 先访问首页
            page.goto("https://bj.lianjia.com/", wait_until="domcontentloaded", timeout=20000)
            random_delay(2000, 3000)

            # 2. 模拟鼠标移动和滚动
            page.mouse.move(random.randint(100, 800), random.randint(100, 400))
            random_delay(500, 1000)
            page.evaluate("window.scrollBy(0, %d)" % random.randint(200, 600))
            random_delay(1000, 2000)

            # 3. 点击进入二手房频道（建立自然的浏览路径）
            try:
                page.click('a[href*="ershoufang"]', timeout=5000)
                random_delay(2000, 4000)
            except Exception:
                page.goto("https://bj.lianjia.com/ershoufang/", wait_until="domcontentloaded", timeout=20000)
                random_delay(2000, 3000)

            # 4. 检查二手房频道是否正常加载
            title = page.title()
            if "CAPTCHA" not in title and "验证" not in title:
                print("  ✅ 预热成功，会话已建立")
            else:
                print("  ⚠️ 预热时遇到验证码，继续尝试...")

        except Exception as e:
            print(f"  ⚠️ 首页预热失败: {e}，继续尝试采集...")

        for community_name, config in COMMUNITIES.items():
            print(f"\n{'='*50}")
            print(f"🏘️ 开始采集: {community_name}")
            print(f"{'='*50}")

            community_id = config["lianjia_id"]

            # 第1级：链家浏览器采集
            listings = scrape_lianjia_with_browser(page, community_name, community_id)
            if listings:
                source_labels.add("链家")
            else:
                # 第2级：贝壳浏览器采集
                print(f"  ⚡ 链家采集失败，尝试贝壳...")
                listings = scrape_kecom_with_browser(page, community_name, community_id)
                if listings:
                    source_labels.add("贝壳")

            if not listings:
                source_labels.add("无数据")
                print(f"  ⚠️ {community_name} 所有渠道均未获取到数据")

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

            random_delay(3000, 7000)

        # 关闭浏览器
        context.close()
        browser.close()

    # 设置来源标签
    source_labels.discard("无数据")
    all_data["source"] = "、".join(sorted(source_labels)) if source_labels else "采集失败"

    if not source_labels:
        all_data["collection_note"] = "浏览器采集均被拦截"
    elif "无数据" not in source_labels:
        all_data["collection_note"] = ""
    else:
        all_data["collection_note"] = "部分小区采集失败"

    # 如果没采集到数据，沿用昨日
    if all_data["total_qualified"] == 0 and yesterday_file.exists():
        print("\n⚠️ 今日未采集到数据，保留昨日数据")
        with open(yesterday_file, "r", encoding="utf-8") as f:
            yesterday_data = json.load(f)
        all_data["communities"] = yesterday_data.get("communities", {})
        all_data["total_qualified"] = yesterday_data.get("total_qualified", 0)
        all_data["nearby_listings"] = yesterday_data.get("nearby_listings", [])
        all_data["collection_note"] = "今日采集失败，沿用昨日数据"

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
