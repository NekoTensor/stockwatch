import { describe, expect, it } from 'vitest';

import { DEFAULT_API_BASE_URL, apiOriginPattern } from '../src/lib/config';

describe('apiOriginPattern', () => {
  it('drops the port, because match patterns are host-scoped', () => {
    expect(apiOriginPattern('http://localhost:8000/api')).toBe('http://localhost/*');
  });

  it('keeps the scheme, so http and https are not confused for one another', () => {
    expect(apiOriginPattern('https://api.example.com/api')).toBe('https://api.example.com/*');
    expect(apiOriginPattern('http://api.example.com/api')).toBe('http://api.example.com/*');
  });

  it('ignores the path', () => {
    expect(apiOriginPattern('https://example.com/deep/prefix/api')).toBe('https://example.com/*');
  });

  it('rejects what the extension could never fetch', () => {
    expect(apiOriginPattern('not a url')).toBeNull();
    expect(apiOriginPattern('')).toBeNull();
    expect(apiOriginPattern('ftp://example.com')).toBeNull();
    expect(apiOriginPattern('javascript:alert(1)')).toBeNull();
  });
});

describe('DEFAULT_API_BASE_URL', () => {
  it('is a usable address even when the build injected nothing', () => {
    expect(apiOriginPattern(DEFAULT_API_BASE_URL)).not.toBeNull();
  });
});
