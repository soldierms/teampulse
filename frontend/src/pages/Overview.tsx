import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type OrgOverview } from "../lib/api";
import { count, percent, oneDecimal, shortDate } from "../lib/format";
import { Card, Empty, Spinner, ToilBadge, TrendArrow } from "../components/ui";

export function Overview() {
  const [data, setData] = useState<OrgOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .get<OrgOverview>("/api/metrics/overview")
      .then(setData)
      .catch((err) => setError(err.message));
  }, []);

  if (error) return <Empty message={error} />;
  if (!data) return <Spinner />;

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Org overview</h1>
        <p className="mt-1 text-sm text-slate-500">
          Week of {shortDate(data.week_start)} — toil score compares against the week before.
        </p>
      </div>

      {data.teams.length === 0 ? (
        <Empty message="No teams yet. Create one in Settings, then claim its PagerDuty services and GitHub repos." />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {data.teams.map((team) => (
            <Link key={team.team_id} to={`/teams/${team.team_id}`} className="block">
              <Card className="transition hover:border-slate-400">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="font-semibold">{team.team_name}</div>
                    <div className="mt-1">
                      <TrendArrow
                        trend={team.trend}
                        delta={team.toil_score - team.toil_score_previous}
                      />
                    </div>
                  </div>
                  <ToilBadge score={team.toil_score} />
                </div>

                <dl className="mt-5 grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <dt className="text-xs text-slate-500">Pages this week</dt>
                    <dd className="font-medium tabular-nums">{count(team.pages_total)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-slate-500">After hours</dt>
                    <dd className="font-medium tabular-nums">
                      {percent(team.after_hours_page_rate)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-slate-500">Change failure</dt>
                    <dd className="font-medium tabular-nums">
                      {percent(team.change_failure_rate)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-slate-500">Deploys / week</dt>
                    <dd className="font-medium tabular-nums">
                      {oneDecimal(team.deploy_frequency_per_week)}
                    </dd>
                  </div>
                </dl>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
