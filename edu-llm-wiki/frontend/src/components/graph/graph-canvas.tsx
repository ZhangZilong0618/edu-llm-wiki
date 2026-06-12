import { useMemo } from "react";

import { type ColorMode } from "./constants";
import { communityColor, isStrongEdge, nodeColor, readableLabel, typeLabel } from "./utils";
import type { GraphData, GraphEdge, GraphNode } from "@/types/wiki";

export type GraphSelection = {
  node: GraphNode;
  degree: number;
} | null;

export type GraphHoverState = {
  node: string;
  neighbors: Set<string>;
} | null;

export interface GraphCanvasProps {
  data: GraphData;
  selected: GraphSelection;
  hover: GraphHoverState;
  searchQuery: string;
  hiddenTypes: Set<string>;
  colorMode: ColorMode;
  communityColors: string[];
  nodeScale: number;
  spacing: number;
  showWeakLinks: boolean;
  onSelect: (nodeId: string) => void;
  onHover: (state: GraphHoverState) => void;
}

type PositionedNode = GraphNode & {
  x: number;
  y: number;
  width: number;
  height: number;
  degree: number;
  lane: number;
  groupId: number;
};

type PositionedEdge = GraphEdge & {
  sourceNode: PositionedNode;
  targetNode: PositionedNode;
};

const LANE_LABELS = ["资料", "概念", "原理/公式", "练习/应用"];
const LANE_ORDER: Record<string, number> = {
  source: 0,
  concept: 1,
  unknown: 1,
  principle: 2,
  formula: 2,
  synthesis: 3,
  query: 3,
};

const CARD_WIDTH = 172;
const CARD_HEIGHT = 60;
const LANE_GAP = 216;
const ROW_GAP = 84;
const GROUP_GAP = 96;
const PADDING_X = 56;
const PADDING_Y = 96;
const LANE_TOP = 56;

export function GraphCanvas(props: GraphCanvasProps) {
  const layout = useMemo(() => buildLearningMapLayout(props), [props]);
  const query = props.searchQuery.trim().toLowerCase();

  if (layout.nodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center bg-[var(--background)] text-sm text-[var(--muted-foreground)]">
        当前筛选下没有可显示的知识点
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-auto bg-[var(--background)]">
      <svg
        width={layout.width}
        height={layout.height}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        className="block min-h-full min-w-full"
        role="img"
        aria-label="知识图谱学习地图"
      >
        <defs>
          <marker
            id="graph-arrow"
            viewBox="0 0 10 10"
            refX="8"
            refY="5"
            markerWidth="5"
            markerHeight="5"
            orient="auto-start-reverse"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#94a3b8" />
          </marker>
          <filter id="node-shadow" x="-15%" y="-20%" width="130%" height="150%">
            <feDropShadow dx="0" dy="3" stdDeviation="4" floodColor="#0f172a" floodOpacity="0.12" />
          </filter>
        </defs>

        <rect width={layout.width} height={layout.height} fill="var(--background)" />

        {layout.lanes.map((lane) => (
          <g key={lane.index}>
            <rect
              x={lane.x - 18}
              y={LANE_TOP}
              width={CARD_WIDTH + 36}
              height={layout.height - LANE_TOP - 32}
              rx={8}
              fill={lane.index % 2 === 0 ? "var(--muted)" : "transparent"}
              opacity={lane.index % 2 === 0 ? 0.42 : 1}
            />
            <text x={lane.x} y={LANE_TOP + 20} fontSize={12} fontWeight={700} fill="var(--muted-foreground)">
              {lane.label}
            </text>
          </g>
        ))}

        {layout.groups.map((group) => (
          <g key={group.id}>
            <line
              x1={56}
              x2={layout.width - 28}
              y1={group.y - 36}
              y2={group.y - 36}
              stroke="var(--border)"
              strokeDasharray="5 7"
            />
            <circle cx={56} cy={group.y - 36} r={5} fill={group.color} />
            <foreignObject
              x={70}
              y={group.y - 50}
              width={layout.width - 100}
              height={24}
            >
              <div
                xmlns="http://www.w3.org/1999/xhtml"
                style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: "var(--foreground)",
                  lineHeight: 1.25,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {group.label}
              </div>
            </foreignObject>
          </g>
        ))}

        <g fill="none">
          {layout.edges.map((edge) => (
            <GraphEdgePath
              key={`${edge.source}->${edge.target}:${edge.edge_type}:${edge.weight}`}
              edge={edge}
              active={isEdgeActive(
                edge,
                props.hover,
                props.selected?.node.id,
                query,
                layout.matchedNodeIds,
              )}
              muted={isEdgeMuted(edge, props.hover, query, layout.connectedNodeIds)}
            />
          ))}
        </g>

        <g>
          {layout.nodes.map((node) => (
            <GraphNodeCard
              key={node.id}
              node={node}
              selected={props.selected?.node.id === node.id}
              hovered={props.hover?.node === node.id}
              related={props.hover?.neighbors.has(node.id) || layout.connectedNodeIds.has(node.id)}
              matched={!query || layout.matchedNodeIds.has(node.id)}
              color={nodeDisplayColor(node, props.colorMode, props.communityColors)}
              onSelect={props.onSelect}
              onHover={(nodeId) => {
                const neighbors = new Set<string>();
                for (const edge of layout.edges) {
                  if (edge.source === nodeId) neighbors.add(edge.target);
                  if (edge.target === nodeId) neighbors.add(edge.source);
                }
                props.onHover({ node: nodeId, neighbors });
              }}
              onLeave={() => props.onHover(null)}
            />
          ))}
        </g>
      </svg>
    </div>
  );
}

function GraphEdgePath({
  edge,
  active,
  muted,
}: {
  edge: PositionedEdge;
  active: boolean;
  muted: boolean;
}) {
  const sx = edge.sourceNode.x + edge.sourceNode.width;
  const sy = edge.sourceNode.y + edge.sourceNode.height / 2;
  const tx = edge.targetNode.x;
  const ty = edge.targetNode.y + edge.targetNode.height / 2;
  const forward = tx >= sx;
  const bend = Math.max(70, Math.abs(tx - sx) * 0.42);
  const c1x = sx + (forward ? bend : -bend);
  const c2x = tx - (forward ? bend : -bend);
  const d = `M ${sx} ${sy} C ${c1x} ${sy}, ${c2x} ${ty}, ${tx} ${ty}`;
  const strong = isStrongEdge(edge);

  return (
    <path
      d={d}
      stroke={active ? "#2563eb" : strong ? "#64748b" : "#cbd5e1"}
      strokeWidth={active ? 2.2 : strong ? 1.5 : 1}
      opacity={muted ? 0.12 : active ? 0.95 : strong ? 0.42 : 0.26}
      markerEnd={strong ? "url(#graph-arrow)" : undefined}
    />
  );
}

function GraphNodeCard({
  node,
  selected,
  hovered,
  related,
  matched,
  color,
  onSelect,
  onHover,
  onLeave,
}: {
  node: PositionedNode;
  selected: boolean;
  hovered: boolean;
  related: boolean;
  matched: boolean;
  color: string;
  onSelect: (nodeId: string) => void;
  onHover: (nodeId: string) => void;
  onLeave: () => void;
}) {
  const muted = !matched && !related;
  const scale = selected || hovered ? 1.04 : 1;
  const cx = node.x + node.width / 2;
  const cy = node.y + node.height / 2;

  return (
    <g
      transform={`translate(${cx} ${cy}) scale(${scale}) translate(${-cx} ${-cy})`}
      opacity={muted ? 0.34 : 1}
      onClick={() => onSelect(node.id)}
      onMouseEnter={() => onHover(node.id)}
      onMouseLeave={onLeave}
      className="cursor-pointer"
    >
      <rect
        x={node.x}
        y={node.y}
        width={node.width}
        height={node.height}
        rx={8}
        fill="var(--background)"
        stroke={selected ? "#2563eb" : hovered ? color : "var(--border)"}
        strokeWidth={selected ? 2.4 : hovered ? 2 : 1}
        filter={selected || hovered ? "url(#node-shadow)" : undefined}
      />
      <rect x={node.x} y={node.y} width={5} height={node.height} rx={3} fill={color} />
      <foreignObject
        x={node.x + 12}
        y={node.y + 6}
        width={node.width - 18}
        height={node.height - 10}
      >
        <div
          xmlns="http://www.w3.org/1999/xhtml"
          style={{
            fontSize: 12,
            fontWeight: 700,
            color: "var(--foreground)",
            lineHeight: 1.25,
            display: "flex",
            flexDirection: "column",
            gap: 2,
            height: "100%",
            overflow: "hidden",
          }}
        >
          <div
            style={{
              wordBreak: "break-word",
              overflowWrap: "anywhere",
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
            }}
          >
            {node.label}
          </div>
          <div
            style={{
              fontSize: 10,
              fontWeight: 400,
              color: "var(--muted-foreground)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {typeLabel(node.node_type)} · {node.degree} 连接
          </div>
        </div>
      </foreignObject>
      {selected && <circle cx={node.x + node.width - 14} cy={node.y + 14} r={4} fill="#2563eb" />}
      <title>{node.label}</title>
    </g>
  );
}

function buildLearningMapLayout(props: GraphCanvasProps) {
  const graph = sanitizeGraphData(props.data);
  const nodeIds = new Set(graph.nodes.map((node) => node.id));
  const visibleNodeIds = new Set(
    graph.nodes
      .filter((node) => !props.hiddenTypes.has(node.node_type || "unknown"))
      .map((node) => node.id),
  );
  const visibleEdges = graph.edges.filter(
    (edge) =>
      nodeIds.has(edge.source) &&
      nodeIds.has(edge.target) &&
      visibleNodeIds.has(edge.source) &&
      visibleNodeIds.has(edge.target) &&
      (props.showWeakLinks || isStrongEdge(edge)),
  );
  const degree = new Map<string, number>();
  for (const edge of visibleEdges) {
    degree.set(edge.source, (degree.get(edge.source) || 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) || 0) + 1);
  }

  const query = props.searchQuery.trim().toLowerCase();
  const matchedNodeIds = new Set<string>();
  const connectedNodeIds = new Set<string>();
  for (const node of graph.nodes) {
    if (!visibleNodeIds.has(node.id)) continue;
    if (
      !query ||
      node.label.toLowerCase().includes(query) ||
      node.node_type.toLowerCase().includes(query)
    ) {
      matchedNodeIds.add(node.id);
      connectedNodeIds.add(node.id);
    }
  }
  if (query) {
    for (const edge of visibleEdges) {
      if (matchedNodeIds.has(edge.source)) connectedNodeIds.add(edge.target);
      if (matchedNodeIds.has(edge.target)) connectedNodeIds.add(edge.source);
    }
  }

  const visibleNodes = graph.nodes
    .filter((node) => visibleNodeIds.has(node.id))
    .sort((a, b) => {
      const communityDelta = normalizedCommunity(a) - normalizedCommunity(b);
      if (communityDelta !== 0) return communityDelta;
      const laneDelta = nodeLane(a) - nodeLane(b);
      if (laneDelta !== 0) return laneDelta;
      return (degree.get(b.id) || 0) - (degree.get(a.id) || 0) || a.label.localeCompare(b.label);
    });

  const groupMap = new Map<number, GraphNode[]>();
  for (const node of visibleNodes) {
    const groupId = normalizedCommunity(node);
    if (!groupMap.has(groupId)) groupMap.set(groupId, []);
    groupMap.get(groupId)!.push(node);
  }

  const nodes: PositionedNode[] = [];
  const groups: { id: number; label: string; y: number; color: string }[] = [];
  let cursorY = PADDING_Y;
  const scaledWidth = CARD_WIDTH * Math.max(0.92, Math.min(1.18, props.nodeScale));
  const scaledHeight = CARD_HEIGHT * Math.max(0.94, Math.min(1.16, props.nodeScale));
  const rowGap = ROW_GAP * Math.max(0.82, Math.min(1.5, props.spacing));

  for (const [groupId, groupNodes] of groupMap) {
    const buckets = [[], [], [], []] as GraphNode[][];
    for (const node of groupNodes) buckets[nodeLane(node)].push(node);
    const groupRows = Math.max(...buckets.map((bucket) => bucket.length), 1);
    const groupHeight = (groupRows - 1) * rowGap + scaledHeight;
    groups.push({
      id: groupId,
      label: groupLabel(groupId, groupNodes),
      y: cursorY,
      color: groupId >= 0 ? communityColor(groupId) : "#94a3b8",
    });

    buckets.forEach((bucket, lane) => {
      bucket.forEach((node, index) => {
        const compactOffset = (groupRows - bucket.length) * rowGap * 0.5;
        nodes.push({
          ...node,
          x: PADDING_X + lane * LANE_GAP,
          y: cursorY + compactOffset + index * rowGap,
          width: scaledWidth,
          height: scaledHeight,
          degree: degree.get(node.id) || 0,
          lane,
          groupId,
        });
      });
    });
    cursorY += groupHeight + GROUP_GAP;
  }

  const byId = new Map(nodes.map((node) => [node.id, node]));
  const edges = visibleEdges
    .map((edge) => {
      const sourceNode = byId.get(edge.source);
      const targetNode = byId.get(edge.target);
      if (!sourceNode || !targetNode) return null;
      return { ...edge, sourceNode, targetNode };
    })
    .filter((edge): edge is PositionedEdge => Boolean(edge));

  return {
    nodes,
    edges,
    groups,
    matchedNodeIds,
    connectedNodeIds,
    lanes: LANE_LABELS.map((label, index) => ({ label, index, x: PADDING_X + index * LANE_GAP })),
    width: PADDING_X * 2 + (LANE_LABELS.length - 1) * LANE_GAP + scaledWidth,
    height: Math.max(520, cursorY + PADDING_Y - GROUP_GAP),
  };
}

function sanitizeGraphData(data: GraphData): GraphData {
  const nodes: GraphNode[] = [];
  const seen = new Set<string>();
  for (const node of data.nodes) {
    const id = String(node.id || "").trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    nodes.push({
      ...node,
      id,
      label: String(node.label || id),
      node_type: node.node_type || "unknown",
      size: Number.isFinite(node.size) ? Math.max(1, node.size) : 1,
      community: Number.isFinite(node.community) ? node.community : -1,
    });
  }

  const nodeIds = new Set(nodes.map((node) => node.id));
  const edges = data.edges
    .map((edge) => ({
      ...edge,
      source: String(edge.source || "").trim(),
      target: String(edge.target || "").trim(),
      edge_type: edge.edge_type || "related",
      weight: Number.isFinite(edge.weight) ? edge.weight : 1,
    }))
    .filter(
      (edge) =>
        edge.source &&
        edge.target &&
        edge.source !== edge.target &&
        nodeIds.has(edge.source) &&
        nodeIds.has(edge.target),
    );

  return { ...data, nodes, edges };
}

function nodeLane(node: GraphNode): number {
  return LANE_ORDER[node.node_type || "unknown"] ?? 1;
}

function normalizedCommunity(node: GraphNode): number {
  return Number.isFinite(node.community) && node.community >= 0 ? node.community : -1;
}

function groupLabel(groupId: number, nodes: GraphNode[]): string {
  if (groupId < 0) return "未分组知识";
  const top = nodes[0];
  return `知识簇 ${groupId + 1}${top ? ` · ${top.label}` : ""}`;
}

function nodeDisplayColor(
  node: PositionedNode,
  colorMode: ColorMode,
  communityColors: string[],
): string {
  if (colorMode === "community" && node.community >= 0) {
    return communityColors[node.community % communityColors.length];
  }
  return nodeColor(node.node_type);
}

function isEdgeActive(
  edge: PositionedEdge,
  hover: GraphHoverState,
  selectedId: string | undefined,
  query: string,
  matched: Set<string>,
): boolean {
  if (selectedId && (edge.source === selectedId || edge.target === selectedId)) return true;
  if (hover && (edge.source === hover.node || edge.target === hover.node)) return true;
  return Boolean(query && (matched.has(edge.source) || matched.has(edge.target)));
}

function isEdgeMuted(
  edge: PositionedEdge,
  hover: GraphHoverState,
  query: string,
  connected: Set<string>,
): boolean {
  if (hover) return edge.source !== hover.node && edge.target !== hover.node;
  if (query) return !connected.has(edge.source) && !connected.has(edge.target);
  return false;
}
