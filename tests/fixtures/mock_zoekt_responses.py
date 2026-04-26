"""
Zoekt HTTP API mock 响应数据

从 test_sourcepilot.py 和 test_api_contract.py 提取的共享 mock 数据。
"""

MOCK_SEARCH_RESPONSE = {
    "Result": {
        "FileMatches": [
            {
                "Repo": "frameworks/base",
                "FileName": "services/core/java/com/android/server/SystemServer.java",
                "Score": 25.5,
                "Matches": [
                    {
                        "LineNum": 120,
                        "Fragments": [
                            {"Pre": "private void ", "Match": "startBootstrapServices", "Post": "() {"}
                        ]
                    }
                ]
            },
            {
                "Repo": "frameworks/base",
                "FileName": "services/core/java/com/android/server/SystemService.java",
                "Score": 15.2,
                "Matches": [
                    {
                        "LineNum": 45,
                        "Fragments": [
                            {"Pre": "public abstract class ", "Match": "SystemService", "Post": " {"}
                        ]
                    }
                ]
            },
        ],
        "Stats": {"MatchCount": 2, "FileCount": 2}
    }
}

MOCK_EMPTY_SEARCH_RESPONSE = {
    "Result": {
        "FileMatches": [],
        "Stats": {"MatchCount": 0, "FileCount": 0}
    }
}

MOCK_REPO_RESPONSE = {
    "Result": {
        "FileMatches": [
            {
                "Repo": "frameworks/base",
                "FileName": "services/core/java/com/android/server/SystemServer.java",
                "Score": 25.5,
                "Matches": [
                    {
                        "LineNum": 120,
                        "Fragments": [
                            {"Pre": "private void ", "Match": "startBootstrapServices", "Post": "() {"}
                        ]
                    }
                ]
            },
        ],
        "Stats": {"MatchCount": 1, "FileCount": 1}
    }
}

MOCK_FILE_CONTENT_HTML = """
<html><body>
<pre><span class="noselect"><a href="#l1">1</a>: </span>package com.android.server;</pre>
<pre><span class="noselect"><a href="#l2">2</a>: </span></pre>
<pre><span class="noselect"><a href="#l3">3</a>: </span>import android.os.Process;</pre>
<pre><span class="noselect"><a href="#l4">4</a>: </span></pre>
<pre><span class="noselect"><a href="#l5">5</a>: </span>public class SystemServer {</pre>
</body></html>
"""
