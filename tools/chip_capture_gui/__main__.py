from __future__ import annotations

import sys


def main() -> int:
    argv = sys.argv[1:]
    if "--opencv" in argv:
        argv = [arg for arg in argv if arg != "--opencv"]
        from .opencv_app import main as opencv_main

        return opencv_main(argv)

    try:
        from .app import main as qt_main
    except ModuleNotFoundError as exc:
        if exc.name != "PyQt5":
            raise
        from .opencv_app import main as opencv_main

        print("PyQt5 is not available; falling back to OpenCV interface.", file=sys.stderr)
        return opencv_main(argv)
    return qt_main()


if __name__ == "__main__":
    raise SystemExit(main())
