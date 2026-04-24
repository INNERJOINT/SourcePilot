"""
Tests for Feishu collection isolation and routing in gateway.py.
No live Milvus/Feishu services required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.projects import ProjectConfig

# ─── Test project fixtures ────────────────────────────────────────────────────

PROJECT_ACE = ProjectConfig(
    name="ace",
    source_root="/src/ace",
    repo_path="/repo/ace",
    index_dir="/idx/ace",
    zoekt_url="http://zoekt-ace:6070",
    dense_collection_name="aosp_code_ace",
    project_type="aosp",
)

PROJECT_FEISHU = ProjectConfig(
    name="feishu_lurk",
    source_root="",
    repo_path="",
    index_dir="",
    zoekt_url="",
    dense_collection_name="feishu_lurk_docs",
    project_type="feishu",
)

PROJECTS = [PROJECT_ACE, PROJECT_FEISHU]


def _patch_projects(monkeypatch):
    import config.projects as cp

    monkeypatch.setattr(cp, "_projects_cache", PROJECTS)


# ─── _is_zoekt_project ────────────────────────────────────────────────────────


class TestIsZoektProject:
    def test_aosp_project_is_zoekt(self, monkeypatch):
        _patch_projects(monkeypatch)
        import gateway.gateway as gw

        assert gw._is_zoekt_project("ace") is True

    def test_feishu_project_is_not_zoekt(self, monkeypatch):
        _patch_projects(monkeypatch)
        import gateway.gateway as gw

        assert gw._is_zoekt_project("feishu_lurk") is False

    def test_default_project_is_zoekt(self, monkeypatch):
        _patch_projects(monkeypatch)
        import gateway.gateway as gw

        # Default project is ace (first in list), which has zoekt_url
        assert gw._is_zoekt_project(None) is True


# ─── _get_dense_adapter collection isolation ─────────────────────────────────


class TestGetDenseAdapterFeishuIsolation:
    def test_ace_adapter_uses_aosp_collection(self, monkeypatch):
        _patch_projects(monkeypatch)
        import gateway.gateway as gw

        gw._dense_adapter = None
        monkeypatch.setattr("config.DENSE_ENABLED", True)

        created = {}

        def _fake_dense(**kwargs):
            inst = MagicMock()
            inst.collection_name = kwargs["collection_name"]
            created[kwargs["collection_name"]] = inst
            return inst

        with patch("adapters.dense.DenseAdapter", side_effect=_fake_dense):
            adapter = gw._get_dense_adapter("ace")

        assert adapter.collection_name == "aosp_code_ace"

    def test_feishu_adapter_uses_feishu_collection(self, monkeypatch):
        _patch_projects(monkeypatch)
        import gateway.gateway as gw

        gw._dense_adapter = None
        monkeypatch.setattr("config.DENSE_ENABLED", True)

        def _fake_dense(**kwargs):
            inst = MagicMock()
            inst.collection_name = kwargs["collection_name"]
            return inst

        with patch("adapters.dense.DenseAdapter", side_effect=_fake_dense):
            adapter = gw._get_dense_adapter("feishu_lurk")

        assert adapter.collection_name == "feishu_lurk_docs"

    def test_ace_and_feishu_adapters_are_different_instances(self, monkeypatch):
        _patch_projects(monkeypatch)
        import gateway.gateway as gw

        gw._dense_adapter = None
        monkeypatch.setattr("config.DENSE_ENABLED", True)

        def _fake_dense(**kwargs):
            inst = MagicMock()
            inst.collection_name = kwargs["collection_name"]
            return inst

        with patch("adapters.dense.DenseAdapter", side_effect=_fake_dense):
            ace_adapter = gw._get_dense_adapter("ace")
            feishu_adapter = gw._get_dense_adapter("feishu_lurk")

        assert ace_adapter is not feishu_adapter
        assert ace_adapter.collection_name != feishu_adapter.collection_name

    def test_feishu_adapter_uses_feishu_output_fields(self, monkeypatch):
        _patch_projects(monkeypatch)
        import gateway.gateway as gw
        from adapters.dense import _FEISHU_OUTPUT_FIELDS

        gw._dense_adapter = None
        monkeypatch.setattr("config.DENSE_ENABLED", True)

        captured_kwargs = {}

        def _fake_dense(**kwargs):
            captured_kwargs.update(kwargs)
            return MagicMock()

        with patch("adapters.dense.DenseAdapter", side_effect=_fake_dense):
            gw._get_dense_adapter("feishu_lurk")

        assert captured_kwargs.get("output_fields") == _FEISHU_OUTPUT_FIELDS


# ─── search() routes Feishu to dense-only ────────────────────────────────────


class TestFeishuSearchRouting:
    @pytest.mark.anyio
    async def test_feishu_search_does_not_call_zoekt(self, monkeypatch):
        """When project=feishu_lurk, gateway.search() must not instantiate ZoektAdapter."""
        _patch_projects(monkeypatch)
        import gateway.gateway as gw

        gw._adapters.clear()
        gw._dense_adapter = None
        monkeypatch.setattr("config.NL_ENABLED", False)
        monkeypatch.setattr("config.DENSE_ENABLED", True)
        monkeypatch.setattr("config.AUDIT_ENABLED", False)

        dense_mock = MagicMock()
        dense_mock.search_by_embedding = AsyncMock(return_value=[])

        zoekt_mock = MagicMock()
        zoekt_mock.search_zoekt = AsyncMock(return_value=[])

        monkeypatch.setattr(gw, "_get_dense_adapter", lambda project=None: dense_mock)

        with patch("adapters.zoekt.ZoektAdapter", return_value=zoekt_mock) as zoekt_cls:
            results = await gw.search(query="feishu test", project="feishu_lurk")

        # ZoektAdapter constructor must NOT be called
        zoekt_cls.assert_not_called()
        # dense must have been called
        dense_mock.search_by_embedding.assert_called_once()
        assert isinstance(results, list)

    @pytest.mark.anyio
    async def test_feishu_search_calls_dense_adapter(self, monkeypatch):
        _patch_projects(monkeypatch)
        import gateway.gateway as gw

        gw._adapters.clear()
        gw._dense_adapter = None
        monkeypatch.setattr("config.NL_ENABLED", False)
        monkeypatch.setattr("config.DENSE_ENABLED", True)
        monkeypatch.setattr("config.AUDIT_ENABLED", False)

        fake_hit = {
            "id": "1",
            "score": 0.9,
            "metadata": {
                "title": "Feishu Doc",
                "url": "http://feishu/doc/1",
                "space_id": "sp1",
                "node_token": "nt1",
                "content": "hello feishu",
            },
        }

        dense_mock = MagicMock()
        dense_mock.search_by_embedding = AsyncMock(return_value=[fake_hit])

        monkeypatch.setattr(gw, "_get_dense_adapter", lambda project=None: dense_mock)

        results = await gw.search(query="feishu test", project="feishu_lurk")

        assert len(results) == 1
        assert results[0]["metadata"]["source"] == "feishu"

    @pytest.mark.anyio
    async def test_aosp_search_does_not_return_feishu_results(self, monkeypatch):
        """When project=ace (AOSP), Feishu results must not appear."""
        _patch_projects(monkeypatch)
        import gateway.gateway as gw

        gw._adapters.clear()
        gw._dense_adapter = None
        monkeypatch.setattr("config.NL_ENABLED", False)
        monkeypatch.setattr("config.DENSE_ENABLED", False)
        monkeypatch.setattr("config.AUDIT_ENABLED", False)

        import httpx
        import respx

        zoekt_hit = {
            "Result": {
                "Files": [
                    {
                        "FileName": "core/Foo.java",
                        "Repository": "frameworks/base",
                        "Branches": ["main"],
                        "Language": "Java",
                        "LineMatches": [
                            {
                                "Line": "class Foo {}",
                                "LineNumber": 1,
                                "LineFragments": [{"LineOffset": 0, "MatchLength": 3}],
                            }
                        ],
                        "Score": 20.0,
                    }
                ]
            }
        }

        with respx.mock:
            respx.get("http://zoekt-ace:6070/search").mock(
                return_value=httpx.Response(200, json=zoekt_hit)
            )
            results = await gw.search(query="class Foo", project="ace")

        # No feishu source in results
        for r in results:
            assert r.get("metadata", {}).get("source") != "feishu"


# ─── feishu_result_to_dict ────────────────────────────────────────────────────


class TestFeishuResultToDict:
    def test_basic_conversion(self):
        from gateway.converters import feishu_result_to_dict

        hit = {
            "id": "42",
            "score": 0.85,
            "metadata": {
                "title": "Design Doc",
                "url": "http://feishu/doc/42",
                "space_id": "sp_abc",
                "node_token": "nt_xyz",
                "content": "Some content here",
            },
        }
        result = feishu_result_to_dict(hit)

        assert result["title"] == "Design Doc"
        assert result["content"] == "Some content here"
        assert result["score"] == 0.85
        assert result["metadata"]["url"] == "http://feishu/doc/42"
        assert result["metadata"]["space_id"] == "sp_abc"
        assert result["metadata"]["node_token"] == "nt_xyz"
        assert result["metadata"]["source"] == "feishu"

    def test_missing_title_falls_back(self):
        from gateway.converters import feishu_result_to_dict

        hit = {"score": 0.5, "metadata": {"url": "http://feishu/doc/1", "content": "text"}}
        result = feishu_result_to_dict(hit)

        assert result["title"] == "Feishu Document"

    def test_score_default_zero(self):
        from gateway.converters import feishu_result_to_dict

        hit = {"metadata": {"title": "T", "content": "c"}}
        result = feishu_result_to_dict(hit)

        assert result["score"] == 0.0

    def test_rrf_compatible_keys_present(self):
        """Result must have title, content, score, metadata for RRF merge."""
        from gateway.converters import feishu_result_to_dict

        hit = {
            "score": 0.7,
            "metadata": {"title": "Doc", "url": "http://u", "content": "x"},
        }
        result = feishu_result_to_dict(hit)

        for key in ("title", "content", "score", "metadata"):
            assert key in result
