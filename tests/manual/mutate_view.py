"""变异测试：故意把视图逻辑改坏，确认 e2e_view.py 会红。

    .venv/Scripts/python.exe tests/manual/mutate_view.py

用法说明：判据是「跑挂了 + 有 FAIL 行提到关键词」，**不要绑死整句断言文案** ——
断言改个名字就会把「跑红」记成「存活」，那是假绿的反面（假存活）。
同理，跑器必须是项目 venv 里的解释器，否则 E2E 会因为缺 PIL 直接崩掉，
也会被误判成「存活」。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE.parents[1] / "src" / "image_annotate_mcp" / "web" / "index.html"
ORIG = TARGET.read_bytes()

MUTANTS = [
    (
        "放大镜取样区偏移（sx 从 N/2 改成 N/3）",
        "  const sx = ix - N/2, sy = iy - N/2;",
        "  const sx = ix - N/3, sy = iy - N/3;",
        "放大镜中心",
    ),
    (
        "缩放锚点漏掉缩放倍数",
        "  S.panX = vx - fx * nz;\n  S.panY = vy - fy * nz;",
        "  S.panX = vx - fx;\n  S.panY = vy - fy;",
        "锚点下的图像像素",
    ),
    (
        "滚轮开关失效（不看 S.wheelZoom）",
        "  if (!S.wheelZoom || !cur()) return;",
        "  if (!cur()) return;",
        "关掉滚轮缩放后滚轮无效",
    ),
    (
        "放大镜不再跟随指针",
        "  if (!S.loupe || S.loupePinned) return;\n  const r = stage.getBoundingClientRect();",
        "  if (true) return;\n  const r = stage.getBoundingClientRect();",
        "拖标题栏把窗口挪走了",
    ),
]


def run_e2e() -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, str(HERE / "e2e_view.py")],
        capture_output=True,
        text=True,
        timeout=300,
    )
    return p.returncode, p.stdout + p.stderr


def main() -> int:
    killed = 0
    for label, old, new, key in MUTANTS:
        text = ORIG.decode("utf-8")
        if text.count(old) != 1:
            print(f"[SKIP] {label}: 锚点命中 {text.count(old)} 次")
            continue
        TARGET.write_bytes(text.replace(old, new).encode("utf-8"))
        try:
            rc, out = run_e2e()
            fails = [ln for ln in out.splitlines() if ln.startswith("[FAIL]")]
            dead = rc != 0 and any(key in ln for ln in fails)
            print(f"{'KILLED  ' if dead else 'SURVIVED'} | {label}")
            for ln in fails[:3]:
                print("           " + ln.strip())
            if dead:
                killed += 1
        finally:
            TARGET.write_bytes(ORIG)

    print(f"\n{killed}/{len(MUTANTS)} 被杀死")
    return 0 if killed == len(MUTANTS) else 1


if __name__ == "__main__":
    sys.exit(main())
