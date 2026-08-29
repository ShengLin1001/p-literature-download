#!/usr/bin/env python
"""Backward-compatible entry point for the official-site-only downloader."""

from pdf_download import build_parser, main, selftest


if __name__ == "__main__":
    args = build_parser().parse_args()
    selftest() if args.selftest else main(args)
