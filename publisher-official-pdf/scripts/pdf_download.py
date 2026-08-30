#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""按 DOI 列表下载期刊官网正文 PDF，并用 mymetal 统一命名。

scansci-pdf 自己会把 PDF 写成 <safe_doi>_Official.pdf 并默认落在用户级 papers 目录，
本脚本负责期刊元数据预检、输出目录、初始化编排和最终命名。

命名规则: 年份-期刊缩写-标题前十个有效字符.pdf。
    10.1103/PhysRevB.88.064104 ->
    2013-PRB-Effect-of-st.pdf

用法:
    scanscipy                                     # 先激活 scansci-pdf venv
    python pdf_download.py                        # 读 ./dois.txt，PDF 落 ./
    python pdf_download.py dois.txt --dry-run
    python pdf_download.py dois.txt -o refs/ --initialize --wait 600
    python pdf_download.py dois.txt -o refs/ --skip-existing --retries 1
    python pdf_download.py dois.txt -o refs/ --report
    python pdf_download.py dois.txt --manual       # 仅在自动模式失败时人工兜底
    python pdf_download.py --selftest
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from mymetal.academic.search.literature_download import (
    check_journal_metadata,
    fetch_doi_metadata,
    generate_pdf_filename,
    is_complete_pdf,
    normalize_doi,
    parse_dois,
)

# Windows 控制台按 UTF-8，避免论文元数据乱码（与 CLAUDE.md 约定一致）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

def fail(msg):
    print("❌ ERROR: " + str(msg))
    raise SystemExit(1)


def scansci_name(doi):
    """scansci-pdf browser-get 实际写出的文件名，用来定位待重命名的文件。"""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", doi).strip("_") or "paper"
    return stem + "_Official.pdf"


def sync_report_filenames(path_report, dict_filename):
    """Keep the browser report aligned with wrapper-renamed PDF files."""
    if not path_report or not path_report.is_file():
        return
    report = json.loads(path_report.read_text(encoding="utf-8"))
    for item in report:
        if item.get("success") and item.get("doi") in dict_filename:
            item["file"] = dict_filename[item["doi"]]
    path_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(args):
    ### check
    path_file = Path(args.dois).expanduser()
    if not path_file.is_file():
        fail("找不到 DOI 列表：" + str(path_file))
    if args.initialize and args.manual:
        fail("--initialize 和 --manual 不能同时使用")
    if not 0 <= args.retries <= 3:
        fail("--retries 必须在 0–3 之间")
    exe = shutil.which(args.scansci_pdf)
    if exe is None and not args.dry_run:
        fail("PATH 中找不到 " + args.scansci_pdf + "；请先在 bash 里运行 `scanscipy` 激活 venv。")
    exe = exe or args.scansci_pdf
    ### to here

    ### prepare
    ldoi = parse_dois(path_file)
    if not ldoi:
        fail(str(path_file) + " 中没有有效 DOI")
    path_out = Path(args.output).expanduser().resolve()
    path_out.mkdir(parents=True, exist_ok=True)

    ltodo, dict_filename, lskip = [], {}, []
    for doi in ldoi:
        metadata = fetch_doi_metadata(doi)
        reason = check_journal_metadata(metadata)
        if reason:
            lskip.append((doi, reason))
            print("⏭️  跳过 " + doi + "：" + reason)
            continue
        filename = generate_pdf_filename(metadata)
        dict_filename[doi] = filename
        if not args.initialize and args.skip_existing and is_complete_pdf(path_out / filename):
            print("📁 已存在，跳过：" + filename)
            continue
        ltodo.append(doi)
    print("📁 列表：" + str(path_file))
    print("📁 落盘目录：" + str(path_out))
    print("📊 待下载 " + str(len(ltodo)) + " / 共 " + str(len(ldoi)) + " 篇\n")
    if not ltodo:
        print("🎉 没有需要处理的期刊正文")
        if lskip:
            raise SystemExit(1)
        return
    ### to here

    ### main：默认由 CloakBrowser 自主处理；--manual 才需要用户逐篇操作
    cmd = [exe, "browser-get", *ltodo, "--output", str(path_out), "--wait", str(args.wait)]
    path_report = None
    if args.initialize:
        cmd.append("--initialize")
    else:
        cmd.extend(["--retries", str(args.retries)])
    if args.manual:
        cmd.append("--manual")
    if args.report:
        path_report = Path(args.report)
        if not path_report.is_absolute():
            path_report = path_out / path_report
        cmd.extend(["--report", str(path_report)])
    print("▶️  $ " + " ".join(cmd) + "\n")
    if args.dry_run:
        for doi in ltodo:
            print("  " + doi + "  →  " + str(path_out / dict_filename[doi]))
        return
    child_env = os.environ.copy()
    child_env.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    child_env.setdefault("CLOAKBROWSER_VERSION", "151.0.7922.108.2")
    if args.initialize:
        completed = subprocess.run(cmd, env=child_env, check=False)
        if completed.returncode:
            fail("初始化失败；浏览器未成功启动或页面未完成。")
        print("\n✅ 初始化结束；请去掉 --initialize 后执行自动下载。")
        return
    t_start = time.time()
    subprocess.run(cmd, env=child_env)  # 部分失败时 rc=1，逐篇结果下面按落盘文件判定，rc 不用
    ### to here

    ### summary：只认这轮新写出的文件，避免把上轮残留的 _Official.pdf 误判为成功
    lok, lfail = [], []
    for doi in ltodo:
        path_src = path_out / scansci_name(doi)
        if (
                path_src.is_file()
                and path_src.stat().st_mtime >= t_start - 1
                and is_complete_pdf(path_src)):
            path_dst = path_out / dict_filename[doi]
            os.replace(path_src, path_dst)  # 覆盖同名旧版；Windows 上 Path.rename 遇同名会炸
            lok.append((doi, path_dst))
        else:
            lfail.append(doi)
    sync_report_filenames(path_report, dict_filename)

    print("\n================ 📊 summary")
    for doi, path_dst in lok:
        print("   成功  " + doi + "  →  " + path_dst.name)
    for doi in lfail:
        print("   失败  " + doi)
    for doi, reason in lskip:
        print("   跳过  " + doi + "  (" + reason + ")")
    print("成功 " + str(len(lok)) + " · 失败 " + str(len(lfail))
          + " · 跳过 " + str(len(lskip)) + " · 共 " + str(len(ldoi)))
    if lfail or lskip:
        if lfail:
            print("❌ 已在同一浏览器会话内自动重试；仍失败的篇目需补足权限后再运行。")
        raise SystemExit(1)
    print("🎉 全部完成")
    ### to here


def selftest():
    assert normalize_doi(" https://doi.org/10.1016/x ") == "10.1016/x"
    assert normalize_doi("doi: 10.1016/x") == "10.1016/x"
    assert scansci_name("10.1016/j.actamat.2024.120459") == "10.1016_j.actamat.2024.120459_Official.pdf"
    metadata = {
        "type": "journal-article",
        "title": ["Effect of strain on the stacking fault energy of copper"],
        "container-title": ["Physical Review B"],
        "published-print": {"date-parts": [[2013]]},
    }
    assert generate_pdf_filename(metadata) == (
        "2013-PRB-Effect-of-st.pdf")

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path_file = Path(tmp) / "dois.txt"
        path_file.write_text("﻿10.1016/a\n\n# c\n10.1016/a\n10.1103/b 金薄膜相变\n", encoding="utf-8")
        assert parse_dois(path_file) == ["10.1016/a", "10.1103/b"]
        path_pdf = Path(tmp) / "complete.pdf"
        path_pdf.write_bytes(b"%PDF-1.7" + b"0" * 5000 + b"%%EOF")
        assert is_complete_pdf(path_pdf)
        path_report = Path(tmp) / "report.json"
        path_report.write_text(
            '[{"doi":"10.1103/b","success":true,"file":"old.pdf"}]',
            encoding="utf-8",
        )
        sync_report_filenames(path_report, {"10.1103/b": "new.pdf"})
        assert json.loads(path_report.read_text(encoding="utf-8"))[0]["file"] == "new.pdf"
    print("✅ selftest ok")


def build_parser():
    parser = argparse.ArgumentParser(description="按 dois.txt 批量 scansci-pdf browser-get 下载官网 PDF")
    parser.add_argument("dois", nargs="?", default="dois.txt", help="DOI 列表，每行一个 DOI（默认 ./dois.txt）")
    parser.add_argument("-o", "--output", default=".", help="PDF 输出目录（默认当前目录 ./）")
    parser.add_argument("--wait", type=int, default=180, help="每篇自动等待秒数（默认 180）")
    parser.add_argument("--initialize", action="store_true",
                        help="只初始化 hCaptcha / SSO / MFA 会话，不下载 PDF")
    parser.add_argument("--retries", type=int, default=1,
                        help="自动下载失败后在同一会话重试次数（0–3，默认 1）")
    parser.add_argument("--manual", action="store_true",
                        help="人工兜底：手动过验证、登录并打开正文 PDF（默认不启用）")
    parser.add_argument("--report", nargs="?", const="browser-get-report.json", default="",
                        help="在输出目录写精简 JSON 报告；可选指定文件名")
    parser.add_argument("--skip-existing", dest="skip_existing", action="store_true",
                        help="目标 PDF 已存在时跳过（默认强制重抓，确保拿官网当前版）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令与落盘文件名，不真正下载")
    parser.add_argument("--scansci-pdf", dest="scansci_pdf", default="scansci-pdf",
                        help="scansci-pdf 命令（默认走 PATH，需先 scanscipy 激活）")
    parser.add_argument("--selftest", action="store_true", help="跑命名 / 解析自检，不下载")
    return parser


if __name__ == "__main__":
    _args = build_parser().parse_args()
    if _args.selftest:
        selftest()
    else:
        main(_args)
