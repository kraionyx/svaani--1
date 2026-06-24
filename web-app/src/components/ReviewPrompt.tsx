import { useState } from 'react';
import * as API from '../api';
import { toast } from '../toast';

const CATEGORIES: [string, string][] = [
  ['wrong_patient_identified', 'Wrong patient identified'],
  ['wrong_speaker_assignment', 'Wrong speaker assigned'],
  ['incorrect_soap_summary', 'SOAP section error'],
  ['medication_extraction_error', 'Medication error'],
  ['timeline_error', 'Timeline error'],
  ['prompt_misunderstanding', 'Misunderstood instruction'],
  ['missing_diagnosis', 'Missing diagnosis'],
  ['hallucination', 'Hallucination / invented content'],
  ['other', 'Other'],
];

export function ReviewPrompt({
  sessionId,
  onSubmit,
}: {
  sessionId: string;
  onSubmit: () => void;
}) {
  const [rating, setRating] = useState<'helpful' | 'needs_improvement' | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [comment, setComment] = useState('');
  const [busy, setBusy] = useState(false);

  function toggle(cat: string) {
    setSelected((s) => { const n = new Set(s); n.has(cat) ? n.delete(cat) : n.add(cat); return n; });
  }

  async function submit() {
    if (!rating) return;
    setBusy(true);
    try {
      await API.submitReview(sessionId, {
        rating,
        error_categories: rating === 'needs_improvement' ? [...selected] : [],
        comment: comment.trim() || null,
      });
      toast(rating === 'helpful' ? 'Thanks for the feedback!' : 'Feedback recorded — thank you.');
      onSubmit();
    } catch (e: any) {
      toast(e.message, true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card panel review-prompt">
      <div className="step-h"><span className="n">✓</span><h3>Was this note helpful?</h3></div>
      <div className="row" style={{ gap: 8, marginBottom: 8 }}>
        <button
          className={`btn sm${rating === 'helpful' ? '' : ' ghost'}`}
          style={rating === 'helpful' ? { background: 'var(--ok)' } : {}}
          onClick={() => setRating('helpful')}
        >
          👍 Helpful
        </button>
        <button
          className={`btn sm${rating === 'needs_improvement' ? '' : ' ghost'}`}
          style={rating === 'needs_improvement' ? { background: 'var(--high)' } : {}}
          onClick={() => setRating('needs_improvement')}
        >
          👎 Needs work
        </button>
      </div>

      {rating === 'needs_improvement' && (
        <>
          <div className="review-cats">
            {CATEGORIES.map(([id, label]) => (
              <label key={id}>
                <input type="checkbox" checked={selected.has(id)} onChange={() => toggle(id)} />
                {' '}{label}
              </label>
            ))}
          </div>
          <label className="lbl">Comments</label>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            placeholder="What was wrong?"
            rows={2}
          />
        </>
      )}

      {rating && (
        <button
          className="btn big"
          style={{ marginTop: 10, padding: '10px 14px' }}
          onClick={submit}
          disabled={busy}
        >
          {busy ? 'Submitting…' : 'Submit feedback'}
        </button>
      )}
    </div>
  );
}
