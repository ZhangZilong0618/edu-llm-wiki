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
  layoutKey: string;
  onSelect: (nodeId: string) => void;
  onHover: (state: GraphHoverState) => void;
}

type RuntimeNode = GraphNode & {
  x: number;
  y: number;
  fx?: number;
  fy?: number;
  degree: number;
  // Simulation state injected by d3-force at runtime.
  vx?: number;
  vy?: number;
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

export interface ComponentCell {
  seed: { x: number; y: number };
  cx: number;
  cy: number;
  size: number;
}

/**
 * Connected-component-aware cell layout. Disconnected subgraphs (e.g. two
 * unrelated course themes) used to be flung to opposite corners by the
 * many-body force while clumping internally. Assigning every component its
 * own cell of the canvas and pulling its nodes toward that cell keeps
 * components side by side and compact.
 */
function assignComponentCells(
  nodeIds: Set<string>,
  links: RuntimeLink[],
  width: number,
  height: number,
): Map<string, ComponentCell> {
  const parent = new Map<string, string>();
  const find = (a: string): string => {
    const root = parent.get(a);
    if (root === undefined) {
      parent.set(a, a);
      return a;
    }
    if (root === a) return a;
    const r = find(root);
    parent.set(a, r);
    return r;
  };
  const union = (a: string, b: string) => {
    const ra = find(a);
    const rb = find(b);
    if (ra !== rb) parent.set(ra, rb);
  };
  nodeIds.forEach((id) => find(id));
  for (const link of links) {
    const s = linkEndpointId(link.source);
    const t = linkEndpointId(link.target);
    if (nodeIds.has(s) && nodeIds.has(t)) union(s, t);
  }
  const groups = new Map<string, string[]>();
  nodeIds.forEach((id) => {
    const r = find(id);
    const list = groups.get(r);
    if (list) list.push(id);
    else groups.set(r, [id]);
  });

  const comps = Array.from(groups.values()).sort((a, b) => b.length - a.length);
  const cells = new Map<string, ComponentCell>();
  const nComp = Math.max(comps.length, 1);
  const aspect = width / Math.max(height, 1);
  const cols = Math.max(1, Math.round(Math.sqrt(nComp * aspect)));
  const rows = Math.max(1, Math.ceil(nComp / cols));
  const maxSize = comps[0]?.length ?? 1;
  const golden = Math.PI * (3 - Math.sqrt(5));

  comps.forEach((members, k) => {
    const col = k % cols;
    const row = Math.floor(k / cols);
    // The force-graph viewport is centred on data coordinate (0, 0), so the
    // cell grid must be centred there too.
    const cx = (col + 0.5) * (width / cols) - width / 2;
    const cy = (row + 0.5) * (height / rows) - height / 2;
    const spread =
      0.46 * Math.min(width / cols, height / rows) *
      (0.55 + 0.45 * Math.sqrt(members.length / Math.max(maxSize, 1)));
    members.forEach((id, i) => {
      const angle = i * golden;
      const r = spread * Math.sqrt((i + 0.6) / Math.max(members.length, 1));
      cells.set(id, {
        seed: { x: cx + Math.cos(angle) * r, y: cy + Math.sin(angle) * r },
        cx,
        cy,
        size: members.length,
      });
    });
  });
  return cells;
}

/**
 * Label-aware collision: a node occupies its circle plus the text drawn to
 * its right, so overlapping labels are the visual bug this force removes.
 */
function makeSeparationForce(nodes: RuntimeNode[], nodeScale: number) {
  return (alpha: number) => {
    const radii = nodes.map((n) => {
      const circle = nodeRadius(n, nodeScale, 1);
      const labelHalf = Math.min(n.label.length, 26) * 2.9;
      return Math.max(circle, Math.min(circle + labelHalf * 0.85, 96));
    });
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = (b.x ?? 0) - (a.x ?? 0);
        const dy = (b.y ?? 0) - (a.y ?? 0);
        const dist = Math.hypot(dx, dy) || 0.01;
        const overlap = radii[i] + radii[j] - dist;
        if (overlap <= 0) continue;
        const push = (overlap * 0.5 * alpha) / dist;
        const ax = dx * push;
        const ay = dy * push;
        if (!a.fx) a.vx = (a.vx ?? 0) - ax;
        if (!a.fy) a.vy = (a.vy ?? 0) - ay;
        if (!b.fx) b.vx = (b.vx ?? 0) + ax;
        if (!b.fy) b.vy = (b.vy ?? 0) + ay;
      }
    }
  };
}

function buildVisibleGraph(
  data: GraphData,
  hiddenTypes: Set<string>,
  showWeakLinks: boolean,
  positions: Map<string, { x: number; y: number }>,
  pinned: Set<string>,
  canvasSize: { width: number; height: number },
  cellTargets: Map<string, ComponentCell>,
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

  const cells = assignComponentCells(
    visibleNodeIds,
    links,
    Math.max(canvasSize.width, 640),
    Math.max(canvasSize.height, 480),
  );
  cellTargets.clear();
  cells.forEach((cell, id) => cellTargets.set(id, cell));
  const nodes = clean.nodes
    .filter((node) => visibleNodeIds.has(node.id))
    .map<RuntimeNode>((node) => {
      const cached = positions.get(node.id);
      const cell = cells.get(node.id);
      const start = cached || cell?.seed || { x: 0, y: 0 };
      const isPinned = pinned.has(node.id) && cached;
      return {
        ...node,
        x: start.x,
        y: start.y,
        ...(isPinned ? { fx: start.x, fy: start.y } : {}),
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
  const base = 8.4 + Math.sqrt(Math.max(node.size, 1)) * 0.98 + Math.min(node.degree * 0.085, 1.5);
  return Math.min(28, base * nodeScale) / Math.max(globalScale, 0.2);
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
    layoutKey,
    onSelect,
    onHover,
  } = props;

  const fgRef = useRef<ForceGraphMethods | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const dragMovedRef = useRef(false);
  const fitOnStopRef = useRef(true);
  const positionsRef = useRef(new Map<string, { x: number; y: number }>());
  const pinnedRef = useRef(new Set<string>());
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [zoom, setZoom] = useState(1);
  const [layoutVersion, setLayoutVersion] = useState(0);

  useEffect(() => {
    positionsRef.current = new Map();
    pinnedRef.current = new Set();
    try {
      const raw = window.localStorage.getItem(`edu-llm-wiki.graph-layout.${layoutKey}`);
      if (raw) {
        const saved = JSON.parse(raw) as {
          positions?: Record<string, { x: number; y: number }>;
          pinned?: string[];
        };
        positionsRef.current = new Map(
          Object.entries(saved.positions || {}).map(([id, point]) => [id, point]),
        );
        pinnedRef.current = new Set(saved.pinned || []);
      }
    } catch {
      // Corrupt layout data must never break the graph; fall back to a fresh
      // force layout.
    }
    setLayoutVersion((version) => version + 1);
  }, [layoutKey]);

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

  const cellTargetsRef = useRef(new Map<string, ComponentCell>());
  const graph = useMemo(
    () => buildVisibleGraph(
      data,
      hiddenTypes,
      showWeakLinks,
      positionsRef.current,
      pinnedRef.current,
      size,
      cellTargetsRef.current,
    ),
    [data, hiddenTypes, showWeakLinks, layoutVersion, size.width, size.height],
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
    const targets = cellTargetsRef.current;
    const compSize = (id: string) => targets.get(id)?.size ?? 1;
    // Gentle per-component repulsion: enough to spread nodes inside a cell
    // without flinging disconnected components to opposite corners.
    fg.d3Force("charge")?.strength((node: { id: string }) =>
      -26 * Math.sqrt(Math.max(compSize(node.id), 1)) - 14,
    );
    fg.d3Force("link")?.distance(50 * Math.max(spacing, 0.6))?.strength?.(0.6);
    fg.d3Force("center")?.strength(0.05);
    // Pull every node toward its component's cell.
    fg.d3Force("cell", (alpha: number) => {
      for (const n of graph.nodes) {
        const t = targets.get(n.id);
        if (!t) continue;
        if (!n.fx) n.vx = (n.vx ?? 0) + (t.cx - (n.x ?? 0)) * 0.05 * alpha;
        if (!n.fy) n.vy = (n.vy ?? 0) + (t.cy - (n.y ?? 0)) * 0.05 * alpha;
      }
    });
    // Keep labels from stacking on top of each other.
    fg.d3Force("separate", makeSeparationForce(graph.nodes, nodeScale));
    fg.d3ReheatSimulation();
    fitOnStopRef.current = true;
  }, [graph, spacing, nodeScale]);

  const persistLayout = useCallback(() => {
    try {
      window.localStorage.setItem(
        `edu-llm-wiki.graph-layout.${layoutKey}`,
        JSON.stringify({
          positions: Object.fromEntries(positionsRef.current),
          pinned: Array.from(pinnedRef.current),
        }),
      );
    } catch {
      // Storage quota/private mode is non-fatal; in-memory pinning still works.
    }
  }, [layoutKey]);

  const cachePositions = useCallback(() => {
    const map = positionsRef.current;
    for (const node of graph.nodes) {
      if (Number.isFinite(node.x) && Number.isFinite(node.y)) {
        map.set(node.id, { x: node.x, y: node.y });
      }
    }
    persistLayout();
  }, [graph.nodes, persistLayout]);

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

      // The user explicitly wants names visible by default, even for large
      // graphs. Hover/search still brighten or focus labels, but never gate
      // whether the text is drawn.
      const shouldShowLabel = true;

      const label = readableLabel(rawNode.label, 26);
      const fontSize = 10.5 / globalScale;
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

      const shouldShowEdgeLabel =
        highlighted ||
        (!dimmed && (graph.links.length <= 260 || globalScale >= 1.15));
      if (!shouldShowEdgeLabel) return;

      const text = readableLabel(edgeLabel(rawLink.edge_type), 14);
      const fontSize = 9.5 / globalScale;
      ctx.font = `${fontSize}px Inter, ui-sans-serif, system-ui, -apple-system, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const mx = (source.x + target.x) / 2;
      const my = (source.y + target.y) / 2;
      ctx.strokeStyle = "rgba(255,255,255,0.88)";
      ctx.lineWidth = 2.8 / globalScale;
      ctx.strokeText(text, mx, my);
      ctx.fillStyle = dimmed ? "rgba(100,116,139,0.45)" : strong ? "rgba(37,99,235,0.82)" : "rgba(71,85,105,0.72)";
      ctx.fillText(text, mx, my);
    },
    [graph.links.length, highlightedLinkKeys, hover, searchQuery],
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
        No knowledge points to display under the current filter
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
          // Keep fx/fy set after drag. Clearing them lets the force simulation
          // immediately pull the node back to its old position.
          node.fx = node.x;
          node.fy = node.y;
          pinnedRef.current.add(node.id);
          positionsRef.current.set(node.id, { x: node.x, y: node.y });
          persistLayout();
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

      <div className="absolute bottom-4 left-4 flex flex-col gap-2 rounded-lg border bg-white/90 p-1 shadow-sm backdrop-blur">
        <button
          type="button"
          onClick={() => fgRef.current?.zoom(zoom * 1.25, 180)}
          className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
          title="Zoom in"
        >
          <ZoomIn className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => fgRef.current?.zoom(Math.max(0.08, zoom / 1.25), 180)}
          className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
          title="Zoom out"
        >
          <ZoomOut className="h-4 w-4" />
        </button>
        <button
          type="button"
          onClick={() => fgRef.current?.zoomToFit(280, 70)}
          className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
          title="Reset View"
        >
          <Maximize className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
