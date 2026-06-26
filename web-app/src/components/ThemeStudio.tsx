import { useState } from 'react';
import { applyCustom, DEFAULT_CUSTOM, loadCustom, saveCustom, type CustomTheme } from '../theme';

const FIELDS: [keyof CustomTheme, string, string][] = [
  ['bg', 'Background', 'Page backdrop'],
  ['surface', 'Surface', 'Cards & panels'],
  ['ink', 'Text', 'Body text & headings'],
  ['accent', 'Accent', 'Buttons, links & highlights'],
];

/** Centered theme-builder modal. Each swatch is a native color input styled as a premium
 *  chip; changes apply live (the rest of the palette derives from these four via CSS
 *  color-mix) and are saved to localStorage so the custom theme survives reloads. */
export function ThemeStudio({ onClose }: { onClose: () => void }) {
  const [t, setT] = useState<CustomTheme>(loadCustom);

  const update = (k: keyof CustomTheme, v: string) => {
    const next = { ...t, [k]: v };
    setT(next); applyCustom(next); saveCustom(next);
  };
  const reset = () => { setT({ ...DEFAULT_CUSTOM }); applyCustom(DEFAULT_CUSTOM); saveCustom(DEFAULT_CUSTOM); };

  return (
    <div className="theme-studio-overlay" onClick={onClose}>
      <div
        className="theme-studio"
        role="dialog"
        aria-modal="true"
        aria-label="Custom theme builder"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="theme-studio-h">
          <div>
            <span className="theme-studio-title">Custom theme</span>
            <span className="theme-studio-sub">Build your palette — changes apply live and are saved in this browser.</span>
          </div>
          <button type="button" className="theme-studio-x" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <div className="theme-studio-body">
          {FIELDS.map(([k, label, desc]) => (
            <label className="theme-row" key={k}>
              <span className="theme-swatch" style={{ background: t[k] }}>
                <input type="color" value={t[k]} onChange={(e) => update(k, e.target.value)} aria-label={label} />
              </span>
              <span className="theme-meta">
                <span className="theme-name">{label}</span>
                <span className="theme-desc">{desc}</span>
              </span>
              <span className="theme-hex">{t[k].toUpperCase()}</span>
            </label>
          ))}
        </div>

        <div className="theme-studio-foot">
          <button type="button" className="theme-btn ghost" onClick={reset}>Reset</button>
          <button type="button" className="theme-btn primary" onClick={onClose}>Done</button>
        </div>
      </div>
    </div>
  );
}
