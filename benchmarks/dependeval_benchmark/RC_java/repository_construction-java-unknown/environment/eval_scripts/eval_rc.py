#!/usr/bin/env python3
"""
Repository Construction Evaluation Script

Evaluates call chain graph similarity using NetworkX.
Based on DependEval's eval_RC.py implementation.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import networkx as nx
except ImportError:
    print("Error: networkx is required. Install with: pip install networkx", file=sys.stderr)
    sys.exit(1)


def build_graph_from_call_chain(call_chain: dict | list) -> nx.DiGraph:
    """
    Build directed graph from call chain data

    Args:
        call_chain: Dictionary or list representing function calls

    Returns:
        NetworkX directed graph
    """
    G = nx.DiGraph()

    if isinstance(call_chain, dict):
        # Process dictionary-based call chain
        for caller, callees in call_chain.items():
            if not callees:
                # Add isolated node
                G.add_node(caller)
            else:
                if isinstance(callees, list):
                    for callee in callees:
                        G.add_edge(caller, callee)
                else:
                    G.add_edge(caller, callees)

    elif isinstance(call_chain, list):
        # Process list-based call chain (inverted format)
        for item in call_chain:
            if isinstance(item, dict):
                for caller, callees in item.items():
                    if isinstance(callees, list):
                        for callee in callees:
                            G.add_edge(caller, callee)
                    else:
                        G.add_edge(caller, callees)
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                # Edge format: (source, target)
                G.add_edge(item[0], item[1])

    return G


def calculate_graph_similarity(pred_graph: nx.DiGraph, gt_graph: nx.DiGraph) -> dict:
    """
    Calculate similarity metrics between two graphs

    Returns:
        Dictionary with node and edge precision, recall, and F1 scores
    """
    # Node-level metrics
    pred_nodes = set(pred_graph.nodes())
    gt_nodes = set(gt_graph.nodes())

    if len(pred_nodes) == 0 and len(gt_nodes) == 0:
        node_precision = node_recall = node_f1 = 1.0
    elif len(pred_nodes) == 0 or len(gt_nodes) == 0:
        node_precision = node_recall = node_f1 = 0.0
    else:
        node_intersection = pred_nodes & gt_nodes
        node_precision = len(node_intersection) / len(pred_nodes) if pred_nodes else 0.0
        node_recall = len(node_intersection) / len(gt_nodes) if gt_nodes else 0.0
        node_f1 = (2 * node_precision * node_recall / (node_precision + node_recall)
                   if (node_precision + node_recall) > 0 else 0.0)

    # Edge-level metrics
    pred_edges = set(pred_graph.edges())
    gt_edges = set(gt_graph.edges())

    if len(pred_edges) == 0 and len(gt_edges) == 0:
        edge_precision = edge_recall = edge_f1 = 1.0
    elif len(pred_edges) == 0 or len(gt_edges) == 0:
        edge_precision = edge_recall = edge_f1 = 0.0
    else:
        edge_intersection = pred_edges & gt_edges
        edge_precision = len(edge_intersection) / len(pred_edges) if pred_edges else 0.0
        edge_recall = len(edge_intersection) / len(gt_edges) if gt_edges else 0.0
        edge_f1 = (2 * edge_precision * edge_recall / (edge_precision + edge_recall)
                   if (edge_precision + edge_recall) > 0 else 0.0)

    return {
        'node_precision': node_precision,
        'node_recall': node_recall,
        'node_f1': node_f1,
        'edge_precision': edge_precision,
        'edge_recall': edge_recall,
        'edge_f1': edge_f1,
    }


def evaluate_rc(prediction_file: Path, ground_truth_file: Path) -> float:
    """
    Evaluate Repository Construction task

    Returns:
        Combined F1 score: 0.15 * node_F1 + 0.85 * edge_F1
    """
    try:
        # Load prediction
        with open(prediction_file) as f:
            pred_data = json.load(f)

        # Load ground truth
        with open(ground_truth_file) as f:
            gt_data = json.load(f)

        # Build graphs
        pred_graph = build_graph_from_call_chain(pred_data)
        gt_graph = build_graph_from_call_chain(gt_data)

        # Calculate similarity
        metrics = calculate_graph_similarity(pred_graph, gt_graph)

        # Combined score with weighted F1 (emphasize edges over nodes)
        combined_f1 = 0.15 * metrics['node_f1'] + 0.85 * metrics['edge_f1']

        print(f"Node F1: {metrics['node_f1']:.4f}", file=sys.stderr)
        print(f"Edge F1: {metrics['edge_f1']:.4f}", file=sys.stderr)
        print(f"Combined F1: {combined_f1:.4f}", file=sys.stderr)

        return combined_f1

    except Exception as e:
        print(f"Error during evaluation: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        return 0.0


def main():
    parser = argparse.ArgumentParser(description="Evaluate Repository Construction")
    parser.add_argument("--prediction", required=True, help="Path to prediction file")
    parser.add_argument("--ground_truth", required=True, help="Path to ground truth file")
    parser.add_argument("--output", required=True, help="Path to output reward file")

    args = parser.parse_args()

    # Run evaluation
    score = evaluate_rc(
        Path(args.prediction),
        Path(args.ground_truth)
    )

    # Write reward
    with open(args.output, 'w') as f:
        f.write(f"{score:.4f}\n")

    print(f"Repository Construction Score: {score:.4f}")


if __name__ == "__main__":
    main()
