#!/usr/bin/env python3
"""
北京二手房监控 - 本地 Mac 采集脚本 v5

核心方案：
  - 使用链家关键词搜索 (/ershoufang/rs小区名/) 获取数据
  - 该URL不需要登录、不需要验证码
  - 使用持久化 Chrome Profile 保持浏览状态
  - 采集后自动生成 HTML、git commit、git push
  - 由 macOS launchd 每天定时触发

使用方式：
  日常采集：python3 local_scraper.py
  不推送：  python3 local_scraper.py --no-push
  有头调试：python3 local_scraper.py --head
"""

import json
import os
import sys
import time
import random
import subprocess
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# ============================================================
# 配置区域
# ============================================================

SCRIPT_DIR = Path(__file__).parent.resolve()

COMMUNITIES = {
    "利泽西园": {
        "min_area": 90,
        "max_price": 550,
        "layout_filter": ["2室1厅", "2室2厅", "3室1厅", "3室2厅"],
    },
    "望馨花园": {
        "min_area": 80,
        "max_price": 550,
        "layout_filter": ["2室1厅", "2室2厅", "3室1厅", "3室2厅"],
    },
    "澳洲康都": {
        "min_area": 80,
        "max_price": 550,
        "layout_filter": ["2室1厅", "2室2厅", "3室1厅", "3室2厅"],
    },
    "城建集团家属楼": {
        "min_area": 0,
        "max_price": 99999,
        "layout_filter": ["1室1厅", "1室0厅", "2室1厅", "2室2厅"],
    },
}

CHROME_PROFILE_DIR = Path.home() / ".lianjia_monitor_chrome_profile"
DATA_DIR = SCRIPT_DIR / "data_history"
LOG_FILE = SCRIPT_DIR / "scraper.log"
NEARBY_PRICE_TOLERANCE = 100
NEARBY_AREA_TOLERANCE = 10


# ============================================================
# 日志
# ============================================================

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ============================================================
# 浏览器
# ============================================================

def create_browser(pw, headless=True):
    """创建持久化Chrome上下文"""
    CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(CHROME_PROFILE_DIR),
        channel="chrome",
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1920,1080",
            "--lang=zh-CN",
        ],
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    )
    log(f"  浏览器启动 (headless={headless})")
    return ctx


def random_delay(min_s=1.0, max_s=3.0):
    time.sleep(random.uniform(min_s, max_s))


def human_scroll(page):
    for _ in range(random.randint(2, 4)):
        page.mouse.wheel(0, random.randint(100, 300))
        time.sleep(random.uniform(0.1, 0.3))
    time.sleep(random.uniform(0.3, 0.8))


# ============================================================
# 采集核心（关键词搜索方式）
# ============================================================

# JS: 从DOM提取房源数据
EXTRACT_LISTINGS_JS = """
() => {
    const results = [];
    document.querySelectorAll('.sellListContent li.clear').forEach(item => {
        try {
            const listing = {};
            const titleEl = item.querySelector('.title a');
            if (titleEl) {
                listing.title = titleEl.textContent.trim();
                listing.url = titleEl.href;
                const m = listing.url.match(/(\\d+)\\.html/);
                if (m) listing.lianjia_id = m[1];
            }
            const infoEl = item.querySelector('.houseInfo');
            if (infoEl) {
                const t = infoEl.textContent.trim();
                listing.info_text = t;
                const lm = t.match(/(\\d室\\d厅)/);
                if (lm) listing.layout = lm[1];
                const am = t.match(/([\\d.]+)平米/);
                if (am) listing.area = parseFloat(am[1]);
                const parts = t.split('|').map(s => s.trim());
                // houseInfo格式通常：小区名 | 户型 | 面积 | 朝向 | 装修 | 楼层
                for (const p of parts) {
                    if (/^[东西南北]+$/.test(p) || /^东|^西|^南|^北/.test(p)) {
                        listing.direction = p;
                        break;
                    }
                }
            }
            const posEl = item.querySelector('.positionInfo');
            if (posEl) listing.floor = posEl.textContent.trim();
            const priceEl = item.querySelector('.totalPrice span');
            if (priceEl) {
                const p = parseFloat(priceEl.textContent.trim());
                if (!isNaN(p)) listing.total_price = p;
            }
            const unitEl = item.querySelector('.unitPrice span');
            if (unitEl) {
                const ut = unitEl.textContent.trim();
                const um = ut.match(/([\\d,]+)/);
                if (um) listing.unit_price = parseInt(um[1].replace(/,/g, ''));
            }
            const followEl = item.querySelector('.followInfo');
            if (followEl) {
                const ft = followEl.textContent.trim();
                listing.follow_info = ft;
                const dm = ft.match(/(\\d{4}[.\\-\\/]\\d{1,2}[.\\-\\/]\\d{1,2})/);
                if (dm) listing.listing_date = dm[1].replace(/\\./g, '-');
            }
            if (listing.total_price) results.push(listing);
        } catch(e) {}
    });
    return results;
}
"""


def scrape_community_by_search(page, community_name):
    """
    通过关键词搜索方式获取小区房源。
    URL: /ershoufang/rs{小区名}/
    不需要登录、不需要验证码。
    """
    all_listings = []
    max_pages = 3

    for page_num in range(1, max_pages + 1):
        if page_num == 1:
            url = f"https://bj.lianjia.com/ershoufang/rs{community_name}/"
        else:
            url = f"https://bj.lianjia.com/ershoufang/pg{page_num}rs{community_name}/"

        log(f"    第{page_num}页: {url}")

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            random_delay(2.0, 4.0)

            # 检查是否被拦截
            current_url = page.url
            if "captcha" in current_url.lower():
                log(f"    ⚠️ 遇到验证码")
                return []
            if "login" in current_url.lower():
                log(f"    ⚠️ 需要登录")
                return []

            human_scroll(page)
            random_delay(0.5, 1.0)

            # 等待房源列表
            try:
                page.wait_for_selector(".sellListContent li.clear", timeout=6000)
            except Exception:
                content = page.content()
                if "没有找到" in content or "暂无" in content or len(content) < 5000:
                    log(f"    暂无更多数据")
                    break

            # 提取房源
            listings = page.evaluate(EXTRACT_LISTINGS_JS)

            if not listings:
                if page_num == 1:
                    log(f"    未解析到数据")
                break

            # 只保留标题/位置包含目标小区名的房源
            target_listings = []
            for item in listings:
                title = item.get("title", "")
                position = item.get("floor", "")  # positionInfo里可能包含小区名
                if community_name in title or community_name in position:
                    item["community"] = community_name
                    item["source"] = "链家"
                    target_listings.append(item)

            all_listings.extend(target_listings)
            log(f"    解析 {len(listings)} 条，其中{community_name} {len(target_listings)} 条")

            # 检查是否有下一页
            has_next = page.evaluate("""
            () => {
                const pb = document.querySelector('.page-box .page-data');
                if (pb) {
                    try {
                        const d = JSON.parse(pb.getAttribute('page-data') || '{}');
                        return d.curPage < d.totalPage;
                    } catch(e) {}
                }
                return false;
            }
            """)
            if not has_next:
                break

            random_delay(3.0, 6.0)

        except Exception as e:
            log(f"    采集异常: {e}")
            break

    log(f"  ✅ {community_name}: 共 {len(all_listings)} 套")
    return all_listings


# ============================================================
# 筛选 / 对比 / 格式化
# ============================================================

def filter_listings(listings, config):
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
        elif (area >= config["min_area"] - NEARBY_AREA_TOLERANCE
              and price <= config["max_price"] + NEARBY_PRICE_TOLERANCE):
            notes = []
            if price > config["max_price"]:
                notes.append(f"总价超出{int(price - config['max_price'])}万")
            if area < config["min_area"]:
                notes.append(f"面积不足{config['min_area']}㎡")
            listing["note"] = "，".join(notes)
            nearby.append(listing)
    return qualified, nearby


def build_listing_id(listing):
    if listing.get("lianjia_id"):
        return f"lj-{listing['lianjia_id']}"
    c = listing.get("community", "")
    prefix_map = {"利泽西园": "lzxy", "望馨花园": "wxxhy", "澳洲康都": "azkd", "城建集团家属楼": "cjjt"}
    prefix = prefix_map.get(c, "other")
    return f"{prefix}-{listing.get('area', 0)}-{listing.get('total_price', 0)}"


def format_listing(listing):
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


def compare_with_yesterday(today_data, yesterday_file):
    changes = {
        "new_listings": [], "removed_listings": [],
        "price_changes": [], "total_yesterday": 0, "total_today": 0,
    }
    if not os.path.exists(yesterday_file):
        return changes
    try:
        with open(yesterday_file, "r", encoding="utf-8") as f:
            yd = json.load(f)
    except Exception:
        return changes

    yesterday_map = {}
    for cdata in yd.get("communities", {}).values():
        for l in cdata.get("listings", []):
            lid = l.get("id", "")
            if lid:
                yesterday_map[lid] = l
    changes["total_yesterday"] = yd.get("total_qualified", 0)

    today_map = {}
    for cdata in today_data.get("communities", {}).values():
        for l in cdata.get("listings", []):
            lid = l.get("id", "")
            if lid:
                today_map[lid] = l
    changes["total_today"] = today_data.get("total_qualified", 0)

    for lid, l in today_map.items():
        if lid not in yesterday_map:
            changes["new_listings"].append(l)
    for lid, l in yesterday_map.items():
        if lid not in today_map:
            changes["removed_listings"].append(l)
    for lid in set(today_map) & set(yesterday_map):
        op = yesterday_map[lid].get("total_price", 0)
        np_ = today_map[lid].get("total_price", 0)
        if op != np_ and op > 0 and np_ > 0:
            changes["price_changes"].append({
                "listing": today_map[lid], "old_price": op, "new_price": np_,
                "diff": np_ - op,
            })
    return changes


# ============================================================
# Git 推送
# ============================================================

def git_push():
    os.chdir(SCRIPT_DIR)
    try:
        subprocess.run(
            ["git", "add", "data_history/", "index.html", "北京购房监控_链家数据.html"],
            check=True, capture_output=True, text=True
        )
        result = subprocess.run(
            ["git", "diff", "--staged", "--quiet"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            log("  Git: 没有变更")
            return True

        today = datetime.now().strftime("%Y-%m-%d")
        subprocess.run(
            ["git", "commit", "-m", f"📊 自动更新: {today} 房源数据"],
            check=True, capture_output=True, text=True
        )
        subprocess.run(
            ["git", "push", "origin", "main"],
            check=True, capture_output=True, text=True, timeout=60
        )
        log("  ✅ Git推送成功")
        return True
    except subprocess.CalledProcessError as e:
        log(f"  ❌ Git失败: {e.stderr[:200] if e.stderr else str(e)}")
        return False
    except subprocess.TimeoutExpired:
        log("  ❌ Git推送超时")
        return False


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="北京二手房监控 - 本地采集 v5")
    parser.add_argument("--head", action="store_true", help="有头模式（调试用）")
    parser.add_argument("--no-push", action="store_true", help="不推送到Git")
    args = parser.parse_args()

    os.chdir(SCRIPT_DIR)

    log("=" * 60)
    log("🏠 北京二手房监控 - 本地采集 v5")
    log(f"📅 {datetime.now().strftime('%Y年%m月%d日 %H:%M')}")
    log("=" * 60)

    from playwright.sync_api import sync_playwright

    DATA_DIR.mkdir(exist_ok=True)
    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    today_file = DATA_DIR / f"{today_str}.json"
    yesterday_file = DATA_DIR / f"{yesterday_str}.json"

    all_data = {
        "date": today_str,
        "source": "",
        "collection_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_qualified": 0,
        "communities": {},
        "nearby_listings": [],
    }

    headless = not args.head

    with sync_playwright() as pw:
        log("🚀 启动浏览器...")
        ctx = create_browser(pw, headless=headless)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # 预热：先访问首页
        log("📡 预热...")
        try:
            page.goto("https://bj.lianjia.com/ershoufang/", wait_until="domcontentloaded", timeout=15000)
            random_delay(2.0, 4.0)
            human_scroll(page)

            if "captcha" in page.url.lower():
                log("⚠️  遇到验证码，等待...")
                # 如果headless模式遇到验证码，切换到有头模式
                if headless:
                    ctx.close()
                    ctx = create_browser(pw, headless=False)
                    page = ctx.pages[0] if ctx.pages else ctx.new_page()
                    page.goto("https://bj.lianjia.com/ershoufang/", wait_until="domcontentloaded", timeout=15000)

                for i in range(180):
                    time.sleep(1)
                    if "captcha" not in page.url.lower() and "CAPTCHA" not in page.title():
                        log("  ✅ 验证码通过")
                        break
                    if i % 30 == 0 and i > 0:
                        log(f"  等待中... ({i}秒)")
                else:
                    log("  ❌ 验证码超时，终止")
                    ctx.close()
                    return
            else:
                items = page.query_selector_all('.sellListContent li.clear')
                log(f"✅ 链家可正常访问 (首页 {len(items)} 条)")
        except Exception as e:
            log(f"⚠️  首页加载失败: {e}")

        random_delay(2.0, 4.0)

        # 逐个小区采集
        success = False
        for community_name, config in COMMUNITIES.items():
            log(f"\n🏘️ {community_name}")

            listings = scrape_community_by_search(page, community_name)

            if listings:
                success = True

            # 筛选
            qualified, nearby = filter_listings(listings, config)
            formatted = [format_listing(l) for l in qualified]

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

            random_delay(5.0, 10.0)

        ctx.close()

    # 数据源标签
    all_data["source"] = "链家" if success else "采集失败"
    all_data["collection_note"] = "" if success else "所有小区均采集失败"

    # 如果没数据，沿用昨日
    if all_data["total_qualified"] == 0 and yesterday_file.exists():
        log("⚠️  今日未采集到数据，尝试沿用昨日...")
        try:
            yd = json.loads(yesterday_file.read_text(encoding="utf-8"))
            if yd.get("total_qualified", 0) > 0:
                all_data["communities"] = yd.get("communities", {})
                all_data["total_qualified"] = yd.get("total_qualified", 0)
                all_data["nearby_listings"] = yd.get("nearby_listings", [])
                all_data["collection_note"] = "今日采集失败，沿用昨日数据"
                log(f"  沿用昨日 {all_data['total_qualified']} 套")
        except Exception:
            all_data["collection_note"] = "今日采集失败，昨日也无数据"

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

    # 保存数据
    with open(today_file, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    log(f"\n💾 数据已保存: {today_file}")

    # 生成HTML
    log("📄 生成HTML报告...")
    try:
        subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "generate_html.py")],
            check=True, capture_output=True, text=True, cwd=str(SCRIPT_DIR)
        )
        log("  ✅ HTML报告已生成")
    except subprocess.CalledProcessError as e:
        log(f"  ❌ HTML生成失败: {e.stderr[:200] if e.stderr else str(e)}")

    # Git推送
    if not args.no_push:
        log("📤 推送到GitHub...")
        git_push()
    else:
        log("⏭️  跳过Git推送 (--no-push)")

    # 摘要
    log("\n" + "=" * 60)
    log("📊 采集摘要")
    log(f"  数据来源: {all_data['source']}")
    log(f"  符合条件: {all_data['total_qualified']} 套")
    for name, cd in all_data["communities"].items():
        log(f"    - {name}: {cd['count']} 套")
    if changes["new_listings"]:
        log(f"  🆕 新上线: {len(changes['new_listings'])} 套")
    if changes["removed_listings"]:
        log(f"  ❌ 已下线: {len(changes['removed_listings'])} 套")
    if changes["price_changes"]:
        log(f"  💰 变动: {len(changes['price_changes'])} 套")
    if all_data.get("collection_note"):
        log(f"  📝 {all_data['collection_note']}")
    log("=" * 60)


if __name__ == "__main__":
    main()
