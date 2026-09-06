from app.evaluations import combine_records, parse_arena, parse_artificial_analysis, parse_benchlm, parse_codesota, parse_models_dev, refresh_source, save_cache


def test_evaluations_endpoint_exposes_source_status(client):
    response = client.get("/v1/evaluations")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert {source["id"] for source in payload["sources"]} >= {"models-dev", "benchlm", "codesota"}


def test_models_dev_preserves_metadata_and_cost():
    rows = parse_models_dev({
        "openai": {
            "models": {
                "gpt-test": {
                    "id": "gpt-test",
                    "name": "GPT Test",
                    "description": "test model",
                    "reasoning": True,
                    "tool_call": True,
                    "modalities": {"input": ["text", "image"], "output": ["text"]},
                    "limit": {"context": 128000},
                    "cost": {"input": 1, "output": 4},
                }
            }
        }
    })
    assert len(rows) == 1
    assert rows[0]["provider"] == "openai"
    assert "vision" in rows[0]["capabilities"]
    assert rows[0]["contextLength"] == 128000
    assert rows[0]["cost"] == {"input": 1, "output": 4}
    assert rows[0]["reasoning"] is True


def test_models_dev_gets_explicit_estimated_intelligence():
    rows = combine_records([{
        "key": "gptmini",
        "modelId": "gpt-mini",
        "label": "GPT Mini",
        "source": "models-dev",
        "aliases": ["gpt-mini"],
        "capabilities": ["chat", "tools"],
        "contextLength": 128000,
        "cost": {"input": 0.1, "output": 0.4},
        "scores": {},
        "ranks": {},
        "tags": [],
    }])
    assert rows[0]["intelligenceSource"] == "estimated"
    assert rows[0]["intelligenceEstimated"] is True
    assert 20 <= rows[0]["intelligence"] <= 95


def test_comparable_leaderboards_merge_with_source_weights():
    records = [
        {"key": "a", "modelId": "a", "label": "A", "source": "benchlm", "aliases": ["a"], "capabilities": [], "cost": {}, "scores": {"overall": 80, "coding": 80, "writing": 90}, "ranks": {}, "tags": []},
        {"key": "a", "modelId": "a", "label": "A", "source": "artificial-analysis", "aliases": ["a"], "capabilities": [], "cost": {}, "scores": {"overall": 85, "coding": 90, "writing": 70}, "ranks": {}, "tags": []},
        {"key": "a", "modelId": "a", "label": "A", "source": "arena", "aliases": ["a"], "capabilities": [], "cost": {}, "scores": {"overall": 1200, "coding": 1200}, "ranks": {}, "tags": []},
        {"key": "b", "modelId": "b", "label": "B", "source": "benchlm", "aliases": ["b"], "capabilities": [], "cost": {}, "scores": {"overall": 60, "coding": 50, "writing": 40}, "ranks": {}, "tags": []},
    ]
    rows = {row["key"]: row for row in combine_records(records)}
    assert rows["a"]["leaderboardScores"]["coding"] > rows["b"]["leaderboardScores"]["coding"]
    assert len(rows["a"]["leaderboardBreakdown"]["coding"]) == 3
    assert "renormalizes" in rows["a"]["leaderboardFormula"]
    assert "top_coding" in rows["a"]["tags"]
    assert "top_writing" in rows["a"]["tags"]


def test_benchlm_scores_and_category_ranks():
    rows = parse_benchlm({
        "items": [{
            "slug": "gpt-test",
            "model": "GPT Test",
            "scores": {"displayScore": 82, "displayCategoryScores": {"coding": 90}},
            "ranking": {"overallRank": 2, "categoryRanks": {"coding": 1}},
        }]
    })
    assert rows[0]["scores"]["overall"] == 82
    assert rows[0]["scores"]["coding"] == 90
    assert rows[0]["ranks"]["coding"] == 1


def test_artificial_analysis_nested_indices_are_normalized():
    rows = parse_artificial_analysis({"data": [{
        "model_name": "GPT Test",
        "model_id": "gpt-test",
        "evaluations": {
            "artificial_analysis_intelligence_index": 91,
            "artificial_analysis_coding_index": 88,
            "artificial_analysis_agentic_index": 84,
        },
        "performance": {"tokens_per_second": 120},
        "artificial_analysis_intelligence_index_cost": {"cost_per_task": {"total_cost": 0.0042}},
        "artificial_analysis_intelligence_index_token_counts": {"output_tokens_per_task": 1850},
    }]})
    assert rows[0]["scores"]["overall"] == 91
    assert rows[0]["scores"]["coding"] == 88
    assert rows[0]["scores"]["agentic"] == 84
    assert rows[0]["speed"] == 120
    assert rows[0]["costPerTask"] == 0.0042
    assert rows[0]["tokensPerTask"] == 1850


def test_efficiency_tiers_use_quality_rank_and_relative_cost():
    records = []
    for index, (name, score, rank, task_cost) in enumerate([
        ("luna", 90, 8, 0.001),
        ("flash", 82, 15, 0.002),
        ("solid", 78, 18, 0.01),
        ("cheap", 72, 20, 0.003),
        ("slow", 95, 2, 0.2),
        ("filler-a", 60, 30, 0.3),
        ("filler-b", 60, 31, 0.4),
        ("filler-c", 60, 32, 0.5),
        ("filler-d", 60, 33, 0.6),
    ]):
        records.append({
            "key": name, "modelId": name, "label": name, "source": "benchlm",
            "aliases": [name], "capabilities": [], "cost": {}, "costPerTask": task_cost,
            "scores": {"overall": score}, "ranks": {}, "rank": rank, "tags": [],
        })
    rows = {row["key"]: row for row in combine_records(records)}
    assert "super_efficient" in rows["luna"]["tags"]
    assert "very_efficient" in rows["flash"]["tags"]
    assert "efficient" in rows["cheap"]["tags"]
    assert not any(tag.endswith("_efficient") for tag in rows["slow"]["tags"])
    assert rows["luna"]["efficiencyCostBasis"] == "cost-per-task"


def test_efficiency_uses_a_high_ranked_category_score():
    rows = combine_records([
        {"key": "luna", "modelId": "luna", "label": "Luna", "source": "benchlm", "aliases": ["luna"], "capabilities": [], "costPerTask": 0.001, "cost": {}, "scores": {"overall": 61, "coding": 75}, "ranks": {"coding": 6}, "rank": 24, "tags": []},
        *[{"key": f"filler-{index}", "modelId": f"filler-{index}", "label": f"Filler {index}", "source": "benchlm", "aliases": [], "capabilities": [], "costPerTask": 0.2 + index, "cost": {}, "scores": {"overall": 60}, "ranks": {}, "rank": 30 + index, "tags": []} for index in range(4)]
    ])
    luna = next(row for row in rows if row["key"] == "luna")
    assert luna["efficiencyIntelligence"] == 75
    assert luna["efficiencyRank"] == 6
    assert "efficient" in luna["tags"]


def test_score_normalization_prevents_elo_from_dominating():
    rows = combine_records([
        {"key": "a", "modelId": "a", "label": "A", "source": "benchlm", "aliases": ["a"], "capabilities": [], "cost": {}, "scores": {"overall": 80}, "ranks": {}, "tags": []},
        {"key": "a", "modelId": "a", "label": "A", "source": "arena", "aliases": ["a"], "capabilities": [], "cost": {}, "scores": {"overall": 1300}, "ranks": {}, "tags": []},
    ])
    assert rows[0]["intelligence"] < 90
    assert rows[0]["intelligenceBreakdown"][1]["score"] < 100


def test_arena_and_codesota_are_tolerant_annotations():
    arena = parse_arena({"meta": {"leaderboard": "code"}, "models": [{"model": "GPT Test", "rank": 1, "score": 1300}]})
    codesota = parse_codesota({"task": "code", "pick": {"model_id": "gpt-test", "model_name": "GPT Test", "score": 99, "score_metric": "accuracy"}})
    assert arena[0]["ranks"] == {"coding": 1}
    assert arena[0]["scores"]["coding"] == 1300
    assert codesota[0]["annotationOnly"] is True


def test_cost_aware_recommendation_tags_and_sixth_band():
    records = []
    for name, rank, blend in (("cheap", 4, 1), ("four-dollar", 1, 12), ("five-dollar", 2, 25), ("six-dollar", 3, 31)):
        records.append({
            "key": name, "modelId": name, "label": name, "source": "benchlm", "aliases": [name],
            "capabilities": [], "cost": {"input": blend, "output": blend}, "scores": {"overall": 90},
            "ranks": {}, "rank": rank, "tags": [],
        })
    rows = {row["key"]: row for row in combine_records(records)}
    assert rows["four-dollar"]["costLabel"] == "$$$$"
    assert "highly_recommended" in rows["four-dollar"]["tags"]
    assert "best_in_class" not in rows["four-dollar"]["tags"]
    assert rows["five-dollar"]["costLabel"] == "$$$$$"
    assert not {"best_in_class", "highly_recommended", "recommended"}.intersection(rows["five-dollar"]["tags"])
    assert rows["six-dollar"]["costLabel"] == "$$$$$$"
    assert not {"best_in_class", "highly_recommended", "recommended"}.intersection(rows["six-dollar"]["tags"])


def test_cost_bands_follow_effective_price_examples():
    records = []
    for index, pair in enumerate(((0.2, 0.6), (2, 6), (None, 15), (5, 50))):
        records.append({
            "key": f"model{index}",
            "modelId": f"model-{index}",
            "label": f"Model {index}",
            "source": "models-dev",
            "aliases": [f"model-{index}"],
            "capabilities": ["chat"],
            "cost": {key: value for key, value in zip(("input", "output"), pair) if value is not None},
            "scores": {},
            "ranks": {},
            "tags": [],
        })
    assert [row["costLabel"] for row in combine_records(records)] == ["$", "$$$", "$$$$", "$$$$$$"]


def test_failed_refresh_keeps_last_successful_records(tmp_path, monkeypatch):
    save_cache(tmp_path, {"updatedAt": "downloaded", "sources": {"benchlm": {"loaded": True, "count": 1, "updatedAt": "downloaded"}}, "records": [{
        "key": "old", "modelId": "old", "label": "Old", "source": "benchlm", "aliases": ["old"], "capabilities": [], "cost": {}, "scores": {"overall": 90}, "ranks": {}, "tags": []
    }]})

    async def failed_fetch(_source, _http, _cache_dir=None, _api_key=""):
        raise RuntimeError("soft ban")

    monkeypatch.setattr("app.evaluations.fetch_source", failed_fetch)
    result = __import__("asyncio").run(refresh_source(tmp_path, "benchlm"))
    assert result["ok"] is False
    assert result["status"]["loaded"] is True
    assert result["status"]["error"] == "soft ban"
    assert result["status"]["updatedAt"] == "downloaded"
    assert result["status"]["lastAttemptAt"]
    assert result["models"][0]["modelId"] == "old"


def test_disabled_sources_are_excluded_from_merged_payload(tmp_path):
    save_cache(tmp_path, {"updatedAt": "now", "sources": {}, "records": [
        {"key": "same", "modelId": "same", "label": "Same", "source": "benchlm", "aliases": ["same"], "capabilities": [], "cost": {}, "scores": {"overall": 99}, "ranks": {}, "tags": []},
        {"key": "same", "modelId": "same", "label": "Same", "source": "arena", "aliases": ["same"], "capabilities": [], "cost": {}, "scores": {"overall": 1100}, "ranks": {}, "tags": []},
    ]})
    from app.evaluations import public_payload
    all_sources = public_payload(tmp_path)["models"][0]
    bench_only = public_payload(tmp_path, {"benchlm"})["models"][0]
    assert all_sources["intelligence"] != bench_only["intelligence"]
    assert bench_only["sources"] == ["benchlm"]


def test_combined_metadata_weights_scores_and_tags():
    rows = combine_records([
        {"key": "gpttest", "modelId": "gpt-test", "label": "GPT Test", "source": "benchlm", "aliases": ["gpt-test"], "capabilities": [], "cost": {"input": 0.2, "output": 0.8}, "scores": {"overall": 90}, "ranks": {"coding": 1}, "tags": []},
        {"key": "gpttest", "modelId": "gpt-test", "label": "GPT Test", "source": "artificial-analysis", "aliases": ["gpt-test"], "capabilities": [], "cost": {}, "scores": {"overall": 80}, "ranks": {}, "tags": []},
    ])
    assert len(rows) == 1
    assert rows[0]["intelligence"] == 85
    assert rows[0]["intelligenceMethod"] == "weighted-leaderboards"
    assert rows[0]["costLabel"]
    assert "top_coding" in rows[0]["tags"]
    assert "recommended" in rows[0]["tags"]
    assert set(rows[0]["sources"]) == {"benchlm", "artificial-analysis"}
