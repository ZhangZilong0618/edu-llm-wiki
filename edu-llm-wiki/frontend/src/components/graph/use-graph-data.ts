// Loads the full graph plus per-node mastery state. Mastery is fetched
// only when ``withMastery`` is true so callers that only need layout data
// (e.g. the canvas itself) skip the second round-trip.

import { useEffect, useState } from "react";

import { api, setProjectId } from "@/lib/api";
import type { GraphData } from "@/types/wiki";

export type MasteryMap = Record<string, MasterySnapshot>;

export interface MasterySnapshot {
  level: "new" | "exposed" | "learning" | "proficient" | "mastered";
  score: number;
  attempts: number;
  exposures: number;
  last_attempt_at: number | null;
  last_exposure_at: number | null;
}

export interface UseGraphDataOptions {
  projectId: string;
  withMastery?: boolean;
}

export interface GraphDataState {
  data: GraphData | null;
  mastery: MasteryMap;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

export function useGraphData({
  projectId,
  withMastery = true,
}: UseGraphDataOptions): GraphDataState {
  const [data, setData] = useState<GraphData | null>(null);
  const [mastery, setMastery] = useState<MasteryMap>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setProjectId(projectId);
    (async () => {
      try {
        const graph = (await api.getGraph()) as GraphData;
        if (cancelled) return;
        setData(graph);
        if (withMastery) {
          try {
            const list = (await api.listMastery()) ?? [];
            if (!cancelled) {
              const map: MasteryMap = {};
              for (const m of list) map[m.node_id] = m as MasterySnapshot;
              setMastery(map);
            }
          } catch {
            // mastery is optional — non-fatal
          }
        }
      } catch (e: any) {
        if (!cancelled) setError(e?.message || String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [projectId, tick, withMastery]);

  return { data, mastery, loading, error, reload: () => setTick((n) => n + 1) };
}
