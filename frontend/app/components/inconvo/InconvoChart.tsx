"use client";

import { useMemo, useState } from "react";
import type { VisualizationSpec } from "vega-embed";
import dynamic from "next/dynamic";

const VegaEmbed = dynamic(() => import("react-vega").then((m) => m.VegaEmbed), {
  ssr: false,
});

const DARK_THEME_CONFIG = {
  axis: {
    labelColor: "#f3f4f6",
    titleColor: "#e5e7eb",
    domainColor: "#475569",
    tickColor: "#475569",
    gridColor: "#1f2937",
  },
  legend: {
    labelColor: "#f3f4f6",
    titleColor: "#e5e7eb",
  },
  title: {
    color: "#e5e7eb",
  },
  view: {
    stroke: "transparent",
  },
};

export function InconvoChart({
  message,
  spec,
  chart,
}: {
  message: string;
  spec?: Record<string, unknown>;
  chart?: {
    type: "bar" | "line";
    xLabel?: string;
    yLabel?: string;
    data:
      | Array<{ label: string; value: number }>
      | { labels: string[]; datasets: Array<{ name: string; values: number[] }> };
  };
}) {
  const [error, setError] = useState<string | null>(null);

  const chartSpec = useMemo<VisualizationSpec | null>(() => {
    if (!spec) return null;

    const userConfig = spec.config as any ?? {};

    return {
      $schema: "https://vega.github.io/schema/vega-lite/v5.json",
      background: "transparent",
      autosize: { type: "fit", contains: "padding" },
      width: "container",
      ...spec,
      config: {
        ...DARK_THEME_CONFIG,
        ...userConfig,
        axis: { ...DARK_THEME_CONFIG.axis, ...(userConfig.axis ?? {}) },
        legend: { ...DARK_THEME_CONFIG.legend, ...(userConfig.legend ?? {}) },
        title: { ...DARK_THEME_CONFIG.title, ...(userConfig.title ?? {}) },
      },
    } as VisualizationSpec;
  }, [spec]);

  const handleError = (err: unknown) => {
    const message = err instanceof Error ? err.message : String(err);
    console.error("Vega-Lite render error:", err);
    setError(message);
  };

  if (!spec && !chart) {
    return <div className="text-sm text-zinc-500">No chart spec provided.</div>;
  }

  if (error) {
    return (
      <div className="text-sm text-red-500">
        Failed to render chart: {error}
      </div>
    );
  }

  return (
    <div className="my-2">
      <p className="mb-2 text-sm">{message}</p>

      {chartSpec ? (
        <div className="w-full">
          <VegaEmbed
            spec={chartSpec}
            options={{ actions: false }}
            onError={handleError}
            style={{ width: "100%" }}
          />
        </div>
      ) : chart ? (
        <div className="p-4 border border-zinc-300 dark:border-zinc-700 rounded-lg bg-zinc-50 dark:bg-zinc-900">
          <p className="text-xs mb-2">
            Legacy {chart.type} chart
            {chart.xLabel && ` (X: ${chart.xLabel})`}
            {chart.yLabel && ` (Y: ${chart.yLabel})`}
          </p>
          <pre className="text-xs overflow-auto">
            {JSON.stringify(chart.data, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
