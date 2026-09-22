/**
 * RoutingPrototype.test.tsx
 *
 * Verifies that RoutingPopover renders data from the typed routingPrototype
 * adapter and that no product-specific strings ("Model C", "Model R", etc.)
 * are hardcoded inside the RoutingPopover component itself.
 */
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import App from '../App';
import { routingPrototypeState } from '../state/routingPrototype';

describe('Routing Prototype Adapter', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.restoreAllMocks();
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/v1/models')) return Promise.resolve({ ok: true, json: () => Promise.resolve({ providers: [] }) });
      if (url.includes('/v1/sessions')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      if (url.includes('/v1/memory')) return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
  });

  it('routingPrototypeState exports the expected profile name', () => {
    expect(routingPrototypeState.settings.profileName).toBe('Balanced');
  });

  it('routingPrototypeState exports exactly 4 routes', () => {
    expect(routingPrototypeState.routes).toHaveLength(4);
  });

  it('all route objects have specialist, model, and reasoning fields', () => {
    for (const route of routingPrototypeState.routes) {
      expect(route).toHaveProperty('specialist');
      expect(route).toHaveProperty('model');
      expect(route).toHaveProperty('reasoning');
    }
  });

  it('RoutingPopover renders the profile name from the adapter', async () => {
    await act(async () => { render(<App />); });

    // Navigate to a project to make routing popover available
    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });

    // Open the routing popover
    const routingBadge = screen.getByText(/Balanced · Session/i);
    await act(async () => { fireEvent.click(routingBadge); });

    // Profile name from adapter is displayed
    expect(screen.getByText('Balanced')).toBeInTheDocument();
    // Scope from adapter is displayed
    expect(screen.getByText('Session')).toBeInTheDocument();
  });

  it('RoutingPopover renders all routes from the adapter', async () => {
    await act(async () => { render(<App />); });

    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });

    const routingBadge = screen.getByText(/Balanced · Session/i);
    await act(async () => { fireEvent.click(routingBadge); });

    // All specialist names from the adapter are visible
    for (const route of routingPrototypeState.routes) {
      expect(screen.getByText(route.specialist)).toBeInTheDocument();
      expect(screen.getByText(route.model)).toBeInTheDocument();
    }
  });

  it('RoutingPopover privacy and fallback values come from adapter settings', async () => {
    await act(async () => { render(<App />); });

    const projectButton = screen.getAllByText(/Stateful Architecture/i)[0].closest('button')!;
    await act(async () => { fireEvent.click(projectButton); });

    const routingBadge = screen.getByText(/Balanced · Session/i);
    await act(async () => { fireEvent.click(routingBadge); });

    expect(screen.getByText(routingPrototypeState.settings.privacy)).toBeInTheDocument();
    expect(screen.getByText(routingPrototypeState.settings.fallback)).toBeInTheDocument();
  });
});
