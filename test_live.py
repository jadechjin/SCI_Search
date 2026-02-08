"""Phase 3 手动验证脚本 — 端到端 pipeline 真实 API 测试

验证流程: 用户输入 → 意图解析 → 查询构建 → 搜索 → 去重 → 评分 → 结果组织

运行前确保 .env 中配置了:
  - LLM provider 的 API key + model
  - SERPAPI_API_KEY (如没有，搜索步骤会跳过，用模拟数据继续)

用法: .venv/Scripts/python test_live.py
"""

import asyncio
import sys
import traceback

from paper_search.config import load_config
from paper_search.llm import create_provider
from paper_search.models import (
    PaperCollection,
    QueryBuilderInput,
    RawPaper,
)
from paper_search.skills.deduplicator import Deduplicator
from paper_search.skills.intent_parser import IntentParser
from paper_search.skills.query_builder import QueryBuilder
from paper_search.skills.relevance_scorer import RelevanceScorer
from paper_search.skills.result_organizer import ResultOrganizer
from paper_search.skills.searcher import Searcher
from paper_search.sources.serpapi_scholar import SerpAPIScholarSource

# ── 颜色 & 格式辅助 ────────────────────────────────────────────

_PASS = 0
_FAIL = 0


def _ok(msg: str) -> None:
    global _PASS
    _PASS += 1
    print(f"  [PASS] {msg}")


def _fail(msg: str) -> None:
    global _FAIL
    _FAIL += 1
    print(f"  [FAIL] {msg}")


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}")


def _section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ── 模拟数据 (当没有 SerpAPI key 时使用) ─────────────────────────

def _make_mock_papers() -> list[RawPaper]:
    """生成模拟搜索结果，用于在没有 SerpAPI key 时继续测试后续技能。"""
    return [
        RawPaper(
            id="mock-1",
            title="Perovskite Solar Cells: A Review of Recent Advances",
            snippet="This review covers recent progress in perovskite solar cell stability...",
            year=2023,
            venue="Nature Energy",
            source="mock",
            citation_count=150,
            authors=[],
        ),
        RawPaper(
            id="mock-2",
            title="Improving Stability of Perovskite Solar Cells via Interface Engineering",
            snippet="Interface engineering approaches to enhance long-term stability...",
            year=2022,
            venue="Advanced Materials",
            source="mock",
            citation_count=85,
        ),
        RawPaper(
            id="mock-3",
            title="Perovskite Solar Cell Stability: A Review",  # 近似重复
            snippet="A comprehensive review of stability issues in perovskite solar cells.",
            year=2023,
            venue="nature energy",
            source="mock",
            citation_count=120,
        ),
        RawPaper(
            id="mock-4",
            title="Machine Learning for Materials Discovery",
            snippet="Application of ML to screen new materials for energy applications.",
            year=2024,
            venue="Science",
            source="mock",
            citation_count=200,
        ),
        RawPaper(
            id="mock-5",
            title="Organic Photovoltaics: Fundamentals and Applications",
            snippet="Comprehensive overview of organic PV technology development.",
            year=2021,
            venue="Solar Energy Materials",
            source="mock",
            citation_count=60,
        ),
    ]


# ── 主流程 ──────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 60)
    print("  Phase 3 端到端 Pipeline 验证")
    print("=" * 60)

    # ── Step 0: 配置 ──────────────────────────────────────────
    _section("Step 0: 加载配置")
    config = load_config()
    llm_cfg = config.llm

    print(f"  LLM:    provider={llm_cfg.provider}, model={llm_cfg.model}")
    print(f"  SerpAPI: {'已配置' if config.sources.get('serpapi_scholar') else '未配置 (将用模拟数据)'}")
    print(f"  Domain:  {config.domain}")

    if not llm_cfg.api_key or not llm_cfg.model:
        print("\n  [ERROR] .env 中 LLM API key 或 model 未配置。")
        sys.exit(1)

    provider = create_provider(llm_cfg)
    _ok(f"LLM provider 创建成功: {type(provider).__name__}")

    has_serpapi = bool(config.sources.get("serpapi_scholar"))

    # ── Step 1: 意图解析 ──────────────────────────────────────
    _section("Step 1: IntentParser — 解析用户查询")
    user_query = "钙钛矿太阳能电池稳定性提升方法 2020年以后"
    print(f"  输入: {user_query}")

    try:
        parser = IntentParser(provider, domain=config.domain)
        intent = await parser.parse(user_query)
        _ok("IntentParser.parse() 成功")
        print(f"  topic:       {intent.topic}")
        print(f"  concepts:    {intent.concepts}")
        print(f"  intent_type: {intent.intent_type.value}")
        print(f"  constraints: year_from={intent.constraints.year_from}")
    except Exception as e:
        _fail(f"IntentParser 失败: {e}")
        traceback.print_exc()
        print("\n  意图解析失败，无法继续后续步骤。")
        _print_summary()
        return

    # ── Step 2: 查询构建 ──────────────────────────────────────
    _section("Step 2: QueryBuilder — 生成搜索策略")
    available_sources = ["serpapi_scholar"] if has_serpapi else ["mock_source"]

    try:
        builder = QueryBuilder(
            provider,
            domain=config.domain,
            available_sources=available_sources,
        )
        qb_input = QueryBuilderInput(intent=intent)
        strategy = await builder.build(qb_input)
        _ok(f"QueryBuilder.build() 成功 — {len(strategy.queries)} 个查询")
        print(f"  sources: {strategy.sources}")
        print(f"  filters: year_from={strategy.filters.year_from}, "
              f"year_to={strategy.filters.year_to}, "
              f"max_results={strategy.filters.max_results}")
        for i, q in enumerate(strategy.queries):
            print(f"  query[{i}]: {q.boolean_query}")
            if q.synonym_map:
                for sm in q.synonym_map[:3]:
                    print(f"    synonym: {sm.keyword} -> {sm.synonyms}")
    except Exception as e:
        _fail(f"QueryBuilder 失败: {e}")
        traceback.print_exc()
        _print_summary()
        return

    # ── Step 3: 搜索 ─────────────────────────────────────────
    _section("Step 3: Searcher — 执行搜索")
    raw_papers: list[RawPaper] = []

    if has_serpapi:
        serpapi_cfg = config.sources["serpapi_scholar"]
        serpapi_source = SerpAPIScholarSource(
            api_key=serpapi_cfg.api_key,
            rate_limit_rps=1.0,
        )
        searcher = Searcher([serpapi_source])

        # 限制搜索量以节省 API 配额
        strategy.filters.max_results = min(strategy.filters.max_results, 15)
        _info(f"限制 max_results={strategy.filters.max_results} (节省 API 配额)")

        try:
            raw_papers = await searcher.search(strategy)
            _ok(f"Searcher.search() 成功 — 获得 {len(raw_papers)} 篇论文")
            for p in raw_papers[:5]:
                print(f"    [{p.year or '????'}] {p.title[:70]}... "
                      f"(citations={p.citation_count})")
            if len(raw_papers) > 5:
                _info(f"... 还有 {len(raw_papers) - 5} 篇")
        except Exception as e:
            _fail(f"Searcher 失败: {e}")
            traceback.print_exc()
            _info("使用模拟数据继续...")
            raw_papers = _make_mock_papers()
    else:
        _info("SerpAPI 未配置，使用模拟数据")
        raw_papers = _make_mock_papers()
        _ok(f"模拟数据加载 — {len(raw_papers)} 篇论文")

    if not raw_papers:
        _fail("没有获得任何论文，无法继续。")
        _print_summary()
        return

    # ── Step 4: 去重 ─────────────────────────────────────────
    _section("Step 4: Deduplicator — 去除重复论文")
    _info(f"去重前: {len(raw_papers)} 篇")

    try:
        deduplicator = Deduplicator(llm=provider)
        deduped_papers = await deduplicator.deduplicate(raw_papers)
        removed = len(raw_papers) - len(deduped_papers)
        if removed > 0:
            _ok(f"去重完成 — 移除 {removed} 篇, 剩余 {len(deduped_papers)} 篇")
        else:
            _ok(f"去重完成 — 无重复, 仍为 {len(deduped_papers)} 篇")
    except Exception as e:
        _fail(f"Deduplicator 失败: {e}")
        traceback.print_exc()
        deduped_papers = raw_papers  # 回退，继续测试后续步骤
        _info("使用未去重数据继续...")

    # ── Step 5: 相关性评分 ───────────────────────────────────
    _section("Step 5: RelevanceScorer — LLM 批量评分")

    try:
        scorer = RelevanceScorer(provider, batch_size=10)
        scored_papers = await scorer.score(deduped_papers, intent)
        _ok(f"RelevanceScorer.score() 成功 — {len(scored_papers)} 篇已评分")

        # 按分数排序展示
        sorted_scored = sorted(scored_papers, key=lambda s: -s.relevance_score)
        for sp in sorted_scored[:5]:
            tags_str = ", ".join(t.value for t in sp.tags) if sp.tags else "无"
            print(f"    [{sp.relevance_score:.2f}] {sp.paper.title[:60]}...")
            print(f"           reason: {sp.relevance_reason[:80]}")
            print(f"           tags: {tags_str}")
        if len(scored_papers) > 5:
            _info(f"... 还有 {len(scored_papers) - 5} 篇")

        # 评分分布
        high = sum(1 for s in scored_papers if s.relevance_score >= 0.7)
        med = sum(1 for s in scored_papers if 0.3 <= s.relevance_score < 0.7)
        low = sum(1 for s in scored_papers if s.relevance_score < 0.3)
        _info(f"评分分布: 高(>=0.7)={high}, 中(0.3-0.7)={med}, 低(<0.3)={low}")

    except Exception as e:
        _fail(f"RelevanceScorer 失败: {e}")
        traceback.print_exc()
        _print_summary()
        return

    # ── Step 6: 结果组织 ─────────────────────────────────────
    _section("Step 6: ResultOrganizer — 筛选、排序、分面统计")

    try:
        organizer = ResultOrganizer(min_relevance=0.3)
        collection: PaperCollection = await organizer.organize(
            scored_papers, strategy, user_query
        )
        _ok(f"ResultOrganizer.organize() 成功")
        print(f"  总发现: {collection.metadata.total_found}")
        print(f"  筛选后: {len(collection.papers)} 篇 (min_relevance=0.3)")

        if collection.papers:
            print(f"\n  === 最终论文列表 (top 5) ===")
            for i, p in enumerate(collection.papers[:5]):
                tags_str = ", ".join(t.value for t in p.tags) if p.tags else ""
                print(f"  {i+1}. [{p.relevance_score:.2f}] {p.title[:65]}")
                if p.year:
                    print(f"     年份: {p.year}  引用: {p.citation_count}  "
                          f"来源: {p.venue or 'N/A'}")
                if tags_str:
                    print(f"     标签: {tags_str}")

        # 分面统计
        facets = collection.facets
        if facets.by_year:
            print(f"\n  === 按年份分布 ===")
            for year in sorted(facets.by_year, reverse=True):
                print(f"    {year}: {facets.by_year[year]} 篇")

        if facets.by_venue:
            print(f"\n  === 按期刊分布 (top 5) ===")
            for venue, count in sorted(facets.by_venue.items(),
                                       key=lambda x: -x[1])[:5]:
                print(f"    {venue}: {count} 篇")

        if facets.top_authors:
            print(f"\n  === 高产作者 (top 5) ===")
            for author in facets.top_authors[:5]:
                print(f"    {author}")

        if facets.key_themes:
            print(f"\n  === 关键主题词 ===")
            print(f"    {', '.join(facets.key_themes)}")

    except Exception as e:
        _fail(f"ResultOrganizer 失败: {e}")
        traceback.print_exc()

    # ── 总结 ─────────────────────────────────────────────────
    _print_summary()


def _print_summary() -> None:
    print(f"\n{'=' * 60}")
    print(f"  验证完成: {_PASS} 通过, {_FAIL} 失败")
    if _FAIL == 0:
        print("  Phase 3 pipeline 全部可用!")
    else:
        print("  存在失败项，请检查上方日志。")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    asyncio.run(main())
