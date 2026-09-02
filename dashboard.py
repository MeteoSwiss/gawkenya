#!/usr/bin/env python3
"""Compatibility entry point for the static GAW Kenya dashboard builder.

The old Dash/FastAPI prototype at this path has been replaced by a static-site
builder suitable for GitHub Pages. The implementation lives under
``monitoring/dashboard``.
"""

from monitoring.dashboard.build_dashboard import main


if __name__ == "__main__":
    main()
