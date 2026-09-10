import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type PersonDetail as PersonDetailData } from "../lib/api";
import { count, oneDecimal, percent, TONE_STROKE } from "../lib/format";
import { MetricChart } from "../components/MetricChart";
import { Empty, RangePicker, SectionTitle, Spinner, Stat } from "../components/ui";

export function PersonDetail() {
  const { userId } = useParams<{ userId: string }>();
  const navigate = useNavigate();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<PersonDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    api
      .get<PersonDetailData>(`/api/metrics/people/${userId}?days=${days}`)
      .then(setData)
      .catch((err) => setError(err.message));
  }, [userId, days]);

  if (error) return <Empty message={error} />;
  if (!data) return <Spinner />;

  const series = (key: string) => data.series.find((s) => s.metric_key === key);
  const totals = data.totals;

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="text-sm text-slate-500 hover:text-slate-900"
          >
            ← Back
          </button>
          <h1 className="mt-1 text-2xl font-semibold">{data.name}</h1>
          <p className="text-sm text-slate-500">{data.email}</p>
        </div>
        <RangePicker value={days} onChange={setDays} />
      </div>

      <div className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Pages" value={count(totals.pages_total)} hint={`over ${days} days`} />
        <Stat label="After-hours pages" value={count(totals.pages_after_hours)} />
        <Stat label="After-hours share" value={percent(totals.after_hours_page_rate)} />
        <Stat label="On-call hours" value={oneDecimal(totals.on_call_hours)} />
      </div>

      <SectionTitle>History</SectionTitle>
      <div className="grid gap-4 lg:grid-cols-2">
        <MetricChart title="Pages per day" series={series("pages_total")} color="#0f172a" />
        <MetricChart
          title="After-hours pages per day"
          series={series("pages_after_hours")}
          color={TONE_STROKE.alarm}
        />
        <MetricChart
          title="On-call hours per day"
          series={series("on_call_hours")}
          color={TONE_STROKE.calm}
        />
        <MetricChart
          title="After-hours share"
          series={series("after_hours_page_rate")}
          color={TONE_STROKE.warn}
          formatValue={(v) => `${Math.round(v * 100)}%`}
        />
      </div>
    </div>
  );
}
