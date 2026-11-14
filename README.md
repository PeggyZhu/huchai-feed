# 沪拆信号

上海二手房网签快照。每次快照相对上一份的成交变化，就是这个站上的「信号」。

征收、动迁带来的换房需求，是阅读这组成交量的背景。站点只存档和对比公开的网签套数，不列地块，也不判断哪一块会拆。

## 数据来源

[网上房地产](https://www.fangdi.com.cn/old_house/old_house.html)（上海市房地产交易中心）二手房频道的昨日成交：

`POST https://www.fangdi.com.cn/oldhouse/getSHYesterdaySell.action`

先打开频道页，再请求这个接口。官方套数**含商业和车位**，所以套数偏高、不能直接当成纯住宅。一手房首页的「今日签约」是另一套滚动数字，不混进这个文件。

仓库里已经核对过的锚点都落在这套二手房口径上，例如 2026-09 全月 23581 套、2026-10-11 的 1615 套、2026-11-01 的 1071 套。2026-10 全月在快照里记的是媒体转引的 **24653** 套；它已经标成完整月，爬虫不会用残缺的日数据把它改掉。

这个接口只公布「昨日」一天，不提供可回补的历史序列。每周跑一次，就只可能多出抓取日前一天的那一个数。

## 仓库里有什么

| 路径 | 作用 |
| --- | --- |
| `fangdi.json` | 最新快照。页面和 `https://peggyzhu.github.io/huchai-feed/fangdi.json` 都用它 |
| `snapshots/YYYY-MM-DD.json` | 按快照日留下的历史。现有五份来自原来的提交，字节原样保留 |
| `snapshots/index.json` | 历史目录 |
| `site/` | 静态页的源文件 |
| `huchai/` | 爬虫、合并、信号和站点构建。只用 Python 标准库 |

一份快照里：

- `updated`：写入日期
- `asOf`：数据覆盖到哪一天
- `mtd`：月内累计。没有完整累计时 `deals` 为 `null`，不会把残缺日加总伪装成官方月累计
- `monthly`：月份。`partial: true` 表示未完月
- `daily`：已经收录的单日，不是一条不缺日的日序列

`snapshots/` 里 2026-10-18 到 2026-11-09 这五份是从 git 历史迁出来的人工快照。爬虫写新文件时会加上 `"writer": "huchai-feed"`，并且拒绝覆盖没有这个标记的归档。

## 自动更新

`.github/workflows/crawl.yml`

- 每周一 02:00 UTC（北京时间周一 10:00）
- 也可以在 Actions 里手动跑 `crawl`
- 先跑测试，再抓取
- 只有快照真的变了才提交并推送
- 源站返回拦截页、空数据或残缺数据时，进程以非 0 退出，**不改** `fangdi.json`

请求很少：频道页一次，接口一次，中间停 1.5 秒。User-Agent 是 `huchai-feed/1.0`，不伪装成浏览器。网络错误和 HTTP 5xx 会退避重试；HTTP 412/403 这类挑战页不会重试，也不会去解脚本。

源站目前对数据中心的请求直接返回瑞数（Ruishu）挑战页，见下面「源站拦截」。挑战不解除的话，每周这次运行会失败，这是故意让失败看得见。失败不会把好数据盖掉。

接口一旦能正常返回 JSON，可以把 cron 从 `0 2 * * 1` 改成 `0 2 * * *`（每天北京时间 10:00，仍然只有两次请求），否则两次抓取之间的那些「昨日」就补不回来。

## 本地运行

需要 Python 3.11 或更高，没有第三方包，也没有密钥。

```bash
python3 -m unittest discover -s tests -v
python3 -m huchai crawl --dry-run
python3 -m huchai crawl --fixture tests/fixtures/sell_ok.json --now 2026-11-14 --dry-run
python3 -m huchai build --out dist
python3 -m huchai preview
```

`--dry-run` 只打印将要写入的快照。`--fixture` 用本地 JSON 代替网络，方便不访问源站做检查。真正写入时去掉 `--dry-run`。

预览地址是 `http://127.0.0.1:8765/`。页面里的 JSON 和样式都是相对路径，放在 `/huchai-feed/` 子路径下也同样能打开。

## 公开页面

构建结果由 `.github/workflows/pages.yml` 用 `actions/deploy-pages` 发布。

- 页面：https://peggyzhu.github.io/huchai-feed/
- 最新 JSON：https://peggyzhu.github.io/huchai-feed/fangdi.json
- 信号：https://peggyzhu.github.io/huchai-feed/signals.json
- 目录：https://peggyzhu.github.io/huchai-feed/snapshots/index.json

页面是静态的，没有后端。它展示最新快照、月度和已收录单日的走势，以及相对上一份快照的变化。历史快照可以逐份打开。

## 源站拦截（2026-11-14）

从这台环境访问 `https://www.fangdi.com.cn/`、二手房频道页和昨日成交接口，TLS 能连上，但响应都是 **HTTP 412**。响应体是瑞数挑战页（含 `$_ts` 脚本，并下发 cookie `UA1L1zGonajvO`），不是成交 JSON。爬虫发现这种响应就退出，不去执行挑战脚本，也不伪造浏览器指纹。

GitHub 托管的 Actions 跑在数据中心，很大概率遇到同一堵墙。那时候 workflow 会红，仓库里的数字保持上次成功的版本。不要为了让 CI 变绿去绕过这道拦截。

## 合并后要做的一次设置

这些开关在仓库设置里，合并 PR 本身不会打开它们。

1. **Actions 写权限。** Settings → Actions → General → Workflow permissions，选 **Read and write permissions**。爬虫要把新快照推回 `main`。如果 `main` 有分支保护，需要允许 `github-actions[bot]` 推送，否则抓取成功后的 `git push` 会失败。
2. **Pages。** Settings → Pages → Build and deployment → Source 选 **GitHub Actions**，保存。
3. 合并到 `main` 后，`pages` workflow 会部署。也可以在 Actions 里手动跑一次 `pages`。
4. 打开 https://peggyzhu.github.io/huchai-feed/ 核对页面。原始 JSON 在上面的固定地址。
5. `crawl` 在源站仍返回 412 时会失败。这不需要修，数据不会被空文件覆盖。源站恢复后，用 Actions 里的 **Run workflow** 再试。

没有自定义域名，也没有付费托管或付费接口。
