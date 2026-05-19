from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
    if "--opencv" in argv:
        raise SystemExit("OpenCV GUI has been removed. Use the Qt GUI without --opencv.")

    from .app import main as qt_main
    return qt_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
