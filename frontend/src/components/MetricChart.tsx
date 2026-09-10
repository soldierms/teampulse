import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { MetricSeries } from "../lib/api";
import { shortDate } from "../lib/format";
import { Card } from "./ui";

interface Props {
  title: string;
  series: MetricSeries | undefined;
  color?: string;
  formatValue?: (value: number) => string;
}

export function MetricChart({ title, series, color = "#0f172a", formatValue }: Props) {
  const points = series?.points ?? [];
  const data = points.map((point) => ({
    date: shortDate(point.period_start),
    value: point.value,
  }));

  return (
    <Card>
      <div className="mb-3 text-sm font-semibold text-slate-700">{title}</div>
      {data.length === 0 ? (
        <div className="flex h-48 items-center justify-center text-sm text-slate-400">
          No data in this range
        </div>
      ) : (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid stroke="#e2e8f0" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11, fill: "#94a3b8" }}
                tickLine={false}
                axisLine={false}
                minTickGap={24}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#94a3b8" }}
                tickLine={false}
                axisLine={false}
                width={56}
                tickFormatter={(value: number) =>
                  formatValue ? formatValue(value) : String(value)
                }
              />
              <Tooltip
                formatter={(value: number) => [
                  formatValue ? formatValue(value) : value.toFixed(2),
                  title,
                ]}
                contentStyle={{
                  borderRadius: 8,
                  border: "1px solid #e2e8f0",
                  fontSize: 12,
                }}
              />
              {/* StrictMode's double-mount leaves Recharts' entry animation
                  stuck at zero path length, so the line never draws. */}
              <Line
                type="monotone"
                dataKey="value"
                stroke={color}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4 }}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Card>
  );
}
