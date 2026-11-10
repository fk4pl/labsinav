"""PyInstaller giriş noktası: eğitmen uygulaması (python -m instructor_app.main ile aynı)."""

import sys

from instructor_app.main import main

if __name__ == "__main__":
    sys.exit(main())
