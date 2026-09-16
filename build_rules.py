#!/usr/bin/env python3

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import unicodedata
from difflib import SequenceMatcher
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path


SING_BOX_VERSION = "1.12.12"
MIHOMO_VERSION = "1.19.17"

SUKKA_REPO = "https://github.com/SukkaLab/ruleset.skk.moe.git"
META_REPO = "https://github.com/MetaCubeX/meta-rules-dat.git"

# Sukka 的水印字符串会不定期变形，例如把字母替换成形状相似的数字：
#   this.ruleset.is.made.by.sukkaw.skk.moe
#   7h15.ru1353t.1s.m4d3.by.5ukk4w.skk.moe
#
# 因此不再维护固定黑名单，而是做“视觉同形归一化 + 模糊匹配”。
_CONFUSABLE_TRANSLATION = str.maketrans({
    # i / l / 1 在这种水印里经常互换，统一成同一个占位字符。
    "i": "1",
    "l": "1",
    "1": "1",
    "|": "1",
    "!": "1",

    "o": "o",
    "0": "o",

    "e": "e",
    "3": "e",

    "a": "a",
    "4": "a",
    "@": "a",

    "s": "s",
    "5": "s",
    "$": "s",

    "t": "t",
    "7": "t",

    "b": "b",
    "8": "b",

    # 偶尔也有人用 6/9 冒充 g。
    "g": "g",
    "6": "g",
    "9": "g",
})


def normalize_visual_text(value: object) -> str:
    """Normalize common leetspeak/lookalike substitutions and separators."""
    value = unicodedata.normalize("NFKC", str(value)).lower()
    value = value.translate(_CONFUSABLE_TRANSLATION)
    # 忽略点号、横线、下划线、空格等分隔符。
    return re.sub(r"[^a-z0-9]+", "", value)


_JUNK_CANONICAL = tuple(
    normalize_visual_text(x)
    for x in (
        "this ruleset is made by sukkaw skk moe",
        "this ruleset is made by sukkaw ruleset skk moe",
    )
)
_JUNK_CORE = normalize_visual_text("this ruleset is made by sukkaw")


def is_junk_watermark(value: object) -> bool:
    """
    Detect Sukka watermark strings even if separators or lookalike characters
    change in future versions.
    """
    normalized = normalize_visual_text(value)

    # 普通短域名不参与 fuzzy match，降低误杀概率。
    if len(normalized) < 20:
        return False

    # 最常见情况：主体句子仍然完整，只改了分隔符/leet 字符。
    if _JUNK_CORE in normalized:
        return True

    # 再容忍少量新增、删除、替换字符。
    return any(
        SequenceMatcher(None, normalized, target).ratio() >= 0.88
        for target in _JUNK_CANONICAL
    )

MOSDNS_KEY_MAP = {
    "domain_suffix": "domain:",
    "domain": "full:",
    "domain_keyword": "keyword:",
    "domain_regex": "regexp:",
}


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(map(str, cmd)))
    return subprocess.run(
        [str(x) for x in cmd],
        cwd=cwd,
        check=check,
        text=True,
        capture_output=capture_output,
    )


def download(url: str, dst: Path) -> None:
    print(f">>> Downloading {url}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, open(dst, "wb") as f:
        shutil.copyfileobj(response, f)


def normalize_arch() -> tuple[str, str]:
    machine = platform.machine().lower()

    if machine in {"x86_64", "amd64"}:
        return "amd64", "amd64-v3"
    if machine in {"aarch64", "arm64"}:
        return "arm64", "arm64"

    raise RuntimeError(f"Unsupported architecture: {machine}")


def make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_tools(tool_dir: Path) -> tuple[Path, Path]:
    tool_dir.mkdir(parents=True, exist_ok=True)

    sing_bin = tool_dir / "sing-box"
    mihomo_bin = tool_dir / "mihomo"

    sing_arch, mihomo_arch = normalize_arch()

    if not sing_bin.exists():
        archive = tool_dir / "sing-box.tar.gz"
        url = (
            f"https://github.com/SagerNet/sing-box/releases/download/"
            f"v{SING_BOX_VERSION}/sing-box-{SING_BOX_VERSION}-linux-{sing_arch}.tar.gz"
        )
        download(url, archive)

        with tarfile.open(archive, "r:gz") as tf:
            member_name = f"sing-box-{SING_BOX_VERSION}-linux-{sing_arch}/sing-box"
            member = tf.getmember(member_name)
            member.name = "sing-box"
            tf.extract(member, path=tool_dir)

        archive.unlink()
        make_executable(sing_bin)

    if not mihomo_bin.exists():
        archive = tool_dir / "mihomo.gz"
        url = (
            f"https://github.com/MetaCubeX/mihomo/releases/download/"
            f"v{MIHOMO_VERSION}/mihomo-linux-{mihomo_arch}-v{MIHOMO_VERSION}.gz"
        )
        download(url, archive)

        with gzip.open(archive, "rb") as src, open(mihomo_bin, "wb") as dst:
            shutil.copyfileobj(src, dst)

        archive.unlink()
        make_executable(mihomo_bin)

    return sing_bin, mihomo_bin


def clone_repo(url: str, dst: Path, *, branch: str | None = None) -> None:
    if dst.exists():
        shutil.rmtree(dst)

    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["-b", branch, "--single-branch"]
    cmd += [url, str(dst)]
    run(cmd)


def copy_or_move(src: Path, dst: Path, *, move: bool = False) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)

    if src.is_dir():
        if move:
            shutil.move(str(src), str(dst))
        else:
            shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        if move:
            shutil.move(str(src), str(dst))
        else:
            shutil.copy2(src, dst)


def prepare_sing_sources(
    repo_root: Path,
    sukka_repo: Path,
    meta_repo: Path,
    sing_dir: Path,
) -> None:
    sukka_src = sukka_repo / "sing-box"

    if sing_dir.exists():
        shutil.rmtree(sing_dir)

    (sing_dir / "sukka").mkdir(parents=True)
    (sing_dir / "metacubex/domainset/notcn").mkdir(parents=True)

    print(">>> Copying Sing-box rule sources...")

    for item in sukka_src.iterdir():
        copy_or_move(item, sing_dir / "sukka" / item.name)

    meta_mapping = {
        "geo-lite/geosite/*.json": "metacubex/domainset",
        "geo/geosite/cn.json": "metacubex/domainset",
        "geo/geosite/gfw.json": "metacubex/domainset",
        "geo/geosite/geolocation-!cn.json": "metacubex/domainset/notcn.json",
        "geo/geosite/cloudflare.json": "metacubex/domainset/cloudflare.json",
        "geo/geosite/cloudflare-cn.json": "metacubex/domainset/cloudflare-cn.json",
        "geo/geosite/googlefcm.json": "metacubex/domainset/googlefcm.json",
        "geo/geosite/google.json": "metacubex/domainset/google.json",
        "geo/geosite/google-cn.json": "metacubex/domainset/google-cn.json",
        "geo/geosite/google@cn.json": "metacubex/domainset/google@cn.json",
    }

    for src_pattern, dst_rel in meta_mapping.items():
        if "*" in src_pattern:
            pattern_path = Path(src_pattern)
            parent = meta_repo / pattern_path.parent
            for src in parent.glob(pattern_path.name):
                copy_or_move(src, sing_dir / dst_rel / src.name)
        else:
            src = meta_repo / src_pattern
            if not src.exists():
                continue

            dst = sing_dir / dst_rel
            if dst.suffix == ".json":
                copy_or_move(src, dst)
            else:
                copy_or_move(src, dst / src.name)

    own_dir = repo_root / "own"
    if own_dir.exists():
        shutil.copytree(own_dir, sing_dir / "own", dirs_exist_ok=True)


def clean_sing_json(sing_dir: Path) -> None:
    print(">>> Cleaning Sing-box JSON rules...")

    for json_file in sing_dir.rglob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"Skipping invalid JSON: {json_file}")
            continue

        modified = False

        if "metacubex" in json_file.parts and data.get("version") == 1:
            data["version"] = 2
            modified = True

        rules = data.get("rules")
        if isinstance(rules, list):
            cleaned_rules = []

            for rule in rules:
                if not isinstance(rule, dict):
                    cleaned_rules.append(rule)
                    continue

                if "process_name" in rule:
                    del rule["process_name"]
                    modified = True

                if json_file.name == "reject.json" and "domain_keyword" in rule:
                    del rule["domain_keyword"]
                    modified = True

                keys_to_remove: list[str] = []

                for key in list(rule.keys()):
                    val = rule[key]
                    if not isinstance(val, list):
                        continue

                    new_val = [
                        x for x in val
                        if not is_junk_watermark(x)
                    ]

                    if (
                        json_file.name == "reject.json"
                        and key in {"domain", "domain_suffix"}
                    ):
                        new_val = [
                            x for x in new_val
                            if "juejin" not in str(x)
                        ]

                    path_posix = json_file.as_posix()
                    if (
                        key == "ip_cidr"
                        and "/sukka/" in f"/{path_posix}"
                        and (
                            "/domainset/" in f"/{path_posix}"
                            or "/non_ip/" in f"/{path_posix}"
                        )
                    ):
                        new_val = []

                    if new_val != val:
                        rule[key] = new_val
                        modified = True

                    if not new_val:
                        keys_to_remove.append(key)

                for key in keys_to_remove:
                    rule.pop(key, None)
                    modified = True

                if rule:
                    cleaned_rules.append(rule)

            if len(cleaned_rules) != len(rules):
                modified = True

            data["rules"] = cleaned_rules

        if not data.get("rules"):
            print(f"Deleting empty file: {json_file}")
            json_file.unlink()
            continue

        if modified:
            json_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )


def compile_sing(sing_dir: Path, sing_bin: Path) -> None:
    print(">>> Compiling Sing-box rules...")

    for srs in sing_dir.rglob("*.srs"):
        srs.unlink()

    for json_file in sorted(sing_dir.rglob("*.json")):
        print(f"Compiling {json_file}")
        result = run(
            [sing_bin, "rule-set", "compile", json_file],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"sing-box failed compiling {json_file}:\n{result.stderr}"
            )


def generate_mosdns(sing_dir: Path, mosdns_dir: Path) -> None:
    print(">>> Generating MosDNS rules...")

    if mosdns_dir.exists():
        shutil.rmtree(mosdns_dir)
    mosdns_dir.mkdir(parents=True)

    for json_file in sing_dir.rglob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

        lines: set[str] = set()

        for rule in data.get("rules", []):
            if not isinstance(rule, dict):
                continue

            for sb_key, prefix in MOSDNS_KEY_MAP.items():
                if sb_key not in rule:
                    continue

                items = rule[sb_key]
                if isinstance(items, str):
                    items = [items]

                if isinstance(items, list):
                    for item in items:
                        lines.add(f"{prefix}{item}")

        if not lines:
            continue

        rel_path = json_file.relative_to(sing_dir)
        txt_file = (mosdns_dir / rel_path).with_suffix(".txt")
        txt_file.parent.mkdir(parents=True, exist_ok=True)
        txt_file.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")


def prepare_mihomo(
    sukka_repo: Path,
    mihomo_dir: Path,
    mihomo_bin: Path,
) -> None:
    sukka_src = sukka_repo / "Clash"

    if mihomo_dir.exists():
        shutil.rmtree(mihomo_dir)

    sukka_dst = mihomo_dir / "sukka"
    sukka_dst.mkdir(parents=True)

    print(">>> Copying Mihomo rule sources...")

    for item in sukka_src.iterdir():
        copy_or_move(item, sukka_dst / item.name)

    print(">>> Cleaning and compiling Mihomo rules...")

    for txt_file in sorted(mihomo_dir.rglob("*.txt")):
        lines = txt_file.read_text(encoding="utf-8").splitlines(keepends=True)

        path_posix = txt_file.as_posix()
        is_ip_folder = "/sukka/ip/" in f"/{path_posix}"

        new_lines: list[str] = []

        for line in lines:
            content = line.strip()

            if is_junk_watermark(content):
                continue

            if txt_file.name == "reject.txt" and "juejin" in content:
                continue

            if is_ip_folder:
                if content.startswith("IP-CIDR"):
                    parts = content.split(",")
                    if len(parts) >= 2:
                        new_lines.append(parts[1].strip() + "\n")
            else:
                new_lines.append(line if line.endswith("\n") else line + "\n")

        if not new_lines:
            print(f"Deleting empty file: {txt_file}")
            txt_file.unlink()
            continue

        txt_file.write_text("".join(new_lines), encoding="utf-8")

        # Mihomo will panic with "empty rule" if a text ruleset contains only
        # comments / blank lines. Detect that before invoking convert-ruleset.
        effective_lines = [
            line.strip()
            for line in new_lines
            if line.strip()
            and not line.lstrip().startswith(("#", ";"))
        ]

        is_deprecated = any(
            "Sukka's Ruleset - Deprecated" in line.lower()
            for line in new_lines
        )

        if not effective_lines:
            print(
                f"WARNING: ruleset contains no effective rules, "
                f"skipping Mihomo compilation: {txt_file}"
            )
            continue

        if is_deprecated:
            print(
                f"WARNING: deprecated ruleset, skipping Mihomo compilation: "
                f"{txt_file}"
            )
            continue

        rule_type = "ipcidr" if is_ip_folder else "domain"
        mrs_path = txt_file.with_suffix(".mrs")

        result = run(
            [
                mihomo_bin,
                "convert-ruleset",
                rule_type,
                "text",
                txt_file,
                mrs_path,
            ],
            capture_output=True,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"mihomo failed compiling {txt_file}:\n{result.stderr}"
            )


def build(repo_root: Path, output_dir: Path, keep_workdir: bool = False) -> None:
    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()

    tool_dir = repo_root / ".cache/rule-build-tools"

    work_ctx = tempfile.TemporaryDirectory(prefix="rule-build-")
    work_dir = Path(work_ctx.name)

    try:
        sing_bin, mihomo_bin = install_tools(tool_dir)

        sukka_repo = work_dir / "ruleset_src"
        meta_repo = work_dir / "meta_src"

        clone_repo(SUKKA_REPO, sukka_repo)
        clone_repo(META_REPO, meta_repo, branch="sing")

        if output_dir.exists():
            shutil.rmtree(output_dir)

        mihomo_dir = output_dir / "mihomo"
        sing_dir = output_dir / "sing"
        mosdns_dir = output_dir / "mosdns"

        output_dir.mkdir(parents=True)

        prepare_sing_sources(repo_root, sukka_repo, meta_repo, sing_dir)
        clean_sing_json(sing_dir)
        compile_sing(sing_dir, sing_bin)

        generate_mosdns(sing_dir, mosdns_dir)

        prepare_mihomo(sukka_repo, mihomo_dir, mihomo_bin)

        print()
        print(">>> Build complete")
        print(f"    {mihomo_dir}")
        print(f"    {sing_dir}")
        print(f"    {mosdns_dir}")

        if keep_workdir:
            kept = repo_root / ".rule-build-work"
            if kept.exists():
                shutil.rmtree(kept)
            shutil.copytree(work_dir, kept)
            print(f">>> Temporary sources copied to {kept}")

    finally:
        work_ctx.cleanup()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Mihomo, Sing-box and MosDNS rules into gh-pages/"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("gh-pages"),
        help="Output directory (default: ./gh-pages)",
    )
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Keep cloned temporary repositories in .rule-build-work/",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    repo_root = Path.cwd()
    build(repo_root, args.output, args.keep_workdir)


if __name__ == "__main__":
    main()
