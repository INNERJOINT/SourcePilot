"""
Tests for multi-project support in MCP handlers.

Covers: project probe, list_projects tool, required/optional schema switching,
probe failure fallback, lazy reprobe on call_tool.
"""
import entry.handlers as handlers
import httpx
import pytest
import respx
from entry.handlers import (
    SOURCEPILOT_URL,
    _handle_list_projects,
    call_tool,
    list_tools,
)

TWO_PROJECTS = [
    {"name": "ace", "source_root": "/x", "zoekt_url": "http://z1:6070"},
    {"name": "t2", "source_root": "/y", "zoekt_url": "http://z2:6071"},
]

ONE_PROJECT = [
    {"name": "ace", "source_root": "/x", "zoekt_url": "http://z1:6070"},
]


@pytest.fixture(autouse=True)
def reset_multi_project(monkeypatch):
    """Reset module-level probe state before each test to prevent cross-test pollution."""
    monkeypatch.setattr(handlers, "_multi_project", None)
    monkeypatch.setattr(handlers, "_project_names", [])


@pytest.mark.asyncio
@respx.mock
async def test_list_projects_tool_calls_api():
    """_handle_list_projects returns TextContent containing name, source_root, zoekt_url."""
    respx.get(f"{SOURCEPILOT_URL}/api/projects").mock(
        return_value=httpx.Response(200, json=TWO_PROJECTS)
    )
    result = await _handle_list_projects({}, "trace-test")
    assert len(result) == 1
    text = result[0].text
    assert "ace" in text
    assert "t2" in text
    assert "/x" in text
    assert "http://z1:6070" in text


@pytest.mark.asyncio
@respx.mock
async def test_multi_project_schema_marks_required():
    """When 2 projects exist, all 6 non-list_projects tools have 'project' in required."""
    respx.get(f"{SOURCEPILOT_URL}/api/projects").mock(
        return_value=httpx.Response(200, json=TWO_PROJECTS)
    )
    tools = await list_tools()
    assert handlers._multi_project is True
    non_list = [t for t in tools if t.name != "list_projects"]
    assert len(non_list) == 6
    for tool in non_list:
        required = tool.inputSchema.get("required", [])
        assert "project" in required, f"{tool.name}.required should include 'project'"


@pytest.mark.asyncio
@respx.mock
async def test_single_project_schema_optional():
    """When 1 project exists, no tool has 'project' in required; _multi_project is False."""
    respx.get(f"{SOURCEPILOT_URL}/api/projects").mock(
        return_value=httpx.Response(200, json=ONE_PROJECT)
    )
    tools = await list_tools()
    assert handlers._multi_project is False
    non_list = [t for t in tools if t.name != "list_projects"]
    for tool in non_list:
        required = tool.inputSchema.get("required", [])
        assert "project" not in required, f"{tool.name}.required should NOT include 'project'"


@pytest.mark.asyncio
@respx.mock
async def test_probe_failure_falls_back_to_optional():
    """When /api/projects returns 500, list_tools does not raise; required omits 'project'."""
    respx.get(f"{SOURCEPILOT_URL}/api/projects").mock(
        return_value=httpx.Response(500, json={"error": "server error"})
    )
    tools = await list_tools()
    assert tools is not None
    # Probe never succeeded — state stays None
    assert handlers._multi_project is None
    non_list = [t for t in tools if t.name != "list_projects"]
    for tool in non_list:
        required = tool.inputSchema.get("required", [])
        assert "project" not in required


@pytest.mark.asyncio
async def test_lazy_reprobe_on_call_tool(monkeypatch):
    """If list_tools probe fails, call_tool triggers a reprobe and updates _multi_project."""
    call_count = 0

    async def fake_probe():
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            # Second probe (triggered by call_tool) succeeds
            handlers._multi_project = True
            handlers._project_names = ["ace", "t2"]
        # First probe: do nothing — _multi_project stays None

    monkeypatch.setattr(handlers, "_probe_projects", fake_probe)

    # First call: list_tools triggers probe #1 → fails
    await list_tools()
    assert handlers._multi_project is None

    # call_tool sees _multi_project is None → triggers probe #2 → succeeds
    with respx.mock:
        respx.get(f"{SOURCEPILOT_URL}/api/projects").mock(
            return_value=httpx.Response(200, json=TWO_PROJECTS)
        )
        await call_tool("list_projects", {})

    assert handlers._multi_project is True


@pytest.mark.asyncio
@respx.mock
async def test_search_regex_schema_includes_project():
    """search_regex tool inputSchema.properties contains 'project' field."""
    respx.get(f"{SOURCEPILOT_URL}/api/projects").mock(
        return_value=httpx.Response(200, json=TWO_PROJECTS)
    )
    tools = await list_tools()
    regex_tool = next(t for t in tools if t.name == "search_regex")
    assert "project" in regex_tool.inputSchema.get("properties", {})


@pytest.mark.asyncio
@respx.mock
async def test_list_repos_schema_includes_project():
    """list_repos tool inputSchema.properties contains 'project' field."""
    respx.get(f"{SOURCEPILOT_URL}/api/projects").mock(
        return_value=httpx.Response(200, json=TWO_PROJECTS)
    )
    tools = await list_tools()
    tool = next(t for t in tools if t.name == "list_repos")
    assert "project" in tool.inputSchema.get("properties", {})


@pytest.mark.asyncio
@respx.mock
async def test_get_file_content_schema_includes_project():
    """get_file_content tool inputSchema.properties contains 'project' field."""
    respx.get(f"{SOURCEPILOT_URL}/api/projects").mock(
        return_value=httpx.Response(200, json=TWO_PROJECTS)
    )
    tools = await list_tools()
    tool = next(t for t in tools if t.name == "get_file_content")
    assert "project" in tool.inputSchema.get("properties", {})
