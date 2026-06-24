// Production login: Google OAuth + email/password (sign in / create account), backed by
// Supabase Auth. On success the AuthProvider picks up the new session and the gate in
// main.tsx swaps this page out for the app.
import { useState, useEffect, useRef } from 'react';
import * as THREE from 'three';
import { getSupabase } from '../lib/supabase';

type Mode = 'signin' | 'signup';

export function LoginPage() {
  const [mode, setMode] = useState<Mode>('signin');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  const cardRef = useRef<HTMLFormElement>(null);
  const [cardTransform, setCardTransform] = useState('perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)');

  const [acceptedTerms, setAcceptedTerms] = useState(false);
  const [termsScrolled, setTermsScrolled] = useState(false);
  const [showTermsModal, setShowTermsModal] = useState(false);

  const redirectTo = window.location.origin + window.location.pathname;

  async function google() {
    if (!acceptedTerms) {
      setError("Please accept the Terms of Use & Privacy Notice to continue.");
      return;
    }
    setError(null); setBusy(true);
    const { error } = await getSupabase().auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo },
    });
    if (error) { setError(error.message); setBusy(false); }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!acceptedTerms) {
      setError("Please accept the Terms of Use & Privacy Notice to continue.");
      return;
    }
    setError(null); setInfo(null); setBusy(true);
    const sb = getSupabase();
    try {
      if (mode === 'signin') {
        const { error } = await sb.auth.signInWithPassword({ email, password });
        if (error) throw error;
      } else {
        const { data, error } = await sb.auth.signUp({ email, password, options: { emailRedirectTo: redirectTo } });
        if (error) throw error;
        if (!data.session) setInfo('Account created. Check your email to confirm, then sign in.');
      }
    } catch (err: any) {
      setError(err?.message || 'Authentication failed');
    } finally {
      setBusy(false);
    }
  }

  const handleMouseMove = (e: React.MouseEvent<HTMLFormElement>) => {
    if (!cardRef.current) return;
    const card = cardRef.current;
    const rect = card.getBoundingClientRect();
    const x = e.clientX - rect.left - rect.width / 2;
    const y = e.clientY - rect.top - rect.height / 2;
    
    // Tilt limit: 12 degrees
    const tiltX = -(y / rect.height) * 12;
    const tiltY = (x / rect.width) * 12;
    
    setCardTransform(`perspective(1000px) rotateX(${tiltX}deg) rotateY(${tiltY}deg) scale3d(1.02, 1.02, 1.02)`);
  };

  const handleMouseLeave = () => {
    setCardTransform('perspective(1000px) rotateX(0deg) rotateY(0deg) scale3d(1, 1, 1)');
  };

  return (
    <div className="login-shell">
      <ThreeBackground />
      
      <form 
        ref={cardRef}
        className="login-card" 
        style={{ transform: cardTransform }}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        onSubmit={submit}
      >
        <div className="login-brand login-card-pop">
          <span className="login-logo">𝓢</span>
          <div>
            <div className="login-title">Svaani<span style={{ color: '#1ec7b1' }}>.</span></div>
            <div className="login-sub">AI Medical Scribe</div>
          </div>
        </div>

        <h1 className="login-h1 login-card-pop">{mode === 'signin' ? 'Sign in to continue' : 'Create your account'}</h1>

        <button type="button" className="login-btn-google login-card-pop" onClick={google} disabled={busy || !acceptedTerms}>
          <GoogleIcon /> Continue with Google
        </button>

        <div className="login-divider login-card-pop">
          <span className="login-divider-text">or</span>
        </div>

        <label className="login-label login-card-pop">Email
          <input className="login-input" type="email" autoComplete="email" required
            value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@hospital.org" />
        </label>
        <label className="login-label login-card-pop">Password
          <input className="login-input" type="password" required minLength={6}
            autoComplete={mode === 'signin' ? 'current-password' : 'new-password'}
            value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" />
        </label>

        {error && (
          <div className="login-card-pop" style={{ background: 'rgba(192, 57, 43, 0.15)', color: '#e74c3c', border: '1px solid rgba(192, 57, 43, 0.3)', borderRadius: 10, padding: '10px 12px', fontSize: 13 }}>
            {error}
          </div>
        )}
        {info && (
          <div className="login-card-pop" style={{ background: 'rgba(31, 157, 107, 0.15)', color: '#2ecc71', border: '1px solid rgba(31, 157, 107, 0.3)', borderRadius: 10, padding: '10px 12px', fontSize: 13 }}>
            {info}
          </div>
        )}

        <div className="login-terms-acceptance login-card-pop">
          <label className={`login-checkbox-label ${!termsScrolled ? 'disabled' : ''} ${acceptedTerms ? 'checked' : ''}`}>
            <input 
              type="checkbox" 
              disabled={!termsScrolled} 
              checked={acceptedTerms}
              onChange={(e) => setAcceptedTerms(e.target.checked)} 
            />
            <span>
              I agree to the <a className="login-link underline" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setShowTermsModal(true); }}>Terms &amp; Privacy Notice</a>
            </span>
          </label>
          {!termsScrolled && (
            <p className="login-terms-hint">
              * Please open and scroll to the bottom of the <a className="login-link underline" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setShowTermsModal(true); }}>Terms &amp; Privacy Notice</a> to enable the checkbox.
            </p>
          )}
        </div>

        <button type="submit" className="login-btn-primary login-card-pop" disabled={busy || !acceptedTerms}>
          {busy ? 'Please wait…' : mode === 'signin' ? 'Sign in' : 'Create account'}
        </button>

        <div className="login-switch login-card-pop">
          {mode === 'signin' ? (
            <>New here?{' '}
              <a className="login-link" onClick={() => { setMode('signup'); setError(null); setInfo(null); }}>Create an account</a></>
          ) : (
            <>Already have an account?{' '}
              <a className="login-link" onClick={() => { setMode('signin'); setError(null); setInfo(null); }}>Sign in</a></>
          )}
        </div>

        <p className="login-legal login-card-pop">A faithful scribe, never prescribes. Your consultations are private to your account.</p>
      </form>

      {showTermsModal && (
        <div className="login-terms-modal-overlay" onClick={() => setShowTermsModal(false)}>
          <div className="login-terms-modal" onClick={(e) => e.stopPropagation()}>
            <div className="login-terms-modal-header">
              <h2>Terms of Use &amp; Privacy Notice</h2>
              <button className="login-terms-close" type="button" onClick={() => setShowTermsModal(false)}>&times;</button>
            </div>
            <div 
              className="login-terms-modal-body"
              onScroll={(e) => {
                const el = e.currentTarget;
                if (el.scrollHeight - el.scrollTop <= el.clientHeight + 15) {
                  setTermsScrolled(true);
                }
              }}
            >
              <h3>Svaani – Terms of Use &amp; Privacy Notice (Login Screen Version)</h3>
              <p className="login-terms-date">Last Updated: June 2026</p>
              <p>By logging into and using the Svaani platform ("Svaani", "we", "us"), you (the "User", "Doctor", or "Healthcare Provider") agree to the following terms:</p>
              
              <h4>1. Roles Under DPDP Act, 2023</h4>
              <p>Svaani acts as a Data Processor. The Hospital and/or the User acting as the Data Fiduciary retains absolute ownership and control over all patient data, including Personal Data and Sensitive Personal Data (Health Data). Svaani processes this data strictly to provide AI clinical scribe services on your behalf.</p>
              
              <h4>2. Data Processing &amp; Architecture</h4>
              <p><strong>Purpose Limitation:</strong> We process patient metadata (Name, Hospital ID, Consultation Date) and consultation audio solely for the purpose of generating clinical notes. We do not collect, use, or sell patient data for marketing, advertising, or training our internal AI models without explicit, separate consent.</p>
              <p><strong>Security Standards:</strong> While Svaani is not currently HIPAA-certified, we follow a secure, safe architecture. All data in transit is encrypted via TLS 1.3, and data at rest is encrypted using AES-256 standards.</p>
              <p><strong>Infrastructure &amp; Localization:</strong></p>
              <ul>
                <li><strong>Testing/Beta Phase:</strong> During our testing phase, audio and text data may be processed via third-party subprocessor APIs (e.g., cloud transcription/LLM services) under strict confidentiality agreements.</li>
                <li><strong>Production Phase:</strong> In our production environment, all patient data is hosted, processed, and stored exclusively on servers located in the Mumbai (ap-south-1) Region, governed under Business Associate Agreements (BAA) with our cloud infrastructure providers to ensure DPDP compliance and data localization.</li>
              </ul>
              
              <h4>3. Audit Logs &amp; Admin Console</h4>
              <p>To ensure security and compliance, Svaani maintains immutable audit logs within our Admin Console. These logs record metadata such as User ID, timestamps, session creations, and data access events. No raw clinical audio or patient health text is stored in the admin logs. These logs are used solely for security monitoring, troubleshooting, and providing compliance reports to the Hospital upon request.</p>
              
              <h4>4. User Responsibility &amp; Liability Limitation</h4>
              <p><strong>Metadata Accuracy:</strong> Svaani uses automated capture methods (e.g., clipboard parsing) to bind patient metadata. The User is solely responsible for verifying that the correct Patient Name and ID are bound to the correct clinical note before saving or exporting it to the Hospital's HMS.</p>
              <p><strong>Clinical Verification:</strong> Svaani generates AI-drafted clinical notes. The User assumes full responsibility for reviewing, editing, and authorizing the final clinical note. Svaani is not liable for any clinical errors, omissions, or misinterpretations in the generated text.</p>
              <p><strong>Limitation of Liability:</strong> Under no circumstances shall Svaani, its founders, or its affiliates be held legally or financially responsible for any direct, indirect, or consequential damages, medical errors, or regulatory penalties arising from the use of the platform. The User uses Svaani at their own risk and agrees to indemnify Svaani against any third-party claims (including patient claims under the DPDP Act) resulting from the User's mishandling of data or failure to verify clinical notes.</p>
              
              <h4>5. Consent to Process</h4>
              <p>By clicking "Login" or "Agree", the User confirms they have the authority to process patient data on behalf of the hospital, and they consent to Svaani processing this data via the secure architecture described above.</p>
            </div>
            
            <div className="login-terms-modal-footer">
              <span className="login-terms-scroll-warning">
                {termsScrolled ? "✓ Terms fully read" : "Scroll to the bottom of the terms to accept"}
              </span>
              <button 
                type="button"
                className={`login-btn-agree ${termsScrolled ? 'active' : ''}`}
                disabled={!termsScrolled}
                onClick={() => {
                  setAcceptedTerms(true);
                  setShowTermsModal(false);
                }}
              >
                Agree &amp; Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function GoogleIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true" style={{ flexShrink: 0 }}>
      <path fill="#4285F4" d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.72v2.26h2.92c1.7-1.57 2.68-3.88 2.68-6.62z" />
      <path fill="#34A853" d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.92-2.26c-.8.54-1.83.86-3.04.86-2.34 0-4.32-1.58-5.02-3.7H.96v2.34A9 9 0 0 0 9 18z" />
      <path fill="#FBBC05" d="M3.98 10.72a5.41 5.41 0 0 1 0-3.44V4.94H.96a9 9 0 0 0 0 8.12l3.02-2.34z" />
      <path fill="#EA4335" d="M9 3.58c1.32 0 2.5.45 3.44 1.35l2.58-2.58C13.46.89 11.43 0 9 0A9 9 0 0 0 .96 4.94l3.02 2.34C4.68 5.16 6.66 3.58 9 3.58z" />
    </svg>
  );
}

function ThreeBackground() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;

    let width = container.clientWidth;
    let height = container.clientHeight;

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x0a1013, 0.0015);

    const camera = new THREE.PerspectiveCamera(55, width / height, 1, 10000);
    camera.position.z = 900;
    camera.position.y = 350;
    camera.lookAt(new THREE.Vector3(0, 0, 0));

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); // Cap pixel ratio for performance
    renderer.setSize(width, height);
    container.appendChild(renderer.domElement);

    const numParticlesX = 75;
    const numParticlesY = 75;
    const separation = 45;
    const amountOfParticles = numParticlesX * numParticlesY;

    const positions = new Float32Array(amountOfParticles * 3);
    const scales = new Float32Array(amountOfParticles);

    let i = 0, j = 0;
    for (let ix = 0; ix < numParticlesX; ix++) {
      for (let iy = 0; iy < numParticlesY; iy++) {
        positions[i] = ix * separation - (numParticlesX * separation) / 2;
        positions[i + 1] = 0;
        positions[i + 2] = iy * separation - (numParticlesY * separation) / 2;
        i += 3;

        scales[j] = 1;
        j++;
      }
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('scale', new THREE.BufferAttribute(scales, 1));

    // Dynamic circular glowing particle texture
    const canvas = document.createElement('canvas');
    canvas.width = 16;
    canvas.height = 16;
    const ctx = canvas.getContext('2d');
    if (ctx) {
      const gradient = ctx.createRadialGradient(8, 8, 0, 8, 8, 8);
      gradient.addColorStop(0, 'rgba(30, 199, 177, 1)');
      gradient.addColorStop(0.2, 'rgba(30, 199, 177, 0.8)');
      gradient.addColorStop(0.5, 'rgba(30, 199, 177, 0.2)');
      gradient.addColorStop(1, 'rgba(30, 199, 177, 0)');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, 16, 16);
    }
    const texture = new THREE.CanvasTexture(canvas);

    const material = new THREE.PointsMaterial({
      size: 7,
      map: texture,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
    });

    const particles = new THREE.Points(geometry, material);
    scene.add(particles);

    let count = 0;
    let reqId: number;
    let mouseX = 0;
    let mouseY = 0;

    const onMouseMove = (e: MouseEvent) => {
      mouseX = (e.clientX - window.innerWidth / 2) * 0.4;
      mouseY = (e.clientY - window.innerHeight / 2) * 0.4;
    };

    window.addEventListener('mousemove', onMouseMove);

    const animate = () => {
      reqId = requestAnimationFrame(animate);

      camera.position.x += (mouseX - camera.position.x) * 0.05;
      camera.position.y += (-mouseY + 250 - camera.position.y) * 0.05;
      camera.lookAt(scene.position);

      const positionsAttr = geometry.attributes.position;
      const positions = positionsAttr.array as Float32Array;

      let i = 0;
      for (let ix = 0; ix < numParticlesX; ix++) {
        for (let iy = 0; iy < numParticlesY; iy++) {
          positions[i + 1] =
            Math.sin((ix + count) * 0.25) * 45 +
            Math.sin((iy + count) * 0.35) * 45 +
            Math.cos((ix + iy + count) * 0.15) * 15;
          i += 3;
        }
      }

      positionsAttr.needsUpdate = true;
      renderer.render(scene, camera);
      count += 0.025;
    };

    animate();

    const onResize = () => {
      if (!container) return;
      width = container.clientWidth;
      height = container.clientHeight;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    };

    window.addEventListener('resize', onResize);

    return () => {
      cancelAnimationFrame(reqId);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('mousemove', onMouseMove);
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
      geometry.dispose();
      material.dispose();
      texture.dispose();
    };
  }, []);

  return <div ref={containerRef} style={{ position: 'absolute', inset: 0, overflow: 'hidden', zIndex: 0 }} />;
}
