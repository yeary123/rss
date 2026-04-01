# Miniflux + GitHub Actions 桥接 + 阿里云

在阿里云 ECS 上用 Docker 跑 **Miniflux**（PostgreSQL + **Caddy** 自动 HTTPS），在 **公开** GitHub 仓库里用 **Actions** 定时抓取大陆 VPS 不易访问的源，合并为 **Atom**，发布到 **GitHub Pages**。iPhone 用 **Safari** 打开你的域名即可阅读；桥接源在 Miniflux 里当作一个订阅地址添加。

## 架构

- **阿里云**：`docker compose` 运行 `postgres`、`miniflux`、`caddy`（Let’s Encrypt）。
- **GitHub**：`bridge/feeds.yaml` 列出桥接源 → `bridge/build_feed.py` 生成 `public/feeds/merged.xml` → Actions 部署到 GitHub Pages。
- **Miniflux**：直连能访问的 Feed；对桥接 Feed 使用 Pages 上的 `merged.xml` URL。

## 1. 准备域名与阿里云

1. 将域名 **A 记录** 指到 ECS **公网 IP**。
2. **安全组**放行 **80、443**（证书申请与访问）；SSH 端口按需放行。
3. ECS 安装 **Docker** 与 **Docker Compose 插件**（官方文档为准）。

## 2. 部署 Miniflux（服务器上）

```bash
git clone <你的仓库URL> rss && cd rss
cp .env.example .env
# 编辑 .env：DOMAIN、BASE_URL、POSTGRES_PASSWORD、ADMIN_USERNAME、ADMIN_PASSWORD
docker compose up -d
```

- `DOMAIN`：仅主机名，如 `rss.example.com`，须与 DNS 一致。
- `BASE_URL`：完整 HTTPS 地址，如 `https://rss.example.com`，**不要**末尾斜杠。

首次启动后，用 Safari 打开 `https://你的域名` 登录 Miniflux。若使用 `CREATE_ADMIN=1`，管理员由 `.env` 中的账号密码创建。

**安全建议**：成功登录后，可在 `docker-compose.yml` 中去掉 Miniflux 的 `CREATE_ADMIN: "1"` 环境变量（及 `.env` 里不再依赖该项），避免重复创建逻辑困扰，然后 `docker compose up -d` 重建容器。

## 3. GitHub 仓库与 Pages

1. 将本仓库推送到 GitHub **公开** 仓库。
2. 打开 **Settings → Pages**，**Build and deployment** 的 **Source** 选 **GitHub Actions**。
3. 编辑 [`bridge/feeds.yaml`](bridge/feeds.yaml)，把 `feed.self_url` 改成你的真实地址：

   `https://<用户名>.github.io/<仓库名>/feeds/merged.xml`

   若使用自定义 Pages 域名，则改为该域名下的同等路径。

4. 在 **Actions** 中运行 **RSS bridge → GitHub Pages**（可手动 **Run workflow**），确认浏览器能打开：

   - `https://<用户名>.github.io/<仓库名>/`
   - `https://<用户名>.github.io/<仓库名>/feeds/merged.xml`

## 4. 在 Miniflux 里订阅桥接 Feed

1. 进入 **Subscriptions → Add subscription**。
2. URL 填上一步的 **`merged.xml` 完整 HTTPS 地址**。
3. 其余在大陆 VPS 上可直接访问的 Feed，照常单独添加。

## 5. 从 ECS 检查能否访问 GitHub Pages（推荐）

在阿里云机器上执行：

```bash
curl -sI "https://<用户名>.github.io/<仓库名>/feeds/merged.xml" | head -5
```

应看到 `HTTP/2 200`（或 301/302 再跟跳到 200）。若此处失败，Miniflux 也无法拉取桥接源，需换网络策略或将静态 XML 改放到你自己域名下（可后续再迭代）。

## 6. 本地生成 merged.xml（可选）

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r bridge/requirements.txt
python bridge/build_feed.py
```

产物为 `public/feeds/merged.xml`（默认已写入 `.gitignore`，不必提交）。

## 文件说明

| 路径 | 说明 |
|------|------|
| `docker-compose.yml` | PostgreSQL、Miniflux、Caddy |
| `Caddyfile` | 反代 Miniflux，自动 HTTPS |
| `.env.example` | 环境变量模板 |
| `bridge/feeds.yaml` | Actions 抓取的源列表与合并 Feed 元数据 |
| `bridge/build_feed.py` | 合并为 Atom |
| `bridge/requirements.txt` | 桥接脚本依赖 |
| `.github/workflows/bridge.yml` | 定时（每 6 小时）与手动触发、发布 Pages |

## 说明与边界

- 合并 Feed 会混合多源条目，按时间排序；失败源会在日志中跳过，下次定时任务再试。
- 默认最多保留 **400** 条条目，可在 `bridge/build_feed.py` 中调整 `MAX_ENTRIES`。
- 无域名时难以在 iOS Safari 上稳定使用 HTTPS；本方案以 **域名 + Let’s Encrypt（经 Caddy）** 为前提。
