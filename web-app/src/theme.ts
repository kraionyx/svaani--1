// Custom user theme: four base colors picked by the user (background / surface / text /
// accent). All other design tokens are *derived* from these four in the `[data-theme=custom]`
// CSS block via color-mix, so the whole app recolors coherently. We only set the four bases
// as inline custom properties on <html>; CSS does the rest.

export const CUSTOM_KEY = 'svaani-theme-custom';

export interface CustomTheme { bg: string; surface: string; ink: string; accent: string; }

// A deliberately distinct default so "Custom" looks different from the presets out of the box.
export const DEFAULT_CUSTOM: CustomTheme = {
  bg: '#eef1f7', surface: '#ffffff', ink: '#16202b', accent: '#6d5ae6',
};

const BASE_VARS: Record<keyof CustomTheme, string> = {
  bg: '--bg', surface: '--surface', ink: '--ink', accent: '--accent',
};

export function loadCustom(): CustomTheme {
  try {
    const raw = localStorage.getItem(CUSTOM_KEY);
    if (raw) return { ...DEFAULT_CUSTOM, ...JSON.parse(raw) };
  } catch { /* ignore malformed */ }
  return { ...DEFAULT_CUSTOM };
}

export function saveCustom(t: CustomTheme): void {
  try { localStorage.setItem(CUSTOM_KEY, JSON.stringify(t)); } catch { /* quota — ignore */ }
}

/** Apply the four base colors as inline CSS variables on <html>. */
export function applyCustom(t: CustomTheme): void {
  const el = document.documentElement;
  (Object.keys(BASE_VARS) as (keyof CustomTheme)[]).forEach((k) => el.style.setProperty(BASE_VARS[k], t[k]));
}

/** Remove the inline overrides so a preset `[data-theme=…]` block takes over again. */
export function clearCustomInline(): void {
  const el = document.documentElement;
  Object.values(BASE_VARS).forEach((v) => el.style.removeProperty(v));
}
