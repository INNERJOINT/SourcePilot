## 代码 RAG 中幻觉的三种典型形态

**知识冲突型（KCH）** 是代码场景中最危险的。LLM 会引入"语法正确但语义错误"的代码，比如使用不存在的 API 参数，这类错误能绕过 linter 但在运行时导致失败。例如 LLM 声称 `ActivityManagerService.checkPermission()` 接受三个参数，实际上只接受两个——代码看起来合理但完全是编造的。

**上下文背叛型** 是 RAG 特有的问题。即使检索到了准确且相关的内容，RAG 模型仍可能生成与检索信息矛盾的输出。比如检索到的代码片段明确显示某函数在 `SystemServer` 中初始化，LLM 却回答说它在 `Zygote` 中初始化——因为模型的参数化知识覆盖了检索结果。

**检索污染型** 是上游问题。RAG 高度依赖检索文档的相关性，如果检索出错，模型的行为就会出问题。在 AOSP 中，查询"camera HAL 权限检查"可能检索到不相关的旧版 HAL 实现，LLM 基于错误上下文生成看似正确但实际过时的答案。

---

## 防线一：预防——在生成之前阻止幻觉

### CRAG（Corrective RAG）：检索质量守门员

CRAG 在传统 RAG 基础上引入自纠正机制，在生成前评估和精化检索到的知识。它的核心是一个**检索评估器**，对每个检索文档评分后分三档处理：

```python
class CRAGEvaluator:
    def evaluate_and_correct(self, query: str, retrieved_docs: list) -> list:
        scored_docs = self.relevance_scorer(query, retrieved_docs)
        
        if max(scored_docs) > HIGH_THRESHOLD:       # ✅ Correct
            # 高质量检索，用 decompose-then-recompose 提取关键信息
            return self.extract_key_strips(scored_docs)
        
        elif max(scored_docs) < LOW_THRESHOLD:       # ❌ Incorrect
            # 检索完全不相关，触发补充检索
            return self.fallback_search(query)       # 扩大搜索范围
        
        else:                                        # ⚠️ Ambiguous
            # 部分相关，融合原始检索 + 补充检索
            refined = self.extract_key_strips(scored_docs)
            supplementary = self.fallback_search(query)
            return self.merge(refined, supplementary)
```

评估器是一个微调的 T5-large 模型，为每个文档分配置信度分数，分为三个级别。在你的场景中，当 Zoekt 和向量检索返回的 AOSP 代码片段置信度不足时，CRAG 会自动触发扩大检索范围（比如从 `frameworks/base/` 扩展到 `system/core/`），而非让 LLM 在低质量上下文中"猜测"。

### 确定性 AST 验证：代码幻觉的终极防线

这是代码场景独有的、比通用文本幻觉检测更可靠的方法。一个确定性的后处理框架，将生成的代码解析为 AST，然后对照通过库内省动态生成的知识库进行验证。在 200 个 Python 代码片段上，检测精确率达到 100%，召回率 87.6%（F1 0.934），并成功自动修正了 77.0% 的幻觉。

对 AOSP 的具体应用方式：

```python
class AOSPCodeHallucinationDetector:
    def __init__(self):
        # 从 AOSP 源码构建 API 知识库
        self.api_kb = self.build_aosp_api_knowledge_base()
    
    def verify_response(self, llm_response: str) -> VerificationResult:
        issues = []
        
        # 1. API 存在性验证
        api_calls = self.extract_api_references(llm_response)
        for api in api_calls:
            if api.class_name not in self.api_kb:
                issues.append(HallucinatedAPI(api, "类不存在"))
            elif api.method_name not in self.api_kb[api.class_name]:
                issues.append(HallucinatedAPI(api, "方法不存在"))
            elif not self.check_params(api):
                issues.append(HallucinatedAPI(api, "参数签名不匹配"))
        
        # 2. 文件路径验证（通过 Zoekt 反查）
        file_refs = self.extract_file_paths(llm_response)
        for path in file_refs:
            zoekt_result = zoekt_search(f'file:"{path}"')
            if not zoekt_result.matches:
                issues.append(HallucinatedPath(path))
        
        # 3. 跨层一致性检查
        # 如果 LLM 说 "HAL 层调用 Framework API"，验证调用方向是否合理
        layer_refs = self.extract_layer_references(llm_response)
        for ref in layer_refs:
            if not self.validate_layer_interaction(ref):
                issues.append(LayerViolation(ref))
        
        return VerificationResult(issues=issues, is_clean=len(issues) == 0)
```

对于低频 API 的幻觉，一个简单但有效的策略是：先让 LLM 生成第一版回答，验证其中引用的 API 是否存在于 API 索引中，如果不存在，则触发 RAG 检索提供正确的 API 文档后重新生成。

---

## 防线二：检测——生成后识别幻觉

### NLI 蕴含验证：逐断言检查

核心思路是将 LLM 输出分解为原子命题，逐一检查每个命题是否被检索上下文"蕴含"（entailed）：

```python
class EntailmentVerifier:
    def __init__(self):
        # 使用 DeBERTa-v3-large 微调的 NLI 模型
        self.nli_model = load_model("cross-encoder/nli-deberta-v3-large")
    
    def verify(self, response: str, context: str) -> list[ClaimVerdict]:
        # 1. 分解为原子命题
        claims = self.decompose_to_claims(response)
        
        verdicts = []
        for claim in claims:
            # 2. NLI 三分类: entailed / contradicted / neutral
            score = self.nli_model.predict(premise=context, hypothesis=claim)
            
            if score.label == "entailed":
                verdicts.append(ClaimVerdict(claim, "SUPPORTED", score.confidence))
            elif score.label == "contradiction":
                verdicts.append(ClaimVerdict(claim, "CONTRADICTED", score.confidence))
            else:  # neutral — 上下文中找不到支持
                verdicts.append(ClaimVerdict(claim, "UNSUPPORTED", score.confidence))
        
        return verdicts
```

RT4CHART 框架为每个命题返回三种标签——Entailed、Contradicted 或 Baseless——并定位对应的回答片段以及明确的支持或矛盾上下文证据。这种方法的优势是提供**细粒度**的定位——不是整体判断"回答有问题"，而是精确标记哪句话有问题以及为什么。

### MetaRAG：变形测试——无需标注数据的黑盒检测

MetaRAG 在无监督、黑盒环境下运行，不需要标注数据也不需要访问模型内部，适用于企业部署。其流程分四步：

1. **分解**：将回答拆为原子事实（如"ActivityManagerService 在 SystemServer 中启动"）
2. **变异**：对每个事实生成同义变体和反义变体（如"AMS 在 Zygote 中启动"）
3. **验证**：同义变体应被上下文蕴含，反义变体应被上下文矛盾——如果反义变体也被"蕴含"了，说明原始回答可能有幻觉
4. **聚合**：将不一致度汇总为响应级幻觉评分

这种方法特别适合你的场景——因为 AOSP 代码库的"ground truth"往往不是预先标注好的，而 MetaRAG 完全不依赖标注。

### ReDeEP：机制可解释性方法

ReDeEP 通过解耦外部上下文和参数化知识来检测 RAG 中的幻觉，并通过调节 Knowledge FFN 和 Copying Head 的贡献来减少幻觉。它基于一个关键洞察：LLM 内部有两套"系统"在竞争——一个从检索上下文中复制信息（Copying Heads），另一个从训练记忆中回忆信息（Knowledge FFNs）。当后者压过前者时，幻觉就产生了。这是 ICLR 2025 Spotlight 论文，代表了当前学术前沿。

---

## 防线三：缓解——降低幻觉的发生率

### 引用强制：要求 LLM "show your work"

标准 RAG 并不能阻止幻觉，模型可能编造引用、引用不存在的代码位置，或者将记忆中的模式与检索内容混淆。通过要求 LLM 引用具体的行范围来进行机械化引用验证。

在你的 AOSP Prompt 中强制要求引用来源：

```python
GROUNDED_PROMPT = """基于以下 AOSP 代码上下文回答问题。

## 规则
1. 每个技术断言必须标注来源：[文件:行号] 格式
2. 如果上下文中找不到答案，明确说"基于提供的上下文无法确定"
3. 不要引用上下文中不存在的 API、类或方法
4. 区分"上下文明确说明"和"我的推断"

## 上下文
{context_with_line_numbers}

## 问题
{query}
"""
```

然后用 Zoekt 反查每个引用是否真实存在：

```python
def verify_citations(response: str, original_context: list) -> dict:
    citations = extract_citations(response)  # 解析 [文件:行号] 标记
    verified, fabricated = [], []
    
    for cite in citations:
        # 用 Zoekt 验证文件和行号是否存在
        result = zoekt_search(f'file:"{cite.file}"', opts={"MaxDocDisplayCount": 1})
        if result.matches and cite.line in range(result.file_length):
            # 进一步验证引用内容是否匹配
            actual_content = get_lines(cite.file, cite.line, cite.line + 3)
            if semantic_similarity(cite.claimed_content, actual_content) > 0.7:
                verified.append(cite)
            else:
                fabricated.append(cite)
        else:
            fabricated.append(cite)
    
    return {"verified": verified, "fabricated": fabricated, 
            "trust_score": len(verified) / max(len(citations), 1)}
```

### Self-Consistency（自一致性）检查

对同一个查询用不同温度（或不同 prompt 变体）生成多次回答，然后比较一致性。如果 5 次回答中有 4 次说"AMS.checkPermission 在 frameworks/base/services 中"，1 次说在别处，那么多数共识很可能是正确的。方差高的断言被标记为低置信度。

### 多阶段生成+验证 Pipeline

将检测和缓解整合为完整的后处理管道：

```python
class HallucinationGuard:
    def __call__(self, query, raw_response, context) -> GuardedResponse:
        # Stage 1: 确定性验证（快速、零误报）
        ast_issues = self.ast_verifier.verify(raw_response)
        citation_issues = self.citation_verifier.verify(raw_response, context)
        
        # Stage 2: 语义验证（较慢、需要模型推理）
        if not ast_issues and not citation_issues:
            nli_verdicts = self.entailment_verifier.verify(raw_response, context)
            unsupported = [v for v in nli_verdicts if v.label != "SUPPORTED"]
        else:
            unsupported = []
        
        # Stage 3: 决策
        all_issues = ast_issues + citation_issues + unsupported
        
        if any(i.severity == "CRITICAL" for i in all_issues):
            # 触发重新生成（带更严格的 prompt + 补充检索）
            return self.regenerate_with_correction(query, all_issues)
        elif all_issues:
            # 标注低置信度区域，附带警告
            return self.annotate_response(raw_response, all_issues)
        else:
            return GuardedResponse(raw_response, confidence="HIGH")
```

---

## AOSP 场景的特殊考量

**API 签名验证**是最有价值的第一道防线——利用 Zoekt 的符号搜索 `sym:checkPermission` 可以在毫秒级确认一个 API 是否存在。**跨层合理性检查**可以捕获"HAL 调用 Framework"这类违反 AOSP 架构分层的幻觉。**版本一致性**则确保 LLM 不会把 Android 12 的 API 行为描述为 Android 14 的——通过检查检索上下文的 branch 标签来验证。

推荐的实施优先级：先做确定性 AST 验证（100% 精确率、零成本），再做引用强制+Zoekt 反查（低成本高回报），然后是 CRAG 检索质量评估（减少上游问题），最后按需加入 NLI 蕴含验证（精细但较慢）。