"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods } from "react-force-graph-2d";
import { Maximize, ZoomIn, ZoomOut } from "lucide-react";

import type { GraphData, GraphEdge, GraphNode } from "@/types/wiki";
import type { ColorMode } from "./constants";
import { edgeLabel, isStrongEdge, mixColor, nodeColorByMode, readableLabel } from "./utils";

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

type RuntimeNode = GraphNode & {
  x: number;
  y: number;
  degree: number;
};

type RuntimeLink = GraphEdge & {
  key: string;
  source: string | RuntimeNode;
  target: string | RuntimeNode;
};

type RuntimeGraph = {
  nodes: RuntimeNode[];
  links: RuntimeLink[];
};

type VisibleGraph = RuntimeGraph & {
  matchedNodeIds: Set<string>;
  connectedNodeIds: Set<string>;
};

function sanitizeGraphData(data: GraphData): GraphData {
  const nodes: GraphNode[] = [];
  const seen = new Set<string>();

  for (const node of data.nodes || []) {
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
  const edges = (data.edges || [])
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

function makeInitialPositions(count: number) {
  // A deterministic low-discrepancy start avoids the old "circle of nodes"
  // and gives d3-force enough separation to form real clusters.
  const golden = Math.PI * (3 - Math.sqrt(5));
  const spread = Math.max(280, Math.sqrt(count) * 68);
  return (index: number, id: string) => {
    let hash = 0;
    for (let i = 0; i < id.length; i += 1) {
      hash = (hash * 31 + id.charCodeAt(i)) % 100003;
    }
    const jitter = ((hash % 97) / 97 - 0.5) * 26;
    const radius = spread * Math.sqrt((index + 0.65) / Math.max(count, 1)) + jitter;
    const angle = index * golden + (hash % 1000) / 1000 * 0.22;
    return {
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
    };
  };
}

function buildVisibleGraph(
  data: GraphData,
  hiddenTypes: Set<string>,
  showWeakLinks: boolean,
  positions: Map<string, { x: number; y: number }>,
): RuntimeGraph {
  const clean = sanitizeGraphData(data);
  const visibleNodeIds = new Set(
    clean.nodes
      .filter((node) => !hiddenTypes.has(node.node_type || "unknown"))
      .map((node) => node.id),
  );

  const links = clean.edges
    .filter(
      (edge) =>
        visibleNodeIds.has(edge.source) &&
        visibleNodeIds.has(edge.target) &&
        (showWeakLinks || isStrongEdge(edge)),
    )
    .map<RuntimeLink>((edge) => ({
      ...edge,
      key: `${edge.source}->${edge.target}:${edge.edge_type}`,
      source: edge.source,
      target: edge.target,
    }));

  const degree = new Map<string, number>();
  for (const link of links) {
    degree.set(link.source as string, (degree.get(link.source as string) || 0) + 1);
    degree.set(link.target as string, (degree.get(link.target as string) || 0) + 1);
  }

  const initial = makeInitialPositions(visibleNodeIds.size);
  const nodes = clean.nodes
    .filter((node) => visibleNodeIds.has(node.id))
    .map<RuntimeNode>((node, index) => {
      const cached = positions.get(node.id);
      const start = cached || initial(index, node.id);
      return {
        ...node,
        x: start.x,
        y: start.y,
        degree: degree.get(node.id) || 0,
      };
    });

  return { nodes, links };
}

function buildSearchState(visible: RuntimeGraph, searchQuery: string) {
  const query = searchQuery.trim().toLowerCase();
  const matchedNodeIds = new Set<string>();
  const connectedNodeIds = new Set<string>();

  if (!query) return { matchedNodeIds, connectedNodeIds };

  for (const node of visible.nodes) {
    if (
      node.label.toLowerCase().includes(query) ||
      (node.node_type || "").toLowerCase().includes(query)
    ) {
      matchedNodeIds.add(node.id);
      connectedNodeIds.add(node.id);
    }
  }

  for (const link of visible.links) {
    if (matchedNodeIds.has(link.source as string)) connectedNodeIds.add(link.target as string);
    if (matchedNodeIds.has(link.target as string)) connectedNodeIds.add(link.source as string);
  }

  return { matchedNodeIds, connectedNodeIds };
}

function linkEndpointId(value: string | RuntimeNode) {
  return typeof value === "string" ? value : value.id;
}

function hexAlpha(color: string, alpha: number) {
  if (!/^#[0-9a-f]{6}$/i.test(color)) return `rgba(148,163,184,${alpha})`;
  const r = Number.parseInt(color.slice(1, 3), 16);
  const g = Number.parseInt(color.slice(3, 5), 16);
  const b = Number.parseInt(color.slice(5, 7), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function nodeRadius(node: RuntimeNode, nodeScale: number, globalScale: number) {
  const base = 3.2 + Math.sqrt(Math.max(node.size, 1)) * 0.62 + Math.min(node.degree * 0.055, 0.65);
  return Math.min(14, base * nodeScale) / Math.max(globalScale, 0.2);
}

export function GraphNetworkCanvas(props: GraphCanvasProps) {
  const {
    data,
    selected,
    hover,
    searchQuery,
    hiddenTypes,
    colorMode,
    nodeScale,
    spacing,
    showWeakLinks,
    onSelect,
    onHover,
  } = props;

  const fgRef = useRef<ForceGraphMethods | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dragMovedRef = useRef(false);
  const fitOnStopRef = useRef(true);
  const positionsRef = useRef(new Map<string, { x: number; y: number }>());
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [zoom, setZoom] = useState(1);

  useEffect(() => {
    const element = containerRef.current;
    if (!element) return;
    const observer = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      if (!rect) return;
      setSize({ width: Math.max(1, rect.width), height: Math.max(1, rect.height) });
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const graph = useMemo(
    () => buildVisibleGraph(data, hiddenTypes, showWeakLinks, positionsRef.current),
    [data, hiddenTypes, showWeakLinks],
  );

  const search = useMemo(() => buildSearchState(graph, searchQuery), [graph, searchQuery]);

  const neighborsByNode = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const link of graph.links) {
      const source = linkEndpointId(link.source);
      const target = linkEndpointId(link.target);
      if (!map.has(source)) map.set(source, new Set());
      if (!map.has(target)) map.set(target, new Set());
      map.get(source)!.add(target);
      map.get(target)!.add(source);
    }
    return map;
  }, [graph]);

  const highlightedNodeIds = useMemo(() => {
    const active = new Set<string>();
    if (hover) {
      active.add(hover.node);
      hover.neighbors.forEach((id) => active.add(id));
    }
    if (searchQuery.trim()) {
      search.connectedNodeIds.forEach((id) => active.add(id));
    }
    return active;
  }, [hover, search.connectedNodeIds, searchQuery]);

  const highlightedLinkKeys = useMemo(() => {
    const keys = new Set<string>();
    if (!hover && !searchQuery.trim()) return keys;

    for (const link of graph.links) {
      const source = linkEndpointId(link.source);
      const target = linkEndpointId(link.target);
      const hoverMatch =
        !!hover &&
        ((hover.node === source && hover.neighbors.has(target)) ||
          (hover.node === target && hover.neighbors.has(source)));
      const searchMatch =
        !!searchQuery.trim() &&
        search.matchedNodeIds.size > 0 &&
        search.matchedNodeIds.has(source) &&
        search.connectedNodeIds.has(target);
      if (hoverMatch || searchMatch) keys.add(link.key);
    }
    return keys;
  }, [graph.links, hover, search.connectedNodeIds, search.matchedNodeIds, searchQuery]);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    const count = graph.nodes.length;
    fg.d3Force("charge")?.strength(count > 300 ? -320 : -240);
    fg.d3Force("link")?.distance(count > 300 ? 74 : 66)?.strength?.(0.42);
    fg.d3Force("center")?.strength(0.06);
    fg.d3ReheatSimulation();
    fitOnStopRef.current = true;
  }, [graph]);

  const cachePositions = useCallback(() => {
    const map = positionsRef.current;
    for (const node of graph.nodes) {
      if (Number.isFinite(node.x) && Number.isFinite(node.y)) {
        map.set(node.id, { x: node.x, y: node.y });
      }
    }
  }, [graph.nodes]);

  // Persisting positions keeps pan/zoom-friendly layout stable when the user
  // only toggles filters or a hover state causes React to re-render.
  useEffect(() => {
    const timer = window.setTimeout(cachePositions, 4200);
    return () => window.clearTimeout(timer);
  }, [cachePositions]);

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg || searchQuery.trim().length < 2 || search.matchedNodeIds.size === 0) return;
    const timer = window.setTimeout(() => {
      fg.zoomToFit(360, 90, (node) => search.connectedNodeIds.has(node.id as string));
    }, 260);
    return () => window.clearTimeout(timer);
  }, [search.connectedNodeIds, search.matchedNodeIds.size, searchQuery]);

  const drawNode = useCallback(
    (rawNode: RuntimeNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const radius = nodeRadius(rawNode, nodeScale, globalScale);
      const isHovered = hover?.node === rawNode.id;
      const isSelected = selected?.node.id === rawNode.id;
      const isHighlighted = highlightedNodeIds.has(rawNode.id);
      const dimmed = (hover || searchQuery.trim()) && !isHighlighted;
      const baseColor = nodeColorByMode(rawNode, colorMode);
      const fill = dimmed ? mixColor(baseColor, "#e2e8f0", 0.78) : baseColor;

      ctx.beginPath();
      ctx.arc(rawNode.x, rawNode.y, radius, 0, Math.PI * 2);
      ctx.fillStyle = fill;
      ctx.fill();

      if (isHovered || isSelected) {
        ctx.beginPath();
        ctx.arc(rawNode.x, rawNode.y, radius + (isSelected ? 3.4 : 2.6) / globalScale, 0, Math.PI * 2);
        ctx.strokeStyle = isSelected ? "rgba(15,23,42,0.82)" : "rgba(15,23,42,0.55)";
        ctx.lineWidth = 1.8 / globalScale;
        ctx.stroke();
      }

      const shouldShowLabel =
        isHovered ||
        isSelected ||
        globalScale >= (graph.nodes.length > 220 ? 2.7 : 1.9) ||
        (searchQuery.trim().length > 0 && isHighlighted);

      if (!shouldShowLabel) return;

      const label = readableLabel(rawNode.label, 26);
      const fontSize = 11 / globalScale;
      ctx.font = `${fontSize}px Inter, ui-sans-serif, system-ui, -apple-system, sans-serif`;
      ctx.textBaseline = "middle";
      ctx.textAlign = "left";
      const x = rawNode.x + radius + 2.5 / globalScale;
      ctx.strokeStyle = "rgba(255,255,255,0.9)";
      ctx.lineWidth = 3 / globalScale;
      ctx.strokeText(label, x, rawNode.y);
      ctx.fillStyle = dimmed ? "rgba(100,116,139,0.72)" : "rgba(15,23,42,0.88)";
      ctx.fillText(label, x, rawNode.y);
    },
    [colorMode, graph.nodes.length, highlightedNodeIds, hover, nodeScale, searchQuery, selected],
  );

  const drawLink = useCallback(
    (rawLink: RuntimeLink, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const source = rawLink.source as RuntimeNode;
      const target = rawLink.target as RuntimeNode;
      if (!source || !target || !Number.isFinite(source.x) || !Number.isFinite(target.x)) return;

      const strong = rawLink.edge_type === "prerequisite";
      const highlighted = highlightedLinkKeys.has(rawLink.key);
      const dimmed = (hover || searchQuery.trim()) && !highlighted;
      const color = strong ? "#2563eb" : "#64748b";
      ctx.beginPath();
      ctx.moveTo(source.x, source.y);
      ctx.lineTo(target.x, target.y);
      ctx.strokeStyle = dimmed ? hexAlpha(color, 0.08) : hexAlpha(color, strong ? 0.52 : 0.28);
      ctx.lineWidth = (highlighted ? 2.1 : strong ? 1.25 : 0.68) / globalScale;
      ctx.stroke();
    },
    [highlightedLinkKeys, hover, searchQuery],
  );

  const handleHover = useCallback(
    (node: RuntimeNode | null) => {
      if (!node) {
        onHover(null);
        return;
      }
      const neighbors = neighborsByNode.get(node.id) || new Set<string>();
      onHover({ node: node.id, neighbors: new Set(neighbors) });
    },
    [neighborsByNode, onHover],
  );

  if (graph.nodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center bg-[var(--background)] text-sm text-[var(--muted-foreground)]">
        当前筛选下没有可显示的知识点
      </div>
    );
  }

  return (
    <div ref={containerRef} className="relative h-full w-full overflow-hidden bg-[var(--background)]">
      <ForceGraph2D<RuntimeNode, RuntimeLink>
        ref={fgRef as any}
        width={size.width}
        height={size.height}
        graphData={graph as any}
        backgroundColor="rgba(0,0,0,0)"
        nodeId="id"
        nodeRelSize={2.6}
        nodeVal={(node) => Math.max(1, node.size)}
        nodeColor={() => "transparent"}
        nodeLabel={(node) => node.label}
        nodeCanvasObjectMode={() => "replace"}
        nodeCanvasObject={drawNode}
        nodePointerAreaPaint={(node, color, ctx, globalScale) => {
          ctx.fillStyle = color;
          ctx.beginPath();
          ctx.arc(node.x, node.y, nodeRadius(node, nodeScale, globalScale) + 1, 0, Math.PI * 2);
          ctx.fill();
        }}
        linkColor={() => "transparent"}
        linkLabel={(link) => edgeLabel(link.edge_type)}
        linkCanvasObjectMode={() => "replace"}
        linkCanvasObject={drawLink}
        linkHoverPrecision={4}
        enableNodeDrag
        enableZoomInteraction
        enablePanInteraction
        warmupTicks={18}
        cooldownTicks={260}
        cooldownTime={6000}
        d3AlphaDecay={0.023}
        d3VelocityDecay={0.28}
        minZoom={0.08}
        maxZoom={10}
        onZoom={({ k }) => setZoom(k)}
        onEngineStop={() => {
          cachePositions();
          if (fitOnStopRef.current) {
            fitOnStopRef.current = false;
            fgRef.current?.zoomToFit(420, Math.max(48, 80 * Math.min(spacing, 1.6)));
          }
        }}
        onNodeDrag={(node, translate) => {
          if (Math.hypot(translate.x, translate.y) > 1.2) dragMovedRef.current = true;
          node.fx = node.x;
          node.fy = node.y;
        }}
        onNodeDragEnd={(node) => {
          node.fx = undefined as any;
          node.fy = undefined as any;
        }}
        onNodeClick={(node) => {
          if (dragMovedRef.current) {
            dragMovedRef.current = false;
            return;
          }
          onSelect(node.id);
        }}
        onNodeHover={handleHover}
      />

      <div className="absolute bottom-4 right-4 flex flex-col gap-2 rounded-lg border bg-white/90 p-1 shadow-sm backdrop-blur">
        <button
          type="button"
          onClick={() => fgRef.current?.zoom(zoom * 1.25, 180)}
          className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
          title="放大"
        >
          <ZoomIn className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => fgRef.current?.zoom(Math.max(0.08, zoom / 1.25), 180)}
          className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
          title="缩小"
        >
          <ZoomOut className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => fgRef.current?.zoomToFit(280, 70)}
          className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
          title="重置视图"
        >
          <Maximize className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
