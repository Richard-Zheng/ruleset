#!/usr/bin/env python3
"""生成 sbbin/ 的 index.html。

用法：make_index.py <目录> <mihomo 版本> <sing-box 版本> [精简架构...]
输出到 stdout。
"""
from __future__ import annotations

import html
import os
import subprocess
import sys


def human(size: int) -> str:
    return f"{size/1048576:.2f} MiB" if size > 1048576 else f"{size/1024:.1f} KiB"


def is_upx(path: str) -> bool:
    with open(path, "rb") as f:
        return b"UPX!" in f.read()


def note(name: str, mihomo_ver: str, singbox_ver: str, lite_archs: list[str]) -> str:
    if name.startswith("mihomo"):
        parts = [f"mihomo {mihomo_ver}", "no_easytier"]
    else:
        parts = [f"sing-box {singbox_ver}"]
        lite = name.endswith("-lite") or any(f"-{arch}" == name[-len(arch) - 1:] for arch in lite_archs)
        parts.append("精简 tags" if lite else "完整 tags")
    return "，".join(parts)


def main() -> None:
    out, mihomo_ver, singbox_ver, *lite_archs = sys.argv[1:]

    rows = []
    for name in sorted(os.listdir(out)):
        path = os.path.join(out, name)
        if name == "index.html" or not os.path.isfile(path):
            continue
        sha = subprocess.run(
            ["sha256sum", path], capture_output=True, text=True
        ).stdout.split()[0]
        tags = note(name, mihomo_ver, singbox_ver, lite_archs)
        if is_upx(path):
            tags += "，UPX"
        rows.append((name, human(os.path.getsize(path)), tags, sha))

    print("""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>sbbin</title>
<style>
 body { font-family: system-ui, sans-serif; margin: 24px; line-height: 1.6; color: #222; }
 h1 { border-bottom: 1px solid #ddd; padding-bottom: 8px; font-size: 20px; }
 table { border-collapse: collapse; font-size: 14px; }
 th, td { text-align: left; padding: 6px 14px 6px 0; vertical-align: top; }
 th { border-bottom: 1px solid #ddd; }
 code { font-size: 12px; color: #555; word-break: break-all; }
 .note { color: #666; font-size: 13px; margin-top: 16px; max-width: 70ch; }
 a { color: #0366d6; text-decoration: none; }
 a:hover { text-decoration: underline; }
</style>
</head>
<body>
<h1>sbbin</h1>
<table>
<tr><th>文件</th><th>大小</th><th>说明</th><th>sha256</th></tr>""")

    for name, size, tags, sha in rows:
        print(
            f'<tr><td><a href="{html.escape(name)}">{html.escape(name)}</a></td>'
            f"<td>{size}</td><td>{html.escape(tags)}</td>"
            f"<td><code>{sha}</code></td></tr>"
        )

    print(
        """</table>
<p class="note">arm64 使用精简 tags（with_dhcp, with_wireguard, with_utls, with_clash_api,
badlinkname, tfogo_checklinkname0），amd64 使用官方完整 tags；UPX 版可用 <code>upx -d</code> 解压。
全部为 linux 静态二进制（CGO_ENABLED=0），amd64 侧 GOAMD64=v1，arm64 侧 GOARM64=v8.0。</p>
</body>
</html>"""
    )


if __name__ == "__main__":
    main()
