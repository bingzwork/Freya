"""Decision Visualization - Export decision trees, graphs, and timelines for debugging and analysis.

This module implements the Decision Visualization capability (Phase 2+ enhancement):
- Exports decision tree/graph structures for debugging
- Generates timeline views of decision → outcome chains
- Supports multiple output formats (DOT/GraphViz, Mermaid, JSON, HTML)
- Integrates with DecisionHistory for historical analysis
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import json
import uuid

from app.decision.history import DecisionHistory, DecisionRecord
from app.decision.models import DecisionType, DecisionCategory

logger = logging.getLogger(__name__)


@dataclass
class VisualizationNode:
    """A node in the decision visualization graph."""
    node_id: str
    label: str
    node_type: str  # "decision", "outcome", "action", "context"
    decision_id: Optional[str] = None
    parent_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[str] = None
    success: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "label": self.label,
            "node_type": self.node_type,
            "decision_id": self.decision_id,
            "parent_id": self.parent_id,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
            "success": self.success,
        }


@dataclass
class VisualizationEdge:
    """An edge in the decision visualization graph."""
    edge_id: str
    source_id: str
    target_id: str
    edge_type: str  # "leads_to", "caused_by", "alternative", "revision"
    label: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type,
            "label": self.label,
            "metadata": self.metadata,
        }


@dataclass
class DecisionTimelineEvent:
    """An event in the decision timeline."""
    event_id: str
    timestamp: str
    event_type: str  # "decision_made", "action_taken", "outcome_recorded", "revision", "approval"
    decision_id: str
    description: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "decision_id": self.decision_id,
            "description": self.description,
            "details": self.details,
        }


class DecisionVisualization:
    """Generates visualizations of decision processes and outcomes.

    This class provides the Decision Visualization capability:
    1. Builds decision graph from history
    2. Exports to multiple formats (DOT, Mermaid, JSON, HTML)
    3. Generates timeline views
    4. Supports filtering and focus modes
    """

    def __init__(
        self,
        decision_history: DecisionHistory,
        workspace: str = ".",
    ):
        """Initialize the visualization engine.

        Args:
            decision_history: DecisionHistory instance with recorded decisions
            workspace: Workspace path for output files
        """
        self.decision_history = decision_history
        self.workspace = Path(workspace).resolve()
        self._output_dir = self.workspace / "visualizations" / "decisions"
        self._output_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------------------
    # Public API - Graph Export
    # -------------------------------------------------------------------------

    def build_decision_graph(
        self,
        decision_ids: Optional[List[str]] = None,
        include_revisions: bool = True,
        include_alternatives: bool = True,
        max_depth: int = 10,
    ) -> Tuple[List[VisualizationNode], List[VisualizationEdge]]:
        """Build a decision graph from history.

        Args:
            decision_ids: Optional list of decision IDs to include (all if None)
            include_revisions: Whether to include revision chains
            include_alternatives: Whether to include alternative options
            max_depth: Maximum graph depth to prevent infinite loops

        Returns:
            Tuple of (nodes, edges)
        """
        records = self._get_filtered_records(decision_ids)
        nodes = []
        edges = []
        node_map: Dict[str, VisualizationNode] = {}

        # Create nodes for each decision record
        for record in records:
            node = self._create_decision_node(record)
            nodes.append(node)
            node_map[node.node_id] = node

            # Add option nodes if requested
            if include_alternatives:
                # Check if alternatives are stored in metadata
                alternatives = record.metadata.get("alternatives_considered", [])
                for i, alt in enumerate(alternatives):
                    alt_node = VisualizationNode(
                        node_id=f"alt_{record.decision_id}_{i}",
                        label=f"Alt: {alt.get('name', 'Unknown')}",
                        node_type="action",
                        parent_id=node.node_id,
                        metadata={"alternative": alt, "chosen": False},
                        timestamp=record.decided_at,
                    )
                    nodes.append(alt_node)
                    node_map[alt_node.node_id] = alt_node

                    edges.append(VisualizationEdge(
                        edge_id=f"edge_{record.decision_id}_alt_{i}",
                        source_id=node.node_id,
                        target_id=alt_node.node_id,
                        edge_type="alternative",
                        label="considered",
                    ))

            # Add chosen option node
            if record.chosen_option_name:
                chosen_node = VisualizationNode(
                    node_id=f"chosen_{record.decision_id}",
                    label=f"✓ {record.chosen_option_name}",
                    node_type="action",
                    parent_id=node.node_id,
                    metadata={"option_name": record.chosen_option_name, "chosen": True},
                    timestamp=record.decided_at,
                )
                nodes.append(chosen_node)
                node_map[chosen_node.node_id] = chosen_node

                edges.append(VisualizationEdge(
                    edge_id=f"edge_{record.decision_id}_chosen",
                    source_id=node.node_id,
                    target_id=chosen_node.node_id,
                    edge_type="leads_to",
                    label="chosen",
                ))

            # Add outcome node
            if record.outcome or record.actual_success is not None:
                success = record.actual_success if record.actual_success is not None else (record.outcome.get("success", False) if record.outcome else False)
                outcome_node = VisualizationNode(
                    node_id=f"outcome_{record.decision_id}",
                    label=f"{'✓ Success' if success else '✗ Failed'}",
                    node_type="outcome",
                    parent_id=chosen_node.node_id if record.chosen_option_name else node.node_id,
                    decision_id=record.decision_id,
                    metadata={"outcome": record.outcome, "success": success},
                    timestamp=record.decided_at,
                    success=success,
                )
                nodes.append(outcome_node)
                node_map[outcome_node.node_id] = outcome_node

                edges.append(VisualizationEdge(
                    edge_id=f"edge_{record.decision_id}_outcome",
                    source_id=chosen_node.node_id if record.chosen_option_name else node.node_id,
                    target_id=outcome_node.node_id,
                    edge_type="leads_to",
                    label="resulted in",
                ))

        # Add revision edges
        if include_revisions:
            self._add_revision_edges(records, nodes, edges, node_map)

        # Add causal edges (decisions that led to other decisions)
        self._add_causal_edges(records, nodes, edges, node_map)

        return nodes, edges

    def _add_revision_edges(
        self,
        records: List[DecisionRecord],
        nodes: List[VisualizationNode],
        edges: List[VisualizationEdge],
        node_map: Dict[str, VisualizationNode],
    ) -> None:
        """Add edges for decision revisions."""
        for record in records:
            if record.metadata and record.metadata.get("is_revision"):
                original_id = record.metadata.get("original_decision_id")
                if original_id and original_id in node_map:
                    edges.append(VisualizationEdge(
                        edge_id=f"edge_rev_{original_id}_{record.decision_id}",
                        source_id=node_map[original_id].node_id,
                        target_id=node_map[record.decision_id].node_id,
                        edge_type="revision",
                        label="revised",
                        metadata={"trigger_changes": record.metadata.get("trigger_changes", [])},
                    ))

    def _add_causal_edges(
        self,
        records: List[DecisionRecord],
        nodes: List[VisualizationNode],
        edges: List[VisualizationEdge],
        node_map: Dict[str, VisualizationNode],
    ) -> None:
        """Add causal edges between related decisions."""
        # Group by plan_id to find sequential decisions
        by_plan = defaultdict(list)
        for record in records:
            plan_id = record.metadata.get("plan_id") if record.metadata else None
            if plan_id:
                by_plan[plan_id].append(record)

        for plan_id, plan_records in by_plan.items():
            plan_records.sort(key=lambda r: r.decided_at)
            for i in range(len(plan_records) - 1):
                curr = plan_records[i]
                next_rec = plan_records[i + 1]
                if curr.decision_id in node_map and next_rec.decision_id in node_map:
                    edges.append(VisualizationEdge(
                        edge_id=f"edge_causal_{curr.decision_id}_{next_rec.decision_id}",
                        source_id=curr.decision_id,
                        target_id=next_rec.decision_id,
                        edge_type="caused_by",
                        label="→",
                        metadata={"plan_id": plan_id},
                    ))

    def _create_decision_node(self, record: DecisionRecord) -> VisualizationNode:
        """Create a visualization node from a decision record."""
        label_parts = [record.decision_type.value]
        if record.component:
            label_parts.append(f"[{record.component}]")
        if record.chosen_option_name:
            label_parts.append(f"→ {record.chosen_option_name[:30]}")

        return VisualizationNode(
            node_id=record.decision_id,
            label=" ".join(label_parts),
            node_type="decision",
            decision_id=record.decision_id,
            metadata={
                "decision_type": record.decision_type.value,
                "category": record.category.value,
                "risk_level": record.risk_level,
                "confidence": record.confidence,
                "confidence_level": record.confidence_level,
                "executed": record.executed,
            },
            timestamp=record.decided_at,
        )

    # -------------------------------------------------------------------------
    # Public API - Format Export
    # -------------------------------------------------------------------------

    def export_dot(
        self,
        nodes: List[VisualizationNode],
        edges: List[VisualizationEdge],
        filename: str = "decision_graph.dot",
        title: str = "Decision Graph",
        rankdir: str = "TB",
    ) -> str:
        """Export graph to DOT format (GraphViz)."""
        lines = [
            f'digraph "{title}" {{',
            f'  rankdir={rankdir};',
            '  node [fontname="Arial", fontsize=10];',
            '  edge [fontname="Arial", fontsize=9];',
            '',
        ]

        # Node definitions with styling
        for node in nodes:
            style = self._get_node_style(node)
            label = node.label.replace('"', '\\"')
            lines.append(f'  "{node.node_id}" [{style}, label="{label}"];')

        lines.append("")

        # Edge definitions
        for edge in edges:
            style = self._get_edge_style(edge)
            label = edge.label.replace('"', '\\"') if edge.label else ""
            label_attr = f', label="{label}"' if label else ""
            lines.append(f'  "{edge.source_id}" -> "{edge.target_id}" [{style}{label_attr}];')

        lines.append("}")
        content = "\n".join(lines)

        output_path = self._output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"[DecisionVisualization] Exported DOT to {output_path}")
        return str(output_path)

    def _get_node_style(self, node: VisualizationNode) -> str:
        """Get DOT style for a node."""
        if node.node_type == "decision":
            risk = node.metadata.get("risk_level", "low")
            colors = {"critical": "#FF4444", "high": "#FF8800", "medium": "#FFCC00", "low": "#44AA44", "info": "#4488FF"}
            color = colors.get(risk, "#888888")
            return f'shape=box, style="filled,rounded", fillcolor="#F5F5F5", color="{color}", penwidth=2'
        elif node.node_type == "action":
            color = "#4CAF50" if node.metadata.get("chosen") else "#2196F3"
            return f'shape=ellipse, style="filled", fillcolor="{color}22", color="{color}"'
        elif node.node_type == "outcome":
            if node.success:
                return 'shape=diamond, style="filled", fillcolor="#4CAF5022", color="#4CAF50"'
            else:
                return 'shape=diamond, style="filled", fillcolor="#FF444422", color="#FF4444"'
        elif node.node_type == "context":
            return 'shape=note, style="filled", fillcolor="#E3F2FD", color="#1976D2"'
        return 'shape=box, style="filled", fillcolor="#FFFFFF", color="#888888"'

    def _get_edge_style(self, edge: VisualizationEdge) -> str:
        """Get DOT style for an edge."""
        if edge.edge_type == "chosen":
            return 'color="#4CAF50", penwidth=2, arrowhead=normal'
        elif edge.edge_type == "alternative":
            return 'color="#2196F3", style=dashed, arrowhead=open'
        elif edge.edge_type == "revision":
            return 'color="#FF9800", style=dotted, penwidth=1.5, arrowhead=vee'
        elif edge.edge_type == "caused_by":
            return 'color="#9C27B0", style=dotted, arrowhead=vee'
        elif edge.edge_type == "leads_to":
            return 'color="#666666", penwidth=1, arrowhead=normal'
        return 'color="#888888", arrowhead=normal'

    def export_mermaid(
        self,
        nodes: List[VisualizationNode],
        edges: List[VisualizationEdge],
        filename: str = "decision_graph.mmd",
        title: str = "Decision Graph",
    ) -> str:
        """Export graph to Mermaid format."""
        lines = [
            f"%% {title}",
            "graph TD",
        ]

        # Node definitions
        node_styles = {}
        for node in nodes:
            node_id = node.node_id.replace("-", "_").replace(".", "_")
            label = node.label.replace('"', "'")

            if node.node_type == "decision":
                risk = node.metadata.get("risk_level", "low")
                if risk in ("critical", "high"):
                    style = "classDef decisionHigh fill:#FFEBEE,stroke:#C62828,stroke-width:2px;"
                else:
                    style = "classDef decision fill:#E3F2FD,stroke:#1565C0,stroke-width:1px;"
                node_styles[node_id] = "decisionHigh" if risk in ("critical", "high") else "decision"
                lines.append(f'  {node_id}["{label}"]')
            elif node.node_type == "action":
                if node.metadata.get("chosen"):
                    node_styles[node_id] = "chosen"
                    lines.append(f'  {node_id}[["✓ {label}"]]')
                else:
                    node_styles[node_id] = "alt"
                    lines.append(f'  {node_id}[("🔷 {label}")]')
            elif node.node_type == "outcome":
                if node.success:
                    node_styles[node_id] = "success"
                    lines.append(f'  {node_id}{{"✅ {label}"}}')
                else:
                    node_styles[node_id] = "failure"
                    lines.append(f'  {node_id}{{"❌ {label}"}}')

        # Edge definitions
        for edge in edges:
            source = edge.source_id.replace("-", "_").replace(".", "_")
            target = edge.target_id.replace("-", "_").replace(".", "_")
            label = f"|{edge.label}|" if edge.label else ""

            if edge.edge_type == "chosen":
                lines.append(f"  {source} ==>{label} {target}")
            elif edge.edge_type == "alternative":
                lines.append(f"  {source} -.->|{edge.label}| {target}")
            elif edge.edge_type == "revision":
                lines.append(f"  {source} ~~~{label} {target}")
            elif edge.edge_type in ("caused_by", "leads_to"):
                lines.append(f"  {source} -->{label} {target}")

        # Class definitions
        lines.append("")
        lines.append("  classDef decision fill:#E3F2FD,stroke:#1565C0,stroke-width:1px;")
        lines.append("  classDef decisionHigh fill:#FFEBEE,stroke:#C62828,stroke-width:2px;")
        lines.append("  classDef chosen fill:#E8F5E9,stroke:#2E7D32,stroke-width:2px;")
        lines.append("  classDef alt fill:#E3F2FD,stroke:#1565C0,stroke-width:1px,stroke-dasharray: 5 5;")
        lines.append("  classDef success fill:#E8F5E9,stroke:#2E7D32,stroke-width:2px;")
        lines.append("  classDef failure fill:#FFEBEE,stroke:#C62828,stroke-width:2px;")

        content = "\n".join(lines)

        output_path = self._output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"[DecisionVisualization] Exported Mermaid to {output_path}")
        return str(output_path)

    def export_json(
        self,
        nodes: List[VisualizationNode],
        edges: List[VisualizationEdge],
        filename: str = "decision_graph.json",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Export graph to JSON format."""
        data = {
            "metadata": metadata or {},
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "nodes": [n.to_dict() for n in nodes],
            "edges": [e.to_dict() for e in edges],
        }

        output_path = self._output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"[DecisionVisualization] Exported JSON to {output_path}")
        return str(output_path)

    def export_html(
        self,
        nodes: List[VisualizationNode],
        edges: List[VisualizationEdge],
        filename: str = "decision_graph.html",
        title: str = "Decision Graph Visualization",
    ) -> str:
        """Export interactive HTML visualization using vis.js."""
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{title}</title>
    <script src="https://unpkg.com/vis-network@9.1.2/dist/vis-network.min.js"></script>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background: #fafafa; }}
        #network {{ width: 100%; height: 800px; border: 1px solid #ddd; background: white; border-radius: 8px; }}
        .controls {{ margin-bottom: 20px; }}
        button {{ margin-right: 10px; padding: 8px 16px; cursor: pointer; }}
        .legend {{ display: flex; gap: 20px; margin-bottom: 20px; flex-wrap: wrap; }}
        .legend-item {{ display: flex; align-items: center; gap: 8px; }}
        .legend-color {{ width: 20px; height: 20px; border-radius: 4px; border: 2px solid; }}
    </style>
</head>
<body>
    <h1>{title}</h1>
    <div class="controls">
        <button onclick="network.setOptions({{physics: {{enabled: true}}}})">Enable Physics</button>
        <button onclick="network.setOptions({{physics: {{enabled: false}}}})">Disable Physics</button>
        <button onclick="fit()">Fit to Screen</button>
    </div>
    <div class="legend">
        <div class="legend-item"><div class="legend-color" style="background:#E3F2FD; border-color:#1565C0;"></div>Decision</div>
        <div class="legend-item"><div class="legend-color" style="background:#FFEBEE; border-color:#C62828;"></div>High Risk Decision</div>
        <div class="legend-item"><div class="legend-color" style="background:#E8F5E9; border-color:#2E7D32;"></div>Chosen Action</div>
        <div class="legend-item"><div class="legend-color" style="background:#E3F2FD; border-color:#1565C0;"></div>Alternative</div>
        <div class="legend-item"><div class="legend-color" style="background:#E8F5E9; border-color:#2E7D32;"></div>Success</div>
        <div class="legend-item"><div class="legend-color" style="background:#FFEBEE; border-color:#C62828;"></div>Failure</div>
        <div class="legend-item"><div class="legend-color" style="background:transparent; border-color:#4CAF50; border-width:3px;"></div>Chosen Path</div>
        <div class="legend-item"><div class="legend-color" style="background:transparent; border-color:#2196F3; border-width:1px; border-style:dashed;"></div>Alternative</div>
        <div class="legend-item"><div class="legend-color" style="background:transparent; border-color:#FF9800; border-width:2px; border-style:dotted;"></div>Revision</div>
    </div>
    <div id="network"></div>
    <script>
        const nodes = new vis.DataSet({json.dumps([n.to_dict() for n in nodes], ensure_ascii=False)});
        const edges = new vis.DataSet({json.dumps([e.to_dict() for e in edges], ensure_ascii=False)});

        const container = document.getElementById('network');
        const data = {{ nodes, edges }};
        const options = {{
            nodes: {{
                shape: 'box',
                font: {{ size: 12 }},
                margin: 10,
            }},
            edges: {{
                arrows: {{ to: {{ enabled: true, scaleFactor: 0.8 }} }},
                smooth: {{ type: 'dynamic' }},
                font: {{ size: 10, align: 'middle' }},
            }},
            physics: {{
                enabled: true,
                barnesHut: {{ gravitationalConstant: -2000, springLength: 150 }}
            }},
            interaction: {{
                hover: true,
                tooltipDelay: 200,
            }},
            layout: {{
                hierarchical: {{ enabled: false }}
            }}
        }};
        const network = new vis.Network(container, data, options);

        // Style nodes based on type
        nodes.forEach(node => {{
            const meta = node.metadata || {{}};
            if (node.node_type === 'decision') {{
                const risk = meta.risk_level || 'low';
                const colors = {{critical: '#FF4444', high: '#FF8800', medium: '#FFCC00', low: '#44AA44', info: '#4488FF'}};
                node.color = {{ background: '#F5F5F5', border: colors[risk] || '#888', highlight: colors[risk] || '#888' }};
                node.shape = 'box';
            }} else if (node.node_type === 'action') {{
                if (meta.chosen) {{
                    node.color = {{ background: '#E8F5E9', border: '#4CAF50', highlight: '#4CAF50' }};
                }} else {{
                    node.color = {{ background: '#E3F2FD', border: '#2196F3', highlight: '#2196F3' }};
                    node.dashes = true;
                }}
                node.shape = 'ellipse';
            }} else if (node.node_type === 'outcome') {{
                if (node.success) {{
                    node.color = {{ background: '#E8F5E9', border: '#4CAF50', highlight: '#4CAF50' }};
                }} else {{
                    node.color = {{ background: '#FFEBEE', border: '#FF4444', highlight: '#FF4444' }};
                }}
                node.shape = 'diamond';
            }}
            nodes.update(node);
        }});

        // Style edges based on type
        edges.forEach(edge => {{
            if (edge.edge_type === 'chosen') {{
                edge.color = {{ color: '#4CAF50', highlight: '#4CAF50' }};
                edge.width = 3;
            }} else if (edge.edge_type === 'alternative') {{
                edge.color = {{ color: '#2196F3', highlight: '#2196F3' }};
                edge.dashes = true;
            }} else if (edge.edge_type === 'revision') {{
                edge.color = {{ color: '#FF9800', highlight: '#FF9800' }};
                edge.dashes = [5, 5];
            }} else if (edge.edge_type === 'caused_by') {{
                edge.color = {{ color: '#9C27B0', highlight: '#9C27B0' }};
                edge.dashes = [10, 5];
            }}
            edges.update(edge);
        }});

        function fit() {{
            network.fit({{ animation: true }});
        }}
    </script>
</body>
</html>"""

        output_path = self._output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html)

        logger.info(f"[DecisionVisualization] Exported HTML to {output_path}")
        return str(output_path)

    # -------------------------------------------------------------------------
    # Public API - Timeline Export
    # -------------------------------------------------------------------------

    def build_timeline(
        self,
        decision_ids: Optional[List[str]] = None,
        include_revisions: bool = True,
        time_range: Optional[Tuple[str, str]] = None,
    ) -> List[DecisionTimelineEvent]:
        """Build a timeline of decision events.

        Args:
            decision_ids: Optional filter by decision IDs
            include_revisions: Include revision events
            time_range: Optional (start, end) ISO timestamps

        Returns:
            List of timeline events sorted by timestamp
        """
        records = self._get_filtered_records(decision_ids)

        if time_range:
            start = datetime.fromisoformat(time_range[0].replace("Z", "+00:00"))
            end = datetime.fromisoformat(time_range[1].replace("Z", "+00:00"))
            records = [r for r in records if start <= datetime.fromisoformat(r.decided_at.replace("Z", "+00:00")) <= end]

        records.sort(key=lambda r: r.decided_at)
        events = []

        for record in records:
            # Decision made event
            events.append(DecisionTimelineEvent(
                event_id=f"evt_dec_{record.decision_id}",
                timestamp=record.decided_at,
                event_type="decision_made",
                decision_id=record.decision_id,
                description=f"Decision: {record.decision_type.value}" + (f" [{record.component}]" if record.component else ""),
                details={
                    "decision_type": record.decision_type.value,
                    "category": record.category.value,
                    "risk_level": record.risk_level,
                    "confidence": record.confidence,
                    "option_count": record.alternatives_count,
                    "chosen": record.chosen_option_name,
                },
            ))

            # Action taken event (if executed)
            if record.executed:
                events.append(DecisionTimelineEvent(
                    event_id=f"evt_act_{record.decision_id}",
                    timestamp=record.decided_at,
                    event_type="action_taken",
                    decision_id=record.decision_id,
                    description=f"Executed: {record.chosen_option_name or 'unknown'}",
                    details={"option": record.chosen_option_name, "action": record.chosen_option_action},
                ))

            # Outcome recorded event
            if record.actual_success is not None or record.outcome:
                success = record.actual_success if record.actual_success is not None else (record.outcome.get("success", False) if record.outcome else False)
                events.append(DecisionTimelineEvent(
                    event_id=f"evt_out_{record.decision_id}",
                    timestamp=record.decided_at,
                    event_type="outcome_recorded",
                    decision_id=record.decision_id,
                    description=f"Outcome: {'Success' if success else 'Failure'}",
                    details={"success": success, "outcome": record.outcome},
                ))

            # Revision events
            if include_revisions and record.metadata and record.metadata.get("is_revision"):
                changes = record.metadata.get("trigger_changes", [])
                events.append(DecisionTimelineEvent(
                    event_id=f"evt_rev_{record.decision_id}",
                    timestamp=record.decided_at,
                    event_type="revision",
                    decision_id=record.decision_id,
                    description=f"Decision revised due to: {', '.join(c.get('change_type', 'unknown') for c in changes)}",
                    details={"original_decision": record.metadata.get("original_decision_id"), "triggers": changes},
                ))

        return events

    def export_timeline_json(
        self,
        events: List[DecisionTimelineEvent],
        filename: str = "decision_timeline.json",
    ) -> str:
        """Export timeline to JSON."""
        data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "event_count": len(events),
            "events": [e.to_dict() for e in events],
        }

        output_path = self._output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"[DecisionVisualization] Exported timeline JSON to {output_path}")
        return str(output_path)

    def export_timeline_mermaid(
        self,
        events: List[DecisionTimelineEvent],
        filename: str = "decision_timeline.mmd",
        title: str = "Decision Timeline",
    ) -> str:
        """Export timeline to Mermaid format."""
        lines = [f"%% {title}", "timeline"]

        current_date = None
        for event in events:
            dt = datetime.fromisoformat(event.timestamp.replace("Z", "+00:00"))
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%H:%M:%S")

            if date_str != current_date:
                lines.append(f"    {date_str} :")
                current_date = date_str

            icon_map = {
                "decision_made": "🤔",
                "action_taken": "⚡",
                "outcome_recorded": "📊",
                "revision": "🔄",
                "approval": "✅",
            }
            icon = icon_map.get(event.event_type, "•")

            lines.append(f"    {time_str} : {icon} {event.description}")

        content = "\n".join(lines)

        output_path = self._output_dir / filename
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(f"[DecisionVisualization] Exported timeline Mermaid to {output_path}")
        return str(output_path)

    # -------------------------------------------------------------------------
    # Convenience Methods
    # -------------------------------------------------------------------------

    def export_all_formats(
        self,
        decision_ids: Optional[List[str]] = None,
        base_filename: str = "decision_graph",
        include_timeline: bool = True,
    ) -> Dict[str, str]:
        """Export graph in all formats."""
        nodes, edges = self.build_decision_graph(decision_ids)
        results = {}

        results["dot"] = self.export_dot(nodes, edges, f"{base_filename}.dot")
        results["mermaid"] = self.export_mermaid(nodes, edges, f"{base_filename}.mmd")
        results["json"] = self.export_json(nodes, edges, f"{base_filename}.json")
        results["html"] = self.export_html(nodes, edges, f"{base_filename}.html")

        if include_timeline:
            timeline_events = self.build_timeline(decision_ids)
            results["timeline_json"] = self.export_timeline_json(timeline_events, f"{base_filename}_timeline.json")
            results["timeline_mermaid"] = self.export_timeline_mermaid(timeline_events, f"{base_filename}_timeline.mmd")

        return results

    def export_specific_decision(
        self,
        decision_id: str,
        formats: List[str] = None,
    ) -> Dict[str, str]:
        """Export visualization for a specific decision and its context."""
        formats = formats or ["dot", "mermaid", "json", "html"]
        records = self._get_filtered_records([decision_id])

        if not records:
            return {"error": f"Decision {decision_id} not found"}

        # Also include related decisions (same plan, revisions)
        related_ids = self._get_related_decision_ids(decision_id)
        all_records = self._get_filtered_records(related_ids)

        nodes, edges = [], []
        for record in all_records:
            nodes.append(self._create_decision_node(record))
            # Add outcome node if available
            if record.actual_success is not None:
                success = record.actual_success
                outcome_node = VisualizationNode(
                    node_id=f"outcome_{record.decision_id}",
                    label=f"{'✓ Success' if success else '✗ Failed'}",
                    node_type="outcome",
                    parent_id=record.decision_id,
                    decision_id=record.decision_id,
                    metadata={"success": success},
                    timestamp=record.timestamp,
                    success=success,
                )
                nodes.append(outcome_node)
                edges.append(VisualizationEdge(
                    edge_id=f"edge_{record.decision_id}_outcome",
                    source_id=record.decision_id,
                    target_id=outcome_node.node_id,
                    edge_type="leads_to",
                ))

        results = {}
        for fmt in formats:
            if fmt == "dot":
                results["dot"] = self.export_dot(nodes, edges, f"{decision_id}.dot", f"Decision {decision_id}")
            elif fmt == "mermaid":
                results["mermaid"] = self.export_mermaid(nodes, edges, f"{decision_id}.mmd", f"Decision {decision_id}")
            elif fmt == "json":
                results["json"] = self.export_json(nodes, edges, f"{decision_id}.json", {"decision_id": decision_id})
            elif fmt == "html":
                results["html"] = self.export_html(nodes, edges, f"{decision_id}.html", f"Decision {decision_id}")

        return results

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    def _get_filtered_records(self, decision_ids: Optional[List[str]]) -> List[DecisionRecord]:
        """Get filtered decision records."""
        all_records = list(self.decision_history._records.values())
        if decision_ids:
            return [r for r in all_records if r.decision_id in decision_ids]
        return all_records

    def _get_related_decision_ids(self, decision_id: str) -> Set[str]:
        """Get IDs of related decisions (same plan, revisions)."""
        related = {decision_id}
        target_record = self.decision_history._records.get(decision_id)

        if not target_record:
            return related

        target_plan = target_record.metadata.get("plan_id") if target_record.metadata else None
        target_original = target_record.metadata.get("original_decision_id") if target_record.metadata else None

        for record in self.decision_history._records.values():
            # Same plan
            if target_plan and record.metadata and record.metadata.get("plan_id") == target_plan:
                related.add(record.decision_id)
            # Revisions of this decision
            if record.metadata and record.metadata.get("original_decision_id") == decision_id:
                related.add(record.decision_id)
            # This is a revision of another
            if target_original and record.decision_id == target_original:
                related.add(record.decision_id)

        return related


# Convenience function
def create_visualization(
    decision_history: DecisionHistory,
    workspace: str = ".",
) -> DecisionVisualization:
    """Create a DecisionVisualization instance with standard configuration."""
    return DecisionVisualization(decision_history, workspace)