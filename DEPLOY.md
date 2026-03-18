# 🏠 北京二手房监控 - GitHub Actions 自动化部署指南

## 部署步骤（5分钟搞定）

### 第一步：创建 GitHub 仓库

1. 打开 https://github.com/new
2. 仓库名填：`beijing-house-monitor`（或你喜欢的名字）
3. 选 **Public**（公开仓库，GitHub Pages 免费）
4. 点 "Create repository"

### 第二步：推送代码到 GitHub

在终端执行以下命令（把 `你的用户名` 换成你的 GitHub 用户名）：

```bash
cd /Users/yangfei/WorkBuddy/20260318115523/github-actions-deploy

git init
git add .
git commit -m "🏠 初始化：北京二手房监控系统"
git branch -M main
git remote add origin https://github.com/你的用户名/beijing-house-monitor.git
git push -u origin main
```

### 第三步：开启 GitHub Pages

1. 打开仓库页面 → 点击 **Settings** → 左侧 **Pages**
2. Source 选择 **GitHub Actions**
3. 保存

### 第四步：手动触发一次测试

1. 打开仓库页面 → 点击 **Actions** 标签
2. 左侧选择 "每日房源数据采集"
3. 点右侧 "Run workflow" → "Run workflow"
4. 等待运行完成（约2-3分钟）

### 第五步：访问你的监控页面

部署完成后，你的监控网页地址是：

```
https://你的用户名.github.io/beijing-house-monitor/
```

手机也能直接打开！🎉

---

## 之后会发生什么？

- **每天北京时间 09:00**，GitHub Actions 会自动：
  1. 采集链家/安居客的最新房源数据
  2. 与前一天数据对比，找出新上线/下线/价格变动
  3. 更新 HTML 报告页面
  4. 自动发布到 GitHub Pages
  5. （可选）推送摘要到微信

- **你不需要做任何事情**，电脑关机也没关系

---

## 可选配置

### 添加微信通知

如果你想每天收到微信推送，可以在 GitHub 仓库设置 Secrets：

1. 仓库 → Settings → Secrets and variables → Actions
2. 点 "New repository secret"
3. Name 填 `WECHAT_WEBHOOK_URL`，Value 填你的微信机器人 webhook 地址

### 添加链家 Cookies（提升采集成功率）

链家有反爬机制，添加登录 cookies 可以显著提升采集成功率：

1. 在浏览器登录链家，用开发者工具复制 cookies
2. 仓库 → Settings → Secrets → New repository secret
3. Name 填 `LIANJIA_COOKIES`，Value 填 cookies 内容

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `scraper.py` | 数据采集脚本，从链家/安居客抓取房源 |
| `generate_html.py` | HTML 报告生成器 |
| `notify.py` | 微信通知推送（可选） |
| `data_history/` | 历史数据存储（JSON格式，按日期命名） |
| `index.html` | 生成的监控报告页面 |
| `.github/workflows/daily-scrape.yml` | GitHub Actions 工作流配置 |

## 修改监控条件

如果要修改监控的小区或筛选条件，编辑 `scraper.py` 文件开头的 `COMMUNITIES` 配置即可。
