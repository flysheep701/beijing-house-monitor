#!/usr/bin/env python3
"""
北京二手房监控 - 数据采集脚本
从链家等平台采集4个目标小区的在售房源信息
"""

import json
import os
import re
import sys
import time
import random
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ============================================================
# 配置区域 - 可根据需要修改
# ============================================================

# 监控小区配置
COMMUNITIES = {
    "利泽西园": {
        "lianjia_id": "1111027374591",  # 链家小区ID
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

# 额外关注的"条件接近"房源的超出范围
NEARBY_PRICE_TOLERANCE = 100  # 总价超出范围（万）
NEARBY_AREA_TOLERANCE = 10    # 面积不足范围（㎡）

# 请求配置
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Cache-Control": "max-age=0",
}

# ============================================================
# 采集逻辑
# ============================================================


def random_sleep(min_sec=2, max_sec=5):
    """随机延时，避免被反爬"""
    time.sleep(random.uniform(min_sec, max_sec))


def fetch_page(url, cookies=None, retry=3):
    """获取网页内容，带重试机制"""
    for attempt in range(retry):
        try:
            session = requests.Session()
            if cookies:
                session.cookies.update(cookies)
            resp = session.get(url, headers=REQUEST_HEADERS, timeout=15)
            resp.encoding = "utf-8"

            # 检查是否被反爬
            if resp.status_code == 200 and "验证" not in resp.text[:500]:
                return resp.text
            elif "验证" in resp.text[:500] or resp.status_code == 403:
                print(f"  ⚠️ 触发反爬验证 (尝试 {attempt+1}/{retry})")
                random_sleep(5, 10)
            else:
                print(f"  ⚠️ HTTP {resp.status_code} (尝试 {attempt+1}/{retry})")
                random_sleep(3, 6)
        except Exception as e:
            print(f"  ❌ 请求异常: {e} (尝试 {attempt+1}/{retry})")
            random_sleep(3, 6)
    return None


def parse_lianjia_listing(item_element):
    """解析链家单条房源信息"""
    listing = {}

    try:
        # 标题和链接
        title_el = item_element.select_one(".title a")
        if title_el:
            listing["title"] = title_el.get_text(strip=True)
            listing["url"] = title_el.get("href", "")
            # 从URL中提取房源ID
            match = re.search(r"/(\d+)\.html", listing["url"])
            if match:
                listing["lianjia_id"] = match.group(1)

        # 房屋信息
        info_el = item_element.select_one(".houseInfo")
        if info_el:
            info_text = info_el.get_text(strip=True)
            listing["info_text"] = info_text

            # 解析户型
            layout_match = re.search(r"(\d室\d厅)", info_text)
            if layout_match:
                listing["layout"] = layout_match.group(1)

            # 解析面积
            area_match = re.search(r"([\d.]+)平米", info_text)
            if area_match:
                listing["area"] = float(area_match.group(1))

            # 解析朝向
            direction_parts = info_text.split("|")
            if len(direction_parts) >= 3:
                listing["direction"] = direction_parts[1].strip()

        # 楼层信息
        position_el = item_element.select_one(".positionInfo")
        if position_el:
            listing["floor"] = position_el.get_text(strip=True)

        # 总价
        price_el = item_element.select_one(".totalPrice span")
        if price_el:
            try:
                listing["total_price"] = float(price_el.get_text(strip=True))
            except ValueError:
                pass

        # 单价
        unit_price_el = item_element.select_one(".unitPrice span")
        if unit_price_el:
            price_text = unit_price_el.get_text(strip=True)
            price_num = re.search(r"([\d,]+)", price_text)
            if price_num:
                listing["unit_price"] = int(price_num.group(1).replace(",", ""))

        # 挂牌信息
        tag_el = item_element.select_one(".followInfo")
        if tag_el:
            listing["follow_info"] = tag_el.get_text(strip=True)

    except Exception as e:
        print(f"  ⚠️ 解析异常: {e}")

    return listing


def scrape_lianjia_community(community_name, config):
    """采集链家某小区的在售房源"""
    community_id = config["lianjia_id"]
    print(f"\n📍 正在采集: {community_name} (链家ID: {community_id})")

    all_listings = []
    page = 1
    max_pages = 5  # 最多采集5页

    while page <= max_pages:
        url = f"https://bj.lianjia.com/ershoufang/c{community_id}/pg{page}/"
        print(f"  📄 第{page}页: {url}")

        html = fetch_page(url)
        if not html:
            print(f"  ❌ 无法获取第{page}页，使用备用方案")
            break

        soup = BeautifulSoup(html, "html.parser")
        items = soup.select(".sellListContent li.clear")

        if not items:
            # 尝试另一个选择器
            items = soup.select("ul.sellListContent li")

        if not items:
            print(f"  ℹ️ 第{page}页没有找到房源")
            break

        for item in items:
            listing = parse_lianjia_listing(item)
            if listing and "total_price" in listing:
                listing["community"] = community_name
                listing["source"] = "链家"
                all_listings.append(listing)

        # 检查是否有下一页
        page_info = soup.select_one(".contentBottom .page-box .page-data")
        if page_info:
            try:
                page_data = json.loads(page_info.get("page-data", "{}"))
                total_pages = page_data.get("totalPage", 1)
                if page >= total_pages:
                    break
            except json.JSONDecodeError:
                break

        page += 1
        random_sleep(2, 4)

    print(f"  ✅ 采集到 {len(all_listings)} 套房源")
    return all_listings


def scrape_anjuke_community(community_name, config):
    """采集安居客某小区的在售房源（备用数据源）"""
    print(f"\n📍 [安居客备用] 正在采集: {community_name}")

    # 安居客搜索URL
    search_name = requests.utils.quote(community_name)
    url = f"https://beijing.anjuke.com/sale/?q={search_name}"

    html = fetch_page(url)
    if not html:
        print(f"  ❌ 安居客采集失败")
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(".property")
    all_listings = []

    for item in items:
        try:
            listing = {}

            title_el = item.select_one(".property-content-title-name")
            if title_el:
                listing["title"] = title_el.get_text(strip=True)

            # 确认是目标小区
            if community_name not in listing.get("title", ""):
                continue

            # 价格
            price_el = item.select_one(".property-price-total-num")
            if price_el:
                try:
                    listing["total_price"] = float(price_el.get_text(strip=True))
                except ValueError:
                    continue

            # 面积
            info_items = item.select(".property-content-info-item")
            for info_item in info_items:
                text = info_item.get_text(strip=True)
                area_match = re.search(r"([\d.]+)㎡", text)
                if area_match:
                    listing["area"] = float(area_match.group(1))
                layout_match = re.search(r"(\d室\d厅)", text)
                if layout_match:
                    listing["layout"] = layout_match.group(1)

            listing["community"] = community_name
            listing["source"] = "安居客"
            all_listings.append(listing)

        except Exception as e:
            continue

    print(f"  ✅ [安居客] 采集到 {len(all_listings)} 套")
    return all_listings


def filter_listings(listings, config):
    """按筛选条件过滤房源"""
    qualified = []
    nearby = []

    for listing in listings:
        area = listing.get("area", 0)
        price = listing.get("total_price", 0)
        layout = listing.get("layout", "")

        # 检查户型
        layout_ok = any(l in layout for l in config["layout_filter"]) if layout else True

        if not layout_ok:
            continue

        # 完全符合条件
        if area >= config["min_area"] and price <= config["max_price"]:
            qualified.append(listing)
        # 条件接近（面积或价格略微超出）
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

    # 构建昨日房源索引（按ID）
    yesterday_map = {}
    for community_name, community_data in yesterday_data.get("communities", {}).items():
        for listing in community_data.get("listings", []):
            lid = listing.get("id") or listing.get("lianjia_id", "")
            if lid:
                yesterday_map[lid] = listing
    changes["total_yesterday"] = yesterday_data.get("total_qualified", 0)

    # 构建今日房源索引
    today_map = {}
    for community_name, community_data in today_data.get("communities", {}).items():
        for listing in community_data.get("listings", []):
            lid = listing.get("id") or listing.get("lianjia_id", "")
            if lid:
                today_map[lid] = listing
    changes["total_today"] = today_data.get("total_qualified", 0)

    # 找新增
    for lid, listing in today_map.items():
        if lid not in yesterday_map:
            changes["new_listings"].append(listing)

    # 找下线
    for lid, listing in yesterday_map.items():
        if lid not in today_map:
            changes["removed_listings"].append(listing)

    # 找价格变动
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
    community = listing.get("community", "")
    area = listing.get("area", 0)
    price = listing.get("total_price", 0)
    layout = listing.get("layout", "")

    # 使用链家ID（如果有）
    if listing.get("lianjia_id"):
        return f"lj-{listing['lianjia_id']}"

    # 否则用小区+面积+价格组合
    community_prefix = {
        "利泽西园": "lzxy",
        "望馨花园": "wxxhy",
        "澳洲康都": "azkd",
        "城建集团家属楼": "cjjt",
    }.get(community, "other")

    return f"{community_prefix}-{area}-{price}"


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
    print("🏠 北京二手房监控 - 数据采集")
    print(f"📅 采集时间: {datetime.now().strftime('%Y年%m月%d日 %H:%M')}")
    print("=" * 60)

    # 确定数据目录
    data_dir = Path("data_history")
    data_dir.mkdir(exist_ok=True)

    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

    today_file = data_dir / f"{today_str}.json"
    yesterday_file = data_dir / f"{yesterday_str}.json"

    # 加载cookies（如果有）
    cookies = {}
    cookie_file = Path(".cookies")
    if cookie_file.exists():
        try:
            with open(cookie_file, "r") as f:
                for line in f:
                    if "=" in line:
                        key, value = line.strip().split("=", 1)
                        cookies[key.strip()] = value.strip()
            print(f"  🍪 已加载 {len(cookies)} 个cookies")
        except Exception:
            pass

    # 采集各小区数据
    all_data = {
        "date": today_str,
        "source": "链家、安居客",
        "collection_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "total_qualified": 0,
        "communities": {},
        "nearby_listings": [],
    }

    captcha_triggered = False

    for community_name, config in COMMUNITIES.items():
        # 先尝试链家
        listings = scrape_lianjia_community(community_name, config)

        # 如果链家没数据，尝试安居客
        if not listings:
            captcha_triggered = True
            listings = scrape_anjuke_community(community_name, config)

        # 过滤
        qualified, nearby = filter_listings(listings, config)

        # 格式化保存
        formatted_listings = [
            format_listing_for_save(l, i) for i, l in enumerate(qualified, 1)
        ]

        filter_desc = f"≥{config['min_area']}㎡ | ≤{config['max_price']}万 | {'、'.join(config['layout_filter'])}"
        if config["max_price"] > 9999:
            filter_desc = f"{'、'.join(config['layout_filter'])}（不限面积和总价）"

        all_data["communities"][community_name] = {
            "filter": filter_desc,
            "count": len(formatted_listings),
            "listings": formatted_listings,
        }

        all_data["total_qualified"] += len(formatted_listings)

        # 收集条件接近的房源
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

        random_sleep(3, 6)

    if captcha_triggered:
        all_data["collection_note"] = "部分平台触发CAPTCHA反爬验证，通过备用数据源补充采集"

    # 如果没采集到任何数据，使用昨日数据（避免页面变空）
    if all_data["total_qualified"] == 0 and yesterday_file.exists():
        print("\n⚠️ 今日未采集到数据，保留昨日数据")
        with open(yesterday_file, "r", encoding="utf-8") as f:
            yesterday_data = json.load(f)
        all_data["communities"] = yesterday_data.get("communities", {})
        all_data["total_qualified"] = yesterday_data.get("total_qualified", 0)
        all_data["nearby_listings"] = yesterday_data.get("nearby_listings", [])
        all_data["collection_note"] = "今日采集失败（反爬验证），沿用昨日数据"

    # 与昨日对比
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

    # 保存今日数据
    with open(today_file, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print(f"\n💾 数据已保存: {today_file}")

    # 输出摘要
    print("\n" + "=" * 60)
    print("📊 采集摘要")
    print(f"  符合条件房源: {all_data['total_qualified']} 套")
    for name, data in all_data["communities"].items():
        print(f"    - {name}: {data['count']} 套")
    if changes["new_listings"]:
        print(f"  🆕 新上线: {len(changes['new_listings'])} 套")
    if changes["removed_listings"]:
        print(f"  ❌ 已下线: {len(changes['removed_listings'])} 套")
    if changes["price_changes"]:
        print(f"  💰 价格变动: {len(changes['price_changes'])} 套")
    print("=" * 60)

    return all_data


if __name__ == "__main__":
    data = main()
