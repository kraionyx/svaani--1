import { useEffect, useRef } from 'react';
import * as THREE from 'three';

interface Props {
  recording: boolean;
  busy: boolean;
}

export function ThreeScene({ recording, busy }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;

    let width = container.clientWidth || 600;
    let height = container.clientHeight || 500;

    // Create scene and camera
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 1, 1000);
    camera.position.z = 180;

    // WebGL Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    container.appendChild(renderer.domElement);

    // Particle texture
    const canvas = document.createElement('canvas');
    canvas.width = 32;
    canvas.height = 32;
    const ctx = canvas.getContext('2d');
    if (ctx) {
      const gradient = ctx.createRadialGradient(16, 16, 0, 16, 16, 16);
      gradient.addColorStop(0, 'rgba(255, 255, 255, 1)');
      gradient.addColorStop(0.2, 'rgba(255, 255, 255, 0.8)');
      gradient.addColorStop(0.5, 'rgba(255, 255, 255, 0.2)');
      gradient.addColorStop(1, 'rgba(255, 255, 255, 0)');
      ctx.fillStyle = gradient;
      ctx.fillRect(0, 0, 32, 32);
    }
    const texture = new THREE.CanvasTexture(canvas);

    // Generate particle points in a spherical distribution
    const count = 3000;
    const positions = new Float32Array(count * 3);
    const originalPositions = new Float32Array(count * 3);
    const angles = new Float32Array(count * 2); // theta, phi for each particle

    for (let i = 0; i < count; i++) {
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);

      const r = 40;
      const x = r * Math.sin(phi) * Math.cos(theta);
      const y = r * Math.sin(phi) * Math.sin(theta);
      const z = r * Math.cos(phi);

      positions[i * 3] = x;
      positions[i * 3 + 1] = y;
      positions[i * 3 + 2] = z;

      originalPositions[i * 3] = x;
      originalPositions[i * 3 + 1] = y;
      originalPositions[i * 3 + 2] = z;

      angles[i * 2] = theta;
      angles[i * 2 + 1] = phi;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));

    // Particle color / material
    // Dynamic color depending on active theme or default teals/reds
    const material = new THREE.PointsMaterial({
      size: 1.5,
      map: texture,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      color: recording ? 0xe74c3c : 0x1ec7b1,
    });

    const particleSystem = new THREE.Points(geometry, material);
    scene.add(particleSystem);

    // Add secondary subtle ring of particles
    const ringCount = 1000;
    const ringPositions = new Float32Array(ringCount * 3);
    for (let i = 0; i < ringCount; i++) {
      const angle = (i / ringCount) * Math.PI * 2;
      const r = 55 + Math.random() * 8;
      ringPositions[i * 3] = r * Math.cos(angle);
      ringPositions[i * 3 + 1] = (Math.random() - 0.5) * 5;
      ringPositions[i * 3 + 2] = r * Math.sin(angle);
    }
    const ringGeometry = new THREE.BufferGeometry();
    ringGeometry.setAttribute('position', new THREE.BufferAttribute(ringPositions, 3));
    const ringMaterial = new THREE.PointsMaterial({
      size: 0.8,
      map: texture,
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      color: recording ? 0xe74c3c : 0xc7972f,
      opacity: 0.6,
    });
    const ringSystem = new THREE.Points(ringGeometry, ringMaterial);
    ringSystem.rotation.x = Math.PI / 6;
    scene.add(ringSystem);

    // Interaction variables
    let timeValue = 0;
    let reqId: number;
    let targetRotationX = 0;
    let targetRotationY = 0;
    let mouseX = 0;
    let mouseY = 0;

    const onMouseMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left - rect.width / 2;
      const y = e.clientY - rect.top - rect.height / 2;
      mouseX = (x / rect.width) * 2;
      mouseY = (y / rect.height) * 2;
    };

    container.addEventListener('mousemove', onMouseMove);

    // Render loop
    const animate = () => {
      reqId = requestAnimationFrame(animate);

      // Mouse-influenced rotations
      targetRotationY += (mouseX * 0.5 - targetRotationY) * 0.05;
      targetRotationX += (mouseY * 0.5 - targetRotationX) * 0.05;

      particleSystem.rotation.y = timeValue * 0.12 + targetRotationY;
      particleSystem.rotation.x = targetRotationX;

      ringSystem.rotation.y = -timeValue * 0.06 + targetRotationY;

      // Morphing calculations
      const posAttr = geometry.attributes.position;
      const posArray = posAttr.array as Float32Array;

      const speedMultiplier = recording ? 3.0 : busy ? 1.8 : 0.8;
      const waveFreq = recording ? 8.0 : 4.0;
      const waveAmp = recording ? 12.0 : busy ? 6.0 : 3.0;

      for (let i = 0; i < count; i++) {
        const theta = angles[i * 2];
        const phi = angles[i * 2 + 1];

        // Base coordinates on sphere
        const origX = originalPositions[i * 3];
        const origY = originalPositions[i * 3 + 1];
        const origZ = originalPositions[i * 3 + 2];

        // Dynamic radius scaling using complex wave functions
        const scale = 1.0 + (
          Math.sin(theta * waveFreq + timeValue * speedMultiplier) * 0.1 +
          Math.cos(phi * waveFreq - timeValue * speedMultiplier * 1.3) * 0.08 +
          Math.sin((theta + phi) * 2.0 + timeValue * speedMultiplier) * 0.05
        ) * (waveAmp / 40);

        posArray[i * 3] = origX * scale;
        posArray[i * 3 + 1] = origY * scale;
        posArray[i * 3 + 2] = origZ * scale;
      }

      posAttr.needsUpdate = true;

      // Smooth color interpolation if recording state changes
      if (recording) {
        material.color.setHex(0xe74c3c);
        ringMaterial.color.setHex(0xe74c3c);
      } else {
        material.color.setHex(0x1ec7b1);
        ringMaterial.color.setHex(0xc7972f);
      }

      renderer.render(scene, camera);
      timeValue += 0.02;
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

    // Cleanup
    return () => {
      cancelAnimationFrame(reqId);
      window.removeEventListener('resize', onResize);
      container.removeEventListener('mousemove', onMouseMove);
      if (container.contains(renderer.domElement)) {
        container.removeChild(renderer.domElement);
      }
      geometry.dispose();
      material.dispose();
      ringGeometry.dispose();
      ringMaterial.dispose();
      texture.dispose();
    };
  }, [recording, busy]);

  return (
    <div 
      ref={containerRef} 
      style={{ 
        width: '100%', 
        height: '100%', 
        minHeight: '320px', 
        position: 'relative', 
        zIndex: 1,
        borderRadius: 'inherit',
        overflow: 'hidden'
      }} 
    />
  );
}
