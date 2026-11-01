"""Original editor backed by the common outbound bridge."""
import re
from src.plugins.management.bridge import EditorBridge as SharedBridge

API_PATH = re.compile(r"(?:me|games|search|songs/[1-9][0-9]*|requests(?:/[1-9][0-9]*(?:/(?:review|withdraw))?)?|candidates(?:/[1-9][0-9]*/decide)?|associate|imports(?:/[1-9][0-9]*(?:/records)?)?|events|logout)")

class EditorBridge(SharedBridge):
    def __init__(self, portal, url, token):
        super().__init__(portal, url, token, api_path=API_PATH)
