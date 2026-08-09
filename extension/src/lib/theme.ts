/**
 * Theme selection.
 *
 * Three states rather than two. "System" is the default and the one most people
 * want — it follows the OS and changes at dusk with everything else — but it is
 * useless on its own to anyone whose OS setting does not match how they want
 * *this* surface to look, which is why Light and Dark are explicit choices
 * rather than an inferred preference.
 *
 * The choice is stamped on `<html data-theme>`, which the stylesheet overrides
 * the `prefers-color-scheme` media query with. It is stored in
 * `chrome.storage.local`, so the popup and the dashboard agree.
 */

export type Theme = 'system' | 'light' | 'dark';

export const THEMES: Theme[] = ['system', 'light', 'dark'];

const STORAGE_KEY = 'stockwatch:theme';

function isTheme(value: unknown): value is Theme {
  return value === 'system' || value === 'light' || value === 'dark';
}

/** Paint the choice. `system` removes the attribute and lets CSS decide. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
}

export async function getTheme(): Promise<Theme> {
  try {
    const stored = await chrome.storage.local.get(STORAGE_KEY);
    const value = stored?.[STORAGE_KEY];
    return isTheme(value) ? value : 'system';
  } catch {
    return 'system';
  }
}

export async function setTheme(theme: Theme): Promise<void> {
  applyTheme(theme);
  try {
    await chrome.storage.local.set({ [STORAGE_KEY]: theme });
  } catch {
    // A storage failure should not undo what the user just saw happen.
  }
}

/**
 * Apply the stored theme before the first paint.
 *
 * Called from the entry point rather than a component: doing it in an effect
 * means the default theme renders first and is then replaced, which reads as a
 * flash of the wrong colour on every open.
 */
export async function initTheme(): Promise<Theme> {
  const theme = await getTheme();
  applyTheme(theme);
  return theme;
}

export function nextTheme(theme: Theme): Theme {
  return THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
}

export const THEME_LABEL: Record<Theme, string> = {
  system: 'Auto',
  light: 'Light',
  dark: 'Dark',
};
