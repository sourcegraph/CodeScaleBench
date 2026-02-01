#!/usr/bin/env python3
"""
Validates commit hashes exist in target repositories.

Checks if commits are reachable in the repository before task generation.
"""

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


def validate_commit(repo_url: str, commit_hash: str) -> Tuple[bool, str]:
    """
    Validate that a commit exists in a repository.
    
    Args:
        repo_url: Full GitHub URL (e.g., https://github.com/requests/requests)
        commit_hash: Full commit hash (40 chars)
    
    Returns:
        (is_valid, message)
    """
    if not commit_hash or len(commit_hash) < 40:
        return False, f"Invalid commit hash format: {commit_hash} (must be full SHA-1, 40 chars)"
    
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)
            
            # Shallow clone to verify commit exists
            result = subprocess.run(
                ["git", "clone", "--depth=1", repo_url, str(tmpdir_path / "repo")],
                capture_output=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return False, f"Failed to clone {repo_url}: {result.stderr.decode()[:100]}"
            
            repo_path = tmpdir_path / "repo"
            
            # Try to fetch the specific commit
            result = subprocess.run(
                ["git", "fetch", f"origin", commit_hash],
                cwd=repo_path,
                capture_output=True,
                timeout=30
            )
            
            if result.returncode != 0:
                # Try to verify if commit exists in shallow clone
                result = subprocess.run(
                    ["git", "rev-list", "--all", "--max-count=1", commit_hash],
                    cwd=repo_path,
                    capture_output=True,
                    timeout=10
                )
                
                if result.returncode != 0:
                    return False, f"Commit {commit_hash[:8]} not found in {repo_url}"
            
            return True, f"✓ Commit {commit_hash[:8]} valid"
            
    except subprocess.TimeoutExpired:
        return False, f"Timeout validating {commit_hash[:8]}"
    except Exception as e:
        return False, f"Error validating {commit_hash[:8]}: {str(e)[:100]}"


def validate_dataset(dataset_path: Path) -> Dict[str, Dict]:
    """
    Validate all commit hashes in a RepoQA dataset.
    
    Returns:
        Dict mapping instance_id to validation result: {
            "valid": bool,
            "message": str,
            "commit": str,
            "repo": str
        }
    """
    results = {}
    
    with open(dataset_path) as f:
        for i, line in enumerate(f, 1):
            try:
                instance = json.loads(line.strip())
                instance_id = instance.get("instance_id")
                repo = instance.get("repository")
                commit = instance.get("commit")
                
                if not instance_id or not repo or not commit:
                    results[instance_id] = {
                        "valid": False,
                        "message": f"Missing required fields",
                        "commit": commit,
                        "repo": repo
                    }
                    continue
                
                # Construct full GitHub URL if needed
                if not repo.startswith("http"):
                    repo_url = f"https://github.com/{repo}.git"
                else:
                    repo_url = repo if repo.endswith(".git") else f"{repo}.git"
                
                is_valid, message = validate_commit(repo_url, commit)
                results[instance_id] = {
                    "valid": is_valid,
                    "message": message,
                    "commit": commit[:8] if commit else None,
                    "repo": repo
                }
                
            except json.JSONDecodeError as e:
                results[f"line_{i}"] = {
                    "valid": False,
                    "message": f"Invalid JSON: {e}",
                    "commit": None,
                    "repo": None
                }
    
    return results


def print_validation_report(results: Dict[str, Dict]):
    """Print a formatted validation report."""
    print("\n" + "=" * 100)
    print("COMMIT HASH VALIDATION REPORT")
    print("=" * 100)
    
    valid_count = sum(1 for r in results.values() if r.get("valid"))
    invalid_count = len(results) - valid_count
    
    print(f"\nSummary: {valid_count}/{len(results)} instances valid\n")
    
    # Show invalid first
    if invalid_count > 0:
        print("❌ INVALID COMMITS:\n")
        for instance_id, result in sorted(results.items()):
            if not result.get("valid"):
                print(f"  {instance_id}")
                print(f"    Commit: {result.get('commit')}")
                print(f"    Repo:   {result.get('repo')}")
                print(f"    Error:  {result.get('message')}\n")
    
    # Show valid
    if valid_count > 0:
        print("✅ VALID COMMITS:\n")
        for instance_id, result in sorted(results.items()):
            if result.get("valid"):
                print(f"  {instance_id}: {result.get('commit')} in {result.get('repo')}")
    
    print("\n" + "=" * 100)
    
    return valid_count == len(results)


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python commit_validator.py <dataset.jsonl>")
        sys.exit(1)
    
    dataset_path = Path(sys.argv[1])
    if not dataset_path.exists():
        print(f"Error: {dataset_path} not found")
        sys.exit(1)
    
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    results = validate_dataset(dataset_path)
    all_valid = print_validation_report(results)
    
    sys.exit(0 if all_valid else 1)
