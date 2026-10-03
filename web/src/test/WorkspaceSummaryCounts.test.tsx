import { render, screen } from '@testing-library/react';
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
});
