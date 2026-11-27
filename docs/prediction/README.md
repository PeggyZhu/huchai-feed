# 小区级征收预测（M0）

本目录是征收预测模块的起点。当前只有已确认的决定、空的正式表，以及一个只做格式和出处检查的校验器。没有小区名单，没有价格，没有分数，也没有周报程序。

已确认的决定写在 [DECISIONS.md](DECISIONS.md)。阈值、档位、排除项和路线图以那份记录为准。

公开网站目前仍只发布网签快照。观察池要公开展示在 GitHub Pages，这件事留到 M5，本里程碑不改页面构建。

## 周报只读台账，不生成新数字

M5 的周报只能读取证据台账 `data/prediction/evidence.json`，以及校验器已经核对回这份台账的项目表和小区表。

周报可以把台账里已经写明的公开记录，按 DECISIONS.md 的规则整理成档位和分数。它不能补出台账里没有的户数、面积、价格、笔数、涨幅或分数。挂牌价、评估价、成交价保持各自的口径。网签的含商业口径与房管局住房口径不相加。

超额涨幅和分数都不是台账字段。校验器会拒绝把这两类名字写进台账。它们以后只能由 M3、M4 的程序从台账记录算出，并且产出的每一行仍然要带来源和口径。

本里程碑没有周报程序。校验器不计算超额涨幅，不分配档位，也不填写分数。

## 正式表和示例数据

正式表在 `data/prediction/`。每一张表都是只有表头的 CSV，加上同名的 JSON。JSON 的 `rows` 是空数组。这些文件会进入仓库，但里面没有任何一条观察。

`data/prediction/示例数据.json` 整份标记为**示例数据**。它只演示字段形状：没有户数、没有面积、没有价格、没有笔数、没有分数。名称里写着「示例数据，非真实小区」。不要把其中任何一行复制到正式表，也不要把它接进页面或周报。

区字段在示例里使用了「黄浦区」，只为了符合区名的取值范围，不表示黄浦区有这条记录。日期 `1999-01-01` 和 `https://example.com/` 都是占位。

## 来源和口径

每一行都必须有来源和口径。证据台账的来源列名是 `来源URL`，其余表的列名是 `来源`。缺一列、空着、或只有空白，校验都不通过。

来源是公开页面的 `http` 或 `https` 地址。正式表里不接受 `example.com`。

口径一次只能写一个。挂牌价、评估价、成交价三者不能出现在同一条的口径里，字段是其中之一时，口径必须与字段相同。含商业口径与房管局住房口径不能写进同一条。项目表的口径必须和类型相同，因此一条征询不能同时标成决定。

社交媒体交叉验证权重为 0。下面这些站点的地址不能作为来源：`weibo.com`、`weibo.cn`、`xiaohongshu.com`、`xhslink.com`、`douyin.com`、`iesdouyin.com`、`tiktok.com`、`twitter.com`、`x.com`、`t.co`、`t.me`、`telegram.me`、`telegram.org`、`bilibili.com`、`douban.com`、`zhihu.com`、`tieba.baidu.com`。

微信公众号不在这份拒绝名单里，也不因此变成可用的交叉验证。官方公告若只有公众号链接，M1 再由人工标成已确认或待核。权重仍然是 0，不能因为社交转发给任何一条加分。

小区表里的户数、套均面积只有在证据台账中已有同一小区、同一来源、同一口径的已确认纯数字原文时才能填写，并且必须与原文一致。带「约」或带单位的原文留在台账里，小区表对应格子保持空白。

观察池的每一行必须引用同一小区在台账里的来源地址。`最后证据日期` 必须等于所引记录里最晚的来源日期。档位或任一分数不是空白时，所引记录里至少要有一条已确认。口径为「程序」时，量价分必须空白。

## 文件

| 路径 | 作用 |
| --- | --- |
| `docs/prediction/DECISIONS.md` | 2026-11-25 已确认的决定和 M0–M5 路线图 |
| `docs/prediction/README.md` | 本说明 |
| `data/prediction/schema/` | 四张表的 JSON Schema 和表头说明 |
| `data/prediction/*.csv`、`*.json` | 正式空表 |
| `data/prediction/示例数据.json` | 唯一的示例文件，不是观察 |
| `scripts/validate_prediction.py` | 标准库校验器 |
| `.github/workflows/prediction.yml` | 单独的校验任务，不部署 Pages |

表头、口径枚举和 JSON 外壳见 [schema/README.md](../../data/prediction/schema/README.md)。

## 校验

在仓库根目录运行：

```bash
python3 scripts/validate_prediction.py
python3 -m unittest tests.test_prediction_validator -v
```

只使用 Python 3.11 及以上的标准库。校验器只读 `data/prediction/`，不打开 `fangdi.json`，不访问网络，不写文件。

`.github/workflows/prediction.yml` 在拉取请求和推送时运行上面的检查。它与 `.github/workflows/pages.yml` 分开：不构建站点，不部署，也不改变周一的网签录入。Pages 工作流失败与否，不由这个任务决定；这个任务失败，也不会去改 Pages 的行为。

## M2

官方公告的抓取、地址解析、小区匹配和程序分在 `huchai/notices/`。规则和样本位置见 [M2.md](M2.md)。

M2 不回填上面的四张正式表，也不把观察池接进页面。样本写在 `samples/m2/`，站点构建不会复制这个目录。

## 本里程碑不做的事

- 不改 `fangdi.json`、`snapshots/`、手动录入，以及 `pages.yml` 的行为。
- 不抓取 fangdi.cn，也不加入任何拦截绕过。
- 不在正式表里填写数字。M1 才回填台账。
- 不停用 grok.com 上的「沪拆信号周更」和「沪拆信号发布校验」。这两项在新版上线前继续并行，上线后由所有者手动停用。
