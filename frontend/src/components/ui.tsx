import type { ReactNode } from "react";
import { TONE_BG, TONE_TEXT, toilTone } from "../lib/format";

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div className={`rounded-xl border border-slate-200 bg-white p-5 ${className}`}>{children}</div>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return <h2 className="mb-3 text-sm font-semibold tracking-wide text-slate-500 uppercase">{children}</h2>;
}

export function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <div className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</div>
      <div className="mt-2 text-2xl font-semibold tabular-nums">{value}</div>
      {hint ? <div className="mt-1 text-xs text-slate-500">{hint}</div> : null}
    </Card>
  );
}

export function ToilBadge({ score }: { score: number }) {
  const tone = toilTone(score);
  return (
    <span
      className={`inline-flex items-baseline gap-1 rounded-lg border px-2.5 py-1 ${TONE_BG[tone]}`}
    >
      <span className={`text-lg font-semibold tabular-nums ${TONE_TEXT[tone]}`}>
        {Math.round(score)}
      </span>
      <span className="text-xs text-slate-500">/100</span>
    </span>
  );
}

export function TrendArrow({ trend, delta }: { trend: string; delta: number }) {
  // Rising toil is bad news, so "up" is the alarming direction here.
  if (trend === "flat") {
    return <span className="text-sm text-slate-400">— no change</span>;
  }
  const rising = trend === "up";
  return (
    <span className={`text-sm font-medium ${rising ? "text-red-600" : "text-teal-700"}`}>
      {rising ? "▲" : "▼"} {Math.abs(Math.round(delta))} vs last week
    </span>
  );
}

export function RangePicker({
  value,
  onChange,
}: {
  value: number;
  onChange: (days: number) => void;
}) {
  return (
    <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
      {[7, 30, 90].map((days) => (
        <button
          key={days}
          type="button"
          onClick={() => onChange(days)}
          className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${
            value === days ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          {days}d
        </button>
      ))}
    </div>
  );
}

export function Empty({ message }: { message: string }) {
  return (
    <Card className="text-center text-sm text-slate-500">
      <p>{message}</p>
    </Card>
  );
}

export function Spinner() {
  return <div className="py-16 text-center text-sm text-slate-500">Loading…</div>;
}
