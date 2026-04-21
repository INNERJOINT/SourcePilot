# Trace Analysis: `be04769a-5b2f-4b85-b23a-6b082ef14e96`

## Basic Info

| Field | Value |
|---|---|
| **Timestamp** | 2026-04-21 08:09:35 |
| **Interface** | HTTP (direct SourcePilot call) |
| **Tool** | `search` |
| **Original Query** | `connectivitycheck.gstatic.com captive portal` |
| **Total Duration** | **4971.1ms** (marked slow) |
| **Status** | ok |
| **Result Count** | 10 |

---

## Pipeline Stage Timeline

```
08:09:35.724  +-- classify --------------  7.2ms  ok
08:09:35.921  +-- rewrite ---------------  196.5ms  ok  (LLM rewrite)
              |
              |  +-- 5-way parallel zoekt_search ----------------+
08:09:35.9~   |  | route0: "connectivitycheck.gstatic.com"       | 3673.7ms SLOW -> 6 hits
              |  | route1: "captive"                              | 3729.2ms SLOW -> 20 hits
              |  | route2: "portal"                               | 4672.3ms SLOW -> 20 hits
              |  | route3: "...gstatic.com captive portal"        | 3667.5ms SLOW -> 3 hits
              |  | route4: "...gstatic.com captive"               | 3536.1ms SLOW -> 3 hits
              |  +-----------------------------------------------+
08:09:40.688  +-- nl_parallel_search ----  4765.3ms SLOW  (bound by slowest route2)
08:09:40.689  +-- rrf_merge -------------  0.2ms  ok
08:09:40.689  +-- rerank ----------------  0.3ms  ok
```

---

## Stage-by-Stage Breakdown

### 1. Classify (7.2ms)

- Determined `query_type = natural_language`, `nl_enabled = true`
- Query contains natural language phrase "captive portal", correctly routed to NL pipeline

### 2. Rewrite (196.5ms)

LLM rewrite produced **5 sub-queries**:

1. `connectivitycheck.gstatic.com` -- exact domain
2. `captive` -- single keyword
3. `portal` -- single keyword
4. `connectivitycheck.gstatic.com captive portal` -- original query
5. `connectivitycheck.gstatic.com captive` -- partial combination

**Issue**: Queries 2 (`captive`) and 3 (`portal`) are overly broad single-word splits that pull in excessive noise (each hitting the 20-result cap). `portal` in particular matched webrtc, u-boot, gradle plugin portal and other completely unrelated content. The LLM rewriter should have kept `captive portal` as a phrase.

### 3. Zoekt Parallel Search (bottleneck: 4672ms)

5-way concurrent, all marked **slow** (>2000ms threshold). The slowest route (`portal`) at 4672ms determined overall parallel wait time. Total raw results: **52** (6+20+20+3+3).

| Route | Query | Hits | Quality |
|---|---|---|---|
| 0 | `connectivitycheck.gstatic.com` | 6 | **High** -- exact domain match, all relevant |
| 1 | `captive` | 20 | **Medium** -- mostly captive portal related, but redundant |
| 2 | `portal` | 20 | **Low** -- heavy noise (gradle plugin portal, webrtc xdg portal, u-boot portals) |
| 3 | original full query | 3 | **High** -- precise match |
| 4 | `gstatic.com captive` | 3 | **High** -- precise match |

### 4. RRF Merge (0.2ms)

- Input: 5 lists, 52 total records
- Dedup: removed 8 duplicates -> **44** unique results
- RRF top score: 0.0487

### 5. Rerank (0.3ms)

- Selected **top 10** from 44 candidates
- Score range: 0.4241 ~ 0.4398 (very narrow, low discriminative power)

---

## Performance Bottleneck Summary

| Stage | Duration | Share | Notes |
|---|---|---|---|
| classify | 7ms | 0.1% | -- |
| rewrite | 197ms | 4.0% | LLM call, acceptable |
| **zoekt parallel** | **4765ms** | **95.9%** | **Bottleneck** |
| rrf + rerank | 0.5ms | 0.0% | Negligible |

**95.9% of time spent in Zoekt search.** All 5 routes took 3.5-4.7s each, suggesting the Zoekt backend was slow (large index or high load at the time).

---

## Top Result Quality

Most relevant hits concentrated in:

- `CaptivePortalLogin/src/.../CaptivePortalLoginActivity.java` -- defines `DEFAULT_CAPTIVE_PORTAL_HTTP_URL = connectivitycheck.gstatic.com`
- `NetworkStack/res/values/config.xml` -- captive portal URL configuration
- `NetworkStack/src/.../NetworkStackUtils.java` -- captive portal constants

These are high-quality matches. However, the rerank score spread is only 0.016 (0.4241-0.4398), indicating the reranker struggles to differentiate among these results.

---

## Key Findings

1. **Query intent classification correct**: classify accurately identified NL query
2. **LLM rewrite has room for improvement**: `captive` and `portal` single-word splits are too broad, introducing noise (especially `portal` matching webrtc/gradle/u-boot). Rewrite should preserve `captive portal` as a compound phrase
3. **Zoekt is the absolute bottleneck**: 96% of total time, 3.5-4.7s per route. Parallel dispatch avoids serial multiplication but per-route latency is inherently high
4. **RRF + Rerank fast but low discrimination**: rerank score range of only 0.016 limits ranking effectiveness
5. **Dense search not enabled**: `dense_enabled: false`, relying solely on Zoekt BM25. Enabling vector retrieval could help filter noise at the semantic level
