import { useState } from 'react';
import { applyCustom, DEFAULT_CUSTOM, loadCustom, saveCustom, type CustomTheme } from '../theme';

const FIELDS: [keyof CustomTheme, string, string][] = [
  ['bg', 'Background', 'Page backdrop'],
  ['surface', 'Surface', 'Cards & panels'],
  ['ink', 'Text', 'Body text & headings'],
  ['accent', 'Accent', 'Buttons, links & highlights'],
];

/** Drag-a-color-bar theme builder. Each native color input is the "color bar"; changes
 *  apply live (the rest of the palette derives from these four via CSS color-mix) and are
 *  saved to localStorage so the custom theme survives reloads. */
export function ThemeStudio({ onClose }: { onClose: () => void }) {
  const [t, setT] = useState<CustomTheme>(loadCustom);

  const update = (k: keyof CustomTheme, v: string) => {
    const next = { ...t, [k]: v };
    setT(next); applyCustom(next); saveCustom(next);
  };
  const reset = () => { setT({ ...DEFAULT_CUSTOM }); applyCustom(DEFAULT_CUSTOM); saveCustom(DEFAULT_CUSTOM); };

  return (
    <div className="theme-studio card">
      <div className="ai-pop-h">
        <span className="ai-pop-title">Custom theme</span>
        <button type="button" className="ai-pop-x" onClick={onClose} aria-label="Close">✕</button>
      </div>
      <p className="hint" style={{ marginTop: 0 }}>
        Drag each color bar to build your own palette. Changes apply live and are saved in this browser.
      </p>
      {FIELDS.map(([k, label, desc]) => (
        <label className="theme-row" key={k}>
          <input type="color" value={t[k]} onChange={(e) => update(k, e.target.value)} aria-label={label} />
          <span className="theme-meta">
            <span className="theme-name">{label}</span>
            <span className="kv">{desc}</span>
          </span>
          <span className="theme-hex">{t[k].toUpperCase()}</span>
        </label>
      ))}
      <div className="row">
        <button type="button" className="btn ghost sm" onClick={reset}>Reset</button>
        <button type="button" className="btn sm" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}
