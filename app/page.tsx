"use client";

import { useEffect, useMemo, useState } from "react";

type Project = {
  id: string;
  name: string;
  state?: string;
  visibility?: string;
};

type Team = {
  id: string;
  name: string;
};

type AuditResult = {
  success: boolean;
  project: string;
  team: string;
  status: string;
  summary: string;
  report: string;
  details: Record<string, unknown>;
  wiki_published: boolean;
  actions: Array<Record<string, unknown>>;
  errors: Array<Record<string, unknown>>;
};

const DEFAULT_QUERY =
  "Analyze the current Azure DevOps board and identify meaningful delivery risks, workload concerns, aging work, deadline pressure, dependencies, and other evidence-backed observations.";

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);
  const [project, setProject] = useState("");
  const [team, setTeam] = useState("");
  const [query, setQuery] = useState(DEFAULT_QUERY);
  const [result, setResult] = useState<AuditResult | null>(null);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingTeams, setLoadingTeams] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    async function loadProjects() {
      try {
        setLoadingProjects(true);
        const response = await fetch("/api/projects", { cache: "no-store" });
        const contentType = response.headers.get("content-type") || "";
        const raw = await response.text();
        let data: { projects?: Project[]; detail?: string };
        try {
          data = contentType.includes("application/json") ? JSON.parse(raw) : {};
        } catch {
          data = {};
        }
        if (!response.ok) {
          throw new Error(
            data.detail ||
              `API /api/projects returned HTTP ${response.status}.`,
          );
        }
        if (!contentType.includes("application/json")) {
          throw new Error(
            "The /api/projects endpoint returned HTML instead of JSON. Start this project with 'vercel dev', not 'npm run dev'.",
          );
        }

        const items: Project[] = data.projects || [];
        setProjects(items);

        if (items.length) {
          setProject(items[0].name);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load projects.");
      } finally {
        setLoadingProjects(false);
      }
    }

    loadProjects();
  }, []);

  useEffect(() => {
    if (!project) {
      setTeams([]);
      setTeam("");
      return;
    }

    async function loadTeams() {
      try {
        setLoadingTeams(true);
        setError("");

        const response = await fetch(
          `/api/teams?project=${encodeURIComponent(project)}`,
          { cache: "no-store" },
        );
        const contentType = response.headers.get("content-type") || "";
        const raw = await response.text();
        let data: { teams?: Team[]; detail?: string };
        try {
          data = contentType.includes("application/json") ? JSON.parse(raw) : {};
        } catch {
          data = {};
        }
        if (!response.ok) {
          throw new Error(data.detail || `API /api/teams returned HTTP ${response.status}.`);
        }
        if (!contentType.includes("application/json")) {
          throw new Error(
            "The /api/teams endpoint returned HTML instead of JSON. Start this project with 'vercel dev', not 'npm run dev'.",
          );
        }

        const items: Team[] = data.teams || [];
        setTeams(items);
        setTeam(items.length ? items[0].name : "");
      } catch (err) {
        setTeams([]);
        setTeam("");
        setError(err instanceof Error ? err.message : "Could not load teams.");
      } finally {
        setLoadingTeams(false);
      }
    }

    loadTeams();
  }, [project]);

  const canRun = useMemo(
    () => Boolean(project && team && query.trim() && !running),
    [project, team, query, running],
  );

  async function runAudit() {
    if (!canRun) return;

    try {
      setRunning(true);
      setError("");
      setResult(null);

      const response = await fetch("/api/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project,
          team,
          query: query.trim(),
        }),
      });

      const contentType = response.headers.get("content-type") || "";
      const raw = await response.text();
      let data: AuditResult & { detail?: string };
      try {
        data = contentType.includes("application/json") ? JSON.parse(raw) : ({} as AuditResult & { detail?: string });
      } catch {
        data = {} as AuditResult & { detail?: string };
      }

      if (!response.ok) {
        throw new Error(data.detail || `Audit API returned HTTP ${response.status}.`);
      }
      if (!contentType.includes("application/json")) {
        throw new Error(
          "The /api/audit endpoint returned HTML instead of JSON. Start this project with 'vercel dev', not 'npm run dev'.",
        );
      }

      setResult(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Audit failed.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <main className="shell">
      <header className="header">
        <div>
          <div className="eyebrow">AZURE DEVOPS · INTELLIGENCE</div>
          <h1>Audit Logger</h1>
          <p className="subtitle">
            Evidence-based Board & Sprint intelligence with consolidated Wiki reporting.
          </p>
        </div>
        <div className="status-pill">
          <span className="status-dot" />
          Live
        </div>
      </header>

      <section className="workspace">
        <aside className="panel controls">
          <div className="panel-heading">
            <span>Audit configuration</span>
            <span className="muted">Runtime selection</span>
          </div>

          <label>
            Azure DevOps project
            <select
              value={project}
              onChange={(event) => setProject(event.target.value)}
              disabled={loadingProjects || running}
            >
              <option value="">
                {loadingProjects ? "Loading projects..." : "Select a project"}
              </option>
              {projects.map((item) => (
                <option key={item.id} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>

          <label>
            Team / board
            <select
              value={team}
              onChange={(event) => setTeam(event.target.value)}
              disabled={!project || loadingTeams || running}
            >
              <option value="">
                {loadingTeams ? "Loading teams..." : "Select a team"}
              </option>
              {teams.map((item) => (
                <option key={item.id} value={item.name}>
                  {item.name}
                </option>
              ))}
            </select>
          </label>

          <label>
            Audit request
            <textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              disabled={running}
              rows={8}
              placeholder="Describe what you want the agent to investigate..."
            />
          </label>

          <button className="run-button" onClick={runAudit} disabled={!canRun}>
            {running ? (
              <>
                <span className="spinner" />
                Running audit...
              </>
            ) : (
              "Run Board Audit"
            )}
          </button>

          <p className="help-text">
            Project and team are selected at request time. They are not stored in
            the deployment environment.
          </p>
        </aside>

        <section className="panel results">
          {!result && !running && !error && (
            <div className="empty">
              <div className="empty-mark">AI</div>
              <h2>Ready for an audit</h2>
              <p>
                Select a project and team, describe the review, and the agent will
                investigate the relevant Azure DevOps evidence.
              </p>
            </div>
          )}

          {running && (
            <div className="empty">
              <div className="loader-large" />
              <h2>Investigating Azure DevOps</h2>
              <p>
                Reading board data, calculating deterministic metrics, and building
                the consolidated audit report.
              </p>
            </div>
          )}

          {error && (
            <div className="error-box">
              <strong>Execution error</strong>
              <span>{error}</span>
            </div>
          )}

          {result && (
            <div className="report">
              <div className="report-top">
                <div>
                  <div className="eyebrow">AUDIT RESULT</div>
                  <h2>{result.project}</h2>
                  <p className="result-team">{result.team}</p>
                </div>
                <div className="result-badges">
                  <span className="badge">{result.status}</span>
                  <span className={result.wiki_published ? "badge success" : "badge"}>
                    {result.wiki_published ? "Wiki published" : "Wiki not published"}
                  </span>
                </div>
              </div>


              {result.report && (
                <div className="report-card">
                  <div className="card-label">Consolidated audit report</div>
                  <pre>{result.report}</pre>
                </div>
              )}

              {result.actions.length > 0 && (
                <div className="summary-card">
                  <div className="card-label">Audit actions</div>
                  <pre>{JSON.stringify(result.actions, null, 2)}</pre>
                </div>
              )}

              {result.errors.length > 0 && (
                <div className="error-box">
                  <strong>Reported execution errors</strong>
                  <pre>{JSON.stringify(result.errors, null, 2)}</pre>
                </div>
              )}
            </div>
          )}
        </section>
      </section>

      <footer>
        <span>Azure DevOps Audit Logger + Board/Sprint Intelligence Agent</span>
        <span>Evidence policy: OBSERVED · INFERRED · UNKNOWN</span>
      </footer>
    </main>
  );
}
