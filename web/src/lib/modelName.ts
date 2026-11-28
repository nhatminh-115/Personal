const knownModelNames: Record<string, string> = {
  'gpt-4o': 'GPT-4o',
  'gpt-4o-mini': 'GPT-4o mini',
  'gpt-4.1': 'GPT-4.1',
  'gpt-4.1-mini': 'GPT-4.1 mini',
  'gpt-4.1-nano': 'GPT-4.1 nano',
  'o1': 'OpenAI o1',
  'o1-mini': 'OpenAI o1 mini',
  'o3': 'OpenAI o3',
  'o3-mini': 'OpenAI o3 mini',
  'o4-mini': 'OpenAI o4 mini',
  'mock-default': 'Demo model',
  'mock-fast': 'Demo fast',
  'mock-pro': 'Demo reasoning',
};

const tokenNames: Record<string, string> = {
  gpt: 'GPT',
  openai: 'OpenAI',
  claude: 'Claude',
  llama: 'Llama',
  qwen: 'Qwen',
  deepseek: 'DeepSeek',
  gemma: 'Gemma',
  phi: 'Phi',
  oss: 'OSS',
  b: 'B',
};

export function friendlyModelName(value: string): string {
  const normalized = value.trim().toLowerCase();
  const known = knownModelNames[normalized];
  if (known) return known;

  const datedModel = normalized.match(/^(gpt-(?:4o(?:-mini)?|4\.1(?:-mini|-nano)?|4\.1))[-_](20\d{2})[-_]?(\d{2})[-_]?(\d{2})$/);
  if (datedModel) {
    const baseName = knownModelNames[datedModel[1]] ?? datedModel[1].toUpperCase();
    const month = new Date(Date.UTC(Number(datedModel[2]), Number(datedModel[3]) - 1, 1)).toLocaleString('en-US', { month: 'short', timeZone: 'UTC' });
    return `${baseName} · ${month} ${datedModel[2]}`;
  }

  return normalized
    .replace(/([a-z])([0-9])/gi, '$1 $2')
    .replace(/([0-9])([a-z])/gi, '$1 $2')
    .replace(/[._:-]+/g, ' ')
    .split(/\s+/)
    .filter(Boolean)
    .map((token) => tokenNames[token] ?? `${token.charAt(0).toUpperCase()}${token.slice(1)}`)
    .join(' ');
}
