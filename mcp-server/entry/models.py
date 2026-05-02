"""Pydantic input and output models for all MCP tools."""

from __future__ import annotations

from pydantic import BaseModel, Field

# ─── Input models ─────────────────────────────────────────────────────────────


class SearchCodeInput(BaseModel):
    query: str = Field(description="Search query: keyword, symbol name, file path, property name, etc.")
    repo: str = Field(default="", description="Optional, restrict search to repo name prefix")
    top_k: int = Field(default=10, description="Number of results to return, default 10")
    lang: str | None = Field(default=None, description="Optional, filter by programming language (e.g. java, cpp, go)")
    branch: str | None = Field(default=None, description="Optional, filter by branch name (e.g. main)")
    case_sensitive: str = Field(
        default="auto",
        description="Case sensitivity mode: auto (default), yes, no",
    )
    project: str | None = Field(default=None, description="Optional, project name (e.g. aosp-14, aosp-15)")


class SearchSymbolInput(BaseModel):
    symbol: str = Field(description="Symbol name to search for (class name, function name, etc.)")
    repo: str = Field(default="", description="Optional, restrict search to repo")
    top_k: int = Field(default=5, description="Number of results to return, default 5")
    lang: str | None = Field(default=None, description="Optional, filter by programming language")
    branch: str | None = Field(default=None, description="Optional, filter by branch name")
    case_sensitive: str = Field(default="auto", description="Case sensitivity mode: auto, yes, no")
    project: str | None = Field(default=None, description="Optional, project name")


class SearchFileInput(BaseModel):
    path: str = Field(description="File name or path pattern (e.g. SystemServer.java or frameworks/base/)")
    query: str = Field(default="", description="Optional, additional keyword to search within matched files")
    top_k: int = Field(default=5, description="Number of results to return, default 5")
    lang: str | None = Field(default=None, description="Optional, filter by programming language")
    branch: str | None = Field(default=None, description="Optional, filter by branch name")
    case_sensitive: str = Field(default="auto", description="Case sensitivity mode: auto, yes, no")
    project: str | None = Field(default=None, description="Optional, project name")


class SearchRegexInput(BaseModel):
    pattern: str = Field(description="Regular expression pattern")
    repo: str = Field(default="", description="Optional, restrict search to repo")
    top_k: int = Field(default=10, description="Number of results to return, default 10")
    lang: str | None = Field(default=None, description="Optional, filter by programming language")
    branch: str | None = Field(default=None, description="Optional, filter by branch name")
    case_sensitive: str = Field(default="auto", description="Case sensitivity mode: auto, yes, no")
    project: str | None = Field(default=None, description="Optional, project name")


class ListReposInput(BaseModel):
    query: str = Field(default="", description="Optional, repo name filter keyword")
    top_k: int = Field(default=50, description="Maximum number of results to return, default 50")
    project: str | None = Field(default=None, description="Optional, project name")


class GetFileContentInput(BaseModel):
    repo: str = Field(description="Repo name (from the repo field of search_file/search_code results)")
    filepath: str = Field(description="File path (from the path field of search results, without repo prefix)")
    start_line: int = Field(default=1, description="Start line number (1-based, default 1)")
    end_line: int | None = Field(default=None, description="End line number (defaults to end of file)")
    project: str | None = Field(default=None, description="Optional, project name")


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
    multi_project: bool = Field(description="Whether this is a multi-project deployment")
