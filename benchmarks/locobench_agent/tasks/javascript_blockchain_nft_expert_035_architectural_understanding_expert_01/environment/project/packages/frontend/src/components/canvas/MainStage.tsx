```tsx
/******************************************************************************
 *  StellarStage Carnival                                                     *
 *  File: packages/frontend/src/components/canvas/MainStage.tsx               *
 *                                                                            *
 *  Interactive 3-D “main stage” scene rendered with React-Three-Fiber.       *
 *  Listens to the Event-Bus for real-time performer actions and maps those   *
 *  events to visual state-machine driven animations + NFT trait previews.    *
 *                                                                            *
 *  The component purposefully lives in the presentation layer; it relies on  *
 *  ports / adapters (GraphQL + WS) for IO and keeps domain knowledge outside *
 *  of the UI.                                                                *
 ******************************************************************************/

import React, {
  memo,
  Suspense,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { Html, OrbitControls, Stage, useGLTF, Loader } from '@react-three/drei';
import * as THREE from 'three';
import shallow from 'zustand/shallow';

import { useStageFeed } from '../../hooks/useStageFeed'; // WebSocket/GraphQL adapter
import { useUiStore } from '../../state/ui.store';       // Zustand UI slice
import { StageEvent, PerformerState } from '../../types/stage';
import {
  clamp,
  lerp,
  mapEventToColor,
  safePromise,
  withTimeout,
} from '../../utils';

/**
 * ---------------------------------------------------------------------------
 * Constants
 * ---------------------------------------------------------------------------
 */

const CAMERA_DISTANCE = 22;
const CAMERA_FAR = 200;
const MODEL_PATH = '/assets/models/stage_v1.glb';
const FALLBACK_COLOR = '#202023';

/**
 * ---------------------------------------------------------------------------
 * MainStage
 * ---------------------------------------------------------------------------
 *
 * Top-level scene wrapper.
 */
type MainStageProps = {
  /** Active on-chain Show identifier passed from route */
  showId: string;
};

export const MainStage: React.FC<MainStageProps> = memo(({ showId }) => {
  /**
   * Global UI store.
   */
  const { toggleBackstage, isBackstageOpen } = useUiStore(
    (state) => ({
      toggleBackstage: state.toggleBackstage,
      isBackstageOpen: state.isBackstageOpen,
    }),
    shallow,
  );

  /**
   * Real-time feed hook. `latestEvent` is overwritten every time a new message
   * comes in from the Event-Bus via WebSocket -> GraphQL subscription.
   */
  const { latestEvent, connectionState } = useStageFeed(showId);

  /**
   * Imperative ref to call imperative methods on the StageRig child.
   */
  const rigRef = useRef<StageRigHandle>(null!);

  /**
   * Drive camera / light transitions on new performer events.
   */
  useEffect(() => {
    if (!latestEvent || !rigRef.current) return;

    switch (latestEvent.type) {
      case 'PERFORMER_MOVE':
        rigRef.current.panTo(latestEvent.payload.position);
        break;
      case 'MOOD_CHANGE':
        rigRef.current.setAmbientColor(mapEventToColor(latestEvent));
        break;
      default:
        break;
    }
  }, [latestEvent]);

  /**
   * Show connection feedback in the DOM overlay.
   */
  const connectionBanner = useMemo(() => {
    if (connectionState === 'READY') return null;
    return (
      <div className="connection-banner">
        {connectionState === 'FAILED' && 'Failed to connect. Re-trying…'}
        {connectionState === 'CONNECTING' && 'Connecting to Live-Stage…'}
      </div>
    );
  }, [connectionState]);

  return (
    <div className="main-stage">
      {connectionBanner}
      <Canvas
        gl={{ antialias: true }}
        camera={{ fov: 55, near: 0.1, far: CAMERA_FAR, position: [0, 6, CAMERA_DISTANCE] }}
        onCreated={({ gl }) => {
          gl.setClearColor(new THREE.Color(FALLBACK_COLOR));
          gl.toneMapping = THREE.ACESFilmicToneMapping;
          gl.outputColorSpace = THREE.SRGBColorSpace;
        }}
      >
        <color attach="background" args={[FALLBACK_COLOR]} />
        <Suspense fallback={<Html center>Loading Stage…</Html>}>
          <Stage environment="city" intensity={0.6}>
            <StageRig ref={rigRef}>
              <ConcertStage />
              <Performers showId={showId} latestEvent={latestEvent} />
            </StageRig>
          </Stage>
        </Suspense>
        <OrbitControls
          enablePan={false}
          maxDistance={60}
          minDistance={10}
          autoRotate
          autoRotateSpeed={0.3}
        />
      </Canvas>
      <Loader />
      {/* Toggle for mobile users */}
      <button
        aria-label="Toggle Backstage"
        className="backstage-toggle"
        onClick={toggleBackstage}
      >
        {isBackstageOpen ? 'Close Backstage' : 'Open Backstage'}
      </button>
    </div>
  );
});

/**
 * ---------------------------------------------------------------------------
 * ConcertStage: Static GLTF scene + baked lighting.
 * ---------------------------------------------------------------------------
 */

const ConcertStage: React.FC = memo(() => {
  const { scene } = useGLTF(MODEL_PATH, true);

  // Improve performance by marking non-dynamic meshes as “static”.
  useLayoutEffect(() => {
    scene.traverse((child) => {
      if ((child as THREE.Mesh).isMesh) {
        child.castShadow = true;
        child.receiveShadow = true;
        (child as THREE.Mesh).geometry.computeVertexNormals();
      }
    });
  }, [scene]);

  return <primitive object={scene} dispose={null} />;
});

useGLTF.preload(MODEL_PATH);

/**
 * ---------------------------------------------------------------------------
 * StageRig
 * ---------------------------------------------------------------------------
 *
 * Adds ambient / spotlights and exposes imperative methods for camera pans.
 * ---------------------------------------------------------------------------
 */

type StageRigHandle = {
  panTo: (target: PerformerState['position']) => void;
  setAmbientColor: (hex: string) => void;
};

const StageRig = React.forwardRef<StageRigHandle, React.PropsWithChildren>(({ children }, ref) => {
  const group = useRef<THREE.Group>(null!);
  const { camera } = useThree();
  const [ambient, setAmbient] = useState(new THREE.Color('#ffffff'));

  /**
   * Imperative API consumed by parent.
   */
  React.useImperativeHandle(ref, () => ({
    panTo: (target) => {
      // Simple camera interpolation toward a 3-D point above the target.
      const dest = new THREE.Vector3(target.x, target.y + 3, target.z + CAMERA_DISTANCE);
      lerpVector(camera.position, dest, 0.15);
    },
    setAmbientColor: (hex) => {
      setAmbient(new THREE.Color(hex));
    },
  }));

  useFrame(() => {
    // Slowly lerp ambient light when color changes.
    if (group.current) {
      const l = group.current.children.find((c) => c.type === 'AmbientLight') as THREE.Light;
      if (l) {
        l.color.lerp(ambient, 0.05);
      }
    }
  });

  return (
    <group ref={group}>
      <ambientLight intensity={0.7} />
      <spotLight
        position={[0, 30, 10]}
        angle={0.3}
        penumbra={0.5}
        intensity={2}
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
      />
      {children}
    </group>
  );
});

StageRig.displayName = 'StageRig';

/**
 * ---------------------------------------------------------------------------
 * Performers Component
 * ---------------------------------------------------------------------------
 *
 * Renders each performer avatar and reacts to incoming events.
 * Only exhibits minimal domain knowledge (PerformerState struct).
 * ---------------------------------------------------------------------------
 */

type PerformersProps = {
  showId: string;
  latestEvent: StageEvent | null;
};

const avatarGeometry = new THREE.SphereGeometry(1, 32, 32);
const avatarMaterial = new THREE.MeshStandardMaterial({ color: 'hotpink' });

const Performers: React.FC<PerformersProps> = ({ showId, latestEvent }) => {
  const [performers, setPerformers] = useState<Record<string, PerformerState>>({});

  /**
   * Map incoming events to local performer states.
   */
  useEffect(() => {
    if (!latestEvent) return;

    setPerformers((prev) => {
      const next = { ...prev };
      switch (latestEvent.type) {
        case 'PERFORMER_SPAWN':
          next[latestEvent.payload.id] = latestEvent.payload;
          break;
        case 'PERFORMER_DESPAWN':
          delete next[latestEvent.payload.id];
          break;
        case 'PERFORMER_MOVE':
        case 'MOOD_CHANGE':
          if (next[latestEvent.payload.id]) {
            next[latestEvent.payload.id] = {
              ...next[latestEvent.payload.id],
              ...latestEvent.payload,
            };
          }
          break;
        default:
          break;
      }
      return next;
    });
  }, [latestEvent]);

  /**
   * Render
   */
  return (
    <>
      {Object.values(performers).map((p) => (
        <PerformerAvatar key={p.id} state={p} />
      ))}
    </>
  );
};

/**
 * ---------------------------------------------------------------------------
 * PerformerAvatar: simple geometry placeholder for the demo.
 * In production this would be a GLTF or Live2D model.
 * ---------------------------------------------------------------------------
 */

type PerformerAvatarProps = {
  state: PerformerState;
};

const PerformerAvatar: React.FC<PerformerAvatarProps> = ({ state }) => {
  const meshRef = useRef<THREE.Mesh>(null!);

  useFrame(() => {
    // Lerp to target position for smooth animation
    if (!meshRef.current) return;

    const target = new THREE.Vector3(state.position.x, state.position.y, state.position.z);
    lerpVector(meshRef.current.position, target, 0.1);

    // Simple pulse animation based on "mood"
    const scale = 1 + clamp(state.mood / 100, 0, 1) * 0.3 * Math.sin(Date.now() * 0.004);
    meshRef.current.scale.setScalar(scale);
  });

  return <mesh ref={meshRef} geometry={avatarGeometry} material={avatarMaterial} />;
};

/**
 * ---------------------------------------------------------------------------
 * Utility: Lerp between two Vector3 positions
 * ---------------------------------------------------------------------------
 */
function lerpVector(vec: THREE.Vector3, dest: THREE.Vector3, alpha: number) {
  vec.lerp(dest, clamp(alpha, 0, 1));
}

/**
 * ---------------------------------------------------------------------------
 * Styles (CSS-in-JS or global SCSS could be used; simplified here)
 * ---------------------------------------------------------------------------
 *
 * .main-stage {
 *   position: relative;
 *   width: 100%;
 *   height: calc(100vh - var(--navbar-height));
 * }
 * .backstage-toggle {
 *   position: absolute;
 *   bottom: 1rem;
 *   right: 1rem;
 *   z-index: 10;
 * }
 * .connection-banner {
 *   position: absolute;
 *   top: 0;
 *   width: 100%;
 *   text-align: center;
 *   background: rgba(0,0,0,0.8);
 *   color: white;
 *   padding: 0.5rem 0;
 *   z-index: 10;
 *   font-size: 0.9rem;
 * }
 */

/**
 * ---------------------------------------------------------------------------
 * Error Boundary (optional for production – ensures Three runtimes don't crash)
 * ---------------------------------------------------------------------------
 */

export class MainStageErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  componentDidCatch(err: unknown) {
    // eslint-disable-next-line no-console
    console.error('[MainStage] Unhandled error:', err);
  }

  render() {
    if (this.state.hasError) {
      return <div className="main-stage-fallback">Something went wrong on stage 😭</div>;
    }
    return this.props.children;
  }
}

/**
 * ---------------------------------------------------------------------------
 * Exports
 * ---------------------------------------------------------------------------
 */

export default function MainStageWithBoundary(props: MainStageProps) {
  return (
    <MainStageErrorBoundary>
      <MainStage {...props} />
    </MainStageErrorBoundary>
  );
}
```