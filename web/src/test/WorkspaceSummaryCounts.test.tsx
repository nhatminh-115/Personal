import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { GlobalHome } from '../components/global/GlobalHome';

describe('workspace aggregate counts', () => {
  it('shows canonical collection totals independently from the loaded preview page', () => {
    render(<GlobalHome
      projects={[]}
      libraryItems={[]}
      libraryCount={118}
      linkedLibraryCount={34}
      activeAutomationCount={6}
      noteCount={203}
      onOpenProject={vi.fn()}
      onOpenProjects={vi.fn()}
      onOpenLibrary={vi.fn()}
      onOpenFile={vi.fn()}
    />);

    expect(screen.getByText('118 saved Library references')).toBeInTheDocument();
    expect(screen.getByText('203 notes · 34 linked files')).toBeInTheDocument();
    expect(screen.getByText('6 active automations')).toBeInTheDocument();
  });

  it('keeps Home actions connected to real project and Library routes when collections are empty', () => {
    const onOpenProjects = vi.fn();
    const onOpenLibrary = vi.fn();
    render(<GlobalHome
      projects={[]}
      libraryItems={[]}
      libraryCount={0}
      linkedLibraryCount={0}
      activeAutomationCount={0}
      noteCount={0}
      onOpenProject={vi.fn()}
      onOpenProjects={onOpenProjects}
      onOpenLibrary={onOpenLibrary}
      onOpenFile={vi.fn()}
    />);

    expect(screen.getByText('No projects yet')).toBeInTheDocument();
    expect(screen.getByText('Your Library is ready for its first file.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Browse projects/ }));
    fireEvent.click(screen.getByRole('button', { name: /Open Library/ }));

    expect(onOpenProjects).toHaveBeenCalledOnce();
    expect(onOpenLibrary).toHaveBeenCalledOnce();
  });
});
