import { useEffect, useMemo, useState } from 'react';
import { ArrowDown, ArrowUpRight, BookOpenText, CircleHelp, FileCheck2, LoaderCircle, Network, Play, RefreshCw } from 'lucide-react';
import type { ProjectRecord } from '../../data/workspaceData';
import { executionErrorText } from '../../lib/executionError';
import { api } from '../../services/api';
import type { WorkspaceEdge, WorkspaceObject } from '../../types';
import './ResearchRadarPanel.css';

interface ResearchRadarPanelProps {
  projects: ProjectRecord[];
  onStudyResearchClaim?: (objectId: string, title: string, projectName: string) => void;
}

const researchObjectTypes = new Set(['research_source', 'research_evidence', 'research_claim']);

function metadataText(object: WorkspaceObject, key: string): string | null {
  const value = object.metadata_json[key];
  if (typeof value === 'string') return value.trim() ? value : null;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (Array.isArray(value)) {
    const entries = value.filter((entry): entry is string => typeof entry === 'string' && Boolean(entry.trim()));
    return entries.length ? entries.join(', ') : null;
  }
  return null;
}

function sourceUrl(object: WorkspaceObject): string | null {
  const value = metadataText(object, 'url');
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'https:' || parsed.protocol === 'http:' ? parsed.toString() : null;
  } catch {
    return null;
  }
}

export function ResearchRadarPanel({ projects, onStudyResearchClaim }: ResearchRadarPanelProps) {
  const savedProjects = useMemo(() => projects.filter((project) => project.source === 'user'), [projects]);
  const [projectName, setProjectName] = useState(savedProjects[0]?.name ?? '');
  const [objects, setObjects] = useState<WorkspaceObject[]>([]);
  const [edges, setEdges] = useState<WorkspaceEdge[]>([]);
  const [objectCursor, setObjectCursor] = useState<string | null>(null);
  const [edgeCursor, setEdgeCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    if (!savedProjects.some((project) => project.name === projectName)) {
      setProjectName(savedProjects[0]?.name ?? '');
    }
  }, [projectName, savedProjects]);

  useEffect(() => {
    let active = true;
    setObjects([]);
    setEdges([]);
    setObjectCursor(null);
    setEdgeCursor(null);
    setError(null);
    if (!projectName) return () => { active = false; };

    setLoading(true);
    void api.fetchWorkspaceGraphPage(projectName).then((page) => {
      if (!active) return;
      setObjects(page.objects.filter((object) => researchObjectTypes.has(object.object_type)));
      setEdges(page.edges.filter((edge) => edge.edge_family === 'provenance'));
      setObjectCursor(page.objects_next_cursor ?? null);
      setEdgeCursor(page.edges_next_cursor ?? null);
    }).catch((reason: unknown) => {
      if (active) setError(executionErrorText(reason));
    }).finally(() => {
      if (active) setLoading(false);
    });

    return () => { active = false; };
  }, [projectName, refreshKey]);

  const researchObjects = useMemo(
    () => objects.filter((object) => researchObjectTypes.has(object.object_type)),
    [objects],
  );
  const objectIds = useMemo(() => new Set(researchObjects.map((object) => object.id)), [researchObjects]);
  const researchEdges = useMemo(
    () => edges.filter((edge) => objectIds.has(edge.source_object_id) && objectIds.has(edge.target_object_id)),
    [edges, objectIds],
  );
  const sourceCount = researchObjects.filter((object) => object.object_type === 'research_source').length;
  const evidenceCount = researchObjects.filter((object) => object.object_type === 'research_evidence').length;
  const claimCount = researchObjects.filter((object) => object.object_type === 'research_claim').length;

  const loadMore = async () => {
    if (!projectName || loadingMore || (!objectCursor && !edgeCursor)) return;
    setLoadingMore(true);
    setError(null);
    try {
      const page = await api.fetchWorkspaceGraphPage(projectName, { object: objectCursor, edge: edgeCursor });
      setObjects((current) => {
        const ids = new Set(current.map((object) => object.id));
        return [...current, ...page.objects.filter((object) => researchObjectTypes.has(object.object_type) && !ids.has(object.id))];
      });
      setEdges((current) => {
        const ids = new Set(current.map((edge) => edge.id));
        return [...current, ...page.edges.filter((edge) => edge.edge_family === 'provenance' && !ids.has(edge.id))];
      });
      setObjectCursor(page.objects_next_cursor ?? null);
      setEdgeCursor(page.edges_next_cursor ?? null);
    } catch (reason) {
      setError(executionErrorText(reason));
    } finally {
      setLoadingMore(false);
    }
  };

  const objectsById = useMemo(() => new Map(researchObjects.map((object) => [object.id, object])), [researchObjects]);
  const grouped = {
    research_source: researchObjects.filter((object) => object.object_type === 'research_source'),
    research_evidence: researchObjects.filter((object) => object.object_type === 'research_evidence'),
    research_claim: researchObjects.filter((object) => object.object_type === 'research_claim'),
  };

  return (
    <section className="research-radar" aria-label="Research Radar">
      <header className="research-radar__header">
        <div>
          <span className="eyebrow">RESEARCH RADAR</span>
          <h2><Network size={18} /> Sources, evidence, and findings</h2>
          <p>A read-only view of saved research provenance. Choose a project to inspect its linked graph.</p>
        </div>
        <label className="research-radar__project">
          <span>Project</span>
          <select value={projectName} onChange={(event) => setProjectName(event.target.value)} disabled={!savedProjects.length}>
            {savedProjects.length ? savedProjects.map((project) => <option key={project.id} value={project.name}>{project.name}</option>) : <option value="">No saved projects</option>}
          </select>
        </label>
      </header>

      {!savedProjects.length ? (
        <div className="research-radar__empty"><CircleHelp size={18} /><span>Create a saved project and run Research there to populate this view.</span></div>
      ) : loading ? (
        <div className="research-radar__empty" role="status"><LoaderCircle size={17} className="research-radar__spin" /> Loading project research…</div>
      ) : error && !researchObjects.length ? (
        <div className="research-radar__empty research-radar__empty--error" role="alert"><span>{error}</span><button type="button" onClick={() => setRefreshKey((current) => current + 1)}><RefreshCw size={14} /> Retry</button></div>
      ) : !researchObjects.length ? (
        <div className="research-radar__empty">
          <BookOpenText size={18} />
          <span>{objectCursor || edgeCursor ? 'No Research artifacts on this page. Older project objects may contain saved sources and claims.' : 'No Research artifacts in this project yet. Research sources and verified claims appear here after a live or deterministic Research run.'}</span>
          {objectCursor || edgeCursor ? <button className="research-radar__more" type="button" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? <LoaderCircle size={14} className="research-radar__spin" /> : <ArrowDown size={14} />} Load older research artifacts</button> : null}
        </div>
      ) : (
        <>
          <div className="research-radar__summary" aria-label="Research artifact counts">
            <span><BookOpenText size={14} /> {sourceCount} sources</span>
            <span><ArrowDown size={14} /> {evidenceCount} evidence</span>
            <span><FileCheck2 size={14} /> {claimCount} claims</span>
            <span><Network size={14} /> {researchEdges.length} provenance links</span>
          </div>
          <p className="research-radar__loaded-note">Counts cover the project pages loaded so far and update as you browse older artifacts.</p>
          <div className="research-radar__columns">
            {([
              ['research_source', 'Sources'],
              ['research_evidence', 'Evidence'],
              ['research_claim', 'Claims'],
            ] as const).map(([type, title]) => (
              <section className="research-radar__column" key={type} aria-label={title}>
                <h3>{title}<span>{grouped[type].length}</span></h3>
                {grouped[type].length ? grouped[type].map((object) => {
                  const url = type === 'research_source' ? sourceUrl(object) : null;
                  const related = researchEdges.filter((edge) => edge.source_object_id === object.id || edge.target_object_id === object.id);
                  return (
                    <article className="research-radar__card" key={object.id}>
                      <div className="research-radar__card-title">
                        <strong>{object.title || 'Untitled research artifact'}</strong>
                        {type === 'research_source' ? <span className={`research-radar__status research-radar__status--${metadataText(object, 'status') ?? 'unknown'}`}>{metadataText(object, 'status') ?? 'status unknown'}</span> : null}
                        {type === 'research_claim' ? <span className={`research-radar__status research-radar__status--${metadataText(object, 'verification_status') ?? 'unknown'}`}>{metadataText(object, 'verification_status') ?? 'verification unknown'}</span> : null}
                      </div>
                      {type === 'research_source' ? <small>{[metadataText(object, 'authors'), metadataText(object, 'year'), metadataText(object, 'venue')].filter(Boolean).join(' · ') || 'Publication metadata unavailable'}</small> : null}
                      <p>{object.content || 'No summary available.'}</p>
                      {related.length ? <div className="research-radar__relations">{related.slice(0, 4).map((edge) => {
                        const otherId = edge.source_object_id === object.id ? edge.target_object_id : edge.source_object_id;
                        const other = objectsById.get(otherId);
                        return <span key={edge.id}>{edge.relation_type.replace(/_/g, ' ')}{other ? ` · ${other.title}` : ''}</span>;
                      })}</div> : null}
                      {type === 'research_claim' && metadataText(object, 'verification_status') === 'verified' && onStudyResearchClaim ? (
                        <button
                          className="research-radar__study"
                          type="button"
                          onClick={() => onStudyResearchClaim(object.id, object.title, projectName)}
                        >
                          <Play size={12} /> Study this finding
                        </button>
                      ) : null}
                      {url ? <a href={url} target="_blank" rel="noreferrer"><span>Open source</span><ArrowUpRight size={13} /></a> : null}
                    </article>
                  );
                }) : <p className="research-radar__column-empty">No {title.toLowerCase()} on this page.</p>}
              </section>
            ))}
          </div>
          {error ? <p className="research-radar__error" role="alert">Could not load the next page: {error}</p> : null}
          {objectCursor || edgeCursor ? <button className="research-radar__more" type="button" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? <LoaderCircle size={14} className="research-radar__spin" /> : <ArrowDown size={14} />} Load older research artifacts</button> : null}
        </>
      )}
    </section>
  );
}
