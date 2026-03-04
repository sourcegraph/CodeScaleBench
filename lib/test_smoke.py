#!/usr/bin/env python3
"""V2 Smoke Tests.

Validates the v2 runner functionality without executing actual Harbor runs.

Usage:
    python -m v2.test_smoke
    # or
    python v2/test_smoke.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))


def test_config_loading():
    """Test configuration loading and validation."""
    print("[TEST] Config loading...")
    
    from lib.config.loader import load_config
    from lib.config.schema import ExperimentConfig
    
    config_path = SCRIPT_DIR / "configs" / "smoke_test.yaml"
    if not config_path.exists():
        print(f"  [SKIP] Config not found: {config_path}")
        return False
    
    config = load_config(config_path)
    assert isinstance(config, ExperimentConfig), "Config should be ExperimentConfig"
    assert config.experiment_name == "v2_smoke_test", "Wrong experiment name"
    assert len(config.mcp_modes) == 2, "Should have 2 MCP modes"
    assert "baseline" in config.mcp_modes, "Should include baseline"
    
    print("  [PASS] Config loading works")
    return True


def test_matrix_expansion():
    """Test matrix expansion generates correct runs and pairs."""
    print("[TEST] Matrix expansion...")
    
    from lib.config.loader import load_config
    from lib.matrix.expander import MatrixExpander
    
    config_path = SCRIPT_DIR / "configs" / "smoke_test.yaml"
    config = load_config(config_path)
    
    expander = MatrixExpander(config, config_path)
    runs, pairs = expander.expand()
    
    assert len(runs) == 2, f"Expected 2 runs, got {len(runs)}"
    assert len(pairs) == 1, f"Expected 1 pair, got {len(pairs)}"
    
    mcp_modes = {r.mcp_mode for r in runs}
    assert "baseline" in mcp_modes, "Should have baseline run"
    assert "deepsearch_hybrid" in mcp_modes, "Should have deepsearch_hybrid run"
    
    baseline_run = next(r for r in runs if r.mcp_mode == "baseline")
    mcp_run = next(r for r in runs if r.mcp_mode == "deepsearch_hybrid")
    assert baseline_run.invariant_hash == mcp_run.invariant_hash, \
        "Paired runs should have same invariant hash"
    
    assert baseline_run.pair_id is not None, "Baseline run should have pair_id"
    assert mcp_run.pair_id is not None, "MCP run should have pair_id"
    assert baseline_run.pair_id == mcp_run.pair_id, "Paired runs should share pair_id"
    
    print("  [PASS] Matrix expansion works")
    return True


def test_deterministic_ids():
    """Test that IDs are deterministic across runs."""
    print("[TEST] Deterministic IDs...")
    
    from lib.config.loader import load_config
    from lib.matrix.expander import MatrixExpander
    
    config_path = SCRIPT_DIR / "configs" / "smoke_test.yaml"
    config = load_config(config_path)
    
    expander1 = MatrixExpander(config, config_path)
    runs1, pairs1 = expander1.expand()
    
    expander2 = MatrixExpander(config, config_path)
    runs2, pairs2 = expander2.expand()
    
    run_ids_1 = sorted(r.run_id for r in runs1)
    run_ids_2 = sorted(r.run_id for r in runs2)
    assert run_ids_1 == run_ids_2, "Run IDs should be deterministic"
    
    pair_ids_1 = sorted(p.pair_id for p in pairs1)
    pair_ids_2 = sorted(p.pair_id for p in pairs2)
    assert pair_ids_1 == pair_ids_2, "Pair IDs should be deterministic"
    
    print("  [PASS] IDs are deterministic")
    return True


def test_mcp_configurator():
    """Test MCP configuration toggle."""
    print("[TEST] MCP configurator...")
    
    from lib.mcp.configurator import MCPConfigurator
    
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        configurator = MCPConfigurator(logs_dir=workspace)
        
        baseline_result = configurator.configure_for_run(
            workspace_dir=workspace / "baseline",
            mcp_mode="baseline"
        )
        
        assert baseline_result.mcp_enabled is False, "Baseline should have MCP disabled"
        assert baseline_result.mcp_config_path is None, "Baseline should have no config file"
        assert baseline_result.env_vars.get("BASELINE_MCP_TYPE") == "none", \
            "Baseline should set BASELINE_MCP_TYPE=none"
        
        os.environ.setdefault("SOURCEGRAPH_ACCESS_TOKEN", "test_token")
        
        mcp_result = configurator.configure_for_run(
            workspace_dir=workspace / "mcp",
            mcp_mode="deepsearch_hybrid"
        )
        
        assert mcp_result.mcp_enabled is True, "MCP run should have MCP enabled"
        assert mcp_result.mcp_config_path is not None, "MCP run should have config file"
        assert mcp_result.mcp_config_path.exists(), "Config file should exist"
        assert mcp_result.env_vars.get("BASELINE_MCP_TYPE") == "deepsearch_hybrid", \
            "MCP run should set correct BASELINE_MCP_TYPE"
        
        with open(mcp_result.mcp_config_path) as f:
            mcp_config = json.load(f)
        assert "mcpServers" in mcp_config, "Config should have mcpServers"
        assert "deepsearch" in mcp_config["mcpServers"], "Should have deepsearch server"
    
    print("  [PASS] MCP configurator works")
    return True


def test_schema_validation():
    """Test JSON schema validation."""
    print("[TEST] Schema validation...")
    
    schemas_dir = SCRIPT_DIR / "v2" / "schemas"
    
    results_schema = schemas_dir / "results_v1.json"
    comparison_schema = schemas_dir / "comparison_v1.json"
    
    assert results_schema.exists(), f"Results schema not found: {results_schema}"
    assert comparison_schema.exists(), f"Comparison schema not found: {comparison_schema}"
    
    with open(results_schema) as f:
        results = json.load(f)
    assert results.get("$schema") is not None, "Results schema should have $schema"
    assert "schema_version" in results.get("properties", {}), "Should have schema_version"
    
    with open(comparison_schema) as f:
        comparison = json.load(f)
    assert comparison.get("$schema") is not None, "Comparison schema should have $schema"
    assert "pair_id" in comparison.get("properties", {}), "Should have pair_id"
    
    print("  [PASS] Schemas are valid JSON")
    return True


def test_harbor_parser():
    """Test Harbor output parsing."""
    print("[TEST] Harbor parser...")
    
    from lib.exporter.harbor_parser import HarborParser
    
    jobs_dir = SCRIPT_DIR / "jobs"
    parser = HarborParser(jobs_dir)
    
    for job_dir in jobs_dir.iterdir():
        if not job_dir.is_dir():
            continue
        
        result = parser.parse_job(job_dir)
        if result:
            print(f"  [INFO] Parsed job: {result.job_name}")
            print(f"         Trials: {len(result.trials)}")
            for trial in result.trials[:2]:
                print(f"         - {trial.task_id}: reward={trial.reward}")
            break
    else:
        print("  [SKIP] No existing jobs to parse")
    
    print("  [PASS] Harbor parser works")
    return True


def run_all_tests():
    """Run all smoke tests."""
    print("\n" + "="*60)
    print("V2 SMOKE TESTS")
    print("="*60 + "\n")
    
    tests = [
        ("Config Loading", test_config_loading),
        ("Matrix Expansion", test_matrix_expansion),
        ("Deterministic IDs", test_deterministic_ids),
        ("MCP Configurator", test_mcp_configurator),
        ("Schema Validation", test_schema_validation),
        ("Harbor Parser", test_harbor_parser),
    ]
    
    passed = 0
    failed = 0
    
    for name, test_fn in tests:
        try:
            if test_fn():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("="*60 + "\n")
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
