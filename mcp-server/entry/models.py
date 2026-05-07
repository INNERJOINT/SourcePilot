"""Pydantic input and output models for all MCP tools."""

from __future__ import annotations

from pydantic import BaseModel, Field

# ─── Input models ─────────────────────────────────────────────────────────────


class SearchCodeInput(BaseModel):
    query: str = Field(
        description="Search query: keyword, symbol name, file path, etc.",
    )
    repo: str = Field(default="", description="Restrict search to repo name prefix")
    top_k: int = Field(default=10, description="Number of results to return")
    lang: str = Field(default="", description="Filter by language (e.g. java, cpp)")
    branch: str = Field(default="", description="Filter by branch name (e.g. main)")
    case_sensitive: str = Field(
        default="auto",
        description="Case sensitivity mode: auto (default), yes, no",
    )
    project: str = Field(default="", description="Project name (e.g. aosp-14)")


class SearchSymbolInput(BaseModel):
    symbol: str = Field(
        description="Symbol name (class name, function name, etc.)",
    )
    repo: str = Field(default="", description="Restrict search to repo")
    top_k: int = Field(default=5, description="Number of results to return")
    lang: str = Field(default="", description="Filter by programming language")
    branch: str = Field(default="", description="Filter by branch name")
    case_sensitive: str = Field(
        default="auto", description="Case sensitivity: auto, yes, no",
    )
    project: str = Field(default="", description="Project name")


class SearchFileInput(BaseModel):
    path: str = Field(
        description="File name or path pattern (e.g. SystemServer.java)",
    )
    query: str = Field(
        default="", description="Additional keyword to search within files",
    )
    top_k: int = Field(default=5, description="Number of results to return")
    lang: str = Field(default="", description="Filter by programming language")
    branch: str = Field(default="", description="Filter by branch name")
    case_sensitive: str = Field(
        default="auto", description="Case sensitivity: auto, yes, no",
    )
    project: str = Field(default="", description="Project name")


class SearchRegexInput(BaseModel):
    pattern: str = Field(description="Regular expression pattern")
    repo: str = Field(default="", description="Restrict search to repo")
    top_k: int = Field(default=10, description="Number of results to return")
    lang: str = Field(default="", description="Filter by programming language")
    branch: str = Field(default="", description="Filter by branch name")
    case_sensitive: str = Field(
        default="auto", description="Case sensitivity: auto, yes, no",
    )
    project: str = Field(default="", description="Project name")


class ListReposInput(BaseModel):
    query: str = Field(default="", description="Repo name filter keyword")
    top_k: int = Field(default=50, description="Max number of results to return")
    project: str = Field(default="", description="Project name")


class GetFileContentInput(BaseModel):
    repo: str = Field(
        description="Repo name (from search_file/search_code results)",
    )
    filepath: str = Field(
        description="File path (from search results, without repo prefix)",
    )
    start_line: int = Field(default=1, description="Start line number (1-based)")
    end_line: int | None = Field(
        default=None, description="End line number (defaults to EOF)",
    )
    project: str = Field(default="", description="Project name")


class ListProjectsInput(BaseModel):
    pass


# ─── Output models ────────────────────────────────────────────────────────────


class SearchHit(BaseModel):
    location: str = Field(description="repo/path or title")
    start_line: int | None = Field(default=None)
    end_line: int | None = Field(default=None)
    content: str = Field(description="Code snippet preview")


class SearchResult(BaseModel):
    query: str = Field(description="Original query")
    total: int = Field(description="Number of hits")
    hits: list[SearchHit]


class RepoInfo(BaseModel):
    name: str
    url: str = Field(default="")


class ListReposResult(BaseModel):
    total: int
    repos: list[RepoInfo]


class FileContentResult(BaseModel):
    repo: str
    filepath: str
    start_line: int
    end_line: int
    total_lines: int
    content: str


class ProjectInfo(BaseModel):
    name: str
    source_root: str = Field(default="")
    zoekt_url: str = Field(default="")


class ListProjectsResult(BaseModel):
    total: int
    projects: list[ProjectInfo]
    multi_project: bool = Field(
        description="Whether this is a multi-project deployment",
    )
