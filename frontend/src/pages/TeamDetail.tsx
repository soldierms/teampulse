import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type TeamDetail as TeamDetailData } from "../lib/api";
import { count, minutes, oneDecimal, percent, TONE_STROKE } from "../lib/format";
import { MetricChart } from "../components/MetricChart";
import { Card, Empty, RangePicker, SectionTitle, Spinner, Stat } from "../components/ui";

export function TeamDetail() {
  const { teamId } = useParams<{ teamId: string }>();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<TeamDetailData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    api
      .get<TeamDetailData>(`/api/metrics/teams/${teamId}?days=${days}`)
      .then(setData)
      .catch((err) => setError(err.message));
  }, [teamId, days]);

  if (error) return <Empty message={error} />;
  if (!data) return <Spinner />;

  const series = (key: string) => data.series.find((s) => s.metric_key === key);
  const totals = data.totals;

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link to="/" className="text-sm text-slate-500 hover:text-slate-900">
            ← All teams
          </Link>
          <h1 className="mt-1 text-2xl font-semibold">{data.team_name}</h1>
        </div>
        <RangePicker value={days} onChange={setDays} />
      </div>

      <div className="mb-8 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Toil score"
          value={oneDecimal(totals.toil_score)}
          hint={`average over ${days} days`}
        />
        <Stat
          label="Pages"
          value={count(totals.pages_total)}
          hint={`${percent(totals.after_hours_page_rate)} after hours`}
        />
        <Stat
          label="Change failure rate"
          value={percent(totals.change_failure_rate)}
          hint={`${count(totals.deploys_total)} deploys`}
        />
        <Stat
          label="p95 time to resolve"
          value={minutes(totals.p95_resolution_minutes)}
          hint={`mean ${minutes(totals.mean_resolution_minutes)}`}
        />
      </div>

      <SectionTitle>Trends</SectionTitle>
      <div className="mb-8 grid gap-4 lg:grid-cols-2">
        <MetricChart title="Pages per day" series={series("pages_total")} color="#0f172a" />
        <MetricChart
          title="After-hours page rate"
          series={series("after_hours_page_rate")}
          color={TONE_STROKE.alarm}
          formatValue={(v) => `${Math.round(v * 100)}%`}
        />
        <MetricChart title="Deploys per day" series={series("deploys_total")} color={TONE_STROKE.calm} />
        <MetricChart
          title="Change failure rate"
          series={series("change_failure_rate")}
          color={TONE_STROKE.warn}
          formatValue={(v) => `${Math.round(v * 100)}%`}
        />
      </div>

      <SectionTitle>On-call load by person</SectionTitle>
      <Card className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs tracking-wide text-slate-500 uppercase">
              <th className="px-5 py-3 font-medium">Person</th>
              <th className="px-5 py-3 text-right font-medium">Pages</th>
              <th className="px-5 py-3 text-right font-medium">After hours</th>
              <th className="px-5 py-3 text-right font-medium">Share</th>
              <th className="px-5 py-3 text-right font-medium">On-call hours</th>
            </tr>
          </thead>
          <tbody>
            {data.members.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-5 py-8 text-center text-slate-500">
                  No members on this team yet.
                </td>
              </tr>
            ) : (
              data.members.map((member) => (
                <tr key={member.user_id} className="border-b border-slate-100 last:border-0">
                  <td className="px-5 py-3">
                    <Link
                      to={`/people/${member.user_id}`}
                      className="font-medium hover:underline"
                    >
                      {member.name}
                    </Link>
                    <div className="text-xs text-slate-500">{member.email}</div>
                  </td>
                  <td className="px-5 py-3 text-right tabular-nums">{count(member.pages_total)}</td>
                  <td className="px-5 py-3 text-right tabular-nums">
                    {count(member.pages_after_hours)}
                  </td>
                  <td
                    className={`px-5 py-3 text-right tabular-nums ${
                      member.after_hours_page_rate >= 0.5 ? "font-semibold text-red-600" : ""
                    }`}
                  >
                    {percent(member.after_hours_page_rate)}
                  </td>
                  <td className="px-5 py-3 text-right tabular-nums">
                    {oneDecimal(member.on_call_hours)}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </Card>
    </div>
  );
}
