"""PyInstaller giriş noktası: öğrenci uygulaması (python -m student_app.main ile aynı)."""

import sys

from student_app.main import main

if __name__ == "__main__":
    sys.exit(main())
