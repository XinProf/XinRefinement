"""``python -m xinrefinement.cli`` 入口：转发到 refine.main()。"""
from __future__ import annotations

from xinrefinement.cli.refine import main

if __name__ == "__main__":
    raise SystemExit(main())
