import { useEffect, useMemo, useRef } from "react";
import Graph from "graphology";
import {
  SigmaContainer,
  useLoadGraph,
  useRegisterEvents,
  useSetSettings,
  useSigma,
} from "@react-sigma/core";
import "@react-sigma/core/lib/style.css";
import forceAtlas2 from "graphology-layout-forceatlas2";
import { Maximize, ZoomIn, ZoomOut } from "lucide-react";

import type { GraphData, GraphEdge, GraphNode } from "@/types/wiki";
import type { ColorMode } from "./constants";
import {
  edgeLabel,
  isStrongEdge,
  layoutIterations,
  nodeColorByMode,
  normalizePositions,
  packComponents,
  readableLabel,
} from "./utils";

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

type VisibleGraph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
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

function buildVisibleGraph(props: GraphCanvasProps): VisibleGraph {
  const graph = sanitizeGraphData(props.data);
  const visibleNodeIds = new Set(
    graph.nodes
      .filter((node) => !props.hiddenTypes.has(node.node_type || "unknown"))
      .map((node) => node.id),
  );

  const visibleEdges = graph.edges.filter(
    (edge) =>
      visibleNodeIds.has(edge.source) &&
      visibleNodeIds.has(edge.target) &&
      (props.showWeakLinks || isStrongEdge(edge)),
  );

  const query = props.searchQuery.trim().toLowerCase();
  const matchedNodeIds = new Set<string>();
  const connectedNodeIds = new Set<string>();

  if (query) {
    for (const node of graph.nodes) {
      if (!visibleNodeIds.has(node.id)) continue;
      if (
        node.label.toLowerCase().includes(query) ||
        (node.node_type || "").toLowerCase().includes(query)
      ) {
        matchedNodeIds.add(node.id);
        connectedNodeIds.add(node.id);
      }
    }
    for (const edge of visibleEdges) {
      if (matchedNodeIds.has(edge.source)) connectedNodeIds.add(edge.target);
      if (matchedNodeIds.has(edge.target)) connectedNodeIds.add(edge.source);
    }
  }

  return {
    nodes: graph.nodes.filter((node) => visibleNodeIds.has(node.id)),
    edges: visibleEdges,
    matchedNodeIds,
    connectedNodeIds,
  };
}

function NetworkGraphLoader({
  visible,
  colorMode,
  communityColors,
  nodeScale,
  spacing,
}: {
  visible: VisibleGraph;
  colorMode: ColorMode;
  communityColors: string[];
  nodeScale: number;
  spacing: number;
}) {
  const loadGraph = useLoadGraph();
  const sigma = useSigma();
  const loadedKeyRef = useRef("");

  useEffect(() => {
    const key = [
      visible.nodes.map((node) => node.id).join(","),
      visible.edges.map((edge) => `${edge.source}->${edge.target}`).join(","),
      colorMode,
      nodeScale,
      spacing,
    ].join("|");
    if (key === loadedKeyRef.current) return;
    loadedKeyRef.current = key;

    const graph = new Graph();
    const maxSize = Math.max(...visible.nodes.map((node) => node.size), 1);
    const radius = Math.max(2.5, Math.sqrt(visible.nodes.length) * 0.9 * spacing);

    visible.nodes.forEach((node, index) => {
      const angle = (2 * Math.PI * index) / Math.max(visible.nodes.length, 1);
      graph.addNode(node.id, {
        x: radius * Math.cos(angle),
        y: radius * Math.sin(angle),
        size: (4 + (Math.sqrt(node.size) / Math.sqrt(maxSize)) * 6) * nodeScale,
        color: nodeColorByMode(node, colorMode),
        label: readableLabel(node.label),
        fullLabel: node.label,
        nodeType: node.node_type,
        community: node.community,
      });
    });

    const weights = visible.edges.map((edge) => edge.weight);
    const minWeight = Math.min(...weights, 0);
    const maxWeight = Math.max(...weights, 1);
    const weightRange = maxWeight - minWeight || 1;

    visible.edges.forEach((edge) => {
      if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) return;
      const edgeKey = `${edge.source}->${edge.target}`;
      if (graph.hasEdge(edgeKey) || graph.hasEdge(`${edge.target}->${edge.source}`)) return;
      const t = (edge.weight - minWeight) / weightRange;
      graph.addEdgeWithKey(edgeKey, edge.source, edge.target, {
        size: 0.4 + t * 2.2,
        color: `rgba(100,116,139,${0.12 + t * 0.7})`,
        label: edgeLabel(edge.edge_type),
        edgeType: edge.edge_type,
        weight: edge.weight,
      });
    });

    if (visible.nodes.length > 1) {
      const settings = forceAtlas2.inferSettings(graph);
      forceAtlas2.assign(graph, {
        iterations: layoutIterations(visible.nodes.length),
        settings: {
          ...settings,
          gravity: 0.9,
          scalingRatio: spacing * 1.8,
          slowDown: 3,
          strongGravityMode: false,
          barnesHutOptimize: visible.nodes.length > 50,
        },
      });
    }

    normalizePositions(graph, Math.max(350, Math.sqrt(visible.nodes.length) * 70 * spacing));
    packComponents(graph, spacing);
    normalizePositions(graph, Math.max(320, Math.sqrt(visible.nodes.length) * 60 * spacing));

    loadGraph(graph);
    sigma.getCamera().animatedReset({ duration: 0 });
    sigma.refresh();
  }, [visible, colorMode, communityColors, nodeScale, spacing, loadGraph, sigma]);

  return null;
}

function NetworkEvents({
  onSelect,
  onHover,
}: {
  onSelect: (nodeId: string) => void;
  onHover: (state: GraphHoverState) => void;
}) {
  const registerEvents = useRegisterEvents();
  const sigma = useSigma();
  const dragRef = useRef<string | null>(null);

  useEffect(() => {
    registerEvents({
      clickNode: ({ node }) => onSelect(node),

      enterNode: ({ node }) => {
        sigma.getContainer().style.cursor = "pointer";
        onHover({
          node,
          neighbors: new Set(sigma.getGraph().neighbors(node)),
        });
      },

      leaveNode: () => {
        sigma.getContainer().style.cursor = "default";
        onHover(null);
      },

      downNode: (event) => {
        event.preventSigmaDefault();
        dragRef.current = event.node;
        sigma.getContainer().style.cursor = "grabbing";
      },

      mousemove: (event) => {
        if (!dragRef.current) return;
        event.preventSigmaDefault();
        const position = sigma.viewportToGraph({ x: event.x, y: event.y });
        sigma.getGraph().setNodeAttribute(dragRef.current, "x", position.x);
        sigma.getGraph().setNodeAttribute(dragRef.current, "y", position.y);
        sigma.refresh();
      },

      mouseup: (event) => {
        if (!dragRef.current) return;
        event.preventSigmaDefault();
        dragRef.current = null;
        sigma.getContainer().style.cursor = "default";
      },
    });
  }, [registerEvents, sigma, onSelect, onHover]);

  return null;
}

function NetworkSettings({
  hover,
  selected,
  matchedNodeIds,
  connectedNodeIds,
  nodeCount,
}: {
  hover: GraphHoverState;
  selected: GraphSelection;
  matchedNodeIds: Set<string>;
  connectedNodeIds: Set<string>;
  nodeCount: number;
}) {
  const setSettings = useSetSettings();
  const sigma = useSigma();

  useEffect(() => {
    setSettings({
      hideEdgesOnMove: true,
      hideLabelsOnMove: true,
      labelDensity: nodeCount > 200 ? 0.08 : nodeCount > 80 ? 0.16 : 0.28,
      labelRenderedSizeThreshold: nodeCount > 200 ? 16 : nodeCount > 80 ? 11 : 8,
      nodeReducer: (node, attributes) => {
        const result = { ...attributes };
        const isHovered = hover?.node === node;
        const isNeighbor = hover?.neighbors.has(node) ?? false;
        const isSelected = selected?.node.id === node;
        const isMatched = matchedNodeIds.size === 0 || matchedNodeIds.has(node);
        const isConnected = connectedNodeIds.size === 0 || connectedNodeIds.has(node);

        if (isSelected) {
          result.size = (attributes.size ?? 8) * 1.3;
          result.zIndex = 10;
          result.forceLabel = true;
        }

        if (isHovered) {
          result.size = (attributes.size ?? 8) * 1.4;
          result.zIndex = 10;
          result.forceLabel = true;
        } else if (isNeighbor) {
          result.zIndex = 5;
          result.forceLabel = true;
        }

        if (hover && !isHovered && !isNeighbor) {
          result.color = "#cbd5e1";
          result.size = (attributes.size ?? 8) * 0.55;
        }

        if (!hover && matchedNodeIds.size > 0 && (!isMatched || !isConnected)) {
          result.color = "#cbd5e1";
          result.size = (attributes.size ?? 8) * 0.65;
        }

        return result;
      },
      edgeReducer: (edge, attributes) => {
        const result = { ...attributes };
        const [source, target] = edge.split("->");
        const isHoverEdge =
          hover?.node === source || hover?.node === target;
        const isSearchEdge =
          matchedNodeIds.size === 0 ||
          ((matchedNodeIds.has(source) || matchedNodeIds.has(target)) &&
            connectedNodeIds.has(source) &&
            connectedNodeIds.has(target));

        result.label = isHoverEdge || (matchedNodeIds.size > 0 && isSearchEdge)
          ? attributes.label ?? ""
          : "";

        if (hover && !isHoverEdge) {
          result.color = "#e2e8f0";
          result.size = 0.3;
          result.zIndex = 0;
        }

        if (isHoverEdge) {
          result.color = "#334155";
          result.size = Math.max(2, (attributes.size ?? 1) * 1.5);
          result.zIndex = 5;
        }

        if (!hover && matchedNodeIds.size > 0 && !isSearchEdge) {
          result.color = "#e2e8f0";
          result.size = 0.3;
          result.zIndex = 0;
        }

        return result;
      },
    });

    sigma.refresh();
  }, [
    setSettings,
    sigma,
    hover,
    selected,
    matchedNodeIds,
    connectedNodeIds,
    nodeCount,
  ]);

  return null;
}

function ViewportControls() {
  const sigma = useSigma();

  return (
    <div className="absolute bottom-4 right-4 flex flex-col gap-2 rounded-lg border bg-white/90 p-1 shadow-sm backdrop-blur">
      <button
        type="button"
        onClick={() => sigma.getCamera().animatedZoom({ duration: 200 })}
        className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
        title="放大"
      >
        <ZoomIn className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={() => sigma.getCamera().animatedUnzoom({ duration: 200 })}
        className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
        title="缩小"
      >
        <ZoomOut className="h-4 w-4" />
      </button>
      <button
        type="button"
        onClick={() => sigma.getCamera().animatedReset({ duration: 250 })}
        className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
        title="重置视图"
      >
        <Maximize className="h-4 w-4" />
      </button>
    </div>
  );
}

export function GraphNetworkCanvas(props: GraphCanvasProps) {
  const visible = useMemo(() => buildVisibleGraph(props), [props]);

  if (visible.nodes.length === 0) {
    return (
      <div className="flex h-full items-center justify-center bg-[var(--background)] text-sm text-[var(--muted-foreground)]">
        当前筛选下没有可显示的知识点
      </div>
    );
  }

  return (
    <div className="relative h-full w-full overflow-hidden bg-[var(--background)]">
      <SigmaContainer
        style={{ width: "100%", height: "100%", background: "transparent" }}
        settings={{
          renderEdgeLabels: true,
          enableEdgeEvents: true,
          hideEdgesOnMove: true,
          zIndex: true,
          defaultEdgeColor: "#cbd5e1",
          defaultNodeColor: "#94a3b8",
          labelSize: 11,
          labelColor: { color: "#334155" },
          edgeLabelSize: 12,
          edgeLabelColor: { color: "#0f172a" },
          labelDensity: visible.nodes.length > 200 ? 0.08 : 0.2,
          labelRenderedSizeThreshold: visible.nodes.length > 200 ? 14 : 8,
          stagePadding: 80,
        }}
      >
        <NetworkGraphLoader
          visible={visible}
          colorMode={props.colorMode}
          communityColors={props.communityColors}
          nodeScale={props.nodeScale}
          spacing={props.spacing}
        />
        <NetworkEvents onSelect={props.onSelect} onHover={props.onHover} />
        <NetworkSettings
          hover={props.hover}
          selected={props.selected}
          matchedNodeIds={visible.matchedNodeIds}
          connectedNodeIds={visible.connectedNodeIds}
          nodeCount={visible.nodes.length}
        />
        <ViewportControls />
      </SigmaContainer>
    </div>
  );
}
