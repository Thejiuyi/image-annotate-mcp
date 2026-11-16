# Agensi 上架操作单

> 打包：`python listing/agensi/build.py` → `listing/agensi/dist/image-annotate-<版本>.zip`
> 上传：Creator Dashboard → Submit a Skill → 选 zip → 填下面第二节的文案 → 提交

## 一、先定三个决定

| 项 | 建议 | 理由 |
|---|---|---|
| 价格 | **$0 免费** | 免费不需要接 Stripe、不涉及退款冲销和税务；主要拿曝光和反链 |
| 名称 | `image-annotate` | 和 GitHub 仓库、skill 名一致；买家在 agent 的技能列表里看到的就是它 |
| 类目/标签 | 见下方 tags | 买家靠关键词搜索，标签决定能不能被搜到 |

⚠️ 免费上架**不需要**设置收款方式。这一条直接绕开条款里最容易咬人的两处
（30 天退款冲销、12 个月不完成 KYC 钱作废）。

## 二、可直接粘贴的文案

### Title

```
image-annotate
```

### Short description（列表页副标题）

```
Ask the user to draw a box on a screenshot; get back exact pixel coordinates, a name, and a cropped template PNG.
```

### Long description

```
Your agent cannot tell where a button is by looking at pixels. It guesses, clicks the
wrong place, and you spend three turns correcting it. The human knows exactly where it
is — they just need somewhere to click.

This skill opens a local page showing the screenshot. The user drags a box, clicks a
point, or draws a polygon, types a name, and hits save. You get back:

- coordinates in ORIGINAL-IMAGE pixels — not screen pixels, not CSS pixels, unaffected
  by browser zoom or display scaling
- the name the user typed
- a cropped template PNG ready for template matching (polygons are masked to the outline,
  so the corners of the bounding box are transparent)

Good for: computer-use agents, game HUD automation, RPA on internal tools, UI test
fixtures, anything where the layout lives only on the user's screen.

What is in the package:

- SKILL.md — the loop: open a session, ask the user to draw, wait for the save, read the
  result, close
- references/data-model.md — every field, the coordinate rules, what each template type
  contains
- references/troubleshooting.md — timeouts, busy ports, a proxy intercepting loopback
- examples/session-walkthrough.md — a full round trip with real payloads
- scripts/check_setup.py — read-only check of the prerequisites (installs nothing)

Requirements — please read before buying:

- Python 3.10 or newer
- the image-annotate-mcp server installed and registered in your MCP client (one-time
  setup, commands in the README)
- a browser on the same machine
- a human, about 10 seconds per annotation — this is human-in-the-loop by design, there
  is no unattended mode

MIT licensed. Source, tests and the web UI: https://github.com/Thejiuyi/image-annotate-mcp
```

### Tags

```
screenshot, coordinates, computer-use, ui-automation, template-matching,
image-annotation, human-in-the-loop, game-automation, vision
```

## 三、提交步骤

1. `https://www.agensi.io/` 注册账号 → Dashboard → Settings → 打开 **Creator Mode**
2. Creator Dashboard → **Submit a Skill**
3. 上传 `dist/image-annotate-0.3.0.zip`
4. 价格填 **0**（Free）
5. 粘上面第二节的文案和 tags
6. 封面/截图单独上传 —— **zip 里不能放图片**，他们的清单要求纯文本；用仓库里的
   `docs/screenshot.png` 和 `docs/demo.gif`
7. 提交 → 8 项自动扫描 → 人工审核，24–48 小时

## 四、如果审核卡住，这样回

最可能的打回理由是「skill 不够自包含」。原文照抄下面这段给审核：

```
This skill is a front-end for the image-annotate-mcp server, which runs locally and is
installed with one pip command. It is deliberately not self-contained: the whole point is
that a human draws on their own screen, so the package cannot bundle the runtime.

The package itself is text-only, contains no network calls, no subprocess, no environment
variable reads, and no install steps — scripts/check_setup.py only reads importlib
metadata and PATH, and prints the install command for the user to run manually.

If local-server dependencies are not eligible for the marketplace, tell me and I will
withdraw the submission.
```

## 五、上架之后要盯的三件事

- **§6.5 不能退出 agent 分发**：下架 listing 可以，但已进入渠道的部分撤不回。上传前想清楚。
- **免费版没有退款冲销**：这也是选 $0 的原因之一。将来改成付费，先补 KYC。
- **版本漂移**：改了仓库的 SKILL.md 或工具签名，记得重新 `build.py` + 在 Creator Studio 更新版本，
  否则买家拿到的是旧说明。

## 六、改完包之后

```bash
python listing/agensi/build.py     # 会重新校验结构、frontmatter、纯文本、单顶层文件夹
```

校验失败会直接列出问题并退出 1 —— 这一步是拿来替代「上传后等 24 小时被打回」的。
