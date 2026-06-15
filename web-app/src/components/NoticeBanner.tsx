import { useEffect } from 'react';

interface Notice {
  from: string;
  to: string;
  reason: string;
  est_delay_s: number[];
}

export function NoticeBanner({
  notice,
  onDismiss,
}: {
  notice: Notice | null;
  onDismiss: () => void;
}) {
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(onDismiss, 7000);
    return () => clearTimeout(t);
  }, [notice]);

  if (!notice) return null;
  const delay = notice.est_delay_s?.length === 2
    ? `~${notice.est_delay_s[0]}–${notice.est_delay_s[1]}s`
    : notice.est_delay_s?.[0] ? `~${notice.est_delay_s[0]}s` : '';
  return (
    <div className="notice-banner">
      <span>⚠</span>
      <span>
        Switching to <b>{notice.to}</b> processing — {notice.reason}.
        {delay && ` Additional delay: ${delay}.`}
      </span>
      <button className="nbtn" onClick={onDismiss}>✕</button>
    </div>
  );
}
