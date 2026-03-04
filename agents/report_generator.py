"""
Report Generator for Ablation Studies.

Generates human-readable Markdown reports comparing agent variants.
"""

from datetime import datetime
from pathlib import Path

from .metrics_aggregator import JobMetrics, AgentMetrics


def generate_comparative_report(job_metrics: JobMetrics) -> str:
    """Generate a comprehensive Markdown report comparing agent variants."""
    lines = []
    
    # Header
    lines.append(f"# Ablation Study Report: {job_metrics.job_name}")
    lines.append("")
    if job_metrics.description:
        lines.append(f"> {job_metrics.description}")
        lines.append("")
    
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Dataset:** {job_metrics.dataset}")
    lines.append(f"**Tasks Evaluated:** {job_metrics.tasks_evaluated}")
    lines.append("")
    
    # Executive Summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(_generate_executive_summary(job_metrics))
    lines.append("")
    
    # Pass Rates Comparison
    lines.append("## Pass Rate Comparison")
    lines.append("")
    lines.append(_generate_pass_rate_table(job_metrics))
    lines.append("")
    
    # Cost Analysis
    lines.append("## Cost Analysis")
    lines.append("")
    lines.append(_generate_cost_table(job_metrics))
    lines.append("")
    
    # Speed Analysis
    lines.append("## Speed Analysis")
    lines.append("")
    lines.append(_generate_speed_table(job_metrics))
    lines.append("")
    
    # MCP Usage Analysis
    if any(a.mcp_used for a in job_metrics.agents.values()):
        lines.append("## MCP Tool Usage")
        lines.append("")
        lines.append(_generate_mcp_table(job_metrics))
        lines.append("")
    
    # Code Changes Summary
    lines.append("## Code Changes Summary")
    lines.append("")
    lines.append(_generate_code_changes_table(job_metrics))
    lines.append("")
    
    # Per-Agent Details
    lines.append("## Agent Details")
    lines.append("")
    for agent_name, agent_metrics in job_metrics.agents.items():
        lines.append(_generate_agent_detail_section(agent_metrics))
        lines.append("")
    
    # Recommendations
    lines.append("## Recommendations")
    lines.append("")
    lines.append(_generate_recommendations(job_metrics))
    
    return "\n".join(lines)


def _generate_executive_summary(job_metrics: JobMetrics) -> str:
    """Generate executive summary paragraph."""
    agents = job_metrics.agents
    if not agents:
        return "No agent data available."
    
    lines = []
    
    # Find best performers
    best_pass_rate = max(agents.values(), key=lambda a: a.pass_rate)
    cheapest = min(agents.values(), key=lambda a: a.avg_cost_usd if a.avg_cost_usd > 0 else float('inf'))
    fastest = min(agents.values(), key=lambda a: a.avg_wall_clock_seconds if a.avg_wall_clock_seconds > 0 else float('inf'))
    
    lines.append(f"Evaluated **{len(agents)} agent variants** across **{job_metrics.tasks_evaluated} tasks**.")
    lines.append("")
    
    if len(agents) > 1:
        lines.append("**Key Findings:**")
        lines.append(f"- **Best Pass Rate:** {best_pass_rate.agent} ({best_pass_rate.pass_rate:.0%})")
        lines.append(f"- **Most Cost Efficient:** {cheapest.agent} (${cheapest.avg_cost_usd:.4f}/task)")
        lines.append(f"- **Fastest:** {fastest.agent} ({fastest.avg_wall_clock_seconds:.1f}s avg)")
        
        # MCP impact
        mcp_agents = [a for a in agents.values() if a.mcp_used]
        non_mcp_agents = [a for a in agents.values() if not a.mcp_used]
        
        if mcp_agents and non_mcp_agents:
            mcp_avg_pass = sum(a.pass_rate for a in mcp_agents) / len(mcp_agents)
            non_mcp_avg_pass = sum(a.pass_rate for a in non_mcp_agents) / len(non_mcp_agents)
            lines.append("")
            lines.append(f"**MCP Impact:** Agents with MCP: {mcp_avg_pass:.0%} pass rate vs {non_mcp_avg_pass:.0%} without MCP")
    else:
        agent = list(agents.values())[0]
        lines.append(f"**Single Agent Results:** {agent.agent}")
        lines.append(f"- Pass Rate: {agent.pass_rate:.0%}")
        lines.append(f"- Avg Cost: ${agent.avg_cost_usd:.4f}")
        lines.append(f"- Avg Time: {agent.avg_wall_clock_seconds:.1f}s")
    
    return "\n".join(lines)


def _generate_pass_rate_table(job_metrics: JobMetrics) -> str:
    """Generate pass rate comparison table."""
    agents = job_metrics.agents
    if not agents:
        return "No data."
    
    lines = []
    lines.append("| Agent | Completed | Passed | Failed | Error | Pass Rate |")
    lines.append("|-------|-----------|--------|--------|-------|-----------|")
    
    for name, agent in sorted(agents.items(), key=lambda x: -x[1].pass_rate):
        lines.append(
            f"| {name} | {agent.tasks_completed} | {agent.tasks_passed} | "
            f"{agent.tasks_failed} | {agent.tasks_error} | **{agent.pass_rate:.0%}** |"
        )
    
    return "\n".join(lines)


def _generate_cost_table(job_metrics: JobMetrics) -> str:
    """Generate cost comparison table."""
    agents = job_metrics.agents
    if not agents:
        return "No data."
    
    lines = []
    lines.append("| Agent | Avg Cost | Total Cost | Avg Tokens | Tokens In | Tokens Out |")
    lines.append("|-------|----------|------------|------------|-----------|------------|")
    
    for name, agent in sorted(agents.items(), key=lambda x: x[1].avg_cost_usd):
        lines.append(
            f"| {name} | ${agent.avg_cost_usd:.4f} | ${agent.total_cost_usd:.4f} | "
            f"{agent.avg_tokens_total:,.0f} | {agent.avg_tokens_input:,.0f} | {agent.avg_tokens_output:,.0f} |"
        )
    
    return "\n".join(lines)


def _generate_speed_table(job_metrics: JobMetrics) -> str:
    """Generate speed comparison table."""
    agents = job_metrics.agents
    if not agents:
        return "No data."
    
    lines = []
    lines.append("| Agent | Avg Time (s) | Median Time (s) | Avg Steps | Agent Exec (s) |")
    lines.append("|-------|--------------|-----------------|-----------|----------------|")
    
    for name, agent in sorted(agents.items(), key=lambda x: x[1].avg_wall_clock_seconds):
        lines.append(
            f"| {name} | {agent.avg_wall_clock_seconds:.1f} | {agent.median_wall_clock_seconds:.1f} | "
            f"{agent.avg_steps_to_completion:.1f} | {agent.avg_agent_execution_seconds:.1f} |"
        )
    
    return "\n".join(lines)


def _generate_mcp_table(job_metrics: JobMetrics) -> str:
    """Generate MCP usage comparison table."""
    agents = job_metrics.agents
    if not agents:
        return "No data."
    
    lines = []
    lines.append("| Agent | MCP Used | Usage Rate | Avg MCP Calls | MCP Tools |")
    lines.append("|-------|----------|------------|---------------|-----------|")
    
    for name, agent in agents.items():
        mcp_tools_str = ", ".join(agent.mcp_tools_seen[:3])
        if len(agent.mcp_tools_seen) > 3:
            mcp_tools_str += f" (+{len(agent.mcp_tools_seen) - 3} more)"
        
        lines.append(
            f"| {name} | {'✅' if agent.mcp_used else '❌'} | {agent.mcp_usage_rate:.0%} | "
            f"{agent.avg_mcp_tools_called:.1f} | {mcp_tools_str or 'None'} |"
        )
    
    return "\n".join(lines)


def _generate_code_changes_table(job_metrics: JobMetrics) -> str:
    """Generate code changes comparison table."""
    agents = job_metrics.agents
    if not agents:
        return "No data."
    
    lines = []
    lines.append("| Agent | Files Modified | Lines Added | Lines Removed | Net Change |")
    lines.append("|-------|----------------|-------------|---------------|------------|")
    
    for name, agent in agents.items():
        net = agent.total_lines_added - agent.total_lines_removed
        net_str = f"+{net}" if net >= 0 else str(net)
        lines.append(
            f"| {name} | {agent.total_files_modified} | +{agent.total_lines_added} | "
            f"-{agent.total_lines_removed} | {net_str} |"
        )
    
    return "\n".join(lines)


def _generate_agent_detail_section(agent: AgentMetrics) -> str:
    """Generate detailed section for a single agent."""
    lines = []
    lines.append(f"### {agent.agent}")
    lines.append("")
    lines.append(f"**Import Path:** `{agent.import_path}`")
    lines.append("")
    lines.append(f"**Task Results:** {agent.tasks_passed}/{agent.tasks_completed} passed ({agent.pass_rate:.0%})")
    lines.append("")
    
    # Performance metrics
    lines.append("**Performance:**")
    lines.append(f"- Avg Wall Clock: {agent.avg_wall_clock_seconds:.1f}s")
    lines.append(f"- Avg Agent Execution: {agent.avg_agent_execution_seconds:.1f}s")
    lines.append(f"- Avg Steps: {agent.avg_steps_to_completion:.1f}")
    lines.append("")
    
    # Cost metrics
    lines.append("**Cost:**")
    lines.append(f"- Avg per Task: ${agent.avg_cost_usd:.4f}")
    lines.append(f"- Total: ${agent.total_cost_usd:.4f}")
    lines.append(f"- Avg Tokens: {agent.avg_tokens_total:,.0f}")
    lines.append("")
    
    # MCP usage
    if agent.mcp_used:
        lines.append("**MCP Usage:**")
        lines.append(f"- Usage Rate: {agent.mcp_usage_rate:.0%}")
        lines.append(f"- Avg Calls per Task: {agent.avg_mcp_tools_called:.1f}")
        lines.append(f"- Tools Used: {', '.join(agent.mcp_tools_seen) or 'None'}")
        lines.append("")
    
    # Trials
    if agent.trials:
        lines.append("**Trials:**")
        for trial in agent.trials[:5]:  # Show first 5
            status_emoji = "✅" if trial.status == "passed" else "❌"
            lines.append(f"- {status_emoji} `{trial.trial_id}` ({trial.timing.wall_clock_seconds:.1f}s, ${trial.cost.total_usd:.4f})")
        if len(agent.trials) > 5:
            lines.append(f"- ... and {len(agent.trials) - 5} more")
    
    return "\n".join(lines)


def _generate_recommendations(job_metrics: JobMetrics) -> str:
    """Generate recommendations based on results."""
    agents = job_metrics.agents
    if not agents:
        return "No data available for recommendations."
    
    lines = []
    
    if len(agents) == 1:
        agent = list(agents.values())[0]
        lines.append(f"Single agent evaluated: **{agent.agent}**")
        if agent.pass_rate >= 0.9:
            lines.append("- High pass rate indicates reliable performance")
        elif agent.pass_rate >= 0.5:
            lines.append("- Moderate pass rate; consider reviewing failed cases")
        else:
            lines.append("- Low pass rate; requires investigation")
        return "\n".join(lines)
    
    # Multi-agent recommendations
    best_pass = max(agents.values(), key=lambda a: a.pass_rate)
    cheapest = min(agents.values(), key=lambda a: a.avg_cost_usd if a.avg_cost_usd > 0 else float('inf'))
    fastest = min(agents.values(), key=lambda a: a.avg_wall_clock_seconds if a.avg_wall_clock_seconds > 0 else float('inf'))
    
    lines.append("Based on the evaluation results:")
    lines.append("")
    
    # Best overall
    if best_pass.pass_rate > 0.9:
        lines.append(f"1. **For maximum reliability:** Use **{best_pass.agent}** ({best_pass.pass_rate:.0%} pass rate)")
    
    # Cost optimization
    if cheapest != best_pass and cheapest.pass_rate > 0.7:
        lines.append(f"2. **For cost optimization:** Consider **{cheapest.agent}** (${cheapest.avg_cost_usd:.4f}/task)")
    
    # Speed optimization
    if fastest != best_pass and fastest.pass_rate > 0.7:
        lines.append(f"3. **For speed:** Consider **{fastest.agent}** ({fastest.avg_wall_clock_seconds:.1f}s avg)")
    
    # MCP analysis
    mcp_agents = [a for a in agents.values() if a.mcp_used]
    non_mcp_agents = [a for a in agents.values() if not a.mcp_used]
    
    if mcp_agents and non_mcp_agents:
        mcp_avg_pass = sum(a.pass_rate for a in mcp_agents) / len(mcp_agents)
        non_mcp_avg_pass = sum(a.pass_rate for a in non_mcp_agents) / len(non_mcp_agents)
        mcp_avg_cost = sum(a.avg_cost_usd for a in mcp_agents) / len(mcp_agents)
        non_mcp_avg_cost = sum(a.avg_cost_usd for a in non_mcp_agents) / len(non_mcp_agents)
        
        lines.append("")
        lines.append("**MCP Trade-off Analysis:**")
        
        if mcp_avg_pass > non_mcp_avg_pass:
            improvement = (mcp_avg_pass - non_mcp_avg_pass) * 100
            lines.append(f"- MCP agents show +{improvement:.1f}% higher pass rate")
        else:
            decrease = (non_mcp_avg_pass - mcp_avg_pass) * 100
            lines.append(f"- MCP agents show -{decrease:.1f}% lower pass rate")
        
        if mcp_avg_cost > non_mcp_avg_cost:
            overhead = ((mcp_avg_cost / non_mcp_avg_cost) - 1) * 100
            lines.append(f"- MCP overhead: +{overhead:.1f}% cost")
        else:
            savings = (1 - (mcp_avg_cost / non_mcp_avg_cost)) * 100
            lines.append(f"- MCP savings: -{savings:.1f}% cost")
    
    return "\n".join(lines)


def save_report(job_metrics: JobMetrics, output_path: str | Path) -> Path:
    """Generate and save the comparative report."""
    output_path = Path(output_path)
    report = generate_comparative_report(job_metrics)
    output_path.write_text(report)
    return output_path


if __name__ == "__main__":
    import sys
    from .metrics_aggregator import aggregate_from_job_directory
    
    if len(sys.argv) < 2:
        print("Usage: python report_generator.py <job_dir>")
        sys.exit(1)
    
    job_dir = Path(sys.argv[1])
    job_metrics = aggregate_from_job_directory(job_dir)
    report = generate_comparative_report(job_metrics)
    print(report)
