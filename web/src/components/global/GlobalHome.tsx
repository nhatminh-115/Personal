import { ArrowRight, MessageSquareText, Paperclip, Sparkles, X } from 'lucide-react';
import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import type { ChatThreadRecord, ProjectRecord } from '../../data/workspaceData';

export type HomeTaskType = 'research' | 'coding' | 'writing';

interface HomeContextFile {
  id: string;
  name: string;
}

export interface HomeConversation {
  thread: ChatThreadRecord;
  project: ProjectRecord;
}

interface GlobalHomeProps {
  projects: ProjectRecord[];
  conversations: HomeConversation[];
  defaultProjectId: string | null;
  onStartConversation: (projectId: string, prompt: string, taskType?: HomeTaskType, contextFileContentIds?: string[]) => void;
  onImportContextFiles: (files: File[], projectId: string) => Promise<HomeContextFile[]>;
  onOpenConversation: (projectId: string, threadId: string) => void;
  onOpenConversations: () => void;
  onOpenProjects: () => void;
}

export function GlobalHome({
  projects,
  conversations,
  defaultProjectId,
  onStartConversation,
  onImportContextFiles,
  onOpenConversation,
  onOpenConversations,
  onOpenProjects,
}: GlobalHomeProps) {
  const [projectId, setProjectId] = useState(defaultProjectId ?? projects[0]?.id ?? '');
  const [prompt, setPrompt] = useState('');
  const [mode, setMode] = useState<'auto' | HomeTaskType>('auto');
  const [contextFiles, setContextFiles] = useState<HomeContextFile[]>([]);
  const [contextError, setContextError] = useState('');
  const [importingContext, setImportingContext] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (projects.some((project) => project.id === projectId)) return;
    setProjectId(defaultProjectId && projects.some((project) => project.id === defaultProjectId)
      ? defaultProjectId
      : projects[0]?.id ?? '');
  }, [defaultProjectId, projectId, projects]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = prompt.trim();
    if (!projectId || !text) return;
    onStartConversation(projectId, text, mode === 'auto' ? undefined : mode, contextFiles.map((file) => file.id));
    setPrompt('');
    setContextFiles([]);
    setContextError('');
  };

  const addContextFiles = async (event: ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(event.currentTarget.files ?? []);
    event.currentTarget.value = '';
    setContextError('');
    const availableSlots = Math.max(0, 5 - contextFiles.length);
    const files = selected.slice(0, availableSlots);
    if (files.length < selected.length) setContextError('Choose up to five files for one conversation.');
    if (!projectId || !files.length) return;

    setImportingContext(true);
    try {
      const imported = await onImportContextFiles(files, projectId);
      setContextFiles((current) => [...current, ...imported.filter((file) => !current.some((item) => item.id === file.id))].slice(0, 5));
    } catch (error) {
      setContextError(error instanceof Error ? error.message : 'Could not add those files to the Library.');
    } finally {
      setImportingContext(false);
    }
  };

  return (
    <section className="global-home-v16" aria-labelledby="home-v16-title">
      <header className="global-home-v16__intro">
        <span className="eyebrow">PERSONAL WORKSPACE</span>
        <h1 id="home-v16-title">A little more room<br />for <span>big thinking.</span></h1>
        <p>Start a conversation, then keep the useful parts close to the project they belong to.</p>
      </header>

      <form className="home-composer-v16" onSubmit={submit}>
        <div className="home-composer-v16__heading">
          <div><div className="home-composer-v16__tag"><Sparkles size={13} /> START A CONVERSATION</div><p>What would you like to work through?</p></div>
          <label className="home-composer-v16__scope">
            <span>Project</span>
            <select aria-label="Project for new conversation" value={projectId} onChange={(event) => { setProjectId(event.target.value); setContextFiles([]); setContextError(''); }} disabled={!projects.length}>
              {projects.length ? projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>) : <option value="">Choose a project</option>}
            </select>
          </label>
          <span className="home-composer-v16__shortcut">ENTER ↵</span>
        </div>
        <label className="home-composer-v16__prompt">
          <span className="sr-only">Start a conversation</span>
          <textarea
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                event.currentTarget.form?.requestSubmit();
              }
            }}
            placeholder={projects.length ? 'What would you like to think through?' : 'Create a project before starting a conversation.'}
            rows={3}
            disabled={!projects.length}
          />
        </label>
        {contextFiles.length ? <div className="home-composer-v16__context-list" aria-label="Selected context files">
          {contextFiles.map((file) => <span className="home-composer-v16__context-file" key={file.id}>{file.name}<button type="button" aria-label={`Remove ${file.name} from context`} onClick={() => setContextFiles((current) => current.filter((item) => item.id !== file.id))}><X size={12} /></button></span>)}
        </div> : null}
        {contextError ? <p className="home-composer-v16__error" role="status">{contextError}</p> : null}
        <div className="home-composer-v16__footer">
          <div className="home-composer-v16__controls">
            <label className="home-composer-v16__mode"><span className="sr-only">Conversation mode</span><select aria-label="Conversation mode" value={mode} onChange={(event) => setMode(event.target.value as 'auto' | HomeTaskType)}>
              <option value="auto">Mode · Auto</option><option value="research">Mode · Research</option><option value="writing">Mode · Write</option><option value="coding">Mode · Code</option>
            </select></label>
            <input ref={fileInputRef} className="sr-only" type="file" multiple disabled={!projectId || importingContext || contextFiles.length >= 5} onChange={addContextFiles} />
            <button className="home-composer-v16__quiet" type="button" disabled={!projectId || importingContext || contextFiles.length >= 5} onClick={() => fileInputRef.current?.click()}><Paperclip size={14} /> {importingContext ? 'Adding files…' : contextFiles.length ? `Add context · ${contextFiles.length}` : 'Add context'}</button>
          </div>
          <button className="home-composer-v16__submit" type="submit" disabled={!projectId || !prompt.trim()}><ArrowRight size={15} /> Start conversation</button>
        </div>
      </form>

      <section className="home-conversations-v16" aria-labelledby="home-recent-conversations">
        <div className="home-conversations-v16__heading">
          <div><span className="eyebrow">PICK UP WHERE YOU LEFT OFF</span><h2 id="home-recent-conversations">Recent conversations</h2></div>
          <button type="button" onClick={onOpenConversations}>All conversations <ArrowRight size={14} /></button>
        </div>
        {conversations.length ? (
          <div className="home-conversations-v16__list">
            {conversations.slice(0, 8).map(({ thread, project }) => (
              <button className="home-conversation-v16" key={thread.id} type="button" onClick={() => onOpenConversation(project.id, thread.id)}>
                <span className="home-conversation-v16__icon"><MessageSquareText size={16} /></span>
                <span className="home-conversation-v16__copy"><strong>{thread.title}</strong><small>{project.name}{thread.summary ? ` · ${thread.summary}` : ''}</small></span>
                <span className="home-conversation-v16__time">{thread.updated}</span>
                <ArrowRight size={14} />
              </button>
            ))}
          </div>
        ) : (
          <div className="home-conversations-v16__empty">
            <MessageSquareText size={18} />
            <div><strong>No conversations to continue</strong><p>Start one above. Your project conversations will appear here.</p></div>
            {!projects.length ? <button type="button" onClick={onOpenProjects}>Create a project <ArrowRight size={13} /></button> : null}
          </div>
        )}
      </section>
    </section>
  );
}
