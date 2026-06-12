// Pure helpers used across the graph view, the filter panel, and the
// learning path component. Kept side-effect-free so they can be unit tested
// without rendering React.

import type Graph from "graphology";

import type { GraphEdge, GraphNode } from "@/types/wiki";

import {
  COMMUNITY_COLORS,
  DEFAULT_HIDDEN_TYPES,
  EDGE_LABELS,
  TYPE_COLORS,
  TYPE_LABELS,
} from "./constants";

export function nodeColor(type: string): string {
  return TYPE_COLORS[type] || "#94a3b8";
}

export function typeLabel(type: string): string {
  return TYPE_LABELS[type] || type;
}

export function edgeLabel(type: string): string {
  return EDGE_LABELS[type] || "相关";
}

export function readableLabel(label: string, max = 22): string {
  const clean = label
    .replace(/\.(md|pdf|docx?|pptx?)$/i, "")
    .replace(/[_-]+/g, " ")
    .trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

export function isStrongEdge(edge: { edge_type: string; weight: number }): boolean {
  return edge.edge_type === "direct" || edge.edge_type === "prerequisite" || edge.weight >= 8;
}

export function mixColor(color: string, mix: string, ratio: number): string {
  if (!/^#[0-9a-f]{6}$/i.test(color)) color = "#94a3b8";
  if (!/^#[0-9a-f]{6}$/i.test(mix)) mix = "#e2e8f0";
  const hex = (c: string, i: number) => parseInt(c.slice(i * 2 + 1, i * 2 + 3), 16);
  const r = Math.round(hex(color, 0) + (hex(mix, 0) - hex(color, 0)) * ratio);
  const g = Math.round(hex(color, 1) + (hex(mix, 1) - hex(color, 1)) * ratio);
  const b = Math.round(hex(color, 2) + (hex(mix, 2) - hex(color, 2)) * ratio);
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

export function communityColor(community: number): string {
  if (community < 0) return "#94a3b8";
  return COMMUNITY_COLORS[community % COMMUNITY_COLORS.length];
}

export function layoutIterations(count: number): number {
  if (count > 500) return 30;
  if (count > 200) return 60;
  return 100;
}

export function nodeColorByMode(node: GraphNode, mode: "type" | "community"): string {
  if (mode === "community") return communityColor(node.community);
  return nodeColor(node.node_type);
}

/** A quick check used by the filter UI when "reset" is pressed. */
export function isDefaultHiddenType(type: string): boolean {
  return DEFAULT_HIDDEN_TYPES.includes(type);
}

/** Group edges by endpoint for the "neighbours" sidebar panel. */
export function groupNeighborsByNode(
  node: GraphNode,
  edges: GraphEdge[],
  nodesById: Record<string, GraphNode>,
): { node: GraphNode; edgeType: string; weight: number }[] {
  const out: { node: GraphNode; edgeType: string; weight: number }[] = [];
  for (const e of edges) {
    if (e.source === node.id) {
      const other = nodesById[e.target];
      if (other) out.push({ node: other, edgeType: e.edge_type, weight: e.weight });
    } else if (e.target === node.id) {
      const other = nodesById[e.source];
      if (other) out.push({ node: other, edgeType: e.edge_type, weight: e.weight });
    }
  }
  return out.sort((a, b) => b.weight - a.weight);
}

/**
 * ForceAtlas2 hands back wildly-varying coordinates. Shift every node so the
 * centroid is at the origin and clamp the bounding box to ``[-extent, extent]``
 * so the camera doesn't have to refit on every rebuild.
 */
export function normalizePositions(graph: Graph, extent = 600): void {
  let minX = Infinity;
  let maxX = -Infinity;
  let minY = Infinity;
  let maxY = -Infinity;
  graph.forEachNode((node, attrs) => {
    const x = attrs.x as number;
    const y = attrs.y as number;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
  });
  if (!isFinite(minX)) return;
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const scale = Math.max(1, Math.max(maxX - minX, maxY - minY) / (extent * 2));
  graph.forEachNode((node, attrs) => {
    const x = attrs.x as number;
    const y = attrs.y as number;
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      graph.setNodeAttribute(node, "x", 0);
      graph.setNodeAttribute(node, "y", 0);
      return;
    }
    graph.setNodeAttribute(node, "x", ((attrs.x as number) - cx) / scale);
    graph.setNodeAttribute(node, "y", ((attrs.y as number) - cy) / scale);
  });
}

/**
 * Spread disconnected components out so a fragmented graph doesn't pile
 * everything on top of each other. The largest component (typically the
 * concept backbone) keeps its FA2 layout at the origin; smaller ones are
 * fanned out on a ring around it. Pure grid packing made isolated sources
 * shoot off-screen, hiding what little signal the user has.
 */
export function packComponents(graph: Graph, spacing: number): void {
  const components: string[][] = [];
  const visited = new Set<string>();
  graph.forEachNode((node) => {
    if (visited.has(node)) return;
    const stack = [node];
    const bucket: string[] = [];
    while (stack.length) {
      const cur = stack.pop()!;
      if (visited.has(cur)) continue;
      visited.add(cur);
      bucket.push(cur);
      graph.forEachNeighbor(cur, (nbr) => {
        if (!visited.has(nbr)) stack.push(nbr);
      });
    }
    components.push(bucket);
  });
  if (components.length <= 1) return;
  // Largest component (sorted by length, idx 0) stays at the origin so the
  // main backbone is centred. The rest orbit at increasing radii so the
  // camera can zoom out to see them.
  const mainRadius = 350 * spacing;
  const others = components.slice(1);
  others.forEach((bucket, i) => {
    const angle = (i / others.length) * Math.PI * 2;
    const ringR = mainRadius + 220 * spacing;
    const cx = Math.cos(angle) * ringR;
    const cy = Math.sin(angle) * ringR;
    bucket.forEach((n, j) => {
      // Tiny intra-component spread so multi-node isolated groups don't
      // overlap exactly.
      const wob = 60 * spacing;
      graph.setNodeAttribute(n, "x", cx + Math.cos((j * 2 * Math.PI) / bucket.length) * wob);
      graph.setNodeAttribute(n, "y", cy + Math.sin((j * 2 * Math.PI) / bucket.length) * wob);
    });
  });
}
