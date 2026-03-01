import sys
from pathlib import Path

if __name__ == "__main__":
    # Run as script (e.g. python main.py from package dir): add parent to path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from canon_lens_tester.ui_app import App
else:
    from .ui_app import App


def main() -> None:
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
