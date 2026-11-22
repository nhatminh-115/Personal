import { describe, expect, it } from 'vitest';

import { resolveApiBaseUrl } from '../services/api';

describe('API base URL', () => {
  it('targets the loopback sidecar for desktop builds', () => {
    expect(resolveApiBaseUrl('desktop')).toBe('http://127.0.0.1:17890');
  });

  it('keeps browser builds on the relative Vite proxy path', () => {
    expect(resolveApiBaseUrl('development')).toBe('');
  });

  it('uses a configured API base URL and removes trailing slashes', () => {
    expect(resolveApiBaseUrl('desktop', ' https://aura.example/api/// ')).toBe('https://aura.example/api');
  });
});
