#!/usr/bin/env python3
"""Hotmart Course Downloader — execute: python hotmark.py

O código fica em src/hotmart_downloader/ (veja docs/estrutura-do-projeto.md).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))

from hotmart_downloader.cli import main  # noqa: E402

if __name__ == '__main__':
    main()
