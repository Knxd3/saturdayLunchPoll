"""
Shared configuration defaults.
"""

import os

# Number of restaurants presented per weekly poll rotation.
WEEKLY_SELECTION_SIZE = max(1, int(os.environ.get("WEEKLY_SELECTION_SIZE", "10")))

