import { useState } from 'react';
import { getSupabase } from '../lib/supabase';
import { X, Eye, EyeOff } from 'lucide-react';

type Mode = 'signin' | 'signup';

export function LoginPage() {
  const [mode, setMode] = useState<Mode>('signin');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [termsError, setTermsError] = useState(false);
  const [showTermsModal, setShowTermsModal] = useState(false);

  const redirectTo = window.location.origin + window.location.pathname;

  function ensureTermsAccepted(): boolean {
    if (acceptedTerms) return true;
    setTermsError(true);
    return false;
  }

  function acceptTerms(checked: boolean) {
    setAcceptedTerms(checked);
    if (checked) { setTermsError(false); }
  }

  async function google() {
    if (!ensureTermsAccepted()) return;
    setError(null); setBusy(true);
    const { error } = await getSupabase().auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo },
    });
    if (error) { setError(error.message); setBusy(false); }
  }

  async function apple() {
    if (!ensureTermsAccepted()) return;
    setError('Apple sign-in not configured yet.');
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!ensureTermsAccepted()) return;
    setError(null); setInfo(null); setBusy(true);
    const sb = getSupabase();
    try {
      if (mode === 'signin') {
        const { error } = await sb.auth.signInWithPassword({ email, password });
        if (error) throw error;
      } else {
        const { data, error } = await sb.auth.signUp({
          email,
          password,
          options: {
            emailRedirectTo: redirectTo,
            data: { full_name: fullName }
          }
        });
        if (error) throw error;
        if (!data.session) setInfo('Account created. Check your email to confirm, then sign in.');
      }
    } catch (err: any) {
      setError(err?.message || 'Authentication failed');
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="min-h-screen w-full flex bg-gradient-to-br from-[#E6F3FA] via-[#D3EBF7] to-[#BFE3F4] font-sans text-slate-800">

        {/* Left Pane - Form */}
        <div className="w-full md:w-1/2 p-8 md:p-12 lg:p-16 flex flex-col justify-between z-10 min-h-screen">

          <div className="flex items-center gap-2 mb-4">
            <div className="px-5 py-1.5 border border-slate-300 rounded-full text-sm font-medium tracking-wide text-slate-700 bg-transparent">
              Svaani
            </div>
          </div>

          <form onSubmit={submit} className="flex-1 flex flex-col max-w-sm mx-auto w-full justify-center">

            <h1 className="text-[32px] leading-tight font-semibold text-slate-900 mb-2">
              {mode === 'signin' ? 'Sign in to continue' : 'Create an account'}
            </h1>
            <p className="text-slate-600 mb-10 text-sm font-medium">
              {mode === 'signin' ? 'Welcome back to Svaani.' : 'Sign up and get 30 day free trial'}
            </p>

            {mode === 'signup' && (
              <div className="mb-5">
                <label className="block text-xs font-medium text-slate-500 mb-2 ml-4">Full name</label>
                <input
                  type="text"
                  value={fullName}
                  onChange={e => setFullName(e.target.value)}
                  placeholder="Amélie Laurent"
                  className="w-full px-5 py-3.5 rounded-full bg-white/40 border border-transparent focus:border-sky-300 focus:bg-white/80 focus:ring-4 focus:ring-sky-100 outline-none transition-all placeholder:text-slate-400 text-sm shadow-sm backdrop-blur-sm"
                  required
                />
              </div>
            )}

            <div className="mb-5">
              <label className="block text-xs font-medium text-slate-500 mb-2 ml-4">Email</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="amelielaurent7622@gmail.com"
                className="w-full px-5 py-3.5 rounded-full bg-white/40 border border-transparent focus:border-sky-300 focus:bg-white/80 focus:ring-4 focus:ring-sky-100 outline-none transition-all placeholder:text-slate-400 text-sm shadow-sm backdrop-blur-sm"
                required
              />
            </div>

            <div className="mb-5 relative">
              <label className="block text-xs font-medium text-slate-500 mb-2 ml-4">Password</label>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  placeholder="••••••••••••••••"
                  className="w-full px-5 py-3.5 rounded-full bg-white/40 border border-transparent focus:border-sky-300 focus:bg-white/80 focus:ring-4 focus:ring-sky-100 outline-none transition-all placeholder:text-slate-400 text-sm shadow-sm backdrop-blur-sm"
                  required
                  minLength={6}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 transition-colors"
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            {error && (
              <div className="mb-5 text-xs text-red-600 bg-red-50 p-3 rounded-2xl border border-red-100">
                {error}
              </div>
            )}

            {info && (
              <div className="mb-5 text-xs text-emerald-600 bg-emerald-50 p-3 rounded-2xl border border-emerald-100">
                {info}
              </div>
            )}

            {/* Terms and conditions - Placed above the submit button */}
            <div className="mb-6 mt-2">
              <label className={`flex items-start gap-2 cursor-pointer text-xs ml-4 ${termsError ? 'text-red-600' : 'text-slate-500'}`}>
                <input
                  type="checkbox"
                  checked={acceptedTerms}
                  onChange={(e) => acceptTerms(e.target.checked)}
                  className="mt-0.5 rounded border-slate-300 text-sky-400 focus:ring-sky-400"
                />
                <span className="leading-tight">
                  I agree to the <a className="underline font-semibold hover:text-sky-600" onClick={(e) => { e.preventDefault(); setShowTermsModal(true); }}>Terms &amp; Conditions</a>
                </span>
              </label>
            </div>

            <button
              type="submit"
              disabled={busy}
              className="w-full bg-[#40C3F7] hover:bg-[#20b4ec] text-white text-sm font-semibold py-4 rounded-full transition-colors shadow-lg shadow-[#40C3F7]/30 mb-6 flex justify-center items-center"
            >
              {busy ? 'Please wait...' : 'Submit'}
            </button>

            <div className="flex gap-4">
              <button
                type="button"
                onClick={apple}
                className="flex-1 bg-transparent border border-slate-300 hover:bg-white/20 py-3 rounded-full flex items-center justify-center gap-2 font-medium text-sm text-slate-700 transition-colors"
              >
                <AppleIcon /> Apple
              </button>
              <button
                type="button"
                onClick={google}
                className="flex-1 bg-transparent border border-slate-300 hover:bg-white/20 py-3 rounded-full flex items-center justify-center gap-2 font-medium text-sm text-slate-700 transition-colors"
              >
                <GoogleIcon /> Google
              </button>
            </div>

          </form>

          <div className="flex justify-between items-center text-xs text-slate-500 font-medium px-4">
            <div>
              {mode === 'signin' ? 'Don\'t have an account?' : 'Have any account?'}
              <button
                type="button"
                onClick={() => { setMode(mode === 'signin' ? 'signup' : 'signin'); setError(null); setInfo(null); }}
                className="ml-1 text-slate-800 underline decoration-slate-400 underline-offset-4 hover:text-sky-600"
              >
                {mode === 'signin' ? 'Sign up' : 'Sign in'}
              </button>
            </div>
            <button type="button" onClick={() => setShowTermsModal(true)} className="underline decoration-slate-400 underline-offset-4 hover:text-sky-600">
              Terms &amp; Conditions
            </button>
          </div>
        </div>

        {/* Right Pane - Image Placeholder */}
        <div className="hidden md:block w-1/2 p-6 lg:p-8 z-10 h-screen">
          <div className="relative w-full h-full drop-shadow-2xl">

            <div
              className="w-full h-full rounded-[2.5rem] overflow-hidden relative group"
              style={{
                WebkitMaskImage: 'radial-gradient(circle at calc(100% - 24px) 24px, transparent 40px, black 41px)',
                maskImage: 'radial-gradient(circle at calc(100% - 24px) 24px, transparent 40px, black 41px)'
              }}
            >
              {/* Image Placeholder */}
              <img
                src="https://res.cloudinary.com/dvlgixtg8/image/upload/v1782543752/ChatGPT_Image_Jun_27_2026_12_31_58_PM_zz7o8y.png"
                alt="Medical Team"
                className="w-full h-full object-cover transition-transform duration-700 group-hover:scale-105"
              />

              {/* Overlay gradient */}
              <div className="absolute inset-0 bg-gradient-to-t from-sky-900/20 to-transparent pointer-events-none"></div>
            </div>

            {/* Close Button positioned in the cutout */}
            <button className="absolute top-0 right-0 bg-white/70 backdrop-blur hover:bg-white text-slate-600 rounded-full transition-all z-20 w-12 h-12 flex items-center justify-center">
              <X size={22} strokeWidth={2.5} />
            </button>

          </div>
        </div>

      </div>

      {/* Terms Modal */}
      {showTermsModal && (
        <div className="fixed inset-0 bg-slate-900/40 backdrop-blur-sm z-50 flex items-center justify-center p-4" onClick={() => setShowTermsModal(false)}>
          <div className="bg-white rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden" onClick={e => e.stopPropagation()}>
            <div className="p-6 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
              <h2 className="text-lg font-bold text-slate-800">Terms of Use &amp; Privacy Notice</h2>
              <button onClick={() => setShowTermsModal(false)} className="text-slate-400 hover:text-slate-600 bg-white shadow-sm p-1.5 rounded-full border border-slate-200">
                <X size={18} />
              </button>
            </div>
            <div className="p-6 overflow-y-auto flex-1 text-sm text-slate-600 space-y-4 prose prose-sm max-w-none">
              <p className="font-semibold text-slate-400 uppercase tracking-wider text-xs">Last Updated: June 2026</p>
              <p>By logging into and using the Svaani platform ("Svaani", "we", "us"), you (the "User", "Doctor", or "Healthcare Provider") agree to the following terms:</p>

              <h4 className="text-slate-800 font-semibold mt-4">1. Roles Under DPDP Act, 2023</h4>
              <p>Svaani acts as a Data Processor. The Hospital and/or the User acting as the Data Fiduciary retains absolute ownership and control over all patient data, including Personal Data and Sensitive Personal Data (Health Data). Svaani processes this data strictly to provide AI clinical scribe services on your behalf.</p>

              <h4 className="text-slate-800 font-semibold mt-4">2. Data Processing &amp; Architecture</h4>
              <p><strong>Purpose Limitation:</strong> We process patient metadata (Name, Hospital ID, Consultation Date) and consultation audio solely for the purpose of generating clinical notes. We do not collect, use, or sell patient data for marketing, advertising, or training our internal AI models without explicit, separate consent.</p>
              <p><strong>Security Standards:</strong> While Svaani is not currently HIPAA-certified, we follow a secure, safe architecture. All data in transit is encrypted via TLS 1.3, and data at rest is encrypted using AES-256 standards.</p>
              <p><strong>Infrastructure &amp; Localization:</strong></p>
              <ul className="list-disc pl-5 space-y-1">
                <li><strong>Testing/Beta Phase:</strong> During our testing phase, audio and text data may be processed via third-party subprocessor APIs (e.g., cloud transcription/LLM services) under strict confidentiality agreements.</li>
                <li><strong>Production Phase:</strong> In our production environment, all patient data is hosted, processed, and stored exclusively on servers located in the Mumbai (ap-south-1) Region, governed under Business Associate Agreements (BAA) with our cloud infrastructure providers to ensure DPDP compliance and data localization.</li>
              </ul>

              <h4 className="text-slate-800 font-semibold mt-4">3. Audit Logs &amp; Admin Console</h4>
              <p>To ensure security and compliance, Svaani maintains immutable audit logs within our Admin Console. These logs record metadata such as User ID, timestamps, session creations, and data access events. No raw clinical audio or patient health text is stored in the admin logs. These logs are used solely for security monitoring, troubleshooting, and providing compliance reports to the Hospital upon request.</p>

              <h4 className="text-slate-800 font-semibold mt-4">4. User Responsibility &amp; Liability Limitation</h4>
              <p><strong>Metadata Accuracy:</strong> Svaani uses automated capture methods (e.g., clipboard parsing) to bind patient metadata. The User is solely responsible for verifying that the correct Patient Name and ID are bound to the correct clinical note before saving or exporting it to the Hospital's HMS.</p>
              <p><strong>Clinical Verification:</strong> Svaani generates AI-drafted clinical notes. The User assumes full responsibility for reviewing, editing, and authorizing the final clinical note. Svaani is not liable for any clinical errors, omissions, or misinterpretations in the generated text.</p>
              <p><strong>Limitation of Liability:</strong> Under no circumstances shall Svaani, its founders, or its affiliates be held legally or financially responsible for any direct, indirect, or consequential damages, medical errors, or regulatory penalties arising from the use of the platform. The User uses Svaani at their own risk and agrees to indemnify Svaani against any third-party claims (including patient claims under the DPDP Act) resulting from the User's mishandling of data or failure to verify clinical notes.</p>

              <h4 className="text-slate-800 font-semibold mt-4">5. Consent to Process</h4>
              <p>By clicking "Login" or "Agree", the User confirms they have the authority to process patient data on behalf of the hospital, and they consent to Svaani processing this data via the secure architecture described above.</p>
            </div>
            <div className="p-4 border-t border-slate-100 bg-slate-50/50 flex flex-col sm:flex-row justify-between items-center gap-4">
              <span className="text-xs text-slate-400 italic">
                Reading this notice does not constitute acceptance — tick the consent box to agree.
              </span>
              <button
                type="button"
                className="bg-sky-500 hover:bg-sky-600 text-white px-6 py-2 rounded-xl font-medium transition-colors whitespace-nowrap"
                onClick={() => setShowTermsModal(false)}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.83.86-3.04.86-2.34 0-4.32-1.58-5.02-3.7H.96v2.34A9 9 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.98 10.72a5.41 5.41 0 0 1 0-3.44V4.94H.96a9 9 0 0 0 0 8.12l3.02-2.34z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.94l3.02 2.34C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  );
}

function AppleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
      <path fill="#000000" d="M14.97 12.3c-.02.04-2.32 3.99-5.12 3.99-1.2 0-1.74-.75-3.32-.75-1.57 0-2.16.73-3.3.77-2.85.08-5.32-4.14-5.32-7.85 0-3.14 2.1-4.8 4.2-4.8 1.4 0 2.6.96 3.4.96.8 0 2.16-1.02 3.82-.98 1.63.04 3.09.84 3.93 2.1-.14.1-2.34 1.38-2.34 4.09 0 3.03 2.6 4.05 2.62 4.06zM9.54 2.45c.67-.81 1.13-1.93.99-3.05-1.02.06-2.22.7-2.92 1.54-.62.72-1.15 1.87-.99 2.95 1.13.1 2.22-.64 2.92-1.44z" />
    </svg>
  );
}
