import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CustomSelect } from '../components/ui/CustomSelect';

describe('CustomSelect', () => {
  const options = [
    { value: '', label: 'Profile', description: 'Use the project routing policy' },
    { value: 'low', label: 'Low' },
    { value: 'high', label: 'High', description: 'More deliberate reasoning' },
  ];

  it('opens a custom listbox and applies a selected option', () => {
    const onChange = vi.fn();
    render(<CustomSelect value="" options={options} onChange={onChange} ariaLabel="Reasoning override" label="Reasoning" variant="topbar" />);

    fireEvent.click(screen.getByRole('button', { name: 'Reasoning override' }));

    expect(screen.getByRole('listbox', { name: 'Reasoning override' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('option', { name: 'High' }));

    expect(onChange).toHaveBeenCalledWith('high');
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
  });

  it('closes with Escape and does not open while disabled', () => {
    const { rerender } = render(<CustomSelect value="" options={options} onChange={vi.fn()} ariaLabel="Reasoning override" />);

    fireEvent.click(screen.getByRole('button', { name: 'Reasoning override' }));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument();

    rerender(<CustomSelect value="" options={options} onChange={vi.fn()} ariaLabel="Reasoning override" disabled />);
    expect(screen.getByRole('button', { name: 'Reasoning override' })).toBeDisabled();
  });
});
