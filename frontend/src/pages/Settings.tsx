import { useCallback, useEffect, useState } from "react";
import { api, type Integration, type Team } from "../lib/api";
import { Card, Empty, SectionTitle, Spinner } from "../components/ui";

export function Settings() {
  const [integrations, setIntegrations] = useState<Integration[] | null>(null);
  const [teams, setTeams] = useState<Team[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(() => {
    Promise.all([api.get<Integration[]>("/api/integrations"), api.get<Team[]>("/api/teams")])
      .then(([ints, tms]) => {
        setIntegrations(ints);
        setTeams(tms);
      })
      .catch((err) => setMessage(err.message));
  }, []);

  useEffect(load, [load]);

  async function triggerSync(id: string) {
    setBusy(id);
    setMessage(null);
    try {
      const result = await api.post<{ queued: boolean }>(`/api/integrations/${id}/sync`);
      setMessage(
        result.queued
          ? "Sync queued — the worker picks it up within a few seconds."
          : "A sync for this integration is already queued.",
      );
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Could not queue the sync");
    } finally {
      setBusy(null);
    }
  }

  if (!integrations) return <Spinner />;

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">Settings</h1>

      {message ? (
        <div className="mb-4 rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm">
          {message}
        </div>
      ) : null}

      <SectionTitle>Integrations</SectionTitle>
      <div className="mb-8 grid gap-3">
        {integrations.length === 0 ? (
          <Empty message="No integrations connected yet." />
        ) : (
          integrations.map((integration) => (
            <Card key={integration.id}>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="font-medium">{integration.display_name}</div>
                  <div className="mt-0.5 text-xs text-slate-500">
                    {integration.provider}
                    {" · "}
                    {integration.status}
                    {integration.last_synced_at
                      ? ` · last synced ${new Date(integration.last_synced_at).toLocaleString()}`
                      : " · never synced"}
                  </div>
                  {integration.last_error ? (
                    <div className="mt-1 text-xs text-red-600">{integration.last_error}</div>
                  ) : null}
                </div>
                <button
                  type="button"
                  onClick={() => triggerSync(integration.id)}
                  disabled={busy === integration.id}
                  className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm font-medium hover:bg-slate-50 disabled:opacity-50"
                >
                  {busy === integration.id ? "Queueing…" : "Sync now"}
                </button>
              </div>
            </Card>
          ))
        )}
      </div>

      <SectionTitle>Teams</SectionTitle>
      <Card className="p-0">
        <ul className="divide-y divide-slate-100">
          {teams.map((team) => (
            <li key={team.id} className="flex items-center justify-between px-5 py-3 text-sm">
              <span className="font-medium">{team.name}</span>
              <span className="text-xs text-slate-500">{team.timezone ?? "org default"}</span>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}
