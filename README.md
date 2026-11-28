# 沪拆信号

上海二手房网签快照。每次快照相对上一份的成交变化，就是这个站上的「信号」。

征收、动迁带来的换房需求，是阅读这组成交量的背景。网签页只存档和对比公开套数。小区公告和套数分档在单独的一页，见下方「公开页面」。那一页不是投资建议。

## 怎么更新数据

自动抓取目前过不了网上房地产的拦截（HTTP 412），所以每周定时任务会失败，`fangdi.json` 保持上次成功的版本。要更新数字，用下面三种办法里的一种。三种都走同一套合并：追加单日、更新 `fangdi.json`、写下 `snapshots/写入日.json`。不会覆盖没有 `origin` 的人工收录，也不会改已经标成完整月的数字（例如 2026-10 的 24653）。套数从你自己打开的页面上读，不要猜。

### 在 GitHub 上录入

合并进 `main`，并且 Actions 有写权限之后：

1. 用普通浏览器打开 <https://www.fangdi.com.cn/old_house/old_house.html>，记下昨日成交套数和它对应的日期。页面打不开就停，不要填一个估计值。
2. 打开本仓库的 **Actions** → **refresh** → **Run workflow**。
3. **成交套数**填整数，**成交日**填 `YYYY-MM-DD`（是昨天，不是点击当天）。面积可以空着。
4. 套数和 JSON 只填一种。要贴 JSON 时放进 **JSON** 框，并且整段只有一行，例如 `{"deals":697,"date":"2026-11-13"}`。多日写成一行数组：`[{"deals":697,"date":"2026-11-13"},{"deals":710,"date":"2026-11-14"}]`。一份带 `daily` 数组的快照太长，用下面的 `--file`，不要塞进这个输入框。
5. 运行。测试通过、数字有变化时，`github-actions[bot]` 会把 `fangdi.json` 和 `snapshots/` 提交到 `main`。随后 `pages` 会更新页面。
6. 四个输入都空着，等于再试一次在线抓取。源站仍返回 412 时这次运行失败，仓库保持原样。

每周一 10:00（北京时间）仍会自动试一次抓取。源站继续拦截时，这次定时运行会失败。要用上面的手动录入来更新。不要执行挑战脚本，也不要改请求去绕过拦截。

### 在自己的电脑上录入

```bash
python3 -m huchai import --deals 697 --date 2026-11-13
python3 -m huchai import --deals 697 --date 2026-11-13 --area 54928.77
python3 -m huchai import --file day.json
python3 -m huchai import --deals 697 --date 2026-11-13 --dry-run
```

`day.json` 可以是单日对象、对象数组，或带 `daily` / `days` / `observations` 数组的快照。快照里用每天的 `key` 和 `deals`。成交日必须写在文件里，命令不会把缺日期的记录当成昨天。`--dry-run` 只打印，不写文件。

确认 `fangdi.json` 和 `snapshots/` 的变化后，自己提交并推送到 `main`。

同一天的数字填错了，可以再导一次正确的套数。已经带 `origin`（`manual` 或 `fangdi`）的那一天会被改掉。没有 `origin` 的人工收录（现在这几条历史单日）不能改。

### 在能正常打开源站的电脑上抓取

如果这台电脑用普通请求就能拿到 JSON（页面没有要求你去过验证，请求也没有被改造成绕过拦截）：

```bash
python3 -m huchai crawl
```

有变化再提交 `fangdi.json` 和 `snapshots/` 并推送。GitHub 上的定时任务用的是同一条命令；那边现在会被 412 拦住，失败是预期结果。

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
| `site/tiers/` | 小区信号页。`data.json` 由 `python3 -m huchai volume` 生成 |
| `huchai/` | 爬虫、录入、合并、信号和站点构建。只用 Python 标准库 |

一份快照里：

- `updated`：写入日期
- `asOf`：数据覆盖到哪一天
- `mtd`：月内累计。没有完整累计时 `deals` 为 `null`，不会把残缺日加总伪装成官方月累计
- `monthly`：月份。`partial: true` 表示未完月
- `daily`：已经收录的单日，不是一条不缺日的日序列

`snapshots/` 里 2026-10-18 到 2026-11-09 这五份是从 git 历史迁出来的人工快照。爬虫或录入写新文件时会加上 `"writer": "huchai-feed"`。录入还会加上 `"ingest": "import"`，页面据此说明这份快照不是自动抓取。两种写入都拒绝覆盖没有 `writer` 的归档。

## 自动更新

`.github/workflows/crawl.yml`

- 每周一 02:00 UTC（北京时间周一 10:00）自动抓取一次
- 也可以在 Actions 里手动跑 `refresh`。填了成交套数和成交日，或贴了一行 JSON，就按录入更新，不访问源站。四个输入都空着才抓取
- 先跑测试，再录入或抓取
- 只有快照真的变了才提交并推送
- 源站返回拦截页、空数据或残缺数据时，进程以非 0 退出，**不改** `fangdi.json`

请求很少：频道页一次，接口一次，中间停 1.5 秒。User-Agent 是 `huchai-feed/1.0`，不伪装成浏览器。网络错误和 HTTP 5xx 会退避重试；HTTP 412/403 这类挑战页不会重试，也不会去解脚本。

源站目前对数据中心的请求直接返回瑞数（Ruishu）挑战页，见下面「源站拦截」。挑战不解除的话，每周这次运行会失败，这是故意让失败看得见。失败不会把好数据盖掉。

接口一旦能正常返回 JSON，可以把 cron 从 `0 2 * * 1` 改成 `0 2 * * *`（每天北京时间 10:00，仍然只有两次请求），否则两次抓取之间的那些「昨日」就补不回来。

## 本地运行

需要 Python 3.11 或更高，没有第三方包，也没有密钥。

```bash
python3 -m unittest discover -s tests -v
python3 -m huchai import --deals 697 --date 2026-11-13 --dry-run
python3 -m huchai crawl --dry-run
python3 -m huchai crawl --fixture tests/fixtures/sell_ok.json --now 2026-11-14 --dry-run
python3 -m huchai build --out dist
python3 -m huchai preview
python3 -m huchai volume
```

`--dry-run` 只打印将要写入的快照。`--fixture` 用本地 JSON 代替网络，方便不访问源站做检查。真正写入时去掉 `--dry-run`。`python3 -m huchai volume` 用贝壳套数和 M2 样本重写 `site/tiers/data.json` 与 `samples/m2/volume_backtest.md`。

预览地址是 `http://127.0.0.1:8765/`。页面里的 JSON 和样式都是相对路径，放在 `/huchai-feed/` 子路径下也同样能打开。

## 公开页面

构建结果由 `.github/workflows/pages.yml` 用 `actions/deploy-pages` 发布。

- 页面：https://peggyzhu.github.io/huchai-feed/
- 小区信号：https://peggyzhu.github.io/huchai-feed/tiers/
- 小区数据：https://peggyzhu.github.io/huchai-feed/tiers/data.json
- 最新 JSON：https://peggyzhu.github.io/huchai-feed/fangdi.json
- 信号：https://peggyzhu.github.io/huchai-feed/signals.json
- 目录：https://peggyzhu.github.io/huchai-feed/snapshots/index.json

页面是静态的，没有后端。网签页展示最新快照、月度和已收录单日的走势，以及相对上一份快照的变化。历史快照可以逐份打开。小区页列出公告匹配到的小区、程序证据和贝壳成交套数，按 2026-11-28 的套数规则给出档位或「未分档」。`fangdi.json` 和 `site/tiers/data.json` 都在仓库里，合并后也可以用 jsDelivr 按仓库文件取，例如 `https://cdn.jsdelivr.net/gh/PeggyZhu/huchai-feed@main/site/tiers/data.json`。页面本身不依赖这个 CDN，构建结果里用的是相对路径。

## 源站拦截（2026-11-14）

从这台环境访问 `https://www.fangdi.com.cn/`、二手房频道页和昨日成交接口，TLS 能连上，但响应都是 **HTTP 412**。响应体是瑞数挑战页（含 `$_ts` 脚本，并下发 cookie `UA1L1zGonajvO`），不是成交 JSON。爬虫发现这种响应就退出，不去执行挑战脚本，也不伪造浏览器指纹。

GitHub 托管的 Actions 跑在数据中心，很大概率遇到同一堵墙。那时候 workflow 会红，仓库里的数字保持上次成功的版本。不要为了让 CI 变绿去绕过这道拦截。

## 合并后要做的一次设置

这些开关在仓库设置里，合并 PR 本身不会打开它们。

1. **Actions 写权限。** Settings → Actions → General → Workflow permissions，选 **Read and write permissions**。爬虫要把新快照推回 `main`。如果 `main` 有分支保护，需要允许 `github-actions[bot]` 推送，否则抓取成功后的 `git push` 会失败。
2. **Pages。** Settings → Pages → Build and deployment → Source 选 **GitHub Actions**，保存。
3. 合并到 `main` 后，`pages` workflow 会部署。也可以在 Actions 里手动跑一次 `pages`。
4. 打开 https://peggyzhu.github.io/huchai-feed/ 核对页面。原始 JSON 在上面的固定地址。
5. 源站仍返回 412 时，每周的自动抓取会失败，数据不会被空文件覆盖。更新数字用上面的「怎么更新数据」：在 Actions 的 **refresh** 里填套数和成交日，或在本机运行 `python3 -m huchai import`。

没有自定义域名，也没有付费托管或付费接口。
