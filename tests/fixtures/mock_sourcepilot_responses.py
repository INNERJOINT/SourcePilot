"""
SourcePilot HTTP API mock 响应数据

从 test_mcp_server.py 提取的共享 mock 数据。
"""

MOCK_SP_SEARCH_RESULTS = [
    {
        "title": "frameworks/base/services/core/java/com/android/server/SystemServer.java",
        "content": "L120: private void startBootstrapServices() {",
        "score": 0.825,
        "metadata": {
            "repo": "frameworks/base",
            "path": "services/core/java/com/android/server/SystemServer.java",
            "start_line": 117,
            "end_line": 123,
        },
    },
    {
        "title": "frameworks/base/services/core/java/com/android/server/SystemService.java",
        "content": "L45: public abstract class SystemService {",
        "score": 0.634,
        "metadata": {
            "repo": "frameworks/base",
            "path": "services/core/java/com/android/server/SystemService.java",
        },
    },
]

MOCK_SP_REPOS = [
    {"name": "frameworks/base", "url": ""},
]

MOCK_SP_FILE_CONTENT = {
    "content": "L1: package com.android.server;\nL2: \nL3: import android.os.Process;\nL4: \nL5: public class SystemServer {",
    "total_lines": 5,
    "repo": "frameworks/base",
    "filepath": "test.java",
    "start_line": 1,
    "end_line": 5,
}
